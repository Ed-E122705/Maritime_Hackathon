"""Added mass and Annex A.4 weighted stability-budget screen, not hydrostatics."""
from .common import model, need, n, placements, check, result, rule

@model('mass')
def evaluate(specs, state, guests):
    spec = need(specs, 'mass')
    mass = equiv = 0.0
    breakdown = []
    for gid, p, loc in placements(specs, guests):
        m = n(p, 'mass_kg')
        weighted = m*n(loc, 'stability_multiplier')
        mass += m
        equiv += weighted
        breakdown.append({'guest_id': gid, 'location': p['location'], 'mass_kg': m, 'equivalent_kg': weighted})
    checks = [check('added_mass', mass, n(spec, 'margin_kg'), 'kg', 'A.4'),
              check('stability_budget', equiv, n(spec, 'stability_budget_kg_eq'), 'kg-eq', 'A.4')]
    for g in guests:
        parts = sum(n(p, 'mass_kg') for p in g['placements'])
        declared = n(g, 'mass_kg')
        checks.append(rule(g['id']+'.mass_balance', abs(parts-declared) <= 1e-9,
                           f'{g["id"]}: component mass {parts:g} kg must equal declared {declared:g} kg.', 'manifest integrity'))
    return result('mass', checks, {'demand_kg': mass, 'capacity_kg': spec['margin_kg'],
                  'equivalent_kg': equiv, 'parts': breakdown, 'naval_stability': 'NOT_VERIFIED'})
