from odoo import models, fields, api
from odoo.exceptions import ValidationError

class RadiologyWorkingHours(models.Model):
    _name = "radiology.working.hours"
    _description = "Radiology Working Hours"
    _order = "weekday, hour_from"

    name = fields.Char(required=True)

    resource_id = fields.Many2one("resource.resource", string="Machine")
    radiologist_id = fields.Many2one("res.partner", string="Radiologist")

    weekday = fields.Selection([
        ("0", "Monday"),
        ("1", "Tuesday"),
        ("2", "Wednesday"),
        ("3", "Thursday"),
        ("4", "Friday"),
        ("5", "Saturday"),
        ("6", "Sunday"),
    ], required=True)

    hour_from = fields.Float(required=True)
    hour_to = fields.Float(required=True)

    active = fields.Boolean(default=True)

    @api.constrains("hour_from", "hour_to")
    def _check_hours(self):
        for rec in self:
            if rec.hour_from >= rec.hour_to:
                raise ValidationError("Start time must be before end time.")

    @api.constrains("weekday", "resource_id", "radiologist_id")
    def _check_overlap(self):
        for rec in self:
            domain = [
                ("id", "!=", rec.id),
                ("weekday", "=", rec.weekday),
                ("active", "=", True),
                "|",
                ("resource_id", "=", rec.resource_id.id),
                ("radiologist_id", "=", rec.radiologist_id.id),
            ]

            overlaps = self.search(domain)

            for o in overlaps:
                if not (rec.hour_to <= o.hour_from or rec.hour_from >= o.hour_to):
                    raise ValidationError("Overlapping working hours detected.")
    

    def get_applicable_hours(self, resource_id, radiologist_id, weekday):
        domain = [
            ("active", "=", True),
            ("weekday", "=", str(weekday)),
            "|", "|",
            ("resource_id", "=", resource_id),
            ("radiologist_id", "=", radiologist_id),
            ("resource_id", "=", False),
            ("radiologist_id", "=", False),
        ]

        return self.search(domain)

    def _is_within_working_hours(self, start, end, resource_id, radiologist_id):

        weekday = start.weekday()
        hours = self.env["radiology.working.hours"].get_applicable_hours(
            resource_id, radiologist_id, weekday
        )

        start_h = start.hour + start.minute / 60
        end_h = end.hour + end.minute / 60

        for h in hours:
            if start_h >= h.hour_from and end_h <= h.hour_to:
                return True

        return False