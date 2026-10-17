"""Discrete positions, single-position mass and footprint, reserved ship slots."""
from .common import model, need, n, flag, positions, placements, check, rule, result

@model('mast')
def evaluate(specs, state, guests):
    pos = positions(specs)
    checks, count, masses, areas = [], {}, {}, {}
    for gid, p, spec in placements(specs, guests):
        if need(spec, 'kind') != 'mast':
            continue
        loc = need(p, 'location')
        count[loc] = count.get(loc, 0)+1
        masses[loc] = masses.get(loc, 0)+n(p, 'mass_kg')
        areas[loc] = areas.get(loc, 0)+n(p, 'area_m2')
        checks.append(rule(gid+'.'+loc+'.unreserved', not flag(spec, 'reserved'),
                           f'{gid}: {loc} is '+('reserved for ship systems.' if spec['reserved'] else 'available to guests.'), 'A.3'))
    for loc in sorted(count):
        spec = pos[loc]
        checks += [check(loc+'.occupancy', count[loc], 1, 'guest', 'A.3'),
                   check(loc+'.mass', masses[loc], n(spec, 'mass_limit_kg'), 'kg', 'A.3'),
                   check(loc+'.area', areas[loc], n(spec, 'area_limit_m2'), 'm2', 'A.3')]
    free = [loc for loc, s in pos.items() if s.get('kind') == 'mast' and not flag(s, 'reserved') and loc not in count]
    return result('mast', checks, {'free_guest_positions': free, 'occupied_guest_positions': sorted(count)})
