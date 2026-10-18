# VesselOS resource model — G1–G5 baseline with G6/G7 assumptions

The documented baseline package uses the five newly attached **G1 (1).json–G5 (1).json** manifests and the `ship_specs.json` from your ZIP. Guest copies are byte-identical to those attachments, under descriptive filenames in `data/guests/`. The host specifications are unchanged.

**G6 and G7 additions:** this README also documents the supplied fire-suppression and perimeter-camera assumptions. Their values are simulation inputs, not measured equipment ratings. Updating this README does not add manifests, modify the resource models or validate G6/G7 integration. Baseline test results and example outputs below apply to the original G1–G5 package.

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

## G6 — Fire detection and water-mist suppression

G6 is one atomic, safety-critical guest with monitoring and suppression modes. It starts in monitoring mode and must not be automatically shed. Suppression is treated as non-interruptible. Mission priority alone must not be used to enforce this protection.

| Parameter | Assumed value |
|---|---|
| Installed mass | 450 kg |
| Installation envelope | 1.5 × 1.0 × 1.8 m |
| Placement / electrical supply / compute node | `hangar` / `stbd` / `node3` |
| Monitoring electrical demand | 0.2 kW |
| Suppression electrical demand | 12.5 kW nominal |
| Suppression startup | Additional 6 kW for 3 s; 18.5 kW total peak |
| Monitoring compute | 2 CPU cores, 4 GB RAM |
| Suppression compute | 4 CPU cores, 8 GB RAM |
| Reserved compute | Maximum mode demand: 4 CPU cores, 8 GB RAM |
| Storage / accelerators | 50 GB (0.05 TB) / 0 |
| Backbone traffic | 1 Mbps monitoring; 2 Mbps suppression |
| Backbone latency allowance | 100 ms |
| SATCOM / LOS / acoustic traffic | 0 Mbps; not required |
| Nominal cooling load | 0.2 kW monitoring; 12.5 kW suppression |

- **Cooling:** the 1:1 electrical-to-heat assumption accounts for equipment heat. It does not represent heat removed from a fire. Startup thermal response remains unspecified.
- **Communications:** backbone telemetry is optional; local detection and suppression control are assumed independent of it. A telemetry loss must not be interpreted as a confirmed absence of fire.
- **Placement:** `hangar`, `stbd` and `node3` reuse existing identifiers. Their use does not establish available space, node capacity, service access or compatibility with G4.
- **Evidence gaps:** physical fit, water supply, installation crew/time, fire-trigger/reset logic and startup thermal response remain unresolved. Do not substitute zero or a healthy state for missing evidence.
- **Source:** supplied `G6_automated_fire_detection_and_suppression_updated.json` assumptions, summarized in the Maritime Hacks data-assumptions report. These supersede the older 500 kg, Bay 2, 2/8 kW and 100 GB G6 values.

## G7 — Perimeter camera with simulated G4 response

G7 supplies perimeter-motion metadata for a simulated G4 response. Its surveillance zone is separate from the launch deck. A motion candidate is not positive object identification and does not, by itself, authorize a launch.

| Parameter | Assumed value |
|---|---|
| Installed mass | 1.2 kg |
| Standby / monitoring / alert electrical demand | 0.020 / 0.040 / 0.065 kW |
| Metadata bandwidth | 0.02 Mbps |
| Heat path | Air |
| Simulation duration / time step | 180 s / 1 s |
| Object appears / clears | 20 s / 46 s |
| Detection confirmation | 2 positive samples |
| Data considered stale after | 5 s |
| Simulated G4 startup | 8 s |
| Initial G4 battery | 80% |
| Demonstration operator approval | 32 s; approval is initially false |
| G4 ship-side standby / flight load | 2 kW |
| G4 ship-side preflight / launch load | 3 kW |
| Simulated launch / patrol / return duration | 5 / 30 / 10 s |
| Reference conditions | 24°C seawater, wind 12 kn, sea state 2, ship speed 7 kn |

- **Launch conditions:** flight-deck clearance is independent of perimeter detection and initially unconfirmed. An occupied deck holds launch. Operator approval and all applicable resource and operating checks are also required.
- **Power boundary:** the 3 kW preflight/launch value is an illustrative ship-side load, not measured drone motor power. Drone propulsion draws from its onboard battery. These Scenario D loads do not replace G4's charging profiles in other scenarios.
- **Simulation boundary:** physical drone control is disabled. The 32 s approval is a demonstration event, not a general authorization policy.
- **Evidence gaps:** camera detection accuracy, measured processing latency, compute allocation, storage, exact placement and installation requirements are not established by this summary. The 1 s simulation step is not proof of real-time response.
- **Source:** supplied `scenario_D_assumptions.json`, summarized in the Maritime Hacks data-assumptions report.

## Integrating G6 and G7

Use the same source/profile/runtime separation as G1–G5:

1. Add exactly one authoritative manifest per guest ID to `data/guests/`. Adapt the supplied G6/G7 fields to the package's schema before claiming compatibility; do not assume a different manifest format will load unchanged.
2. Extend `resource_profiles.json` only for missing demonstration inputs and register their reasons and sources in `assumptions.json`. Keep unknown facts explicit. Existing assumption counts below describe the baseline and must be regenerated after integration.
3. Add explicit installation, placement, power mode, operation, supply and compute-node selections to the runtime state. Represent G7 detection freshness, operator approval and deck clearance independently.
4. Connect G6 per-mode demand, startup peak/duration, cooling, compute, storage and optional telemetry to the relevant models. Add its non-shedding policy to decision logic; a manifest note is not enforcement.
5. Connect G7 air heat, metadata and mode-dependent power to the models. Enforce the G4 launch conditions in the decision layer. Resolve flight/fire compatibility explicitly; a resource-total pass does not authorize simultaneous operations.
6. Review resource margins, schema validation and evidence gaps; then add regression checks for G6 mode/startup changes, non-shedding, missing telemetry, G7 stale detection, absent approval and occupied-deck launch holds. Run the existing test/audit commands and record new results separately.

### Combined resource checks

| Configuration / check | Illustrative result |
|---|---|
| Installed G3 + G4 + G5 | 9,565 kg |
| Add G6 (450 kg) and G7 (1.2 kg) | **10,016.2 kg: 16.2 kg above the 10,000 kg guest allowance** |
| Supplied combined monitoring case | 48.240 kW |
| Supplied G4 preflight + G6 suppression + G7 alert case | 61.565 kW |
| Same case during G6 startup | 67.565 kW |

The power figures are reported illustrative scenario totals, not newly executed results from this package. They use different operating selections from the charging examples below. Switching off a guest does not remove its installed mass. In the model, `installed: false` represents physical absence; it must not be used merely to hide a switched-off guest's mass. A feasible electrical total does not resolve mass, placement, cooling, timing or operational conflicts.

## Assumptions and varying results

The G1–G5 baseline `assumptions.json` separates **25 assumption/scenario records**, **8 source-rule records**, and **7 unresolved-input groups**. It is an evidence register; numerical execution inputs live in `resource_profiles.json`, `ship_specs.json`, and the runtime state. Each record says what is used, why, its effect, its source location and how to replace or verify it. Several records describe a scenario or model scope rather than an invented physical number.

Read `data/ASSUMPTIONS_AND_JUSTIFICATIONS.md` for the full list. `data/PHYSICAL_ACCOUNT_WORKING.csv` is the working register. `data/ASSUMPTIONS_REVIEW.md` summarizes the changes and remaining gaps.

The baseline `data/ASSUMPTIONS_SENSITIVITY.json` contains 12 actual deterministic model runs, varying generators, temperature, cooling fault, G5 mode, link capacity and G4 bitrate. They are explicit test scenarios, not uncertainty distributions.

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

G6/G7 documentation above extends the assumption set only. Their executable integration, safety-policy enforcement and validation results must be supplied before describing this package as a tested G1–G7 implementation.
