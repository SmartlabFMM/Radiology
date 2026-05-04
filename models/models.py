# from odoo import models, fields, api


# class radiology(models.Model):
#     _name = 'radiology.radiology'
#     _description = 'radiology.radiology'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

