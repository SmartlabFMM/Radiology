from odoo import models, fields, api
from odoo.exceptions import ValidationError


class RadiologyAppointment(models.Model):
    _name = "radiology.appointment"
    _description = "Radiology Appointment"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # =========================
    # FIELDS
    # =========================

    name = fields.Char(default="New", tracking=True)

    patient_id = fields.Many2one(
        "res.partner",
        required=True,
        domain="[('is_patient', '=', True)]",
        tracking=True,
    )

    radiologist_id = fields.Many2one(
        "res.partner",
        domain="[('is_radiologist', '=', True)]",
        tracking=True,
    )

    resource_id = fields.Many2one(
        "resource.resource",
        string="Machine",
        required=True,
        tracking=True,
    )

    date_start = fields.Datetime(tracking=True)
    date_end = fields.Datetime(tracking=True)

    duration = fields.Float(default=1.0)

    state = fields.Selection([
        ("draft", "Waiting List"),
        ("scheduled", "Scheduled"),
        ("done", "Done"),
        ("cancel", "Cancelled"),
    ], default="draft", tracking=True)

    priority = fields.Selection([
        ("0", "Low"),
        ("1", "Normal"),
        ("2", "High"),
        ("3", "Urgent"),
    ], default="1")

    notes = fields.Text()

    calendar_event_id = fields.Many2one(
        "calendar.event",
        string="Calendar Event",
        ondelete="set null"
    )

    # calendar compatibility fields
    start = fields.Datetime(
        compute="_compute_calendar_fields",
        inverse="_inverse_calendar_fields",
        store=True,
    )

    stop = fields.Datetime(
        compute="_compute_calendar_fields",
        inverse="_inverse_calendar_fields",
        store=True,
    )

    # =========================
    # CALENDAR SYNC
    # =========================

    @api.depends("date_start", "date_end")
    def _compute_calendar_fields(self):
        for rec in self:
            rec.start = rec.date_start
            rec.stop = rec.date_end

    def _inverse_calendar_fields(self):
        for rec in self:
            rec.date_start = rec.start
            rec.date_end = rec.stop

    def _create_calendar_event(self):
        self.ensure_one()

        event = self.env["calendar.event"].create({
            "name": f"Radiology - {self.patient_id.name}",
            "start": self.date_start,
            "stop": self.date_end,
            "partner_ids": [(6, 0, list(filter(None, [
                self.patient_id.id,
                self.radiologist_id.id
            ])))],
            "description": self.notes or "",
        })

        self.calendar_event_id = event.id
        return event

    def action_open_calendar_event(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "calendar.event",
            "view_mode": "form",
            "res_id": self.calendar_event_id.id,
            "target": "current",
        }

    # =========================
    # CONFLICT LOGIC
    # =========================

    def _check_machine_conflict(self, start, end, resource_id, exclude_id=None):
        domain = [
            ("resource_id", "=", resource_id),
            ("date_start", "<", end),
            ("date_end", ">", start),
        ]

        if exclude_id is not None:
            domain.append(("id", "!=", exclude_id))

        return self.search(domain, limit=1)

    def _normalize_many2one_value(self, value):
        if isinstance(value, (list, tuple)):
            if not value:
                return False
            if value[0] in (0, 1, 4) and len(value) > 1:
                return value[1]
            if value[0] == 6 and len(value) > 2:
                return value[2][0] if value[2] else False
            return value[1] if len(value) > 1 else False
        return value

    def _check_radiologist_conflict(self, start, end, radiologist_id, exclude_id=None):
        if not radiologist_id:
            return False

        domain = [
            ("radiologist_id", "=", radiologist_id),
            ("date_start", "<", end),
            ("date_end", ">", start),
        ]

        if exclude_id is not None:
            domain.append(("id", "!=", exclude_id))

        return self.search(domain, limit=1)

    def _validate_no_conflict(self, start, end, resource_id, radiologist_id, exclude_id=None):

        if not start or not end or not resource_id:
            raise ValidationError("Start, end and machine are required.")

        # machine conflict (HARD RULE)
        if self._check_machine_conflict(start, end, resource_id, exclude_id):
            raise ValidationError("⚠ Machine already booked for this time slot!")

        # radiologist conflict (HARD RULE)
        if self._check_radiologist_conflict(start, end, radiologist_id, exclude_id):
            raise ValidationError("⚠ Radiologist already busy in this time slot!")

    # =========================
    # ORM OVERRIDES
    # =========================

    @api.model_create_multi
    def create(self, vals_list):

        for vals in vals_list:
            start = vals.get("date_start") or vals.get("start")
            end = vals.get("date_end") or vals.get("stop")
            resource = self._normalize_many2one_value(vals.get("resource_id"))
            radiologist = self._normalize_many2one_value(vals.get("radiologist_id"))

            self._validate_no_conflict(
                start,
                end,
                resource,
                radiologist,
            )

        records = super().create(vals_list)

        return records

    def write(self, vals):

        for rec in self:
            start = vals.get("date_start") or vals.get("start") or rec.date_start
            end = vals.get("date_end") or vals.get("stop") or rec.date_end
            resource = self._normalize_many2one_value(vals.get("resource_id", rec.resource_id.id))
            radiologist = self._normalize_many2one_value(vals.get("radiologist_id", rec.radiologist_id.id))

            rec._validate_no_conflict(
                start,
                end,
                resource,
                radiologist,
                exclude_id=rec.id
            )

        res = super().write(vals)

        # sync calendar AFTER write
        for rec in self:
            if rec.calendar_event_id:
                rec.calendar_event_id.write({
                    "start": rec.date_start,
                    "stop": rec.date_end,
                })

        return res

    # =========================
    # UTILITY
    # =========================

    def is_machine_available(self, start, end, resource_id):
        return not self._check_machine_conflict(start, end, resource_id)