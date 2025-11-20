from odoo import models, fields, api


class StationExpense(models.Model):
    _name = 'station.expense'
    _description = 'Station Shift Expenses'

    def _default_station_id(self):
        employee = self.env.user.employee_id
        return employee.station_ids and employee.station_ids[0]
    
    station_id = fields.Many2one('station.station', string='Station', required=True, default=_default_station_id)
    shift_id = fields.Many2one('station.shift', 
                               string='Shift',
                               domain="[('station_id', '=', station_id), ('state', '=', 'running')]")
    company_id = fields.Many2one(
        related='station_id.company_id', string='Company')
    name = fields.Char(string='Name', readonly=True, default='/')
    expense_line = fields.One2many('station.expense.line', inverse_name='expense_id', string='Items')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['name'] = self.env['ir.sequence'].next_by_code('station.expense.sequence')
        return super().create(vals_list)
    
    
class StationExpenseLine(models.Model):
    _name = 'station.expense.line'
    _description = 'Station expense lines'
    
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain="[('company_id', 'in', (company_id, False)), ('can_be_expensed', '=', True)]")
    expense_id = fields.Many2one('station.expense', string='Expense')
    station_id = fields.Many2one(
        related='expense_id.company_id', string='Station')
    company_id = fields.Many2one(
        related='expense_id.company_id', string='Company')
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    name = fields.Char(string='Name')
    amount = fields.Monetary('Amount', currency_field='currency_id')
    
    
    