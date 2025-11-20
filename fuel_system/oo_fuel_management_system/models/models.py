from odoo import api, models, fields
from odoo.exceptions import ValidationError


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'
    
    station_id = fields.Many2one('station.station', string='Linked Station')
    

class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    
    station_ids = fields.Many2many('station.station', string='Stations')
    fms_variance_ids = fields.One2many('fms.variance.line', inverse_name='employee_id', string='Variances')


class FmsVarianceLine(models.Model):
    _name = 'fms.variance.line'
    _description = 'Employee FMS Losses'
    
    employee_id = fields.Many2one('hr.employee', string='Employee')
    name = fields.Char(string='Description')
    amount = fields.Float(string='Amount')
    shift_id = fields.Many2one('station.shift', string='Shift')
    date = fields.Date(related='shift_id.date', string='Date')
    
    
class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    is_wet_product = fields.Boolean(string='Wet Product')
    is_dry_stock = fields.Boolean(string='Dry Stock')
    stock_type = fields.Selection(string='Stock Type', 
                                  selection=[('lube', 'Lubes'), ('lpg', 'LPG'),('other', 'Others')])

class Product(models.Model):
    _inherit = 'product.product'

    @property
    def expense_account_id(self):
        return self.property_account_expense_id or self.categ_id.property_account_expense_categ_id
    
    @property
    def income_account_id(self):
        return self.property_account_income_id or self.categ_id.property_account_income_categ_id
    
    
class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')

    def _prepare_invoice(self):
        res = super()._prepare_invoice()
        res['shift_id'] = self.shift_id.id
        res['invoice_date'] = self._context.get('context_date', res.get('invoice_date'))
        return res
    
    def _prepare_confirmation_values(self):
        return {
            'state': 'sale',
            'date_order': self._context.get('context_date') or self.date_order or fields.Datetime.now()
        }
    
    
class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
        
    employee_id = fields.Many2one('hr.employee', string='Shift Employee')
    location_id = fields.Many2one('stock.location', string='Location')
    
    def _prepare_procurement_values(self, group_id=False):
        res = super()._prepare_procurement_values(group_id)
        if self.location_id:
            res.update(location_id=self.location_id.id, date=self.order_id.date_order)
        return res
    
    
class AccountPayment(models.Model):
    _inherit = 'account.payment'
    
    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            journal = self.env['account.journal'].browse(vals['journal_id'])
            if vals['payment_type'] == 'inbound':
                if not journal.inbound_payment_method_line_ids:
                    raise ValidationError(
                        f'Please define an inbound payment method line for the journal {journal.name}')
                if not journal.inbound_payment_method_line_ids.filtered(lambda i: i.id == vals.get('payment_method_line_id')):
                    vals['payment_method_line_id'] = journal.inbound_payment_method_line_ids[0].id
                    
            if vals['payment_type'] == 'outbound':
                if not journal.outbound_payment_method_line_ids:
                    raise ValidationError(
                        f'Please define an outbound payment method line for the journal {journal.name}')
                if not journal.outbound_payment_method_line_ids.filtered(lambda i: i.id == vals.get('payment_method_line_id')):
                    vals['payment_method_line_id'] = journal.outbound_payment_method_line_ids[0].id

        return super().create(vals_list)
    
    
class AccountMove(models.Model):
    _inherit = 'account.move'
    
    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')


class StockPicking(models.Model):
    _inherit = 'stock.picking'
    
    shift_id = fields.Many2one('station.shift', string='Shift')


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    shift_id = fields.Many2one('station.shift', string='Shift')
    station_processed = fields.Boolean(string='Station Processed')
    
    
class StockRule(models.Model):
    _inherit = 'stock.rule'
    
    def _get_custom_move_fields(self):
        res = super()._get_custom_move_fields()
        res.extend(['location_id', 'date'])
        return res