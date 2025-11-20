from . import models
from . import wizards
from . import reports

from odoo import api, SUPERUSER_ID


def _post_init_shift_history(cr, registry):
    """"""
    env = api.Environment(cr, SUPERUSER_ID, {})
    shifts = env['station.shift'].search([])
    for shift in shifts:
        hist = env['shift.history'].search([('shift_id', '=', shift.id)])
        if not hist:
            env['shift.history'].add_current(shift)
