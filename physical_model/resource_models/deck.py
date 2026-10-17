"""Validate chosen deck placements and current flight/ramp operation conditions.

Does not search for a placement or grant an at-sea installation window.
"""
from .common import model, need, n, placements, check, rule, result, InputError

@model('deck')
def evaluate(specs, state, guests):
    rows = placements(specs, guests)
    loads, units, lengths = {}, {}, {}
    checks = []
    for gid, p, spec in rows:
        if need(spec, 'kind') == 'mast':
            continue
        loc = need(p, 'location')
        loads[loc] = loads.get(loc, 0) + n(p, 'mass_kg')
        units[loc] = units.get(loc, 0) + n(p, 'units')
        dims, limits = need(p, 'dimensions_m'), need(spec, 'dimensions_m')
        if len(dims) != 3 or len(limits) != 3:
            raise InputError('dimensions_m must be [length, width, height]')
        if loc.startswith('bay'):
            from .common import number
            lengths[loc] = lengths.get(loc, 0) + number(dims[0], loc+'.length')
        for i, axis in enumerate(('length', 'width', 'height')):
            from .common import number
            checks.append(check(f'{gid}.{loc}.{axis}', number(dims[i], axis), number(limits[i], axis), 'm', 'A.3 / declared envelope'))
    for loc in sorted(loads):
        spec = specs['positions'][loc]
        if loc in lengths:
            checks.append(check(loc+'.packed_length', lengths[loc], spec['dimensions_m'][0], 'm', 'axis-aligned bay packing assumption'))
        checks += [check(loc+'.mass', loads[loc], n(spec, 'mass_limit_kg'), 'kg', 'A.3 / assumption'),
                   check(loc+'.occupancy', units[loc], n(spec, 'units'), 'units', 'A.3')]
    operations = need(state, 'active_operations')
    if not isinstance(operations, list) or len(set(operations)) != len(operations):
        raise InputError('active_operations must be a unique list')
    if any(op not in ('flight', 'ramp') for op in operations):
        raise InputError('Unknown deck operation')
    checks.append(rule('flight_ramp_exclusion', len(operations) < 2,
                       'Flight deck and ramp operations cannot run together.', 'A.3'))
    for op in operations:
        limits = need(need(specs, 'operations'), op)
        speed = n(state, 'speed_kn')
        checks += [check(op+'.sea_state', n(state, 'sea_state'), n(limits, 'max_sea_state'), 'sea-state', 'A.3'),
                   rule(op+'.speed', n(limits, 'min_speed_kn') <= speed <= n(limits, 'max_speed_kn'),
                        f'{op}: speed {speed:g} kn must lie in {limits["min_speed_kn"]}–{limits["max_speed_kn"]} kn.', 'A.3'),
                   rule(op+'.course', need(state, 'course') == 'steady', f'{op}: steady course required during operation.', 'A.3'),
                   rule(op+'.deck_clear', need(state, 'deck_state') == 'clear', f'{op}: deck must be clear.', 'A.3')]
        if op == 'flight':
            checks.append(check('flight.wind', n(state, 'wind_kn'), n(limits, 'max_wind_kn'), 'kn', 'A.3'))
    return result('deck', checks, {'occupancy_units': units, 'mass_by_position_kg': loads})
