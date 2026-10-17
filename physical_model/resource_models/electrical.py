"""Guest reserves, mission lines, and simultaneous bounded peak demand."""
from .common import model, need, n, mode, check, rule, result, InputError

@model('electrical')
def evaluate(specs, state, guests):
    spec = need(specs, 'electrical')
    online = n(state, 'gensets_online')
    if online not in (1, 2):
        raise InputError('gensets_online must be 1 or 2')
    band = need(state, 'speed_band')
    reserves = need(spec, 'reserve_kw_by_speed')
    if band not in reserves:
        raise InputError(f'No sea-going reserve specified for speed band: {band}')
    continuous = n(reserves[band], str(int(online)))
    extra_capacity = n(need(spec, 'peak_extra_kw'), str(int(online)))
    max_duration = n(spec, 'peak_max_duration_s')
    lines = need(spec, 'lines_kw')
    online_lines = need(state, 'online_power_lines')
    if not isinstance(online_lines, list) or len(set(online_lines)) != len(online_lines):
        raise InputError('online_power_lines must contain unique line IDs')
    if any(line not in lines for line in online_lines):
        raise InputError('Unknown online power line')
    loads = {line: 0.0 for line in lines}
    peak_lines = {line: 0.0 for line in lines}
    total = peak_extra = 0.0
    checks = []
    for g in guests:
        m = mode(g)
        power, extra, duration = n(m, 'power_kw'), n(m, 'peak_extra_kw'), n(m, 'peak_duration_s')
        line = need(g, 'power_line')
        if line not in lines:
            raise InputError(f'{g["id"]}: unknown mission power line {line}')
        total += power
        peak_extra += extra
        loads[line] += power
        peak_lines[line] += power + extra
        checks.append(rule(g['id'] + '.peak_duration', extra == 0 or (0 < duration <= max_duration),
                           f'{g["id"]}: peak duration {duration:g} s, permitted up to {max_duration:g} s; sustained demand belongs in power_kw.', 'A.1'))
    checks += [check('continuous_reserve', total, continuous, 'kW', 'A.1 / selected speed'),
               check('coincident_peak', total + peak_extra, continuous + (extra_capacity if total < continuous else 0), 'kW', 'A.1')]
    for line in sorted(lines):
        capacity = n(lines, line) if line in online_lines else 0
        checks += [check(line + '.continuous', loads[line], capacity, 'kW', 'A.1'),
                   check(line + '.peak', peak_lines[line], capacity, 'kW', 'A.1; conservative line peak cap')]
    return result('electrical', checks, {'demand_kw': total, 'capacity_kw': continuous,
                  'remaining_kw': continuous-total, 'peak_demand_kw': total+peak_extra,
                  'line_demands_kw': loads})
