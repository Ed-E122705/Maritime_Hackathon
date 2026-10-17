# Resource-model input/output contract

## Input authority

1. `data/guests/` contains the newly attached G1–G5 files, unchanged in content. Never edit a guest file to simulate a state change.
2. `physical_model/data/ship_specs.json` supplies configured host limits, including separately disclosed host placeholders.
3. Runtime state contains installation selections, placement, selected power mode, operation and observed/simulated environment.
4. `resource_profiles.json` supplies explicit missing-data demonstration choices. `assumptions.json` documents their evidence and limits.

`ShipState.from_dict(values)` has no physical defaults. `ShipState.from_files()` explicitly selects packaged base-state/runtime fixtures. Nested updates preserve unaffected fields; lists are replaced. To remove a guest, set its `installed` flag to false.

## Entrypoints

```python
from physical_model.snapshot import load_snapshot, build_snapshot
from physical_model.ship_state import ShipState

report = load_snapshot(guest_dir='guests', runtime_path='scenarios/B_minute8_conflict.json')
# For live dictionaries:
# report = build_snapshot(specs, ShipState.from_dict(state), canonical_guests, profiles)
```

`manifest_adapter.evaluate_canonical(...)` remains a compatible alias for loading files. Resource modules expose `evaluate(specs, state, normalized_guests)`. `constraints.evaluate(...)` aggregates their results. Use `snapshot.build_snapshot(...)` when source provenance and installation requests for uninstalled guests are needed.

## Runtime guest selections

Each installed guest needs a valid `placement` configuration. `operation` is an operational-mode ID or null. `power_mode` is a declared electrical-mode ID.

- A non-null `power_mode_id` on the selected operation defines its only valid power mode. If runtime omits that selection, the adapter uses the declared mapping.
- `allowed_power_mode_ids` constrains the selected power mode, as in G5.
- A null mapping does not declare zero load or a standby mapping. Select a mode explicitly; associated load remains conditional. G3 deployed power additionally uses its disclosed survey profile until the source supplies a fixed mapping.
- `power_line` overrides the profile's branch assignment.
- Invalid modes, unknown guest IDs, duplicate components or contradictory mappings raise `InputError`.

Known guest numerical values override applicable demo values. The G5 SATCOM reservation policy deliberately uses its maximum in every mode. Per-link latency tolerances remain synthetic; they are not derived requirements from host link latency.

## Temporal and installation context

`guest_state.G4` can contain `battery_percent`, `flight_elapsed_minutes`, `mode_elapsed_minutes`, `eta_to_landing_min`, and `minutes_since_low_battery`. When battery is below the manifest threshold:

```text
minutes_since_low_battery + eta_to_landing_min <= recovery_deadline_minutes
```

Missing onset/ETA/battery evidence gives `UNKNOWN` when required; an ETA longer than the entire budget is already a definite failure. The caller must retain the actual deadline origin across snapshots. This is a necessary time-budget check, not a trajectory planner.

Installation requests select one record and supply a time budget, for example:

```json
{
  "guest_id": "G3",
  "operation": "swap_vehicle_only",
  "operation_target": "vehicle",
  "available_minutes": 45
}
```

For G4 use `operation: "swap_component"`, `component_id: "drone"`, and its available window. Legacy `change: "vehicle_swap"` / `"drone_swap"` remain supported. In port, `change: "new_guest"` plus a component ID can select a record that has no operation label. Multiple records require separate explicit requests; combined crew/time scheduling is outside this screen.

`mode_change_requests` carry `guest_id`, `from_mode`, `to_mode`, and `elapsed_minutes`. Noninterruptible duration comes from the source mode. These are screening inputs, not applied actions.

For supplied guest processing deadlines use:

```json
{"guest_state": {"G1": {"processing_timing": {"worst_case_ms": 15, "verified": true}}}}
```

Set verification only with supporting evidence. Processing deadlines and link-latency tolerances are different quantities.

## Report fields

| Field | Meaning |
|---|---|
| `status` | `PASS`, `FAIL`, or `UNKNOWN` for conditional physical/operational simulation |
| `physical_feasible`, `feasible` | True only when `status` is PASS; these flags exclude source/timing qualification |
| `timing_status`, `timing_verified` | Host/declared guest timing evidence, independent of physical status |
| `overall_model_status` | Combined physical/operational and timing status |
| `assessment_basis` | `CONDITIONAL_SIMULATION` |
| `source_evidence_status` | `UNKNOWN` for this supplied evidence set, even when modeled budgets pass |
| `assessment_status` | Includes model status and source evidence; a known FAIL takes precedence |
| `full_admission_status` | `NOT_EVALUATED` |
| `resources` | Eight requested resource reports, plus canonical operational rules |
| `resources[name].checks` | Named check, status, reason/source and demand/capacity/margin where numerical |
| `constraint_violations` | All failed checks with resource-qualified IDs |
| `unresolved_constraints` | All UNKNOWN checks, retained even alongside a failure |
| `guest_resources` | Selected mode, operation, placements, mass and normalized resource demands per guest |
| `assumption_ids_used` | Register IDs for active/context choices; conservative context IDs may cover inactive subchecks |
| `source_evidence_gaps`, `host_evidence_gaps` | Missing evidence, separately from numerical infeasibility |
| `input_sha256` | Hashes of canonical serialized specs, state, profiles and guest dictionaries for replay |

A source-only admission decision cannot use a successful synthetic compute/geometry/latency check as proof. Resolve the evidence gaps and evaluate the mission envelope, reachable transitions, placement alternatives, priority policy, timing, and installation schedule in the decision engine.
