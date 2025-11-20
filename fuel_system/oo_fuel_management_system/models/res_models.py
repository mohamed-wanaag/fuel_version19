from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @property
    def income_account_id(self):
        return self.property_account_receivable_id or self.parent_id.property_account_receivable_id
    