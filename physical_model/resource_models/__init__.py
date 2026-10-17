"""Eight physical/time resource checks, plus canonical guest operating constraints."""
from . import electrical, cooling, deck, mast, mass, datalinks, compute, timing, operational
MODELS = (electrical, cooling, deck, mast, mass, datalinks, compute, timing)

def evaluate_all(specs, state, guests):
    results = {m.__name__.rsplit('.', 1)[-1]: m.evaluate(specs, state, guests) for m in MODELS}
    # Canonical rules are evaluated only for normalized guests carrying manifest context.
    if state.get('_guest_manifests') or any(g.get('_manifest') is not None and g.get('installed') for g in guests):
        results['operational'] = operational.evaluate(specs, state, guests)
    statuses = [r['status'] for k,r in results.items() if k != 'timing']
    status = 'FAIL' if 'FAIL' in statuses else ('UNKNOWN' if 'UNKNOWN' in statuses else 'PASS')
    timing_status = results['timing']['status']
    return {'status':status, 'feasible': status == 'PASS', 'physical_feasible': status == 'PASS',
            'timing_status':timing_status, 'timing_verified':timing_status == 'PASS',
            'resources':results,
            'scope':'Snapshot physical/operational feasibility only; D1 mission envelope and D3/D4 decisions live in separate engine.'}
