from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime


class RadiologyAppointment(models.Model):
    _name = "radiology.appointment"
    _description = "Radiology Appointment"
    _inherit = ["mail.thread", "mail.activity.mixin"]

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

    start = fields.Datetime( tracking=True)
    stop = fields.Datetime( tracking=True)

    duration = fields.Float(compute="_compute_duration", store=True)

    state = fields.Selection([
        ("draft", "Draft"),
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

    calendar_event_id = fields.Many2one("calendar.event")

    # -------------------------
    # COMPUTE
    # -------------------------
    @api.depends("start", "stop")
    def _compute_duration(self):
        for rec in self:
            if rec.start and rec.stop:
                diff = rec.stop - rec.start
                rec.duration = diff.total_seconds() / 3600
            else:
                rec.duration = 0.0

    # -------------------------
    # VALIDATION
    # -------------------------
    @api.constrains("start", "stop", "resource_id")
    def _check_dates(self):
        for rec in self:
            if rec.start and rec.stop and rec.start >= rec.stop:
                raise ValidationError("End must be after start")

    # -------------------------
    # CALENDAR EVENT
    # -------------------------
    def _create_calendar_event(self):
        for rec in self:
            event = self.env["calendar.event"].create({
                "name": f"Radiology - {rec.patient_id.name}",
                "start": rec.start,
                "stop": rec.stop,
                "partner_ids": [(6, 0, [
                    rec.patient_id.id,
                    rec.radiologist_id.id
                ])],
            })
            rec.calendar_event_id = event.id

    def action_open_calendar_event(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "calendar.event",
            "view_mode": "form",
            "res_id": self.calendar_event_id.id,
            "target": "current",
        }

    def action_open_slot_wizard(self):
        self.ensure_one()
        default_date = False
        if self.start:
            default_date = fields.Date.to_string(self.start.date())

        return {
            "type": "ir.actions.act_window",
            "res_model": "radiology.slot.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_patient_id": self.patient_id.id or False,
                "default_radiologist_id": self.radiologist_id.id or False,
                "default_resource_id": self.resource_id.id or False,
                "default_date": default_date,
            },
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
            ("start", "<", end),
            ("stop", ">", start),
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
            return fields.Datetime.from_string(value)

        return False

    def _check_radiologist_conflict(self, start, end, radiologist_id, exclude_id=None):

        if not radiologist_id:
            return False

        start = self._normalize_datetime_value(start)
        end = self._normalize_datetime_value(end)

        domain = [
            ("radiologist_id", "=", radiologist_id),
            ("state", "in", ["scheduled"]),
            ("start", "<", end),
            ("stop", ">", start),
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

            start = vals.get("start") or vals.get("start")
            end = vals.get("stop") or vals.get("stop")
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
                and rec.start
                and rec.stop
                and not rec.calendar_event_id
            ):
                rec._create_calendar_event()

        return records

    def write(self, vals):

        for rec in self:
            start = vals.get("start") or vals.get("start") or rec.start
            end = vals.get("stop") or vals.get("stop") or rec.stop
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
                and rec.start
                and rec.stop
            ):

                if not rec.calendar_event_id:

                    event = self.env["calendar.event"].create({
                        "name": f"Radiology - {rec.patient_id.name}",
                        "start": rec.start,
                        "stop": rec.stop,
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
                        "start": rec.start,
                        "stop": rec.stop,
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
    
    @api.constrains('start', 'stop', 'resource_id', 'radiologist_id')
    def _check_conflict_constraint(self):
        for rec in self:

            # ✅ ONLY validate when scheduled
            if rec.state != "scheduled":
                continue

            rec._validate_no_conflict(
                rec.start,
                rec.stop,
                rec.resource_id.id,
                rec.radiologist_id.id,
                rec.state,
                rec.id
            )