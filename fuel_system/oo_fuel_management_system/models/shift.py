import logging

from collections import defaultdict
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


STATES = [
    ('draft', 'Starting'),
    ('running', 'In Progress'),
    ('done', 'Closed'),
    ('waiting_approval', 'Waiting Approval'),
    ('approved', 'Approved'),
    ('interfaced', 'Interfaced'),
    ('cancelled', 'Cancelled')
]


class StationShift(models.Model):
    _name = 'station.shift'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc'
    _description = 'Station Shifts'

    def _default_station_id(self):
        stations = self.env.user.employee_id.station_ids
        if stations:
            return stations[0]
        return self.env['station.station'].search(
            [('company_id', '=', self.env.company.id), ('tank_ids', '!=', [])], limit=1)

    state = fields.Selection(
        string='Status', default='draft', selection=STATES, tracking=True)
    type_id = fields.Many2one('station.shift.type',
                              string='Shift Type', required=True, tracking=True, copy=False)
    date = fields.Date(string='Date', required=True, tracking=True, copy=False)
    name = fields.Char(string='Name', required=True,
                       default='/', readonly=True, copy=False, tracking=True)
    closing_warning = fields.Char(string='Closing Warning', compute='_compute_closing_warning', store=True)
    has_starting_warning = fields.Boolean(string='Starting Warning')
    show_starting_warning = fields.Boolean(string='Show Starting Warning')
    is_admin = fields.Boolean(string='Station Admin', compute='_compute_user_access')
    can_approve = fields.Boolean(string='Can Approve', compute='_compute_user_access')
    station_id = fields.Many2one(
        'station.station', string='Station', required=True, default=_default_station_id, tracking=True)
    company_id = fields.Many2one(related='station_id.company_id', string='Company')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    opening_balance = fields.Float(string='Opening Balance', readonly=True)
    cash_collected = fields.Float(
        string='Cash Collected', compute='_compute_balances')
    cash_banked = fields.Float(string='Cash Banked', compute='_compute_balances')
    closing_balance = fields.Float(
        string='Closing Balance', compute='_compute_balances')
    petty_cash_opening = fields.Float(
        string='Opening Petty Cash', readonly=True)
    petty_cash_spent = fields.Float(
        string='Petty Cash Spent', compute='_compute_balances')
    petty_cash_reimbursed = fields.Float(string='Re-imbursed Petty Cash')
    total_expenses = fields.Float(
        string='Expenses', compute='_compute_balances')
    closing_petty_cash = fields.Float(
        string='Closing Petty Cash', compute='_compute_balances')
    default_employee_id = fields.Many2one(
        'hr.employee', string='Default Dry Sales Employee', domain="[('station_ids', 'in', station_id)]")

    sale_ids = fields.Many2many('sale.order', string='Sales', readonly=True)
    sales_count = fields.Integer(
        string='Sales Count', compute='_compute_transactions')
    move_ids = fields.Many2many('account.move', string='Moves', readonly=True)
    moves_count = fields.Integer(
        string='Moves Count', compute='_compute_transactions')
    picking_ids = fields.Many2many(
        'stock.picking', string='Transfers', readonly=True)
    pickings_count = fields.Integer(
        string='Pickings Count', compute='_compute_transactions')
    payment_ids = fields.Many2many(
        'account.payment', string='Account Payments', readonly=True)
    payments_count = fields.Integer(
        string='Payments Count', compute='_compute_transactions')

    gun_sale_line = fields.One2many(
        'shift.gun.sale.line', inverse_name='shift_id', string='Gun Sales')
    dry_sale_line = fields.One2many(
        'shift.dry.sale.line', inverse_name='shift_id', string='Dry Stock Sales')
    other_sale_line = fields.One2many(
        'shift.other.sale.line', inverse_name='shift_id', string='Other Sales')
    credit_sale_line = fields.One2many(
        'shift.credit.sale.line', inverse_name='shift_id', string='Credit Sales')
    direct_sale_line = fields.One2many(
        'shift.direct.sale.line', inverse_name='shift_id', string='Direct Sales')
    collection_line = fields.One2many(
        'shift.collection.line', inverse_name='shift_id', string='Shift Collections')
    summary_line = fields.One2many(
        'shift.summary.line', inverse_name='shift_id', string='Shift Summary')
    tank_stock_take_line = fields.One2many(
        'shift.tank.stock.take', 'shift_id', string='Tank Stock Take Lines')
    expense_line = fields.One2many(
        'shift.expense.line', 'shift_id', string='Shift Expenses')
    petty_line = fields.One2many(
        'shift.petty.cash.line', 'shift_id', string='Petty Cash ')
    banking_line = fields.One2many(
        'shift.banking.line', 'shift_id', string='Banking', domain="[('line_type', '=', 'banking')]")
    payment_line = fields.One2many(
        'shift.payment.line', 'shift_id', string='Payments', domain="[('line_type', '=', 'payment')]")
    received_stock_line = fields.One2many(
        'shift.transfer.line', inverse_name='shift_id', string='Received Stock')

    _sql_constraints = [
        ('type_date_stationid_state_uniq', 'UNIQUE(type_id,date,station_id,state)',
         'Another shift for the same station already exists in the same perid and status'),
    ]

    @property
    def is_station_accountant(self):
        return self.env.user.has_group('oo_fuel_management_system.group_station_management_manager')

    @property
    def is_station_admin(self):
        return self.env.user.has_group('oo_fuel_management_system.group_station_management_manager')
    
    @api.onchange('company_id')
    def _onchange_company_id(self):
        for rec in self:
            rec.currency_id = rec.company_id.currency_id

    @api.depends('state')
    def _compute_closing_warning(self):
        for rec in self:
            rec.closing_warning = False
            pending_sales = rec.sale_ids.filtered(lambda s: s.state == 'draft')
            pending_pickings = rec.picking_ids.filtered(
                lambda p: p.state != 'done')
            if pending_sales or pending_pickings:
                rec.closing_warning = 'Some sales and transfers could not be automatically validated,\
                    please use the magic buttons below to manually validate'

    def _compute_user_access(self):
        for rec in self:
            rec.is_admin = self.is_station_admin
            rec.can_approve = self.is_station_accountant

    @api.depends('sale_ids', 'move_ids', 'picking_ids', 'payment_ids')
    def _compute_transactions(self):
        for rec in self:
            rec.sales_count = len(rec.sale_ids)
            rec.moves_count = len(rec.move_ids)
            rec.pickings_count = len(rec.picking_ids)
            rec.payments_count = len(rec.payment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            station = self.env['station.station'].browse(vals['station_id'])
            vals['name'] = f'FMS/{station.code}/{station.next_sequence:04}'
            station.write({'next_sequence': station.next_sequence + 1})
        return super().create(vals_list)

    @api.constrains('petty_cash_reimbursed', 'petty_cash_spent', 'petty_cash_opening')
    def _constrains_petty_cash(self):
        for rec in self:
            petty_cash = rec.petty_cash_reimbursed + rec.petty_cash_opening
            if rec.petty_cash_spent > petty_cash:
                raise ValidationError('Petty cash spent cannot exceed total petty cash available!')

    @api.constrains('cash_banked', 'cash_collected', 'opening_balance')
    def _constrains_cash_banked(self):
        for rec in self:
            cash = rec.opening_balance + rec.cash_collected
            if rec.cash_banked > cash:
                raise ValidationError('Cash banked cannot exceed total cash available!')

    @api.constrains('date', 'type_id', 'station_id')
    def _constrains_shift_period(self):
        for rec in self:
            existing = self.search(
                [('station_id', '=', rec.station_id.id),
                 ('date', '=', rec.date), ('type_id', '=', rec.type_id.id), ('id', '!=', rec.id)], limit=1)
            if existing:
                raise ValidationError('A shift for the same day and type already exists!')
            existing = self.search([
                ('id', '!=', rec.id),
                ('date', '=', rec.date),
                ('type_id', '=', rec.type_id.id),
                ('type_id.sequence', '>', rec.type_id.sequence),
            ])
            if existing:
                raise ValidationError(
                    f"Shift of type {rec.type_id.name} cannot be added after a shift of type {existing.type_id.name}!")
        
    def _validate_start_shift(self):
        self.ensure_one()
        if self.date and self.date > fields.date.today():
            raise ValidationError('You cannot start a future shift!')
            
        existing = self.search(
                [('station_id', '=', self.station_id.id),
                 ('date', '=', self.date),
                 ('id', '!=', self.id),
                 ('state', 'in', ('draft', 'running', 'done', 'waiting_approval'))
                 ], limit=1)
        if existing:
            raise ValidationError(f'You cannot start a shift while another shift is open: Shift {existing.name}')
        
        return self.env['shift.history'].linear_validate(self)
        
    def action_start(self):
        for rec in self:
            history = rec._validate_start_shift()
            if history:  
                guns = self.env['station.gun'].search([('station_id', '=', rec.station_id.id)])
                tanks = self.env['station.tank'].search([('station_id', '=', rec.station_id.id)])

                guns = guns.filtered(lambda g: g.id not in rec.gun_sale_line.mapped('gun_id.id'))
                tanks = tanks.filtered(lambda t: t.id not in rec.tank_stock_take_line.mapped('tank_id.id'))
                rec.write({
                    'gun_sale_line': [(0, 0, {'gun_id': gun.id}) for gun in guns],
                    'tank_stock_take_line': [(0, 0, {'tank_id': tank.id, 'opening_qty': tank.current_volume}) for tank in tanks],
                    'state': 'running',
                    'opening_balance': self.station_id.closing_cash,
                    'petty_cash_opening': self.station_id.last_shift_id.closing_petty_cash
                })
                rec.gun_sale_line._oncreate_populate()
                rec.tank_stock_take_line._onchange_tank_id()
            else:
                self.has_starting_warning = True
                self.show_starting_warning = True

    def action_skip_starting_warning(self):
        self.show_starting_warning = False
        self.env['shift.history'].add_current(self)
        return self.action_start()
        
    def _validate_product_availability(self):
        for rec in self:
            warning = 'Following products do not have enough availability \n'
            for tank in rec.station_id.tank_ids:
                gun_sale = sum(rec.gun_sale_line.filtered(lambda g: g.tank_id == tank).mapped('net_sales'))
                direct = sum(rec.direct_sale_line.filtered(lambda d: d.tank_id == tank).mapped('quantity'))
                credit = sum(rec.credit_sale_line.filtered(lambda c: c.product_id == tank.product_id).mapped('quantity'))
                incoming = sum(rec.received_stock_line.filtered(
                    lambda r: r.product_id == tank.product_id and r.location_id == tank.location_id).mapped('quantity'))
                current_quantity = self.env['stock.quant']._get_available_quantity(tank.product_id, tank.location_id)
                sales = gun_sale + direct + credit
                forecast = current_quantity + incoming
                if sales > forecast:
                    warning += f'{tank.product_id.name}: Total sale: {sales} / Forecast: {forecast} \n'

            dry_stock = rec.dry_sale_line.mapped('product_id')
            for product in dry_stock:
                sale = sum(rec.dry_sale_line.filtered(lambda d: d.product_id == product).mapped('quantity'))
                credit = sum(rec.credit_sale_line.filtered(lambda c: c.product_id == product).mapped('quantity'))
                incoming = sum(rec.received_stock_line.filtered(
                    lambda r: r.product_id == product and r.location_id == rec.station_id.dry_stock_location_id).mapped('quantity'))
                current_quantity = self.env['stock.quant']._get_available_quantity(product, rec.station_id.dry_stock_location_id)
                sales = sale + credit
                forecast = incoming + current_quantity
                if sales > forecast:
                    warning += f'{product.name}: Total sale: {sales} / Forecast: {forecast} \n'

            rec.closing_warning = warning

    def _validate_lines(self):
        if self.mapped('gun_sale_line').filtered(lambda g: not g.employee_id):
            raise ValidationError('Missing Employee in Gun sales')
        
        self.dry_sale_line._validate_lines()
        for line in self.received_stock_line:
            line._validate_incoming_stock_availability()
        
        self.gun_sale_line._compute_price()
        self.dry_sale_line._compute_price()
        self.other_sale_line._compute_price()
        self.direct_sale_line._compute_price()
        self.credit_sale_line._compute_price()
        self.tank_stock_take_line._calculate_tank_operations()

    def action_draft(self):
        for rec in self:
            to_state = 'draft' if rec.state == 'cancelled' else 'running'
            rec.write({'state': to_state})

    def action_move_in_progress(self):
        self.write({'state': 'running'})
        
    def action_compute_shift(self):
        for rec in self:
            rec._validate_lines()
            rec.summary_line = [(5, 0, 0)]
            employee_group = defaultdict(dict)

            for line in rec.gun_sale_line:
                wet = employee_group[line.employee_id.id].get('wet_quantity', 0)
                employee_group[line.employee_id.id]['wet_quantity'] = wet + line.amount

            for line in rec.dry_sale_line:
                if line.product_id.stock_type == 'lube':
                    discount = employee_group[line.employee_id.id].get('discount', 0)
                    lubes = employee_group[line.employee_id.id].get('lubes_quantity', 0)
                    employee_group[line.employee_id.id]['lubes_quantity'] = lubes + line.amount
                    employee_group[line.employee_id.id]['discount'] = discount + line.discount

                if line.product_id.stock_type == 'lpg':
                    discount = employee_group[line.employee_id.id].get('discount', 0)
                    lpg = employee_group[line.employee_id.id].get('lpg_quantity', 0)
                    employee_group[line.employee_id.id]['lpg_quantity'] = lpg + line.amount
                    employee_group[line.employee_id.id]['discount'] = discount + line.discount

            for line in rec.other_sale_line:
                discount = employee_group[line.employee_id.id].get('discount', 0)
                others = employee_group[line.employee_id.id].get('others_quantity', 0)
                employee_group[line.employee_id.id]['others_quantity'] = others + line.amount
                employee_group[line.employee_id.id]['discount'] = discount + line.discount

            for line in rec.credit_sale_line:
                credit = employee_group[line.employee_id.id].get('credit_sales', 0)
                employee_group[line.employee_id.id]['credit_sales'] = credit + line.amount

                if line.product_id.stock_type == 'lube':
                    lubes = employee_group[line.employee_id.id].get('lubes_quantity', 0)
                    employee_group[line.employee_id.id]['lubes_quantity'] = lubes + line.amount

                if line.product_id.stock_type == 'lpg':
                    lpg = employee_group[line.employee_id.id].get('lpg_quantity', 0)
                    employee_group[line.employee_id.id]['lpg_quantity'] = lpg + line.amount

                if line.product_id.stock_type == 'other':
                    others = employee_group[line.employee_id.id].get('others_quantity', 0)
                    employee_group[line.employee_id.id]['others_quantity'] = others + line.amount

            for line in rec.direct_sale_line:
                direct = employee_group[line.employee_id.id].get('direct_sale', 0)
                employee_group[line.employee_id.id]['direct_sale'] = direct + line.amount

            for line in rec.collection_line:
                collected = employee_group[line.employee_id.id].get('collections', 0)
                employee_group[line.employee_id.id]['collections'] = collected + line.amount

            for line in rec.expense_line:
                expense = employee_group[line.employee_id.id].get('expenses', 0)
                employee_group[line.employee_id.id]['expenses'] = expense + line.amount

            for line in rec.payment_line.filtered(lambda b: b.line_type == 'payment'):
                cash_collected = employee_group[line.employee_id.id].get('cash_collected', 0)
                employee_group[line.employee_id.id]['cash_collected'] = cash_collected + line.amount

            for _id, group in employee_group.items():
                group['employee_id'] = _id

            summary_line = list(map(lambda c: (0, 0, c), employee_group.values()))
            rec.write({'summary_line': summary_line, 'opening_balance': self.station_id.closing_cash})
            rec.tank_stock_take_line._calculate_tank_operations()
            rec.summary_line._compute_amounts()

    def action_done(self):
        self._validate_lines()
        self.tank_stock_take_line._close()
        self.gun_sale_line._validate_closing()
        self.summary_line._validate_closing()
        self._validate_product_availability()
        self.write({'state': 'done', 'opening_balance': self.station_id.closing_cash})

    def _validate_orders(self, group):
        self.ensure_one()
        orders = self.env['sale.order']
        moves = self.env['account.move']

        for partner, lines in group.items():
            order = self.env['sale.order'].create({
                'partner_id': partner,
                'date_order': self.date,
                'shift_id': self.id,
                'warehouse_id': self.station_id.warehouse_id.id,
                'pricelist_id': self.station_id.pricelist_id.id,
                'order_line': lines,
            })
            orders |= order
            date_ctx = {'context_date': self.date}
            order.with_context(date_ctx).action_confirm()
            if order.picking_ids:
                order.picking_ids.action_confirm()
                order.picking_ids.action_assign()
                if any(order.picking_ids.mapped('show_check_availability')):
                    raise ValidationError("Some of the selected products have no availability!")

                order.picking_ids.with_context(skip_sms=True, skip_immediate=True).button_validate()
                moves |= order.with_context(date_ctx)._create_invoices()
        return orders, moves

    def _process_sales(self):
        self.ensure_one()
        credit_group = defaultdict(list)
        direct_tank_sale_group = defaultdict(list)
        partner_group = defaultdict(list)
        orders = self.env['sale.order']
        invoices = self.env['account.move']

        for line in self.credit_sale_line:
            vals = line._make_sale_line()
            vals and credit_group[vals.pop('partner_id')].append((0, 0, vals))
        order, invoice = self._validate_orders(credit_group)
        orders |= order
        invoices |= invoice

        for line in self.direct_sale_line:
            vals = line._make_sale_line()
            vals and direct_tank_sale_group[vals.pop('partner_id')].append((0, 0, vals))
        order, invoice = self._validate_orders(direct_tank_sale_group)
        orders |= order
        invoices |= invoice

        gun_lines, cash_partner = self.gun_sale_line._make_grouped_product_line()
        partner_group[cash_partner.id].extend([(0, 0, gline) for gline in gun_lines])

        for line in self.dry_sale_line:
            vals = line._make_sale_line()
            vals and partner_group[vals.pop('partner_id')].append((0, 0, vals))

        for line in self.other_sale_line:
            vals = line._make_sale_line()
            vals and partner_group[vals.pop('partner_id')].append((0, 0, vals))
        order, invoices_to_pay = self._validate_orders(partner_group)
        orders |= order
        invoices |= invoices_to_pay
        self.write({
            'move_ids': [(4, inv.id) for inv in invoices],
            'sale_ids': [(4, order.id) for order in orders],
            'picking_ids': [(4, pick.id) for pick in orders.mapped('picking_ids')]
        })
        return invoices_to_pay

    def _prepare_move_line_values(self, lines, dest_account, reference):
        line_ids = []
        for line in lines:
            line_ids.append((0, 0, {
                'product_id': line.product_id.id,
                'name': line.name,
                'account_id': line.product_id.expense_account_id.id,
                'debit': line.amount,
                'credit': 0,
                'currency_id': line.currency_id.id
            }))
        line_ids.append((0, 0, {
            'name': reference,
            'account_id': dest_account.id,
            'credit': sum([line[-1]['debit'] for line in line_ids]),
            'debit': 0,
            'currency_id': self.currency_id.id
        }))
        return line_ids

    def _prepare_move_values(self, journal_id, reference, partner_id=False):
        self.ensure_one()
        return {
            'move_type': 'entry',
            'state': 'draft',
            'company_id': self.company_id.id,
            'partner_id': partner_id,
            'invoice_date': self.date,
            'ref': reference,
            'name': '/',
            'currency_id': self.currency_id.id,
            'journal_id': journal_id.id,
            'shift_id': self.id,
        }
    
    def _process_excess_liability(self, moves, amount):
        if float_is_zero(amount, precision_digits=2):
            return moves
        reference = f'{self.name} Variance Excess'
        vals = self._prepare_move_values(
            self.station_id.unbanked_journal_id, reference, self.station_id.cash_partner_id.id)
        vals['line_ids'] = [
            (0, 0, {
                'name': reference,
                'account_id': self.station_id.unbanked_journal_id.default_account_id.id,
                'credit': 0,
                'debit': amount,
                'currency_id': self.currency_id.id
            }),
            (0, 0, {
                'name': reference,
                'account_id': self.station_id.liability_account_id.id,
                'credit': amount,
                'debit': 0,
                'currency_id': self.currency_id.id
            })
        ]
        moves |= self.env['account.move'].create(vals)
        return moves

    def process_credit_notes(self):
        # Expenses and loss variances will create a credit note kind of JE
        variance_status = self.summary_line._variance_status()
        moves = self.env['account.move']
        lines = []
        for line in self.expense_line:
            lines.append((0, 0, {
                'name': line.name,
                'price_unit': line.amount,
                'account_id': line.product_id.expense_account_id.id,
            }))
        if variance_status['loss'] > 0:
            lines.append((0, 0, {
                'name': f'{self.name} Variance Loss',
                'price_unit': variance_status['loss'],
                'account_id': self.station_id.loss_account_id.id,
            }))
        
        if lines:
            vals = {
                'move_type': 'out_refund',
                'state': 'draft',
                'company_id': self.company_id.id,
                'partner_id': self.station_id.cash_partner_id.id,
                'invoice_date': self.date,
                'name': '/',
                'currency_id': self.currency_id.id,
                'journal_id': self.station_id.expense_journal_id.id,
                'shift_id': self.id,
                'invoice_line_ids': lines
            }
            moves |= self.env['account.move'].create(vals)
        moves = self._process_excess_liability(moves, variance_status['liability'])
        return moves

    def process_petty_cash(self):
        moves = self.env['account.move']
        for rec in self.filtered('petty_line'):
            journal = rec.station_id.petty_cash_journal_id
            vals = self._prepare_move_values(journal, f'{rec.name} | Petty Cash')
            vals['line_ids'] = rec._prepare_move_line_values(
                rec.petty_line, journal.default_account_id, f'{rec.name} | Petty Cash')
            moves |= self.env['account.move'].create(vals)
        return moves

    def process_payments(self):
        payments = self.env['account.payment']
        payments_to_pay = self.env['account.payment']
        payments |= self.env['account.payment'].create(self.banking_line._make_banking_payment_line())
        for line in self.collection_line:
            payments |= self.env['account.payment'].create(line._make_payment_line())

        payments_to_pay |= self.env['account.payment'].create(
            self.payment_line._make_grouped_journal_payment_line())

        payments |= payments_to_pay
        payments and payments.filtered(lambda d: d.state == 'draft').action_post()
        return payments, payments_to_pay

    def _process_moves(self, moves_to_pay, payment):
        expense_move = self.process_credit_notes()
        moves = self.process_petty_cash()
        moves |= expense_move
        moves and moves._post()

        moves_to_pay |= expense_move.filtered(lambda m: m.move_type != 'out_invoice')
        if not moves_to_pay or not payment:
            return moves
        lines = moves_to_pay.mapped('line_ids')
        dest_accounts = payment.mapped('destination_account_id')
        lines |= payment.mapped('line_ids')
        lines.filtered(lambda ln: ln.move_id.state != 'posted').mapped('move_id')._post(soft=False)
        lines.filtered(
            lambda line: line.account_id in dest_accounts and not line.reconciled).reconcile()
        return moves

    def action_request_approval(self):
        self.write({'state': 'waiting_approval'})

    def action_post(self):
        self.opening_balance = self.station_id.closing_cash
        self.received_stock_line.do_pickings()
        moves_to_pay = self._process_sales()
        payments, payment_to_pay = self.process_payments()
        moves = self._process_moves(moves_to_pay, payment_to_pay)

        self.station_id.write(
            {'closing_cash': self.closing_balance, 'last_shift_id': self.id})
        self.summary_line._close()
        self.write({
            'state': 'interfaced',
            'move_ids': [(4, move.id) for move in moves],
            'payment_ids': [(4, pay.id) for pay in payments],
            'picking_ids': [(4, pick.id) for pick in self.received_stock_line.mapped('picking_id')],
        })
        # ? refactor: why this hack
        self.move_ids.filtered(lambda d: d.state == 'draft')._post()

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def _update_gun_last_reading(self):
        for line in self.mapped('gun_sale_line'):
            line.gun_id.write({
                'last_reading': line.closing_reading,
                'last_manual_reading': line.manual_closing_reading,
                'last_cash_reading': line.cash_closing_reading
            })
            
    def action_approve(self):
        self._update_gun_last_reading()
        self.write({'opening_balance': self.station_id.closing_cash, 'state': 'approved'})

    def action_reject(self):
        self.write({'state': 'done'})

    def _compute_price_unit(self, product, uom=False):
        return self.station_id.pricelist_id._get_product_price(product=product, uom=uom, date=self.date, quantity=1)

    @api.depends('banking_line', 'summary_line', 'opening_balance', 'petty_line')
    def _compute_balances(self):
        for rec in self:
            rec.cash_banked = sum(rec.banking_line.filtered(lambda b: b.line_type == 'banking').mapped('amount'))
            rec.cash_collected = sum(rec.payment_line.filtered(
                lambda d: d.journal_id == rec.station_id.unbanked_journal_id and \
                    d.line_type == 'payment').mapped('amount'))
            rec.closing_balance = rec.opening_balance + rec.cash_collected - rec.cash_banked
            rec.petty_cash_spent = sum(rec.petty_line.mapped('amount'))
            rec.total_expenses = sum(rec.expense_line.mapped('amount'))
            rec.closing_petty_cash = rec.petty_cash_opening + rec.petty_cash_reimbursed - rec.petty_cash_spent

    def action_open_receiving_moves(self):
        self.ensure_one()
        return {
            'name': 'Apply Pickings',
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'receive.move.wizard',
            'target': 'new',
            'context': {'default_shift_id': self.id}
        }
        
    def open_shift_sale_orders(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "oo_fuel_management_system.oo_station_management_sale_action")
        action['domain'] = [('id', 'in', self.sale_ids.ids)]
        return action

    def open_shift_payments(self):
        action = self.env["ir.actions.actions"]._for_xml_id(
            "oo_fuel_management_system.oo_station_management_payment_action")
        action['domain'] = [('id', 'in', self.payment_ids.ids)]
        return action

    def open_shift_entries(self):
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_journal_line")
        action['domain'] = [('id', 'in', self.move_ids.ids)]
        action['context'] = {'search_default_misc_filter': 0}
        return action

    def open_shift_transfer(self):
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_picking_action_picking_type")
        action['domain'] = [('id', 'in', self.picking_ids.ids)]
        return action


class ShiftGunSales(models.Model):
    _name = 'shift.gun.sale.line'
    _description = 'Station Shift Gun Sales'

    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(
        related='shift_id.station_id', string='Station')
    company_id = fields.Many2one(
        related='shift_id.company_id', string='Company')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', domain="[('station_ids', 'in', station_id)]")
    gun_id = fields.Many2one('station.gun', string='Gun',
                             required=True, domain="[('tank_id.station_id', '=', station_id)]")
    tank_id = fields.Many2one(related='gun_id.tank_id', string='Tank')
    pump = fields.Char(related='gun_id.pump', string='Pump', store=True)
    opening_reading = fields.Float(
        string='Opening Reading', required=True, default=0, readonly=True)
    manual_opening_reading = fields.Float(
        string='Manual Opening', required=True, default=0, readonly=True)
    cash_opening_reading = fields.Float(
        string='Cash Opening', required=True, default=0, readonly=True)
    closing_reading = fields.Float(
        string='Closing Reading', required=True, default=0)
    manual_closing_reading = fields.Float(
        string='Manual Closing', required=True, default=0)
    cash_closing_reading = fields.Float(
        string='Cash Closing', required=True, default=0)
    reading_difference = fields.Float(
        string='Variance', required=True, compute="_compute_amount")
    price_unit = fields.Float(
        string='Unit Price', compute="_compute_price", store=True)
    rtt = fields.Float(string='RTT', help='Returned to Tank')
    net_sales = fields.Float(string='Net Sales', compute='_compute_amount')
    amount = fields.Float(string='Amount', compute='_compute_amount')
    is_admin = fields.Boolean(string='Is Admin', related='shift_id.is_admin')
    

    @api.constrains('reading_difference')
    def _constrains_reading_difference(self):
        for rec in self:
            if rec.reading_difference < 0:
                raise ValidationError(
                    f'Gun sale closing reading must be greater than opening reading! {rec.gun_id.name}')

    @api.depends('price_unit', 'opening_reading', 'closing_reading', 
                 'manual_opening_reading', 'manual_closing_reading', 'rtt')
    def _compute_amount(self):
        for rec in self:
            electric_difference = rec.closing_reading - rec.opening_reading
            manual_difference = rec.manual_closing_reading - rec.manual_opening_reading
            sales = rec.station_id.reading_type == 'electronic' and electric_difference or manual_difference
            sales -= rec.rtt
            rec.net_sales = sales
            rec.amount = rec.price_unit * sales
            rec.reading_difference = electric_difference - manual_difference
            if float_is_zero(manual_difference, precision_digits=2) or float_is_zero(electric_difference, precision_digits=2):
                rec.reading_difference = 0

    @api.onchange('gun_id')
    def _onchange_gun_id(self):
        for rec in self.filtered('gun_id'):
            rec.opening_reading = rec.gun_id.last_reading
            rec.closing_reading = rec.gun_id.last_reading
            rec.manual_opening_reading = rec.gun_id.last_manual_reading
            rec.manual_closing_reading = rec.gun_id.last_manual_reading
            rec.cash_opening_reading = rec.gun_id.last_cash_reading
            rec.cash_closing_reading = rec.gun_id.last_cash_reading

    @api.depends('gun_id', 'shift_id.date')
    def _compute_price(self):
        for rec in self:
            if rec.gun_id:
                rec.price_unit = rec.shift_id._compute_price_unit(rec.gun_id.product_id, rec.tank_id.uom_id)
            else:
                rec.price_unit = 0

    def _oncreate_populate(self):
        for rec in self:
            rec._onchange_gun_id()
            rec._compute_price()

    def _validate_closing(self):
        for rec in self:
            rec.shift_id.closing_warning = False
            if abs(rec.reading_difference) > rec.gun_id.tank_id.allowable_gun_variance:
                rec.shift_id.closing_warning = '\n Manual and electronic gun difference exceeds allowable gun difference'
                if rec.shift_id.is_station_accountant:
                    continue
                raise ValidationError('Manual and electronic gun difference cannot exceed allowable gun difference')

    def _make_grouped_product_line(self):
        shift = self.mapped('shift_id')
        if len(shift) > 1:
            raise ValidationError('Please compute one shift at a time')
        products = {}
        for line in self:
            product = line.gun_id.product_id
            if products.get(product):
                products[product]['product_uom_qty'] += line.net_sales
            else:
                products[product] = {
                    'product_id': product.id,
                    'name': product.name,
                    'product_uom': product.uom_id.id,
                    'product_uom_qty': line.net_sales,
                    'price_unit': line.price_unit,
                    'location_id': line.gun_id.tank_id.location_id.id
                }
        
        for product in products:
            credit = shift.credit_sale_line.filtered(lambda c: c.product_id == product).mapped('quantity')
            products[product]['product_uom_qty'] -= sum(credit)
        return list(products.values()), shift.station_id.cash_partner_id
    

class ShiftDrySales(models.Model):
    _name = 'shift.dry.sale.line'
    _description = 'Station Shift Dry Sales'

    product_id = fields.Many2one('product.product',
                                 string='Product',
                                 domain="[('id', 'in', available_product_ids)]",
                                 required=True)
    before_quantity = fields.Float(string='Stock', readonly=True)
    quantity = fields.Float(string='Sold', required=True)
    after_quantity = fields.Float(string='Stock Left', compute="_compute_amount")
    uom_id = fields.Many2one('uom.uom', string='Uom', required=True,
                             domain="[('relative_uom_id', '=', uom_category_id)]")
    uom_category_id = fields.Many2one(related='product_id.uom_id.relative_uom_id')
    price_unit = fields.Float(string='Unit Price', compute='_compute_price', store=True)
    amount = fields.Float(string='Amount', compute='_compute_amount', inverse='_inverse_compute_amount')
    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    partner_id = fields.Many2one(related='station_id.cash_partner_id', string='Customer')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, domain="[('station_ids', 'in', station_id)]")
    discount = fields.Float(string='Discount')
    order_line_id = fields.Many2one('sale.order.line', string='Order Line')
    available_product_ids = fields.Many2many('product.product',
                                             string='Available Products', compute='_compute_available_products')
    stock_warning = fields.Boolean(string='Stock Warning', compute="_compute_amount")
    
    @api.depends('station_id')
    def _compute_available_products(self):
        for rec in self:
            rec.available_product_ids = rec.station_id.product_ids.filtered(
                lambda p: p.stock_type in ('lpg', 'lube', 'other') and p.detailed_type != 'service').ids

    @api.depends('price_unit', 'before_quantity', 'quantity', 'discount')
    def _compute_amount(self):
        for rec in self:
            rec.amount = (rec.price_unit - rec.discount) * rec.quantity
            rec.after_quantity = rec.before_quantity - rec.quantity
            rec.stock_warning = rec.after_quantity < 0

    @api.onchange('amount')
    def _inverse_compute_amount(self):
        for rec in self:
            price = rec.price_unit - rec.discount
            rec.quantity = price and rec.amount / price or 0
            
    @api.onchange('product_id', 'partner_id')
    def _onchange_product_id(self):
        for rec in self.filtered('product_id'):
            rec.uom_id = rec.product_id.uom_id
            rec.before_quantity = self.env['stock.quant']._get_available_quantity(
                rec.product_id, rec.station_id.dry_stock_location_id)

    @api.depends('product_id', 'partner_id', 'shift_id.date')
    def _compute_price(self):
        for rec in self:
            if rec.product_id:
                rec.price_unit = rec.shift_id._compute_price_unit(rec.product_id)
            else:
                rec.price_unit = 0

    @api.constrains('discount', 'price_unit')
    def _constrains_discount(self):
        for rec in self:
            if rec.discount > rec.price_unit:
                raise ValidationError('Dry sales discount cannot be greater than item price unit!')

    def _validate_lines(self):
        if self.filtered(lambda d: d.after_quantity < 0):
            raise ValidationError('Dry stock remaining quantity cannot be less than 0')
        
    def _make_sale_line(self):
        self.ensure_one()
        credit_sales = self.shift_id.credit_sale_line.filtered(
            lambda c: c.product_id == self.product_id and c.employee_id == self.employee_id).mapped('quantity')
        qty = self.quantity - sum(credit_sales)
        if qty <= 0:
            return
        return {
            'product_id': self.product_id.id,
            'name': self.product_id.name,
            'product_uom_qty': qty,
            'product_uom': self.uom_id.id,
            'price_unit': self.price_unit - self.discount,
            'partner_id': self.partner_id.id,
            'employee_id': self.employee_id.id,
            'location_id': self.station_id.dry_stock_location_id.id
        }


class ShiftOtherSales(models.Model):
    _name = 'shift.other.sale.line'
    _description = 'Station Other Sales'

    product_id = fields.Many2one('product.product',
                                 string='Product',
                                 domain="[('id', 'in', available_product_ids)]",
                                 required=True)
    quantity = fields.Float(string='Quantity', required=True)
    uom_id = fields.Many2one('uom.uom', string='Uom', required=True, domain="[('relative_uom_id', '=', uom_category_id)]")
    uom_category_id = fields.Many2one(related='product_id.uom_id.relative_uom_id')
    price_unit = fields.Float(string='Unit Price', compute="_compute_price", store=True)
    amount = fields.Float(string='Amount', compute='_compute_amount', inverse='_inverse_compute_amount')
    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    partner_id = fields.Many2one(related='station_id.cash_partner_id', string='Customer')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, domain="[('station_ids', 'in', station_id)]")
    discount = fields.Float(string='Discount')
    order_line_id = fields.Many2one('sale.order.line', string='Order Line')
    available_product_ids = fields.Many2many('product.product',
                                             string='Available Products', compute='_compute_available_products')

    @api.depends('station_id')
    def _compute_available_products(self):
        for rec in self:
            rec.available_product_ids = rec.station_id.product_ids.filtered(
                lambda p: p.stock_type == 'other' and p.detailed_type == 'service').ids

    @api.depends('price_unit', 'quantity', 'discount')
    def _compute_amount(self):
        for rec in self:
            rec.amount = (rec.price_unit - rec.discount) * rec.quantity

    @api.onchange('amount')
    def _inverse_compute_amount(self):
        for rec in self:
            price = rec.price_unit - rec.discount
            rec.quantity = price and rec.amount / price or 0
            
    @api.constrains('discount', 'price_unit')
    def _constrains_discount(self):
        for rec in self:
            if rec.discount > rec.price_unit:
                raise ValidationError('Other sales discount cannot be greater than item price unit!')

    @api.onchange('product_id', 'partner_id')
    def _onchange_product_id(self):
        for rec in self.filtered('product_id'):
            rec.uom_id = rec.product_id.uom_id

    @api.depends('product_id', 'shift_id.date')
    def _compute_price(self):
        for rec in self:
            if rec.product_id:
                rec.price_unit = rec.shift_id._compute_price_unit(rec.product_id, date=rec.shift_id.date)
            else:
                rec.price_unit = 0

    def _make_sale_line(self):
        self.ensure_one()
        credit_sales = self.shift_id.credit_sale_line.filtered(
            lambda c: c.product_id == self.product_id and c.employee_id == self.employee_id).mapped('quantity')
        qty = self.quantity - sum(credit_sales)
        if qty <= 0:
            return
        location_id = self.station_id.warehouse_id.lot_stock_id

        if self.product_id.is_dry_stock:
            location_id = self.station_id.dry_stock_location_id
        else:
            tank = self.station_id.tank_ids.filtered(lambda t: t.product_id == self.product_id)
            location_id = tank and tank[0].location_id

        return {
            'product_id': self.product_id.id,
            'name': self.product_id.name,
            'product_uom_qty': qty,
            'product_uom': self.uom_id.id,
            'price_unit': self.price_unit - self.discount,
            'partner_id': self.partner_id.id,
            'employee_id': self.employee_id.id,
            'location_id': location_id.id
        }


class ShiftCreditSales(models.Model):
    _name = 'shift.credit.sale.line'
    _description = 'Station Shift Credit Sales'

    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    date = fields.Date(related='shift_id.date', string='Date')
    product_id = fields.Many2one('product.product',
                                 string='Product',
                                 required=True,
                                 domain="[('id', 'in', available_product_ids)]")
    uom_id = fields.Many2one('uom.uom', string='Uom', required=True,
                             domain="[('relative_uom_id', '=', uom_category_id)]")
    uom_category_id = fields.Many2one(related='product_id.uom_id.relative_uom_id')
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 required=True,
                                 domain="[('id', 'in', available_partner_ids)]")
    partner_ref = fields.Char(string='Account', related='partner_id.ref')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, domain="[('station_ids', 'in', station_id)]")
    quantity = fields.Float(string='Quantity', required=True)
    discount = fields.Float(string='Discount')
    price_unit = fields.Float(string='Unit Price', compute="_compute_price", store=True)
    amount = fields.Float(string='Amount', compute='_compute_amount', inverse='_inverse_compute_amount')
    order_line_id = fields.Many2one('sale.order.line', string='Order Line')
    lpo_number = fields.Char(string='LPO NO', required=True)
    vehicle_no = fields.Char(string='Vehicle NO', required=True)
    vehicle_mileage = fields.Float(string='Mileage', required=True)
    invoice_no = fields.Char(string='Invoice No')
    available_product_ids = fields.Many2many('product.product',
                                             string='Available Products', compute='_compute_available_products')
    available_partner_ids = fields.Many2many(related='station_id.partner_ids', string='Available Credit Customer')

    @api.depends('station_id')
    def _compute_available_products(self):
        for rec in self:
            rec.available_product_ids = rec.station_id.product_ids.ids

    @api.depends('price_unit', 'quantity', 'discount')
    def _compute_amount(self):
        for rec in self:
            rec.amount = (rec.price_unit - rec.discount) * rec.quantity

    @api.onchange('amount')
    def _inverse_compute_amount(self):
        for rec in self:
            price = rec.price_unit - rec.discount
            rec.quantity = price and rec.amount / price or 0
            
    @api.constrains('discount', 'price_unit')
    def _constrains_discount(self):
        for rec in self:
            if rec.discount > rec.price_unit:
                raise ValidationError('Credit sales discount cannot be greater than item price unit!')

    @api.onchange('product_id', 'partner_id')
    def _onchange_product_id(self):
        for rec in self.filtered('product_id'):
            rec.uom_id = rec.product_id.uom_id

    @api.depends('product_id', 'shift_id.date')
    def _compute_price(self):
        for rec in self:
            if rec.product_id:
                rec.price_unit = rec.shift_id._compute_price_unit(rec.product_id)
            else:
                rec.price_unit = 0

    def _make_sale_line(self):
        self.ensure_one()
        if self.quantity <= 0:
            return
        location_id = self.station_id.warehouse_id.lot_stock_id

        if self.product_id.is_dry_stock:
            location_id = self.station_id.dry_stock_location_id
        else:
            tank = self.station_id.tank_ids.filtered(lambda t: t.product_id == self.product_id)
            location_id = tank and tank[0].location_id

        return {
            'product_id': self.product_id.id,
            'name': self.product_id.name,
            'product_uom_qty': self.quantity,
            'price_unit': self.price_unit - self.discount,
            'partner_id': self.partner_id.id,
            'employee_id': self.employee_id.id,
            'product_uom': self.uom_id.id,
            'location_id': location_id.id
        }


class ShiftDirectSales(models.Model):
    _name = 'shift.direct.sale.line'
    _description = 'Station Shift Direct Sales'

    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(
        related='shift_id.station_id', string='Station')
    tank_id = fields.Many2one(
        'station.tank', string='Tank', domain="[('station_id', '=', station_id)]")
    product_id = fields.Many2one(
        related='tank_id.product_id', string='Product')
    uom_id = fields.Many2one('uom.uom', string='Uom', required=True,
                             domain="[('relative_uom_id', '=', uom_category_id)]")
    uom_category_id = fields.Many2one(related='product_id.uom_id.relative_uom_id')
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 required=True,
                                 domain="[('company_id', 'in', (company_id, False))]")
    partner_ref = fields.Char(string='Account', related='partner_id.ref')
    company_id = fields.Many2one(
        related='shift_id.company_id', string='Company')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, domain="[('station_ids', 'in', station_id)]")
    quantity = fields.Float(string='Quantity', required=True)
    discount = fields.Float(string='Discount')
    price_unit = fields.Float(
        string='Unit Price', compute="_compute_price", store=True)
    amount = fields.Float(string='Amount', compute='_compute_amount', inverse='_inverse_compute_amount')
    order_line_id = fields.Many2one('sale.order.line', string='Order Line')
    lpo_number = fields.Char(string='LPO NO', required=True)
    vehicle_no = fields.Char(string='Vehicle NO', required=True)
    invoice_no = fields.Char(string='Invoice No')

    @api.depends('price_unit', 'quantity', 'discount')
    def _compute_amount(self):
        for rec in self:
            rec.amount = (rec.price_unit - rec.discount) * rec.quantity

    @api.onchange('amount')
    def _inverse_compute_amount(self):
        for rec in self:
            price = rec.price_unit - rec.discount
            rec.quantity = price and rec.amount / price or 0
            
    @api.constrains('discount', 'price_unit')
    def _constrains_discount(self):
        for rec in self:
            if rec.discount > rec.price_unit:
                raise ValidationError(
                    'Direct sales discount cannot be greater than item price unit!')

    @api.onchange('product_id', 'partner_id')
    def _onchange_product_id(self):
        for rec in self.filtered('product_id'):
            rec.uom_id = rec.product_id.uom_id

    @api.depends('product_id', 'shift_id.date')
    def _compute_price(self):
        for rec in self:
            if rec.product_id:
                rec.price_unit = rec.shift_id._compute_price_unit(rec.product_id)
            else:
                rec.price_unit = 0

    def _make_sale_line(self):
        self.ensure_one()
        if self.quantity <= 0:
            return
        return {
            'product_id': self.product_id.id,
            'name': self.product_id.name,
            'product_uom_qty': self.quantity,
            'price_unit': self.price_unit - self.discount,
            'discount': self.discount,
            'partner_id': self.partner_id.id,
            'employee_id': self.employee_id.id,
            'product_uom': self.uom_id.id,
            'location_id': self.tank_id.location_id.id,
        }


class ShiftCollection(models.Model):
    _name = 'shift.collection.line'
    _description = 'Station Shift Collections'

    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    currency_id = fields.Many2one(related='shift_id.currency_id', string='Currency')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, domain="[('station_ids', 'in', station_id)]")
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 required=True,
                                 domain="[('company_id', 'in', (company_id, False))]")
    amount = fields.Monetary(string='Amount', currency_field="currency_id")
    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Mode',
        required=True,
        compute='_compute_journal_id')
    name = fields.Char(string='Reference')
    payment_id = fields.Many2one('account.payment', string='Payment')

    @api.depends('journal_id', 'employee_id')
    def _compute_journal_id(self):
        for rec in self:
            rec.journal_id = rec.station_id.unbanked_journal_id

    def _make_payment_line(self):
        self.ensure_one()
        if self.amount <= 0:
            raise ValidationError('Collection amount must be positive')
        journal = self.journal_id
        payment_methods = journal.inbound_payment_method_line_ids
        if not payment_methods:
            raise ValidationError(f'Please define an inbound payment method for the journal {journal.name}')

        return {
            'journal_id': journal.id,
            'company_id': self.company_id.id,
            'shift_id': self.shift_id.id,
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'date': self.shift_id.date,
            'ref': f"{self.name or self.shift_id.name} Collection",
            'payment_type': 'inbound',
            'payment_method_line_id': payment_methods[0].payment_method_id.id,
        }


class ShiftSummary(models.Model):
    _name = 'shift.summary.line'
    _description = 'Shift Summary'

    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, domain="[('station_ids', 'in', station_id)]")
    wet_quantity = fields.Float(string='Wet Products')
    lubes_quantity = fields.Float(string='Lube Products')
    lpg_quantity = fields.Float(string='LPG Products')
    others_quantity = fields.Float(string='Other Services')
    discount = fields.Float(string='Discount')
    total_sales = fields.Float(string='Total Sales', compute='_compute_amounts', store=True)
    credit_sales = fields.Float(string='Credit Sales')
    collections = fields.Float(string='Collections')
    expenses = fields.Float(string='Expenses')
    expected_cash = fields.Float(string='Total Expected Cash', compute='_compute_amounts', store=True)
    cash_collected = fields.Float(string='Collected Cash')
    direct_sale = fields.Float(string='Direct Sale')
    variance = fields.Float(string='Variance', compute='_compute_amounts', store=True)

    @api.depends('cash_collected', 'expected_cash', 'wet_quantity', 'lubes_quantity',
                 'lpg_quantity', 'others_quantity', 'collections')
    def _compute_amounts(self):
        for rec in self:
            rec.total_sales = rec.wet_quantity + rec.lubes_quantity + rec.lpg_quantity \
                + rec.others_quantity + rec.direct_sale
            rec.expected_cash = rec.total_sales + rec.collections - rec.expenses - rec.credit_sales
            rec.variance = (rec.expected_cash - rec.cash_collected) * -1
                
    def _validate_closing(self):
        for line in self:
            expense = line.shift_id.expense_line.filtered(lambda s: s.employee_id == line.employee_id)
            expense_amount = sum(expense.mapped('amount'))
            if expense_amount > line.expected_cash:
                raise ValidationError(
                    f"{line.employee_id.name}'s expenses cannot exceed their total cash collected")
            
            allowed_variance = line.station_id.allowable_cash_variance
            raise_variance = float_compare(abs(line.variance), allowed_variance, precision_digits=2) > 0
            if line.variance < 0 and raise_variance:
                if self.shift_id.is_station_accountant:
                    continue
                
                raise ValidationError(
                    f'{line.employee_id.name} summary variance exceeds allowed station variance of {allowed_variance}')
                    
    def _close(self):
        for rec in self.filtered('variance'):
            rec.employee_id.write({
                'fms_variance_ids': [(0, 0, {
                    'name': f'{rec.shift_id.name} Short',
                    'amount': rec.variance,
                    'shift_id': rec.shift_id.id
                })]
            })

    def _variance_status(self):
        status = {'liability': 0, 'loss': 0}
        for line in self.filtered(lambda s: not float_is_zero(s.variance, precision_digits=2)):
            if float_compare(line.variance, 0, precision_digits=2) > 0:
                status['liability'] += line.variance
            else:
                status['loss'] += abs(line.variance)
        return status


class ShiftExpenseLine(models.Model):
    _name = 'shift.expense.line'
    _description = 'Shift Expenses'

    product_id = fields.Many2one('product.product', string='Product',
                                 domain="[('can_be_expensed', '=', True),('company_id', 'in', (company_id, False))]")
    name = fields.Char(string='Name', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', domain="[('station_ids', 'in', station_id)]")
    amount = fields.Monetary('Amount', currency_field="currency_id")
    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    currency_id = fields.Many2one(related='shift_id.currency_id', string='Currency')


class ShiftTankStockTake(models.Model):
    _name = 'shift.tank.stock.take'
    _description = 'Shift Tank Dippings'

    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    tank_id = fields.Many2one('station.tank', string='Tank', required=True,
                              domain="[('station_id', '=', station_id)]")
    location_id = fields.Many2one(related='tank_id.location_id', string='Stock Location')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    opening_qty = fields.Float(string='Opening Qty', required=True, readonly=True)
    received_qty = fields.Float(string='Received Qty', readonly=True)
    sales_qty = fields.Float(string='Pump Sales', readonly=True)
    book_closing_qty = fields.Float(string='Book Closing Qty', compute="_compute_quantities")
    closing_dip_qty = fields.Float(string='Closing Dips')
    variance = fields.Float(string='Variance', compute="_compute_quantities")
    reason = fields.Char(string='Variance Reason')

    @api.constrains('closing_dip_qty', 'tank_id.max_volume')
    def _constrains_closing_dip_qty(self):
        for rec in self:
            if rec.closing_dip_qty > rec.tank_id.max_volume:
                raise ValidationError(f'Closing dip for tank {rec.tank_id.name} \
                    exceeds its maximum capacity of {rec.tank_id.max_volume}')

    @api.onchange('tank_id')
    def _onchange_tank_id(self):
        for rec in self:
            rec.opening_qty = rec.tank_id.current_volume
            rec.closing_dip_qty = rec.tank_id.current_volume

    @api.depends('opening_qty', 'received_qty', 'sales_qty', 'closing_dip_qty')
    def _compute_quantities(self):
        for rec in self:
            book_closing_qty = rec.opening_qty + rec.received_qty - rec.sales_qty
            rec.book_closing_qty = book_closing_qty
            rec.variance = (book_closing_qty - rec.closing_dip_qty) * -1

    def _close(self):
        for rec in self:
            if abs(rec.variance) > rec.tank_id.allowable_variance:
                if not rec.shift_id.is_station_accountant:
                    raise ValidationError(f'Dipping variance for tank {rec.tank_id.name} exceeds the allowed variance range!')
                if not rec.reason:
                    raise ValidationError('Please add a dipping variance reason.')
            rec.tank_id.write({'current_volume': rec.closing_dip_qty})

    def _update_pump_sales(self):
        for rec in self:
            rec.sales_qty = sum(
                rec.shift_id.gun_sale_line.filtered(lambda g: g.tank_id == rec.tank_id).mapped('net_sales'))

    def _get_received_quantities(self):
        for rec in self:
            transfers = rec.shift_id.received_stock_line.filtered(lambda t: t.location_id == rec.location_id)
            rec.received_qty = sum(transfers.mapped('quantity'))

    def _calculate_tank_operations(self):
        self._update_pump_sales()
        self._get_received_quantities()


class ShiftPettyCashLine(models.Model):
    _name = 'shift.petty.cash.line'
    _description = 'Shift Petty Cash Line'

    product_id = fields.Many2one(
        'product.product',
        string='Product',
        domain="[('can_be_expensed', '=', True), ('company_id', 'in', (company_id, False))]")
    name = fields.Char(string='Name', required=True)
    amount = fields.Monetary('Amount', currency_field="currency_id")
    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    currency_id = fields.Many2one(related='shift_id.currency_id', string='Currency')


class ShiftPaymentLine(models.Model):
    _name = 'shift.payment.line'
    _description = 'Shift Payment Line'

    name = fields.Char(string='Reference')
    amount = fields.Monetary('Amount', currency_field="currency_id")
    shift_id = fields.Many2one('station.shift', string='Shift')
    # Todo: deprecate line type column
    line_type = fields.Selection(string='Line Type',
                                 selection=[('banking', 'Banking'), ('payment', 'Payment')],
                                 default='payment',
                                 required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    currency_id = fields.Many2one(related='shift_id.currency_id', string='Currency')
    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Mode',
        required=True,
        domain="[('id', 'in', available_journal_ids)]")
    available_journal_ids = fields.Many2many(
        'account.journal',
        compute='_compute_available_journals',
        string='Available Payment Methods')

    @api.depends('shift_id')
    def _compute_available_journals(self):
        for rec in self:
            rec.available_journal_ids = rec.station_id.payment_mode_ids.ids

    def _make_grouped_journal_payment_line(self):
        payments = {}
        for rec in self.filtered(lambda p: p.line_type == 'payment'):
            if rec.amount <= 0:
                raise ValidationError('Payment amount must be positive')
            if payments.get(rec.journal_id):
                payments[rec.journal_id]['amount'] += rec.amount
            else:
                payment_methods = rec.journal_id.inbound_payment_method_line_ids
                if not payment_methods:
                    raise ValidationError(
                        f'Please define an inbound payment method for the journal {rec.journal_id.name}')
                payments[rec.journal_id] = {
                    'journal_id': rec.journal_id.id,
                    'payment_method_line_id': payment_methods[0].id,
                    'ref': f'{rec.name or rec.shift_id.name} Payment',
                    'amount': rec.amount,
                    'payment_type': 'inbound',
                    'company_id': rec.company_id.id,
                    'shift_id': rec.shift_id.id,
                    'date': rec.shift_id.date,
                    'partner_id': rec.station_id.cash_partner_id.id
                }
        return list(payments.values())


class ShiftBankingLine(models.Model):
    _name = 'shift.banking.line'
    _description = 'Shift Banking Line'

    name = fields.Char(string='Reference', required=True)
    amount = fields.Monetary('Amount', currency_field="currency_id")
    shift_id = fields.Many2one('station.shift', string='Shift')
    # Todo: deprecate line type column
    line_type = fields.Selection(string='Line Type',
                                 selection=[('banking', 'Banking'), ('payment', 'Payment')],
                                 default='banking',
                                 required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    currency_id = fields.Many2one(related='shift_id.currency_id', string='Currency')
    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Mode',
        domain="[('id', 'in', available_journal_ids)]")
    available_journal_ids = fields.Many2many(
        'account.journal',
        compute='_compute_available_journals',
        string='Available Payment Methods')

    @api.depends('shift_id')
    def _compute_available_journals(self):
        for rec in self:
            rec.available_journal_ids = rec.station_id.journal_ids.ids

    def _make_banking_payment_line(self):
        payments = {}
        for rec in self.filtered(lambda p: p.line_type == 'banking'):
            if rec.amount <= 0:
                raise ValidationError('Banking amount must be positive')
            if payments.get(rec.journal_id):
                payments[rec.journal_id]['amount'] += rec.amount
            else:
                journal = rec.station_id.unbanked_journal_id
                payment_methods = journal.outbound_payment_method_line_ids
                if not payment_methods:
                    raise ValidationError(
                        f'Please define an outbound payment method for the journal {journal.name}')
                payments[rec.journal_id] = {
                    'journal_id': journal.id,
                    'destination_journal_id': rec.journal_id.id,
                    'payment_method_line_id': payment_methods[0].id,
                    'ref': f'{rec.name or rec.shift_id.name} Banking',
                    'amount': rec.amount,
                    'payment_type': 'outbound',
                    'is_internal_transfer': True,
                    'company_id': rec.company_id.id,
                    'shift_id': rec.shift_id.id,
                    'date': rec.shift_id.date,
                }
        return list(payments.values())


class ShiftTransferLine(models.Model):
    _name = 'shift.transfer.line'
    _description = 'Shift received stocks'

    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(related='shift_id.station_id', string='Station')
    company_id = fields.Many2one(related='shift_id.company_id', string='Company')
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain="[('id', 'in', available_product_ids)]")
    location_id = fields.Many2one('stock.location', string='Receiving Location',
                                  domain="[('company_id', 'in', (company_id, False))]", required=True)
    quantity = fields.Float(string='Offloaded Quantity', required=True)
    loaded_quantity = fields.Float(string='Loaded Quantity', required=True)
    uom_id = fields.Many2one('uom.uom', string='Uom', required=True,
                             domain="[('relative_uom_id', '=', uom_category_id)]")
    uom_category_id = fields.Many2one(related='product_id.uom_id.relative_uom_id')
    picking_id = fields.Many2one('stock.picking', string='Picking', readonly=True)
    available_product_ids = fields.Many2many('product.product',
                                             string='Available Products', compute='_compute_available_products')
    driver = fields.Char(string='Driver', required=False)
    truck = fields.Char(string='Truck', required=False)
    variance = fields.Float(string='Variance', compute="_compute_variance")
    can_edit_location = fields.Boolean(string='Can Edit Location', readonly=True)
    move_line_id = fields.Many2one('stock.move.line', string='Related Move', readonly=True)
        
    @api.constrains('quantity', 'loaded_quantity')
    def _constrains_quantity(self):
        for rec in self:
            if float_compare(rec.quantity, rec.loaded_quantity, 2) > 0:
                raise ValidationError('Offloaded quantity cannot be greater than loaded quantity')
            
    @api.depends('loaded_quantity', 'quantity')
    def _compute_variance(self):
        for rec in self:
            rec.variance = (rec.loaded_quantity - rec.quantity) * -1

    @api.depends('station_id')
    def _compute_available_products(self):
        for rec in self:
            rec.available_product_ids = rec.station_id.product_ids.ids

    @api.onchange('product_id', 'station_id')
    def _onchange_product_id(self):
        for rec in self.filtered('product_id'):
            rec.uom_id = rec.product_id.uom_id
            rec.can_edit_location = True
            if rec.product_id.is_wet_product:
                tank = rec.station_id.tank_ids.filtered(lambda t: t.product_id == rec.product_id)
                if len(tank) == 1:
                    rec.location_id = tank.location_id
                    rec.can_edit_location = False
                else:
                    rec.can_edit_location = True
            if rec.product_id.is_dry_stock:
                rec.location_id = rec.station_id.dry_stock_location_id 
                rec.can_edit_location = False
        
    def _prepare_stock_move_values(self, picking):
        self.ensure_one()
        return {
            'name': self.shift_id.name,
            'product_id': self.product_id.id,
            'product_uom_qty': self.quantity,
            'product_uom': self.uom_id.id,
            'picking_id': picking.id,
            'state': 'draft',
            'date': self.shift_id.date,
            'location_id': picking.location_id.id,
            'location_dest_id': self.location_id.id,
            'picking_type_id': picking.picking_type_id.id,
            'warehouse_id': picking.picking_type_id.warehouse_id.id,
            'procure_method': 'make_to_stock',
        }

    def _prepare_picking_values(self):
        self.ensure_one()
        return {
            'picking_type_id': self.station_id.operation_type_id.id,
            'state': 'draft',
            'origin': self.shift_id.name,
            'location_id': self.station_id.operation_type_id.default_location_src_id.id,
            'location_dest_id': self.location_id.id,
            'shift_id': self.shift_id.id,
        }

    def _validate_incoming_stock_availability(self):
        self.ensure_one()
        quantity = self.env['stock.quant']._get_available_quantity(
            self.product_id, self.station_id.operation_type_id.default_location_src_id
        )
        if quantity < self.quantity:
            raise ValidationError(
                f'You cannot receive more quantity than there is for product {self.product_id.name}')
        if not self.driver or not self.truck:
            raise ValidationError('Some Receiving stock lines have no driver or truck')

    def do_pickings(self):
        for rec in self:
            rec._validate_incoming_stock_availability()
            picking = self.env['stock.picking'].create(rec._prepare_picking_values())
            self.env['stock.move'].create(rec._prepare_stock_move_values(picking))
            picking.action_confirm()
            picking.action_assign()
            picking.with_context(skip_sms=True, skip_immediate=True).button_validate()
            rec.picking_id = picking
            
    @api.ondelete(at_uninstall=False)
    def _unlink_processed_moves(self):
        self.mapped('move_line_id').write({'station_processed': False})
        
