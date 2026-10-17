"""Shared validation and JSON-ready result format. Units are explicit in keys."""
from functools import wraps
from math import isfinite

class InputError(ValueError):
    """Missing or invalid model input: cannot certify feasibility."""

def number(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise InputError(f'{label}: expected a finite number')
    if value < minimum:
        raise InputError(f'{label}: must be >= {minimum}')
    return float(value)

def need(obj, key):
    if not isinstance(obj, dict) or key not in obj:
        raise InputError(f'Missing required field: {key}')
    return obj[key]

def n(obj, key, minimum=0):
    return number(need(obj, key), key, minimum)

def flag(obj, key):
    value = need(obj, key)
    if not isinstance(value, bool):
        raise InputError(f'{key}: expected boolean')
    return value

def mode(guest):
    modes = need(guest, 'modes')
    name = need(guest, 'mode')
    if not isinstance(modes, dict) or name not in modes:
        raise InputError(f'{guest.get("id")}: unknown mode {name}')
    return modes[name]

def guests_checked(guests):
    if not isinstance(guests, (list, tuple)):
        raise InputError('guests: expected list')
    ids = []
    for g in guests:
        gid = need(g, 'id')
        if not isinstance(gid, str) or not gid:
            raise InputError('Guest id must be a nonempty string')
        ids.append(gid)
        flag(g, 'installed')
    if len(set(ids)) != len(ids):
        raise InputError('Duplicate guest IDs')
    return [g for g in guests if g['installed']]

def check(name, demand, capacity, unit, source):
    demand = number(demand, name + '.demand')
    capacity = number(capacity, name + '.capacity')
    margin = capacity - demand
    passed = margin >= -1e-9
    return {'name': name, 'status': 'PASS' if passed else 'FAIL',
            'demand': demand, 'capacity': capacity, 'remaining': margin,
            'unit': unit, 'source': source,
            'reason': f'{name}: requires {demand:g} {unit}; capacity {capacity:g} {unit}; '
                      + (f'margin {max(0, margin):g} {unit}.' if passed
                         else f'exceeds by {-margin:g} {unit}.')}

def rule(name, passed, reason, source):
    return {'name': name, 'status': 'PASS' if passed else 'FAIL',
            'reason': reason, 'source': source}

def unknown(name, reason):
    return {'name': name, 'status': 'UNKNOWN', 'reason': reason, 'source': 'missing evidence'}

def result(resource, checks, details=None):
    failed = [c for c in checks if c['status'] == 'FAIL']
    missing = [c for c in checks if c['status'] == 'UNKNOWN']
    status = 'FAIL' if failed else ('UNKNOWN' if missing else 'PASS')
    binding = failed or missing
    return {'resource': resource, 'status': status, 'feasible': status == 'PASS',
            'checks': checks, 'binding_constraints': [c['name'] for c in binding],
            'reason': ' '.join(c['reason'] for c in binding) if binding else 'All modeled checks pass.',
            'details': details or {}}

def model(resource):
    """Return UNKNOWN for malformed inputs; never silently replace them with zeros."""
    def decorate(fn):
        @wraps(fn)
        def wrapped(specs, state, guests):
            try:
                selected = guests_checked(guests)
                return fn(specs, state, selected)
            except (InputError, KeyError, TypeError, IndexError, AttributeError) as exc:
                return result(resource, [unknown('input_validation', str(exc))])
        return wrapped
    return decorate

def positions(specs):
    return need(specs, 'positions')

def placements(specs, guests):
    available = positions(specs)
    rows = []
    for g in guests:
        parts = need(g, 'placements')
        if not isinstance(parts, list) or not parts:
            raise InputError(f'{g["id"]}: installed guest needs physical placements')
        for p in parts:
            loc = need(p, 'location')
            if loc not in available:
                raise InputError(f'Unknown placement: {loc}')
            rows.append((g['id'], p, available[loc]))
    return rows
