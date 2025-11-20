import re
from odoo import models, fields, api, Command


class FuelStation(models.Model):
    _name = 'station.station'
    _description = 'Stations'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True, size=4)
    next_sequence = fields.Integer(string='Next Sequence', default=1)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', required=True, domain="[('company_id', 'in', (company_id, False))]")
    partner_id = fields.Many2one(
        related='warehouse_id.partner_id', string='Address')
    cash_partner_id = fields.Many2one('res.partner', 
                                      string='Cash Sales Partner', 
                                      domain="[('company_id', 'in', (company_id, False))]")
    reading_type = fields.Selection(string='Meter Reading Type', 
                                    selection=[('electronic', 'Electronic'), ('manual', 'Manual')],
                                    default='electronic', required=True)
    
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    
    tank_ids = fields.One2many('station.tank', inverse_name='station_id', string='Tanks', copy=False)
    journal_ids = fields.Many2many('account.journal', 
                                  string='Banking Journals',
                                  required=True, 
                                  domain="[('company_id', 'in', (company_id, False))]")
    payment_mode_ids = fields.Many2many('account.journal', 
                                  string='Payment Modes',
                                  required=True, 
                                  relation='shift_payment_mode_rel',
                                  domain="[('company_id', 'in', (company_id, False))]")
    petty_cash_journal_id = fields.Many2one('account.journal', 
                                  string='Petty Cash Journal',
                                  required=True, 
                                  domain="[('company_id', 'in', (company_id, False))]")
    unbanked_journal_id = fields.Many2one('account.journal', 
                                  string='Unbanked Cash Journal',
                                  required=True, 
                                  domain="[('company_id', 'in', (company_id, False))]")
    expense_journal_id = fields.Many2one('account.journal', 
                                  string='Expenses Journal',
                                  required=True, 
                                  domain="[('company_id', 'in', (company_id, False))]")
    pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', required=True)
    last_shift_id = fields.Many2one('station.shift', string='Last Shift', readonly=True, copy=False)
    last_shift_date = fields.Date(string='Last Shift Date', related='last_shift_id.date', copy=False)
    closing_cash = fields.Float(string='Closing Cash', related='last_shift_id.closing_balance', copy=False)
    operation_type_id = fields.Many2one('stock.picking.type', 
                                        string='Operation Type',
                                        required=True,
                                        domain=[('code', '=', 'incoming')],
                                        help="Operation type to use to transfer stock into the station.")
    dry_stock_location_id = fields.Many2one('stock.location', string='Dry Stock Location',
                                            domain="[('usage', '=', 'internal')]", required=True)
    partner_ids = fields.Many2many('res.partner', string='Credit Customer',
                                   domain="[('company_id', 'in', (company_id, False))]", copy=True)
    
    liability_account_id = fields.Many2one(
        "account.account",
        string="Excess Payments Account",
        required=True,
        domain=lambda self: f"[('account_type', 'in', ('asset_current', 'asset_non_current')), ('active', '=', True)]",
        help="Excess customer payments will be posted into this account")
    loss_account_id = fields.Many2one(
        "account.account",
        string="Loss Account",
        required=True,
        domain=lambda s: f"[('account_type', 'in', ('liability_current', 'liability_non_current')),('active', '=', True)]",
        help="Station payments loss will be posted into this account")
    allowable_cash_variance = fields.Monetary(string='Allowed Cash Variance', currency_field='currency_id')
    product_ids = fields.Many2many('product.product', string='Products', compute='_compute_product_ids')
    shift_history_ids = fields.Many2many('shift.history',
                                         string='Station Shift History',
                                         domain=lambda s: [('station_id', '=', s.id)],
                                         readonly=True)
    
    _sql_constraints = [
        ('code_uniq', 'UNIQUE(code, company_id)', 'Code must be unique per company'),
    ]
    
    def _compute_product_ids(self):
        product = self.env['product.product']
        for rec in self:
            rec.product_ids = product.search([('product_tmpl_id', 'in', rec.pricelist_id.item_ids.mapped('product_tmpl_id').ids)])

    @api.constrains('pricelist_id')
    def _constrains_pricelist_id(self):
        for rec in self:
            rec.pricelist_id.station_id = rec.id
    
    def link_pricelists(self):
        for rec in self:
            rec.pricelist_id.write({'station_id': rec.id})
    
    def _duplicate_tanks(self, duplicate_tanks):
        tanks = []
        for tank in duplicate_tanks:
            location = tank.location_id.copy(default={
                'location_id': self.warehouse_id.lot_stock_id.id, 
                'name': self.warehouse_id.lot_stock_id.name
                })
            tanks.append(Command.create({
                'name': tank.name,
                'location_id': location.id,
                'station_id': tank.name,
                'uom_id': tank.uom_id.id,
                'product_id': tank.product_id.id,
                'gun_ids': [Command.create({
                    'name': gun.name, 
                    'pump': gun.pump, 
                    }) for gun in tank.gun_ids]
            }))
        return tanks
    
    def _related_duplicates(self, code):
        station_pricelist = self.pricelist_id.copy(default={'name': f'{code} Pricelist'})        
        warehouse = self.warehouse_id.copy(default={'name': f'WH-{code}', 'code': code})
        warehouse.view_location_id.write({'name': code})
        dry_stock_location = self.dry_stock_location_id.copy(default={'name': f'{code}', 'location_id': warehouse.lot_stock_id.id})
        return dict(
            warehouse_id=warehouse.id,
            operation_type_id=warehouse.in_type_id.id,
            dry_stock_location_id=dry_stock_location.id,
            pricelist_id=station_pricelist.id
        )

    
    def copy(self, default=None):
        default = dict(default or {})

        # Find a unique code for the copied station
        station_model = self.env['station.station'].with_context(active_test=False)
        read_codes = station_model.search_read([('company_id', '=', self.company_id.id)], ['code'])
        all_codes = {code_data['code'] for code_data in read_codes}

        copy_code = self.code
        code_prefix = re.sub(r'\d+', '', self.code).strip()
        copy_prefix = code_prefix[:self._fields['code'].size - 1]
        counter = 1
        while copy_code in all_codes:
            copy_code = f"{copy_prefix}{counter}"
            counter += 1
            
        default.update(code=copy_code, name=f'{copy_code} - copy', **self._related_duplicates(copy_code))
        res =  super().copy(default)
        self.env.user.employee_ids.write({'station_ids': [(4, res.id)]})
        res.write({'tank_ids': res._duplicate_tanks(self.tank_ids)})
        return res
    
    
class StationTank(models.Model):
    _name = 'station.tank'
    _description = 'Station Tanks'

    name = fields.Char(string='Name', required=True)
    active = fields.Boolean(string='Active', default=True)
    station_id = fields.Many2one('station.station', string='Station')
    location_id = fields.Many2one(
        'stock.location', string='Location', required=True, domain="[('company_id', 'in', (company_id, False))]")
    current_volume = fields.Float(string='Current Volume', readonly=False, copy=False)
    max_volume = fields.Float(string='Max Volume')
    gun_ids = fields.One2many(
        'station.gun', inverse_name='tank_id', string='Guns', copy=True)
    company_id = fields.Many2one(
        related='station_id.company_id', string='Company')
    product_id = fields.Many2one('product.product',
                                 string='Product',
                                 domain="[('is_wet_product', '=', True), ('company_id', 'in', (company_id, False))]")
    uom_id = fields.Many2one('uom.uom', string='Uom', required=True, domain="[('relative_uom_id', '=', uom_category_id)]")
    uom_category_id = fields.Many2one(related='product_id.uom_id.relative_uom_id')
    allowable_variance = fields.Float(string='Allow Tank VAR')
    allowable_gun_variance = fields.Float(string='Allow Gun VAR')
    
    
    _sql_constraints = [
        ('location_uniq', 'UNIQUE(location_id)',
         'Tank location must be unique per product'),
    ]
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        for rec in self:
            rec.write({'uom_id': rec.product_id.uom_id.id})


class StationGuns(models.Model):
    _name = 'station.gun'
    _description = 'Station Guns'

    name = fields.Char(string='Name', required=True)
    tank_id = fields.Many2one('station.tank', string='Tank')
    station_id = fields.Many2one(related='tank_id.station_id', string='Station')
    pump = fields.Char(string='Pump')
    product_id = fields.Many2one(related='tank_id.product_id', string='Product')
    company_id = fields.Many2one(related='tank_id.company_id', string='Company')
    last_reading = fields.Float(string='Last Reading', readonly=False, copy=False)
    last_manual_reading = fields.Float(string='Last Manual Reading', readonly=False, copy=False)
    last_cash_reading = fields.Float(string='Last Cash Reading', readonly=False, copy=False)

