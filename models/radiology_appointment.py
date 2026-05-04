from odoo import models, fields, api
from odoo.exceptions import ValidationError


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

    date_start = fields.Datetime()
    date_end = fields.Datetime()

    duration = fields.Float(default=1.0)

    state = fields.Selection([
        ("draft", "Waiting List"),
        ("scheduled", "Scheduled"),
        ("done", "Done"),
        ("cancel", "Cancelled"),
    ], default="draft")

    priority = fields.Selection([
        ("0", "Low"),
        ("1", "Normal"),
        ("2", "High"),
        ("3", "Urgent"),
    ], default="1")

    notes = fields.Text()