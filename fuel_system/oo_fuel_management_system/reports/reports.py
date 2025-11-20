from odoo import models, api
from collections import OrderedDict


class StationShiftReports(models.Model):
    _inherit = 'station.shift'

    @api.model
    def _get_daily_summary_report(self):
        self.ensure_one()
        wet = sum(self.summary_line.mapped('wet_quantity'))
        dry = sum(self.dry_sale_line.mapped('amount'))
        service = sum(self.other_sale_line.mapped('amount'))
        collections = sum(self.summary_line.mapped('collections'))

        rtt = self.gun_sale_line.filtered('rtt').mapped(lambda g: (g.rtt, g.price_unit))
        dry_discount = sum(self.dry_sale_line.mapped('discount'))
        other_discount = sum(self.other_sale_line.mapped('discount'))
        credit_discount = sum(self.credit_sale_line.mapped('discount'))
        direct_discount = sum(self.direct_sale_line.mapped('discount'))

        payments = {'Less (-): Credit Sales': sum(self.credit_sale_line.mapped('amount'))}
        payment_modes = self.station_id.payment_mode_ids - self.station_id.unbanked_journal_id
        for mode in payment_modes:
            payments[f'Less (-): {mode.name} Sales'] = sum(
                self.payment_line.filtered(lambda p: p.journal_id == mode).mapped('amount'))

        data = OrderedDict({
            'FUEL SALES': wet,
            'Add (+): DRY STOCK SALES': dry,
            'Add (+): SERVICE SALES': service,
            'Add (+): CASH COLLECTIONS': collections,
            'TOTAL GROSS INCOME': wet + dry + service + collections,
            'DEDUCTIONS': '',
            'Less (-): Fuel Transfers, Pump Test/ RTT & Gen. Fuel': sum(map(lambda r: r[0] * r[1], rtt)),
            'Less (-/+): Price Difference': 0,
            'Less (-): Discounts': dry_discount + other_discount + credit_discount + direct_discount,
            'Less (-): Expenses': sum(self.expense_line.mapped('amount')),
            'TOTAL NET SALES (Gross Sales - Deductions)': sum(self.summary_line.mapped('total_sales'))
        })
        data.update(payments)
        data['Attendant Excess/ Short +/-'] = sum(self.summary_line.mapped('variance'))
        data['TOTAL CASH EXPECTED FOR THE DAY'] = self.cash_collected
        data['Less (-): Cash Banked'] = self.cash_banked
        data['Add:B/F +/-'] = self.opening_balance
        data['CASH AT HAND/CASH CARRIED FORWARD'] = self.closing_balance
        bolded = ['TOTAL GROSS INCOME', 'TOTAL NET SALES (Gross Sales - Deductions)', 
                  'TOTAL CASH EXPECTED FOR THE DAY', 'CASH AT HAND/CASH CARRIED FORWARD']
        return data, bolded
