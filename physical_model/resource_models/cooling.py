"""Temperature derating, 1:1 heat balance and cooling-path compatibility.

No transient buffer is credited: this is a continuous feasibility check.
"""
from .common import model, need, n, mode, flag, positions, check, rule, result, InputError, unknown

@model('cooling')
def evaluate(specs, state, guests):
    spec = need(specs, 'cooling')
    cold, hot = n(spec, 'cold_c'), n(spec, 'hot_c')
    temp = n(state, 'seawater_c', -273.15)
    if hot <= cold or not cold <= temp <= hot:
        raise InputError('Temperature outside validated cooling curve or invalid endpoints')
    fraction = (temp-cold)/(hot-cold)
    cap = n(spec, 'cold_kw') + fraction*(n(spec, 'hot_kw')-n(spec, 'cold_kw'))
    loss = n(spec, 'fault_loss_fraction')
    if loss > 1:
        raise InputError('fault_loss_fraction must be <= 1')
    if flag(state, 'cooling_fault'):
        cap *= 1-loss
    pos = positions(specs)
    loop = total = 0.0
    checks = []
    air_loads = {}
    for g in guests:
        m = mode(g)
        power = n(m, 'power_kw')
        if n(m, 'peak_extra_kw') > 0:
            checks.append(unknown(g['id']+'.peak_thermal', 'Nonzero electrical peak requires transient heat-path and buffer accounting; not verified by the continuous cooling model.'))
        heat_sum = 0.0
        paths = need(m, 'heat_paths')
        if not isinstance(paths, list) or not paths:
            raise InputError(f'{g["id"]}: heat_paths required, including explicit zero paths when off')
        occupied = {need(p, 'location') for p in need(g, 'placements')}
        for path in paths:
            loc, heat = need(path, 'location'), n(path, 'kw')
            if loc not in pos or loc not in occupied:
                raise InputError(f'{g["id"]}: cooling location must be one of its placements')
            method = need(pos[loc], 'cooling')
            heat_sum += heat
            if method == 'loop':
                loop += heat
            elif method == 'air':
                air_loads[loc] = air_loads.get(loc, 0) + heat
            else:
                raise InputError(f'Unknown cooling method: {method}')
        total += heat_sum
        checks.append(rule(g['id']+'.heat_balance', abs(heat_sum-power) <= 1e-9,
                           f'{g["id"]}: {power:g} kW electric must equal {heat_sum:g} kW declared heat under A.2.', 'A.2'))
    checks.append(check('chilled_water_continuous', loop, cap, 'kW', 'A.2'))
    for loc, heat in sorted(air_loads.items()):
        checks.append(check(loc+'.air_heat', heat, n(pos[loc], 'air_heat_limit_kw'), 'kW', 'A.2 / assumption if non-mast'))
    return result('cooling', checks, {'total_heat_kw': total, 'loop_demand_kw': loop,
                  'capacity_kw': cap, 'remaining_kw': cap-loop, 'transient_buffer_credited': False})
