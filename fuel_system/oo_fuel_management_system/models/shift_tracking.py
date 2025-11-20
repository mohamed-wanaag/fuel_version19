import logging
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class StationShiftType(models.Model):
    _name = 'station.shift.type'
    _description = 'Staftion Shift Types'

    active = fields.Boolean(string='Active', default=True)
    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(string='Sequnce', required=True)

    @api.ondelete(at_uninstall=False)
    def _ondelete(self):
        shifts = self.env['station.shift'].search([('type_id', 'in', self.ids)])
        if shifts:
            raise ValidationError('You cannot delete a period linked to a station. Archive it instead')


class ShiftHistory(models.Model):
    _name = 'shift.history'
    _description = 'Shift History'
    _order = 'date desc'
    _rec_name = 'shift_id'

    station_id = fields.Many2one('station.station', string='Station', required=True)
    shift_id = fields.Many2one('station.shift', string='Shift')
    type_id = fields.Many2one('station.shift.type', string='Shift Type', required=True)
    date = fields.Date(string='Date', required=True)
    sequence = fields.Integer(string='Sequence', required=True)
    state = fields.Selection(related='shift_id.state', string='Shift Status')

    @api.constrains('station_id', 'date', 'type_id', 'state')
    def _constrains_history(self):
        for rec in self:
            history = self.search(
                [('station_id', '=', rec.station_id.id),
                 ('date', '=', rec.date),
                 ('type_id', '=', rec.type_id.id),
                 ('id', '!=', rec.id)
                 ])
            if history:
                raise ValidationError(f'A shift history with the same station, period and date already exists.\
                    You might need to cancel this shift and create a new one {history.id}')
    
    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        for rec in res:
            rec.station_id.write({'shift_history_ids': [(4, rec.id)]})
        return res
    
    def next_history(self, shift):
        next_type = self.env['station.shift.type'].search(
            [('id', '!=', shift.type_id.id), ('sequence', '>', shift.type_id.sequence)],
            order='sequence', limit=1)
        next_date = shift.date
        if not next_type:
            next_date = next_date + timedelta(days=1)
            next_type = self.env['station.shift.type'].search([], order='sequence', limit=1)
        history = self.search(
                [('station_id', '=', shift.station_id.id),
                 ('date', '=', next_date),
                 ('type_id', '=', next_type.id),
                 ('shift_id', '=', False),
                 ])
        if history:
            return history
        vals = {
            'type_id': next_type.id,
            'date': next_date,
            'station_id': shift.station_id.id,
            'sequence': next_type.sequence,
        }
        _logger.info(f'Adding next shift from shift {shift} with vals {vals}')
        return self.create(vals)

    def add_current(self, shift):
        history = self.search(
                [('station_id', '=', shift.station_id.id),
                 ('date', '=', shift.date),
                 ('type_id', '=', shift.type_id.id),
                 ('shift_id', '=', shift.id),
                 ])
        if history:
            return history
        vals = {
            'type_id': shift.type_id.id,
            'sequence': shift.type_id.sequence,
            'date': shift.date,
            'station_id': shift.station_id.id
        }
        _logger.info(f'Adding shift {shift} with vals {vals}')
        return self.create(vals)

    def linear_validate(self, shift):
        if not self.search([]):
            # if this is the first shift then start a new sequence
            return self.next_history(shift)
            
        history = self.search([
            ('station_id', '=', shift.station_id.id), 
            ('date', '=', shift.date),
            ('type_id', '=', shift.type_id.id),
            ('shift_id', 'in', (False, shift.id))
        ])
        if history:
            _logger.info(f'Found history {history}')
            
            history.write({'shift_id': shift.id})
            return self.next_history(shift)
