from odoo import models, fields, api
from odoo.exceptions import ValidationError


class RadiologyWorkingHoursLine(models.Model):
    _name = "radiology.working.hours.line"
    _description = "Radiology Working Hours Line"

    config_id = fields.Many2one("radiology.working.hours", required=True, ondelete="cascade")

    name = fields.Char(required=True, default=lambda self: "New Working Hours Line")


    weekday = fields.Selection([
        ("0", "Monday"),
        ("1", "Tuesday"),
        ("2", "Wednesday"),
        ("3", "Thursday"),
        ("4", "Friday"),
        ("5", "Saturday"),
        ("6", "Sunday"),
    ], required=True)

    shift = fields.Selection([
        ("morning", "Morning"),
        ("evening", "Evening"),
    ], required=True)

    hour_from = fields.Float(required=True)
    hour_to = fields.Float(required=True)

    @api.constrains("weekday", "hour_from", "hour_to", "config_id")
    def _check_overlap(self):
        for line in self:
            siblings = self.search([
                ("id", "!=", line.id),
                ("config_id", "=", line.config_id.id),
                ("weekday", "=", line.weekday),
            ])

            for o in siblings:
                if not (line.hour_to <= o.hour_from or line.hour_from >= o.hour_to):
                    raise ValidationError(
                        "Overlapping hours in same day are not allowed."
                    )

    
    def action_open_slot_wizard(self):
        self.ensure_one()
        wizard = self.env['radiology.slot.wizard'].create({
            'radiologist_id': self.config_id.radiologist_id.id or False,
            'resource_id': self.config_id.resource_id.id or False,
            'date': self.env['radiology.slot.wizard']._fields['date'].default(self),
        })
        wizard._generate_slots()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'radiology.slot.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }