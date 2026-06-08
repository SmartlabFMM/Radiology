from odoo import models, fields, api


class RadiologyWorkingHours(models.Model):
    _name = "radiology.working.hours"
    _description = "Radiology Working Hours"

    name = fields.Char(required=True, default=lambda self: "New Working Hours")
    radiologist_id = fields.Many2one(
        "res.partner",
        domain="[('is_radiologist', '=', True)]",
        tracking=True,
        required=True,
    )

    resource_id = fields.Many2one(
        "resource.resource",
        string="Machine",
        required=True,
        tracking=True,
    )

    slot_duration = fields.Float(
        string="Slot Duration (hours)",
        default=0.5,
        digits=(6, 2),
        help="Each machine slot length, e.g. 0.5 for 30 minutes or 1.0 for 60 minutes.",
    )

    line_ids = fields.One2many(
        "radiology.working.hours.line",
        "config_id",
    )

    active = fields.Boolean(default=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done')
    ], default='draft')

    def action_open_slot_wizard(self):
        self.ensure_one()
        wizard = self.env['radiology.slot.wizard'].create({
            'radiologist_id': self.radiologist_id.id or False,
            'resource_id': self.resource_id.id or False,
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


    @api.model
    def create(self, vals):
        record = super().create(vals)

        if record.line_ids:
            return record

        shifts = {
            "morning": (8.0, 14.0),
            "evening": (14.0, 20.0),
        }

        lines = []

        for day in range(7):
            for shift_name, (start, end) in shifts.items():

                if day == 6 and shift_name == "evening":
                    continue

                lines.append((0, 0, {
                    "weekday": str(day),
                    "shift": shift_name,
                    "hour_from": start,
                    "hour_to": end,
                }))

        record.write({"line_ids": lines})

        return record
