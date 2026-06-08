from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date, timedelta, datetime
import logging

_logger = logging.getLogger(__name__)


class RadiologySlotWizard(models.TransientModel):
    _name = "radiology.slot.wizard"
    _description = "Available Slot Picker"
    _rec_name = "date"

    # --- Inputs ---
    appointment_id = fields.Many2one("radiology.appointment", string="Source Appointment")
    patient_id = fields.Many2one("res.partner", required=True,
                                  domain="[('is_patient','=',True)]")
    radiologist_id = fields.Many2one("res.partner", required=True,
                                      domain="[('is_radiologist','=',True)]")
    resource_id = fields.Many2one("resource.resource", string="Machine", required=True)
    date = fields.Date(required=True, default=fields.Date.today)
    duration = fields.Float(
        string="Slot Duration (hours)",
        readonly=True,
        compute="_compute_duration",
    )

    next_available_date = fields.Date(string="Next Available Date")
    has_slots = fields.Boolean(compute="_compute_has_slots")

    # --- Output ---
    slot_ids = fields.One2many("radiology.slot.wizard.line", "wizard_id",
                                string="Available Slots")

    @api.depends("slot_ids")
    def _compute_has_slots(self):
        for rec in self:
            rec.has_slots = bool(rec.slot_ids)

    # --------------------------------------------------
    # CORE: compute available slots for the chosen day
    # --------------------------------------------------
    def _get_slot_duration(self, resource_id, radiologist_id):
        if not resource_id or not radiologist_id:
            return 0.0

        config = self.env["radiology.working.hours"].search([
            ("resource_id", "=", resource_id),
            ("radiologist_id", "=", radiologist_id),
            ("active", "=", True),
        ], limit=1)
        return config.slot_duration if config else 0.0

    def _build_slot_commands(self, date, resource_id, radiologist_id, slot_duration):
        if slot_duration <= 0:
            return []

        target_weekday = str(date.weekday())
        machine_lines = self.env["radiology.working.hours.line"].search([
            ("config_id.resource_id", "=", resource_id),
            ("config_id.active", "=", True),
            ("weekday", "=", target_weekday),
        ])
        radio_lines = self.env["radiology.working.hours.line"].search([
            ("config_id.radiologist_id", "=", radiologist_id),
            ("config_id.active", "=", True),
            ("weekday", "=", target_weekday),
        ])

        if not machine_lines or not radio_lines:
            return []

        free_ranges = self._intersect_ranges(
            [(l.hour_from, l.hour_to) for l in machine_lines],
            [(l.hour_from, l.hour_to) for l in radio_lines],
        )

        if not free_ranges:
            return []

        appointment_model = self.env["radiology.appointment"]
        slots = []

        for (range_start, range_end) in free_ranges:
            cursor = range_start
            while cursor + slot_duration <= range_end:
                slot_start = self._float_to_dt(date, cursor)
                slot_end = self._float_to_dt(date, cursor + slot_duration)

                machine_busy = appointment_model._check_machine_conflict(
                    slot_start, slot_end, resource_id)
                radio_busy = appointment_model._check_radiologist_conflict(
                    slot_start, slot_end, radiologist_id)

                if not machine_busy and not radio_busy:
                    slots.append((0, 0, {
                        "resource_id": resource_id,
                        "slot_start": slot_start,
                        "slot_end": slot_end,
                    }))

                cursor += slot_duration

        return slots

    def _find_next_available_date(self, start_date, resource_id, radiologist_id, slot_duration):
        if slot_duration <= 0 or not start_date or not resource_id or not radiologist_id:
            return False
        check_date = start_date + timedelta(days=1)
        for i in range(30):
            slots = self._build_slot_commands(check_date, resource_id, radiologist_id, slot_duration)
            if slots:
                return check_date
            check_date += timedelta(days=1)
        return False

    def _generate_slots(self):
        if not self.resource_id or not self.radiologist_id or not self.date:
            self.slot_ids = [(5, 0, 0)]
            self.next_available_date = False
            return

        slot_duration = self._get_slot_duration(
            self.resource_id.id,
            self.radiologist_id.id,
        )
        if slot_duration <= 0:
            self.slot_ids = [(5, 0, 0)]
            self.next_available_date = False
            return

        slots = self._build_slot_commands(
            self.date,
            self.resource_id.id,
            self.radiologist_id.id,
            slot_duration,
        )

        # Use virtual commands: clear existing + add new slots
        self.slot_ids = [(5, 0, 0)] + slots

        if not slots:
            self.next_available_date = self._find_next_available_date(
                self.date,
                self.resource_id.id,
                self.radiologist_id.id,
                slot_duration,
            )
        else:
            self.next_available_date = False

    @api.onchange("radiologist_id", "resource_id", "date")
    def _onchange_generate_slots(self):
        self._generate_slots()

    @api.model
    def default_get(self, field_names):
        """Standard defaults only; slot generation is done after record creation."""
        return super().default_get(field_names)

    def action_find_slots(self):
        """Explicit 'Find Slots' button — saves the wizard first (object button behaviour),
        then regenerates available slots and reopens the same record."""
        self.ensure_one()
        self._generate_slots()
        return self._reopen()

    def action_prev_day(self):
        self.ensure_one()
        self.date = self.date - timedelta(days=1)
        self._generate_slots()
        return self._reopen()

    def action_next_day(self):
        self.ensure_one()
        self.date = self.date + timedelta(days=1)
        self._generate_slots()
        return self._reopen()

    def action_go_to_next_available_date(self):
        self.ensure_one()
        if self.next_available_date:
            self.date = self.next_available_date
            self._generate_slots()
        return self._reopen()

    def _book_slot(self, slot):
        """Create or update the appointment from a given slot line."""
        self.ensure_one()
        if not slot.slot_start:
            raise ValidationError("Slot start time is missing. Please try again.")
        if not slot.slot_end:
            raise ValidationError("Slot end time is missing. Please try again.")

        resource = slot.resource_id or self.resource_id
        if not resource:
            raise ValidationError("Machine is not set on the slot.")

        _logger.info(
            "Booking slot: ID=%s, start=%s, end=%s, resource=%s",
            slot.id, slot.slot_start, slot.slot_end, resource.name,
        )

        vals = {
            "patient_id": self.patient_id.id,
            "radiologist_id": self.radiologist_id.id,
            "resource_id": resource.id,
            "start": slot.slot_start,
            "stop": slot.slot_end,
            "state": "scheduled",
        }

        if self.appointment_id:
            self.appointment_id.write(vals)
            appointment = self.appointment_id
        else:
            appointment = self.env["radiology.appointment"].create(vals)

        return {
            "type": "ir.actions.act_window",
            "res_model": "radiology.appointment",
            "view_mode": "form",
            "res_id": appointment.id,
            "target": "current",
        }

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------
    @staticmethod
    def _intersect_ranges(ranges_a, ranges_b):
        """Return list of (start, end) float pairs that are in both sets."""
        result = []
        for a_start, a_end in ranges_a:
            for b_start, b_end in ranges_b:
                start = max(a_start, b_start)
                end = min(a_end, b_end)
                if start < end:
                    result.append((start, end))
        return result

    @staticmethod
    def _float_to_dt(day: date, hour_float: float) -> datetime:
        h = int(hour_float)
        m = int(round((hour_float - h) * 60))
        return datetime(day.year, day.month, day.day, h, m)

    @api.depends("radiologist_id", "resource_id")
    def _compute_duration(self):
        for rec in self:
            if rec.resource_id and rec.radiologist_id:
                config = self.env["radiology.working.hours"].search([
                    ("resource_id", "=", rec.resource_id.id),
                    ("radiologist_id", "=", rec.radiologist_id.id),
                    ("active", "=", True),
                ], limit=1)
                rec.duration = config.slot_duration if config else 0.0
            else:
                rec.duration = 0.0

    def _warn(self, msg):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": msg, "type": "warning", "sticky": False},
        }

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }


class RadiologySlotWizardLine(models.TransientModel):
    _name = "radiology.slot.wizard.line"
    _description = "Slot Line"

    wizard_id = fields.Many2one("radiology.slot.wizard", ondelete="cascade")
    resource_id = fields.Many2one("resource.resource", string="Machine", store=True)
    slot_start = fields.Datetime(string="Start", store=True)
    slot_end = fields.Datetime(string="End", store=True)

    def action_select_and_book(self):
        """One-click booking: book this slot immediately."""
        self.ensure_one()
        return self.wizard_id._book_slot(self)