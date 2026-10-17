"""Per-link capacity, blackout and worst-case latency (no bandwidth pooling)."""
from .common import model, need, n, flag, mode, check, rule, result, InputError

@model('datalinks')
def evaluate(specs, state, guests):
    links = need(specs, 'datalinks')
    states = need(state, 'links')
    emission = need(state, 'emission')
    if emission not in ('normal', 'silent'):
        raise InputError('emission must be normal or silent')
    noise = need(state, 'noise')
    if noise not in ('quiet', 'normal', 'manoeuvring'):
        raise InputError('Unknown noise level')
    layered = flag(state, 'layered_water')
    machinery = flag(state, 'deck_machinery')
    sums = {name: 0.0 for name in links}
    capacities = {}
    checks = []
    for name, spec in links.items():
        link_state = need(states, name)
        connected = flag(link_state, 'connected')
        latency = n(link_state, 'latency_ms')
        capacity = n(link_state, 'available_mbps')
        checks.append(check(name+'.reported_capacity', capacity, n(spec, 'max_mbps'), 'Mbps', 'A.5 / narrowed upper bound'))
        if not connected or (name in ('satcom', 'los') and emission == 'silent'):
            capacity = 0
        if name == 'acoustic' and (noise == 'manoeuvring' or machinery or layered):
            capacity = 0
        capacities[name] = capacity
        for g in guests:
            demands = need(mode(g), 'datalinks')
            if set(demands) != set(links):
                raise InputError(f'{g["id"]}: declare all links explicitly, including zero demand')
            request = demands[name]
            demand = n(request, 'mbps')
            maximum = n(request, 'max_latency_ms')
            required = flag(request, 'required')
            sums[name] += demand
            if demand > 0 or required:
                checks += [rule(g['id']+'.'+name+'.available', capacity > 0,
                                f'{g["id"]}: {name} required but effective capacity is {capacity:g} Mbps.', 'A.5 / state'),
                           check(g['id']+'.'+name+'.latency', latency, maximum, 'ms',
                                 request.get('latency_source', 'declared latency tolerance'))]
    checks.extend(check(name+'.bandwidth', sums[name], capacities[name], 'Mbps', 'A.5 / observed state') for name in sorted(links))
    return result('datalinks', checks, {'demand_mbps': sums, 'effective_capacity_mbps': capacities})
