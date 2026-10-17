"""Check supplied worst-case timing evidence; does not infer WCET from CPU usage."""
from .common import model, need, n, flag, check, unknown, result, InputError

@model('timing')
def evaluate(specs, state, guests):
    deadlines = need(specs, 'timing_ms')
    evidence = need(state, 'timing')
    checks = []
    for action, limit in deadlines.items():
        from .common import number
        limit = number(limit, action+'.deadline')
        item = evidence.get(action)
        if item is None:
            checks.append(unknown(action, f'{action}: no worst-case timing evidence supplied.'))
            continue
        value = n(item, 'worst_case_ms')
        verified = flag(item, 'verified')
        if not verified:
            checks.append(unknown(action, f'{action}: {value:g} ms is an unverified estimate.'))
        checks.append(check(action, value, limit, 'ms', 'A.8 / supplied timing evidence'))
    if not deadlines:
        raise InputError('timing_ms must not be empty')
    for guest in guests:
        manifest = guest.get('_manifest')
        if manifest is None:
            continue
        limit = manifest['resources']['response_time']['max_processing_latency_ms']
        name = guest['id'] + '.processing_latency'
        if limit is None:
            checks.append(unknown(name, 'Guest processing-latency requirement is not declared.'))
            continue
        limit = number(limit, name + '.limit')
        measured = state.get('guest_state', {}).get(guest['id'], {}).get('processing_timing')
        if measured is None:
            checks.append(unknown(name, 'No guest processing timing evidence supplied.'))
            continue
        if not flag(measured, 'verified'):
            checks.append(unknown(name, 'Guest processing timing is an unverified estimate.'))
        checks.append(check(name, n(measured, 'worst_case_ms'), limit, 'ms', 'Guest response_time / supplied evidence'))
    return result('timing', checks, {'meaning': 'Evidence screening only; not a schedulability proof.'})
