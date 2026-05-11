from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.fields import Datetime
from datetime import datetime

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
        default=lambda self: False
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

        attendees = list(filter(None, [
            self.env.user.partner_id.id,   # current user
            self.patient_id.id,
            self.radiologist_id.id,
        ]))

        event = self.env["calendar.event"].create({
            "name": f"Radiology - {self.patient_id.name}",
            "start": self.date_start,
            "stop": self.date_end,
            "user_id": self.env.user.id,
            "partner_ids": [(6, 0, list(filter(None, [
                self.patient_id.id,
                self.radiologist_id.id
            ])))],
            "description": self.notes or "",
            "show_as": "busy",
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

        start = self._normalize_datetime_value(start)
        end = self._normalize_datetime_value(end)

        domain = [
            ("resource_id", "=", resource_id),
            ("state", "in", ["scheduled"]),
            ("date_start", "<", end),
            ("date_end", ">", start),
        ]

        if exclude_id is not None:
            domain.append(("id", "!=", exclude_id))

        return self.search(domain, limit=1)

    def _normalize_many2one_value(self, value):
        if not value:
            return False

        if isinstance(value, (list, tuple)):
            return value[0] if value else False

        if hasattr(value, "id"):
            return value.id

        return value

    def _normalize_datetime_value(self, value):
        if not value:
            return False

        if isinstance(value, datetime):
            return value

        if isinstance(value, str):
            return Datetime.from_string(value)

        return False

    def _check_radiologist_conflict(self, start, end, radiologist_id, exclude_id=None):

        if not radiologist_id:
            return False

        start = self._normalize_datetime_value(start)
        end = self._normalize_datetime_value(end)

        domain = [
            ("radiologist_id", "=", radiologist_id),
            ("state", "in", ["scheduled"]),
            ("date_start", "<", end),
            ("date_end", ">", start),
        ]

        if exclude_id is not None:
            domain.append(("id", "!=", exclude_id))

        return self.search(domain, limit=1)

    def _validate_no_conflict(self, start, end, resource_id, radiologist_id, state, exclude_id=None):

        # 🚫 Skip if not scheduled
        if state != "scheduled":
            return

        start = self._normalize_datetime_value(start)
        end = self._normalize_datetime_value(end)

        if not start or not end or not resource_id:
            raise ValidationError("Start, end and machine are required.")

        if start >= end:
            raise ValidationError("End must be after start.")

        # 🚫 Skip conflict check if not scheduled
        if state != "scheduled":
            return

        if self._check_machine_conflict(start, end, resource_id, exclude_id):
            raise ValidationError("⚠ Machine already booked for this time slot!")

        if self._check_radiologist_conflict(start, end, radiologist_id, exclude_id):
            raise ValidationError("⚠ Radiologist already busy in this time slot!")

    # =========================
    # ORM OVERRIDES
    # =========================

    @api.model_create_multi
    def create(self, vals_list):

        for vals in vals_list:
            if not vals.get('patient_id'):
                raise ValidationError("Patient is required")

            start = vals.get("date_start") or vals.get("start")
            end = vals.get("date_end") or vals.get("stop")
            resource = self._normalize_many2one_value(vals.get("resource_id"))
            radiologist = self._normalize_many2one_value(vals.get("radiologist_id"))
            state = vals.get("state", "draft")

            self._validate_no_conflict(
                start,
                end,
                resource,
                radiologist,
                state,
            )

        records = super().create(vals_list)

        for rec in records:
            if (
                rec.state == "scheduled"
                and rec.date_start
                and rec.date_end
                and not rec.calendar_event_id
            ):
                rec._create_calendar_event()

        return records

    def write(self, vals):

        for rec in self:
            start = vals.get("date_start") or vals.get("start") or rec.date_start
            end = vals.get("date_end") or vals.get("stop") or rec.date_end
            state = vals.get("state", rec.state)

            resource = vals.get("resource_id", rec.resource_id.id)
            radiologist = vals.get("radiologist_id", rec.radiologist_id.id)

            resource = self._normalize_many2one_value(resource)
            radiologist = self._normalize_many2one_value(radiologist)

            rec._validate_no_conflict(
                start,
                end,
                resource,
                radiologist,
                state,
                rec.id
            )

        res = super().write(vals)

        for rec in self:

            # =========================
            # CREATE EVENT
            # =========================
            if (
                rec.state == "scheduled"
                and rec.date_start
                and rec.date_end
            ):

                if not rec.calendar_event_id:

                    event = self.env["calendar.event"].create({
                        "name": f"Radiology - {rec.patient_id.name}",
                        "start": rec.date_start,
                        "stop": rec.date_end,
                        "user_id": self.env.user.id,
                        "partner_ids": [(6, 0, list(filter(None, [
                            rec.patient_id.id,
                            rec.radiologist_id.id,
                        ])))],
                        "description": rec.notes or "",
                    })

                    rec.calendar_event_id = event.id

                else:
                    rec.calendar_event_id.write({
                        "name": f"Radiology - {rec.patient_id.name}",
                        "start": rec.date_start,
                        "stop": rec.date_end,
                        "partner_ids": [(6, 0, list(filter(None, [
                            rec.patient_id.id,
                            rec.radiologist_id.id,
                        ])))],
                        "description": rec.notes or "",
                    })

            # =========================
            # DELETE EVENT IF CANCELLED
            # =========================
            elif rec.state in ["cancel"] and rec.calendar_event_id:
                rec.calendar_event_id.unlink()
                rec.calendar_event_id = False

        return res

    # =========================
    # UTILITY
    # =========================

    def is_machine_available(self, start, end, resource_id):
        return not self._check_machine_conflict(start, end, resource_id)
    
    @api.constrains('date_start', 'date_end', 'resource_id', 'radiologist_id')
    def _check_conflict_constraint(self):
        for rec in self:

            # ✅ ONLY validate when scheduled
            if rec.state != "scheduled":
                continue

            rec._validate_no_conflict(
                rec.date_start,
                rec.date_end,
                rec.resource_id.id,
                rec.radiologist_id.id,
                rec.state,
                rec.id
            )