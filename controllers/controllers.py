# from odoo import http


# class Radiology(http.Controller):
#     @http.route('/radiology/radiology', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/radiology/radiology/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('radiology.listing', {
#             'root': '/radiology/radiology',
#             'objects': http.request.env['radiology.radiology'].search([]),
#         })

#     @http.route('/radiology/radiology/objects/<model("radiology.radiology"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('radiology.object', {
#             'object': obj
#         })

