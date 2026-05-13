from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date, timedelta, datetime


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
    duration = fields.Selection([
        ("0.5", "30 minutes"),
        ("1.0", "1 hour"),
        ("1.5", "1 hour 30 minutes"),
        ("2.0", "2 hours"),
    ], string="Duration", required=True, default="0.5")

    # --- Output ---
    slot_ids = fields.One2many("radiology.slot.wizard.line", "wizard_id",
                                string="Available Slots")

    # --------------------------------------------------
    # CORE: compute available slots for the chosen day
    # --------------------------------------------------
    def action_compute_slots(self):
        self.ensure_one()
        self.slot_ids.unlink()

        target_weekday = str(self.date.weekday())  # "0"=Mon … "6"=Sun

        # 1. Fetch working hour lines for the machine
        machine_lines = self.env["radiology.working.hours.line"].search([
            ("config_id.resource_id", "=", self.resource_id.id),
            ("config_id.active", "=", True),
            ("weekday", "=", target_weekday),
        ])

        # 2. Fetch working hour lines for the radiologist
        radio_lines = self.env["radiology.working.hours.line"].search([
            ("config_id.radiologist_id", "=", self.radiologist_id.id),
            ("config_id.active", "=", True),
            ("weekday", "=", target_weekday),
        ])

        if not machine_lines or not radio_lines:
            return self._warn("No working hours defined for this day.")

        # 3. Intersect their time ranges (in float hours)
        free_ranges = self._intersect_ranges(
            [(l.hour_from, l.hour_to) for l in machine_lines],
            [(l.hour_from, l.hour_to) for l in radio_lines],
        )

        if not free_ranges:
            return self._warn("No common availability this day.")

        # 4. Subtract existing appointments using the requested duration
        slot_duration = float(self.duration)
        if slot_duration <= 0:
            raise ValidationError("Please choose a valid slot duration.")

        slots = []
        appointment_model = self.env["radiology.appointment"]

        for (range_start, range_end) in free_ranges:
            cursor = range_start
            while cursor + slot_duration <= range_end:
                slot_start = self._float_to_dt(self.date, cursor)
                slot_end = self._float_to_dt(self.date, cursor + slot_duration)

                machine_busy = appointment_model._check_machine_conflict(
                    slot_start, slot_end, self.resource_id.id)
                radio_busy = appointment_model._check_radiologist_conflict(
                    slot_start, slot_end, self.radiologist_id.id)

                if not machine_busy and not radio_busy:
                    slots.append((0, 0, {
                        "wizard_id": self.id,
                        "slot_start": slot_start,
                        "slot_end": slot_end,
                    }))

                cursor += slot_duration

        if not slots:
            return self._warn("No free slots this day — all booked.")

        self.slot_ids = slots
        return self._reopen()

    def action_book(self):
        self.ensure_one()
        selected = self.slot_ids.filtered("selected")
        if len(selected) != 1:
            raise ValidationError("Please select exactly one slot.")

        appointment = self.env["radiology.appointment"].create({
            "patient_id": self.patient_id.id,
            "radiologist_id": self.radiologist_id.id,
            "resource_id": self.resource_id.id,
            "start": selected.slot_start,
            "stop": selected.slot_end,
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
    slot_start = fields.Datetime(string="Start", readonly=True)
    slot_end = fields.Datetime(string="End", readonly=True)
    selected = fields.Boolean(string="Pick")