# VesselOS resource model — updated G1–G5

This package uses the five newly attached **G1 (1).json–G5 (1).json** manifests and the `ship_specs.json` from your ZIP. Guest copies are byte-identical to those attachments, under descriptive filenames in `data/guests/`. The host specifications are unchanged.

The package includes `ship_state.py`, all eight requested resource models, `constraints.py`, `snapshot.py`, and tests. It evaluates a selected ship/guest configuration and produces resource demand, capacity, margin, reasons, and evidence gaps. It does not choose placements or schedule an entire mission.

## Run

Use Python 3.10 or newer, from this folder:

```bash
python3 run_example.py --output example_output.json
python3 -m physical_model.snapshot --runtime scenarios/B_after_G5_throttle.json --output throttled_snapshot.json
python3 -m unittest discover -s physical_model/tests -v
python3 scripts/audit_assumptions.py
python3 scripts/run_sensitivity.py
```

No third-party packages are required for the model or tests. If `jsonschema` is installed, loading also applies `data/guest_schema.json`; otherwise the loader uses structural and semantic-reference checks. This delivery's recorded checks used the standard-library path.

## Files to integrate

| File or directory | Purpose |
|---|---|
| `physical_model/ship_state.py` | Immutable state container, nested scenario updates, explicit file loading |
| `physical_model/manifest_adapter.py` | Canonical guest facts plus runtime selections and disclosed profiles → normalized model input |
| `physical_model/resource_models/electrical.py` | Continuous and declared peak loads; total and branch capacities |
| `physical_model/resource_models/cooling.py` | Heat balance, temperature derating, fault capacity, air/loop routing |
| `physical_model/resource_models/deck.py` | Position dimensions, mass, occupancy and flight/ramp operating limits |
| `physical_model/resource_models/mast.py` | Reserved positions, occupancy, mass and area |
| `physical_model/resource_models/mass.py` | Installed mass and weighted stability-budget screen |
| `physical_model/resource_models/datalinks.py` | Separate link capacity, latency, connectivity and blackout checks |
| `physical_model/resource_models/compute.py` | Per-node CPU/RAM/accelerators, placement and storage reserve |
| `physical_model/resource_models/timing.py` | Host deadlines and declared guest processing deadlines versus supplied evidence |
| `physical_model/resource_models/operational.py` | Guest operating conditions, conflicts, battery deadline and installation screening |
| `physical_model/constraints.py` | Combined model status, violations and unresolved checks |
| `physical_model/snapshot.py` | Deterministic JSON snapshot, per-guest resources, input hashes and evidence status |
| `physical_model/data/assumptions.json` | Reviewed assumption register, source references and justifications |
| `physical_model/data/resource_profiles.json` | Executable demonstration choices for missing demands, dimensions and operational policy |
| `physical_model/data/ship_specs.json` | Supplied host capacities and constraints |
| `physical_model/data/example_state.json` | Explicit base simulation state |
| `physical_model/data/sample_runtime.json` | Installation, placement, power/operation selections and context |
| `data/guests/` | One current authoritative file per guest ID |
| `physical_model/tests/` | Resource boundaries, integration and updated-manifest regressions |

Keep the package layout for the quickest integration. To use your existing guest directory:

```bash
python3 run_example.py --guest-dir /path/to/your/guest_manifests
```

Both `G1.json` and `g1.json` naming styles work. Keep exactly one file per guest ID in that directory. The adapter reads IDs inside the files; it rejects duplicate IDs. Historical files under `tests/fixtures/legacy_guest_manifests/` are isolated test fixtures and are never loaded in production.

## Use it in Python

```python
from physical_model.ship_state import ShipState
from physical_model.snapshot import build_snapshot, load_snapshot
from physical_model.manifest_adapter import ROOT, load_json, load_canonical_guests

# Simple file-based interface; defaults explicitly select the packaged demo.
report = load_snapshot()
print(report['status'])                 # conditional physical/operational simulation
print(report['assessment_status'])      # also considers timing and source evidence
print(report['resources']['cooling']['details'])

# Live state or hypothetical change; originals are not modified.
state = ShipState.from_files()
candidate = state.updated({
    'gensets_online': 1,
    'guests': {'G5': {'power_mode': 'low_power'}},
})
data = ROOT / 'physical_model' / 'data'
report = build_snapshot(
    specs=load_json(data / 'ship_specs.json'),
    state=candidate,
    canonical_guests=load_canonical_guests(),
    profiles=load_json(data / 'resource_profiles.json'),
)
```

`ShipState.from_dict(your_state)` inserts no healthy readings or guest modes. `updated()` merges nested objects, replaces arrays/scalars, and returns a new state. Set `installed: false` to remove a guest; an empty update object preserves existing fields. Invalid manifest selections raise `InputError`; missing resource-state evidence yields `UNKNOWN` in the affected model. `evaluate_canonical(...)` remains available as a compatible file interface.

## Changes driven by your updated guests

- **Power mappings:** consume `power_mode_id` and `allowed_power_mode_ids`. A fixed mapping may supply an omitted power selection; a contradictory selection is rejected. A null mapping requires an explicit runtime choice and remains conditional.
- **Conflicts:** the corrected `launch_recovery` identifiers now connect G2/G3 conflicts to G4's actual operation.
- **Installation:** select the updated operation/component/target record. G3's `swap_vehicle_only` keeps the cradle installed; crew and duration come from the chosen record. Missing installation time budget yields `UNKNOWN`.
- **G5 cooling:** all declared 45/8 kW goes to the bay chilled-water path. The invented 1 kW antenna split is removed.
- **G5 data:** reserve the declared 6 Mbps maximum in both modes. A 70% capability loss does not establish a 70% bandwidth reduction.
- **G3 survey:** deployed power remains an explicit demonstration estimate; the surveying compute profile is used. A later declared operation-power mapping supersedes the estimate.
- **Source-driven numbers:** read guest bandwidth, compute values when provided, mass, battery threshold/deadline, noninterruptible charge duration and radar capability loss from the manifests.
- **Recovery deadline:** check elapsed time since low-battery onset plus landing ETA. A new snapshot does not reset the deadline.
- **Existing roof:** G5 requires the declared roof availability and drone-clearance conditions; it does not require G4 to be admitted if an existing roof is available.
- **Uncertainty:** G1 transmission is suppressed in silence without claiming buffering. G2 buffering has no specified duration/capacity. Unknown peaks, geometry, compute and guest latency tolerances remain disclosed.

## Assumptions and varying results

`assumptions.json` separates **25 assumption/scenario records**, **8 source-rule records**, and **7 unresolved-input groups**. It is an evidence register; numerical execution inputs live in `resource_profiles.json`, `ship_specs.json`, and the runtime state. Each record says what is used, why, its effect, its source location and how to replace or verify it. Several records describe a scenario or model scope rather than an invented physical number.

Read `data/ASSUMPTIONS_AND_JUSTIFICATIONS.md` for the full list. `data/PHYSICAL_ACCOUNT_WORKING.csv` is the working register. `data/ASSUMPTIONS_REVIEW.md` summarizes the changes and remaining gaps.

`data/ASSUMPTIONS_SENSITIVITY.json` contains 12 actual deterministic model runs, varying generators, temperature, cooling fault, G5 mode, link capacity and G4 bitrate. They are explicit test scenarios, not uncertainty distributions.

| Scenario | Electrical demand | Loop demand / capacity | Conditional physical status |
|---|---:|---:|---|
| G3 charge + G4 initial charge + G5 full; two gensets, 24°C, normal cooling | 105 kW | 105 / 133.33 kW | PASS |
| Same guests; one genset, 30°C, cooling fault | 105 kW | 105 / 72 kW | FAIL |
| Same degraded state; G5 low power | 68 kW | 68 / 72 kW | PASS |
| G5 low power with only 2 Mbps SATCOM available | 68 kW | Depends on selected thermal state | FAIL — 6 Mbps reserved |

All successful examples still have incomplete source/timing evidence. Numeric `verified: true` is a caller assertion, not a benchmark performed by this code.

After reviewing deliberate source/profile changes, update affected register references and hashes, then run:

```bash
python3 scripts/render_assumption_docs.py
python3 scripts/audit_assumptions.py
```

The audit detects stale source hashes, stale JSON-pointer values, unregistered trace IDs and inconsistent generated documentation. Do not refresh hashes without reviewing the assumptions they support.

## Scope and integration boundary

`status` / `physical_feasible` describe the selected physical/operational simulation. `timing_status` remains separate. `overall_model_status` includes timing, and `assessment_status` additionally includes incomplete source evidence. `full_admission_status` is `NOT_EVALUATED`.

The other decision components still need full mission-envelope admission, placement search, priority arbitration, reachable transitions, crew/crane scheduling, thermal buffer state, autonomy authorization and real timing validation. The weighted stability check is a challenge budget screen, not a hydrostatic calculation. No physical actions are issued.

The original three-brain composition interface (`brain_state.compose_state`) and five example scenarios remain available. See `data/DATA_CONTRACT_FOR_DECISION_TEAM.md` for the input/output contract and `TEST_RESULTS.txt` for recorded validation.
