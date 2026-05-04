from odoo import models, fields


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_patient = fields.Boolean()
    is_radiologist = fields.Boolean()

    medical_id = fields.Char()
    specialization = fields.Char()