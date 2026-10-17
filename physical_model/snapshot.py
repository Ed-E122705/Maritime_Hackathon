"""Build a deterministic JSON report from canonical guests and one ship state.

Pure evaluation only: no file changes or physical actions in build_snapshot.
Use write_snapshot explicitly to save a result. Input hashes identify exactly
which guest/spec/profile/state dictionaries produced a simulation.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from .ship_state import ShipState
from .manifest_adapter import ROOT, load_json, load_canonical_guests, normalize_guests
from .constraints import evaluate, combine_statuses


def _digest(value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def build_snapshot(specs, state, canonical_guests, profiles):
    """Evaluate caller-owned dictionaries without implicit default inputs.

    state includes the `guests` selection object, plus observed ship conditions.
    Invalid manifest/mode/profile choices raise InputError/ValueError; missing
    resource-state evidence produces UNKNOWN in the affected model.
    """
    values = state.to_dict() if isinstance(state, ShipState) else ShipState.from_dict(state).to_dict()
    normalized, used = normalize_guests(canonical_guests, values, profiles)
    # Installation requests can concern guests not yet installed.
    evaluation_state = copy.deepcopy(values)
    evaluation_state['_guest_manifests'] = {g['id']: copy.deepcopy(g) for g in canonical_guests}
    evaluation_state['_operational_policy'] = copy.deepcopy(profiles['operational_policy'])
    report = evaluate(specs, evaluation_state, normalized)
    report.update({
        'schema_version': 'vessel-snapshot/2',
        'assessment_basis': 'CONDITIONAL_SIMULATION',
        'assumption_ids_used': used,
        'source_evidence_status': 'UNKNOWN',
        'source_evidence_gaps': {g['id']: g['_source_evidence_gaps'] for g in normalized},
        'host_evidence_gaps': [
            'Host hangar/roof dimensions and limits are unverified screening placeholders.',
            'Backbone aggregation and reserve-by-speed mapping are selected model choices.',
            'Reported environment and link state need external verification; the mission envelope is not evaluated.'
        ],
        'full_admission_status': 'NOT_EVALUATED',
        'installed_guest_ids': [g['id'] for g in normalized],
        'guest_resources': {
            g['id']: {'mass_kg': g['mass_kg'], 'placements': copy.deepcopy(g['placements']),
                      'power_line': g['power_line'], 'power_mode': g['mode'], 'operation': g['operation'],
                      'resources': copy.deepcopy(g['modes'][g['mode']])}
            for g in normalized
        },
        'input_sha256': {'specs': _digest(specs), 'state': _digest(values),
                         'profiles': _digest(profiles), 'guests': _digest(canonical_guests)},
        'scope': 'Chosen operating snapshot with disclosed estimates; no full-envelope admission or transition scheduling.',
    })
    # UNKNOWN is intentional for the supplied evidence set, even if every demo
    # budget passes. A known failure still takes precedence over missing evidence.
    report['assessment_status'] = combine_statuses([report['overall_model_status'], report['source_evidence_status']])
    return report


def load_snapshot(guest_dir=None, runtime_path=None, specs_path=None, state_path=None, profile_path=None):
    """File convenience interface; omitted paths select the bundled demo files."""
    data = ROOT / 'physical_model' / 'data'
    return build_snapshot(
        specs=load_json(specs_path or data / 'ship_specs.json'),
        state=ShipState.from_files(state_path=state_path, runtime_path=runtime_path),
        canonical_guests=load_canonical_guests(guest_dir),
        profiles=load_json(profile_path or data / 'resource_profiles.json'),
    )


def write_snapshot(report, path):
    path = Path(path)
    payload = json.dumps(report, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding='utf-8')
    return path


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('guest-dir', 'runtime', 'specs', 'state', 'profiles', 'output'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    report = load_snapshot(guest_dir=args.guest_dir, runtime_path=args.runtime,
                           specs_path=args.specs, state_path=args.state, profile_path=args.profiles)
    if args.output:
        write_snapshot(report, args.output)
    else:
        print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
