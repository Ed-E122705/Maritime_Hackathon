"""Evaluate explicit deterministic scenarios; do not invent statistical uncertainty."""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physical_model.ship_state import ShipState
from physical_model.snapshot import build_snapshot, write_snapshot
from physical_model.manifest_adapter import load_json, load_canonical_guests


def run():
    data = ROOT / 'physical_model/data'
    specs = load_json(data / 'ship_specs.json')
    guests = load_canonical_guests()
    profiles = load_json(data / 'resource_profiles.json')
    charge = ShipState.from_files(runtime_path=ROOT / 'scenarios/B_generator_trip_overload.json')
    results = []

    def record(name, state, profile, changed):
        report = build_snapshot(specs, state, guests, profile)
        resources = report['resources']
        results.append({'case': name, 'varied_inputs': changed,
                        'physical_simulation_status': report['status'],
                        'assessment_status': report['assessment_status'],
                        'electrical': resources['electrical']['details'],
                        'cooling': resources['cooling']['details'],
                        'datalinks': resources['datalinks']['details'],
                        'constraint_violations': report['constraint_violations'],
                        'input_sha256': report['input_sha256']})

    for gensets, temp, fault, mode in [(2,24,False,'full'), (1,30,True,'full'),
                                      (1,30,True,'low_power'), (1,24,False,'low_power')]:
        updates = {'gensets_online': gensets, 'seawater_c': temp, 'cooling_fault': fault,
                   'guests': {'G5': {'power_mode': mode}}}
        record(f'charge_gensets{gensets}_{temp}C_fault{int(fault)}_{mode}', charge.updated(updates), profiles, updates)
    # Throttling electrical demand does not imply a reduction in required SATCOM.
    low = charge.updated({'guests': {'G5': {'power_mode': 'low_power'}}})
    for capacity in (2, 8):
        updates = {'links': {'satcom': {'available_mbps': capacity}}}
        record(f'g5_low_satcom_{capacity}Mbps', low.updated(updates), profiles, updates)
    # Isolate video range; all values are explicitly selected test inputs.
    video = ShipState.from_files().updated({
        'guests': {g['id']: {'installed': g['id'] == 'G4'} for g in guests},
        'guest_state': {'G4': {'battery_percent': 60, 'flight_elapsed_minutes': 10}},
        'links': {'los': {'available_mbps': 10}},
    }).updated({'guests': {'G4': {'operation': 'in_flight'}}})
    for rate in (5, 10, 20):
        profile = copy.deepcopy(profiles)
        profile['g4_los_nominal_mbps'] = rate
        record(f'g4_video_{rate}Mbps_on_10Mbps_link', video, profile, {'g4_los_nominal_mbps': rate, 'available_los_mbps': 10})
    survey = ShipState.from_files(runtime_path=ROOT / 'scenarios/B_minute0_survey.json').updated({
        'guests': {g['id']: {'installed': g['id'] == 'G3'} for g in guests}})
    for capacity in (.001, .003, .005):
        updates = {'links': {'acoustic': {'available_mbps': capacity}}}
        record(f'g3_acoustic_capacity_{capacity}Mbps', survey.updated(updates), profiles, updates)
    output = {'meaning': 'Explicit demonstration scenarios, not confidence intervals. Source evidence remains incomplete.',
              'cases': results}
    write_snapshot(output, ROOT / 'data/ASSUMPTIONS_SENSITIVITY.json')
    print(f'Wrote {len(results)} evaluated sensitivity cases.')
    for case in results:
        print(case['case'], case['physical_simulation_status'])


if __name__ == '__main__':
    run()
