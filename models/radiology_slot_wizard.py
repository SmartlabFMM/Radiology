from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date, timedelta, datetime
import logging

_logger = logging.getLogger(__name__)


class RadiologySlotWizard(models.TransientModel):
    _name = "radiology.slot.wizard"
    _description = "Available Slot Picker"

    # --- Inputs ---
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
    # Field "slot_start" does not exist in model "radiology.slot.wizard"
    # Field "slot_end" does not exist in model "radiology.slot.wizard"
    # We will define these fields in the line model instead, as they are per-slot, not per-wizard.
    # This is to avoid confusion and data integrity issues, since the wizard itself does not have a single start/end time, but each slot does.
    # slot_start = fields.Datetime(string="Start", readonly=True, store=False)
    # slot_end = fields.Datetime(string="End", readonly=True, store=False)
    # we will move these fields to the RadiologySlotWizardLine model, as they are specific to each slot, not the wizard as a whole.
    # This way, each slot line will have its own start and end time, which makes more sense given the data structure.
    # The wizard itself is just a container for the selected date, radiologist, and machine, while the lines represent the individual available slots with their own start/end times.
    # This also avoids confusion about which start/end time is being referred to when we talk about the wizard vs the slots.
    # We will define slot_start and slot_end in the RadiologySlotWizardLine model, and remove them from the wizard model.

    # --- Output ---
    slot_ids = fields.One2many("radiology.slot.wizard.line", "wizard_id",
                                string="Available Slots")

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

    def _generate_slots(self):
        if not self.resource_id or not self.radiologist_id or not self.date:
            self.slot_ids = [(5, 0, 0)]
            return

        slot_duration = self._get_slot_duration(
            self.resource_id.id,
            self.radiologist_id.id,
        )
        if slot_duration <= 0:
            self.slot_ids = [(5, 0, 0)]
            return

        slots = self._build_slot_commands(
            self.date,
            self.resource_id.id,
            self.radiologist_id.id,
            slot_duration,
        )

        # Use virtual commands: clear existing + add new slots
        self.slot_ids = [(5, 0, 0)] + slots

    @api.onchange("radiologist_id", "resource_id", "date")
    def _onchange_generate_slots(self):
        self._generate_slots()

    @api.model
    def default_get(self, field_names):
        res = super().default_get(field_names)
        default_date = res.get("date") or self.env.context.get("default_date")
        resource_id = res.get("resource_id") or self.env.context.get("default_resource_id")
        radiologist_id = res.get("radiologist_id") or self.env.context.get("default_radiologist_id")

        if default_date and resource_id and radiologist_id:
            # Convert string date to date object if needed
            if isinstance(default_date, str):
                from datetime import datetime as dt
                default_date = dt.strptime(default_date, "%Y-%m-%d").date()
            
            slot_duration = self._get_slot_duration(resource_id, radiologist_id)
            if slot_duration > 0:
                slots = self._build_slot_commands(
                    default_date,
                    resource_id,
                    radiologist_id,
                    slot_duration,
                )
                if slots:
                    res["slot_ids"] = slots
        return res

    def action_book(self):
        self.ensure_one()
        selected = self.slot_ids.filtered("selected")
        if len(selected) != 1:
            raise ValidationError("Please select exactly one slot.")

        slot = selected[0]
        
        # Debug: Log slot data
        _logger = __import__('logging').getLogger(__name__)
        _logger.warning(f"Slot selected: ID={slot.id}, start={slot.slot_start}, end={slot.slot_end}, resource_id={slot.resource_id}")
        
        # If slot times are missing, recompute them
        slot_start = slot.slot_start
        slot_end = slot.slot_end
        
        if not slot_start or not slot_end:
            # Recompute slots to get the correct times
            _logger.warning("Slot times are empty, recomputing...")
            slot_duration = self._get_slot_duration(
                self.resource_id.id,
                self.radiologist_id.id,
            )
            if slot_duration > 0:
                recomputed_slots = self._build_slot_commands(
                    self.date,
                    self.resource_id.id,
                    self.radiologist_id.id,
                    slot_duration,
                )
                # Find the selected slot in recomputed list by index or position
                if recomputed_slots and len(recomputed_slots) > 0:
                    # Get the first recomputed slot (simplified - assumes slots are in same order)
                    first_slot_data = recomputed_slots[0][2]
                    slot_start = first_slot_data.get("slot_start")
                    slot_end = first_slot_data.get("slot_end")
        
        # Validate slot has all required fields
        if not slot_start:
            raise ValidationError(f"Slot start time is empty. Please select a valid slot.")
        if not slot_end:
            raise ValidationError(f"Slot end time is empty. Please select a valid slot.")
        
        resource = slot.resource_id or self.resource_id
        if not resource:
            raise ValidationError("Machine is not set. Please select a valid slot.")

        appointment = self.env["radiology.appointment"].create({
            "patient_id": self.patient_id.id,
            "radiologist_id": self.radiologist_id.id,
            "resource_id": resource.id,
            "start": slot_start,
            "stop": slot_end,
            "state": "scheduled",
        })

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
    resource_id = fields.Many2one("resource.resource", string="Machine", readonly=True, store=True)
    slot_start = fields.Datetime(string="Start", readonly=True, store=True)
    slot_end = fields.Datetime(string="End", readonly=True, store=True)
    selected = fields.Boolean(string="Pick", store=True)

    @api.onchange("selected")
    def _onchange_selected(self):
        if not self.selected or not self.wizard_id:
            return
        for line in self.wizard_id.slot_ids:
            if line != self:
                line.selected = False