from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class ReceiveMoves(models.Model):
    _name = 'receive.move.wizard'
    _description = 'Shift stock from moves'

    shift_id = fields.Many2one('station.shift', string='Shift')
    station_id = fields.Many2one(
        related='shift_id.station_id', string='Station')
    picking_type_id = fields.Many2one(related='station_id.operation_type_id')
    location_id = fields.Many2one(related='picking_type_id.default_location_src_id', string='Location')
    
    move_lines = fields.Many2many('stock.move.line', 
                                string='Moves',
                                domain="[('location_dest_id', '=', location_id), ('station_processed', '=', False), ('state', '=', 'done')]")
    

    def action_apply(self):
        vals = []
        for move in self.move_lines:
            vals.append((0, 0, {
                'product_id': move.product_id.id,
                'shift_id': self.shift_id.id,
                'location_id': move.picking_id.location_dest_id.id,
                'quantity': move.qty_done,
                'loaded_quantity': move.qty_done,
                'uom_id': move.product_uom_id.id,
                'move_line_id': move.id
            }))
        self.shift_id.write({'received_stock_line': vals})
        self.shift_id.received_stock_line._onchange_product_id()
        self.move_lines.write({'station_processed': True})
