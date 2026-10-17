"""Node-aware CPU, RAM, accelerators and shared storage; ship reserve protected."""
from .common import model, need, n, flag, mode, check, rule, result, InputError

@model('compute')
def evaluate(specs, state, guests):
    spec = need(specs, 'compute')
    fraction = n(spec, 'guest_fraction')
    if fraction > 1:
        raise InputError('guest_fraction must lie in [0, 1]')
    nodes = need(spec, 'nodes')
    live = need(state, 'compute_nodes_online')
    if not isinstance(live, list) or len(set(live)) != len(live) or any(k not in nodes for k in live):
        raise InputError('compute_nodes_online must be unique known nodes')
    dimensions = ('cores', 'ram_gb', 'accelerators')
    caps = {k: {d: n(s, d)*fraction for d in dimensions} for k, s in nodes.items()}
    # Accelerators are indivisible: a rack-level reserve can be placed on named nodes.
    for key, node in nodes.items():
        caps[key]['accelerators'] = n(node, 'guest_accelerators')
        if caps[key]['accelerators'] > n(node, 'accelerators'):
            raise InputError('guest_accelerators exceeds physical node inventory')
        if not caps[key]['accelerators'].is_integer():
            raise InputError('guest_accelerators must be integer')
    checks = [check('rack.accelerator_reserve', sum(c['accelerators'] for c in caps.values()),
                    sum(n(s, 'accelerators') for s in nodes.values())*fraction, 'accelerators', 'A.7 / whole device reserve')]
    loads = {k: {d: 0.0 for d in dimensions} for k in nodes}
    storage = 0.0
    for g in guests:
        c = need(mode(g), 'compute')
        storage += n(c, 'storage_tb')
        allocs = need(c, 'allocations')
        totals = {d: 0.0 for d in dimensions}
        for alloc in allocs:
            key = need(alloc, 'node')
            if key not in nodes:
                raise InputError(f'Unknown compute node: {key}')
            for d in dimensions:
                val = n(alloc, d)
                if d == 'accelerators' and not val.is_integer():
                    raise InputError('accelerators must be integer')
                loads[key][d] += val
                totals[d] += val
        for d in dimensions:
            demand = n(c, d)
            checks.append(rule(g['id']+'.'+d+'.allocation_balance', abs(totals[d]-demand) <= 1e-9,
                               f'{g["id"]}: {d} allocation {totals[d]:g} must equal demand {demand:g}.', 'manifest integrity'))
    for key in sorted(nodes):
        for d in dimensions:
            checks.append(check(key+'.'+d, loads[key][d], caps[key][d] if key in live else 0, d, 'A.7 / node placement'))
    checks.append(check('online_rack.accelerators', sum(v['accelerators'] for v in loads.values()),
                        sum(n(nodes[k], 'accelerators') for k in live)*fraction,
                        'accelerators', 'A.7 / reserve on surviving hardware'))
    storage_capacity = n(spec, 'shared_storage_tb')*fraction
    checks.append(check('shared_storage', storage, storage_capacity, 'TB', 'A.7 / reserve applied'))
    return result('compute', checks, {'node_demands': loads, 'guest_capacity_by_online_node': {k: caps[k] for k in live},
                  'storage_demand_tb': storage, 'storage_capacity_tb': storage_capacity})
