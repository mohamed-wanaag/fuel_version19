from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_print_proforma_invoice(self):
        return self.env.ref(
            "oo_fuel_management_system.action_report_proforma_invoice"
        ).report_action(self)

    def action_print_invoice2(self):
        return self.env.ref(
            "oo_fuel_management_system.sales_order_report"
        ).report_action(self)
