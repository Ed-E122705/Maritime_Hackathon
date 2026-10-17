# Assumptions and justifications — updated G1–G5

Ship specifications from the uploaded ZIP plus the newly attached G1 (1).json through G5 (1).json. Canonical guest copies are byte-identical to those updates; ship_specs is unchanged.

The guest manifests supply facts; `resource_profiles.json` supplies explicit demonstration choices. Reducing unjustified inference matters more than reducing the number of JSON keys. No random noise or unsupported probability distribution is added.

**Interpretation:** `status` is a conditional physical/operational simulation; `assessment_status` also includes timing and missing source evidence. A simulation PASS is not a full admission decision.

This register has 25 assumption/scenario records, 8 source-rule records and 7 unresolved input groups.

## Corrected issues

- **FIX01** — G5 heat split contradicted its chilled-water load rule. Corrected adapter; removed antenna_heat_kw profiles.
- **FIX02** — 70% capability loss was used to invent 1.8 Mbps low-power bandwidth. Removed; reserve manifest upper bound for both modes and label actual low-power rate unresolved.
- **FIX03** — G1 buffering and source-derived guest latency requirements were asserted without support. Corrected register, README, code comment and data contract.
- **FIX04** — Several G1–G5 link requirements were duplicated as constants in adapter. Adapter now reads canonical numeric rates; profile only supplies missing choices.
- **FIX05** — Surveying compute profile for G3 was present but unused when power_mode=standby. Select explicit surveying compute profile; put survey power in editable profile.
- **FIX06** — assumption_ids_used omitted baseline geometry, latency, host reserve and zero-peak scope. Expanded conservative trace list and explicit source-evidence gaps. Baseline IDs may also appear for inactive subchecks; they are context, not proof of execution.
- **FIX07** — All source rules and demo inputs were labeled assumptions; unused shape profiles obscured active choices. Classified records separately; removed unreachable per-guest dimension entries.
- **LIMIT02** — A physical PASS can rely on synthetic geometry, compute and latency plus unverified timing. Canonical reports now include CONDITIONAL_SIMULATION, source_evidence_status UNKNOWN and full_admission_status NOT_EVALUATED.
- **FIX08** — Updated guest operation power references and corrected conflict IDs were not integrated. Replaced all five guest copies byte-for-byte with the newly attached files; validate and use their fixed/allowed power mappings.
- **FIX09** — Battery deadline was checked against a fresh 12-minute ETA budget every snapshot. Use source event limits and require elapsed time since threshold crossing; missing evidence stays UNKNOWN.
- **FIX10** — G5 roof placement incorrectly required G4 to be installed despite the source allowing an existing roof. Use the canonical roof-availability and drone-clearance conditions.
- **FIX11** — Installation action labels and durations were ignored; some operational source values were hard-coded. Match updated operation/target records and their crew/time demands. Read drone mass, battery deadline, charge duration and radar loss from source data. Expose remaining policy constants in profiles.
- **FIX12** — The requested ship_state.py, constraints.py and snapshot.py interfaces were absent. Added immutable state updates, constraint aggregation and deterministic traceable snapshots while preserving evaluate_canonical.
- **LIMIT01** — Snapshot checks do not schedule trajectories, thermal buffering, cranes, crew tasks, autonomy permissions, recovery alignment or the full mission envelope. Expose NOT_EVALUATED full admission and UNKNOWN source evidence; downstream decision/timeline engine must cover these.

## Assumptions and scenario choices

### PHY-01 — Guest electrical reserve by speed

Classification: `NARROWED_REFERENCE`

**Current choice:** Slow/cruise both use 200 kW with two gensets and 100 kW with one.

**Why:** These are the selected ship_specs reference budgets. Equal slow/cruise values are a flat demo mapping, not evidence of a speed curve or the lowest capacity throughout the mission.

**Effect on results:** All electrical margins move directly with this choice; shore-side resources do not validate at-sea admission.

**How to replace or verify it:** Supply a speed/load-dependent reserve table or evaluate explicit scenarios throughout the envelope.

**Suggested sensitivity inputs:** {"basis": "Sensitivity samples within Annex A.1 ranges already referenced by the project; not measurements.", "one_genset_kw": [90, 100, 120], "two_genset_kw": [150, 200, 250]}

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/electrical/reserve_kw_by_speed`

Implementation: `physical_model/resource_models/electrical.py:evaluate`

### PHY-02 — Mission-line assignment and outages

Classification: `SCENARIO_ASSIGNMENT`

**Current choice:** 150 kW per port/stbd line is configured; sample G1/G2/G3 port, G4/G5 stbd; both live initially.

**Why:** Branch capacities are in ship_specs. Guest cabling and post-trip line survival are choices in runtime, not guest-card requirements.

**Effect on results:** A lost or overloaded branch can fail while total power passes.

**How to replace or verify it:** Provide generator/branch connectivity; set explicit connections and available lines for each scenario.

**Suggested sensitivity inputs:** {"online_lines": [["port", "stbd"], ["port"], ["stbd"]]}

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/electrical/lines_kw`
- [physical_model/data/sample_runtime.json](../physical_model/data/sample_runtime.json) at `/guests`
- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/online_power_lines`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`, `physical_model/resource_models/electrical.py:evaluate`

### PHY-03 — Electrical peak concurrency and line ceiling

Classification: `MODEL_APPROXIMATION`

**Current choice:** Declared peaks coincide; no branch overload above 150 kW; duration cap 60 s. Current canonical adapter only evaluates sustained demand (MODE-07).

**Why:** Peak schedules and branch transient ratings are absent. Host peak extras are in ship_specs; current guest peaks are null.

**Effect on results:** Can overestimate overlapping declared peaks. It does not establish current G1–G5 peak feasibility.

**How to replace or verify it:** Supply guest peaks/durations and a schedule; do not turn unknown peak into a source zero.

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/electrical/peak_extra_kw`
- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/electrical/peak_max_duration_s`
- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/resources/power_modes`
- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/resources/power_modes`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/resources/power_modes`
- [data/guests/G1_passive_radio_sensor.json](../data/guests/G1_passive_radio_sensor.json) at `/resources/power_modes`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/resources/power_modes`

Implementation: `physical_model/resource_models/electrical.py:evaluate`

### PHY-04 — Thermal storage omitted from sustained check

Classification: `MODEL_APPROXIMATION`

**Current choice:** No temporary thermal buffer credit; explicit nonzero peak needs a transient model.

**Why:** Snapshot input has no thermal-buffer energy/reuse history.

**Effect on results:** Sustained headroom is conservative relative to a temporary buffer; no conclusion about admissible short excursions.

**How to replace or verify it:** Implement buffer energy and cooldown tracking before crediting transient headroom.

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/cooling`

Implementation: `physical_model/resource_models/cooling.py:evaluate`

### PHY-05 — Roof cooling path

Classification: `UNVERIFIED_HOST_PLACEHOLDER`

**Current choice:** Roof is set to air cooling with 2 kW limit. Bay/hangar loop and mast air paths are recorded separately as source/configured rules.

**Why:** G5 permits a roof location but provides no roof heat rating. The revised G5 mapping consumes all declared heat on the loop, so this placeholder is not exercised by default G5.

**Effect on results:** Any future roof-dissipated heat check is conditional on an unverified limit.

**How to replace or verify it:** Obtain a roof equipment thermal limit; do not copy mast limit without disclosure.

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/roof`

Implementation: `physical_model/resource_models/cooling.py:evaluate`

### PHY-06 — Hangar dimensions and assembly limit

Classification: `UNVERIFIED_HOST_PLACEHOLDER`

**Current choice:** Host 12×8×4 m / 1500 kg; demo G4 assembly 8×6×3 m; one occupancy unit.

**Why:** These numbers exist in ship_specs and profiles, but G4 declares masses, not equipment dimensions. Flight-deck dimensions are not hangar dimensions. A 150 kg drone limit is different from a 1500 kg assembly limit.

**Effect on results:** A geometry PASS is only for the assumed boxes, not verified physical fit.

**How to replace or verify it:** Obtain actual hangar interior/exterior envelopes and mounting allowance. Keep UNKNOWN in a source-only assessment.

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/hangar`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G4/dimensions_by_location/hangar`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/assembly/components`

Implementation: `physical_model/manifest_adapter.py:_placing`, `physical_model/resource_models/deck.py:evaluate`

### PHY-07 — Roof structure and antenna envelope

Classification: `UNVERIFIED_HOST_PLACEHOLDER`

**Current choice:** Host roof 2×2×2 m / 100 kg; antenna assumed 0.6×0.6×1 m; canonical area 0.3 m².

**Why:** The 0.36 m² example box is not the manifest footprint; its shape/height and host limit are not supplied. Neither may be described as proven conservative.

**Effect on results:** Box fit and positive clearance flags do not prove real roof strength or rotor clearance.

**How to replace or verify it:** Use confirmed dimensions, roof rating and clearance evidence; retain canonical area independently.

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/roof`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G5/dimensions_by_location/roof`
- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/assembly/components/1`

Implementation: `physical_model/manifest_adapter.py:_placing`, `physical_model/resource_models/deck.py:evaluate`, `physical_model/resource_models/operational.py:evaluate`

### PHY-08 — Bay units and assumed equipment boxes

Classification: `MODEL_APPROXIMATION`

**Current choice:** Bay1 has two units; whole-Bay1 G3 box 6.1×2.4×2.6 m, half-Bay1 G2/G5 box 3.05×2.4×2.6 m; Bay2 boxes 3×2.4×2.6 m.

**Why:** Manifest bay fractions determine occupancy; they do not specify exact guest dimensions. Axis-aligned length packing is a simple screen with no service/installation clearances.

**Effect on results:** Declared slots may fit while true geometry is unknown. Assumed boxes exactly fill bay envelopes and leave no proven service clearance.

**How to replace or verify it:** Measure module envelopes; separate occupancy checks from geometry evidence.

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/bay1`
- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/bay2`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G2/dimensions_by_location`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G3/dimensions_by_location`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G5/dimensions_by_location`

Implementation: `physical_model/manifest_adapter.py:_placing`, `physical_model/resource_models/deck.py:evaluate`

### SYS-01 — Guest compute demand profiles

Classification: `SYNTHETIC_DEMO_INPUT`

**Current choice:** Mode-specific cores/RAM/accelerators/storage are in resource_profiles; all five source compute declarations are null.

**Why:** These are arbitrary executable test loads, not benchmarks or justified vendor estimates. They are retained to keep the demonstration runnable and labeled as assumptions.

**Effect on results:** Compute PASS is conditional on substituted demands. Deployed G3 now uses the intended surveying compute profile.

**How to replace or verify it:** Benchmark each mode or supply actual guest requirements; unknown values must not be presented as zero.

**Suggested sensitivity inputs:** {"basis": "Optional analyst stress multipliers, not a physical uncertainty range.", "demonstration_load_scale": [0.5, 1, 2]}

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G5/compute_by_mode`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G2/compute_by_mode`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G3/compute_by_mode`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G1/compute_by_mode`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G4/compute_by_mode`
- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/resources/compute`
- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/resources/compute`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/resources/compute`
- [data/guests/G1_passive_radio_sensor.json](../data/guests/G1_passive_radio_sensor.json) at `/resources/compute`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/resources/compute`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`, `physical_model/resource_models/compute.py:evaluate`

### SYS-02 — Compute reservation implementation

Classification: `MODEL_APPROXIMATION`

**Current choice:** 80% guest CPU/RAM per node; 80% shared storage; node4 accelerator reserved; integer guest total also limited on surviving hardware.

**Why:** The reserve fraction is configured. Applying it to each node and storage and reserving an entire accelerator are implementation choices that may strand otherwise usable resources.

**Effect on results:** At four online nodes: 102.4 cores, 409.6 GB RAM, 16 TB, at most three whole guest accelerators; node4 allows none.

**How to replace or verify it:** Confirm reservation granularity and actual accelerator partitioning.

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/compute`

Implementation: `physical_model/resource_models/compute.py:evaluate`

### SYS-03 — Guest compute-node placement

Classification: `SCENARIO_ASSIGNMENT`

**Current choice:** G1→node1; G2/G3→node2; G4→node3; G5→node4.

**Why:** Reproducible fixture choices; no guest requires these physical nodes in its manifest.

**Effect on results:** Node overload may occur even with total rack headroom; reassignment can change feasibility.

**How to replace or verify it:** Have the placement engine evaluate alternative eligible nodes.

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G5/compute_node`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G2/compute_node`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G3/compute_node`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G1/compute_node`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G4/compute_node`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`

### COM-01 — Backbone aggregation and link upper bounds

Classification: `NARROWED_REFERENCE`

**Current choice:** Configured maxima: 20,000 Mbps backbone; 8 SATCOM; 20 LOS; 0.005 acoustic.

**Why:** SATCOM/LOS/acoustic use chosen upper bounds; 20,000 Mbps assumes both 10 Gbps backbone links can be pooled. Redundancy alone does not establish aggregation.

**Effect on results:** Overstates availability if links are redundant or degraded; live capacities are independent inputs.

**How to replace or verify it:** Confirm topology. Use explicit runtime effective capacities.

**Suggested sensitivity inputs:** {"acoustic_mbps": [0.001, 0.003, 0.005], "backbone_mbps": [10000, 20000], "basis": "Reference-range/topology scenarios, not measurements.", "los_mbps": [1, 5, 20], "satcom_mbps": [2, 4, 8]}

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/datalinks`
- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/links`

Implementation: `physical_model/resource_models/datalinks.py:evaluate`

### COM-02 — G1/G2 unspecified shore transport

Classification: `SCENARIO_ASSIGNMENT`

**Current choice:** Default profile routes G1 0.2 and G2 0.5 Mbps to SATCOM; profile can select LOS. Silence suppresses these transmissions.

**Why:** Manifests leave shore transport unspecified. G1 supports passive sensing in silence but does not establish buffering. G2 buffering is stated but capacity/duration are unknown.

**Effect on results:** Selected shared link can saturate; zero transmission in silence does not prove data retention or delivery.

**How to replace or verify it:** Select real transport and define loss/buffering policy explicitly.

**Suggested sensitivity inputs:** {"shore_transport": ["satcom", "los"]}

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G1/shore_transport`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G2/shore_transport`
- [data/guests/G1_passive_radio_sensor.json](../data/guests/G1_passive_radio_sensor.json) at `/resources/data_links/1`
- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/resources/data_links/1`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`

### COM-03 — G3 acoustic guest demand

Classification: `SYNTHETIC_DEMO_INPUT`

**Current choice:** 0.003 Mbps during surveying.

**Why:** The manifest provides no acoustic demand. A middle-of-host-range throughput is an arbitrary test load; host capability is not a guest requirement.

**Effect on results:** Acoustic bandwidth feasibility is conditional; host state may be lower or disconnected.

**How to replace or verify it:** Measure/control the guest messaging load; source-supported demand remains UNKNOWN.

**Suggested sensitivity inputs:** {"basis": "Illustrative workload samples, not known demand bounds.", "demo_demand_mbps": [0.001, 0.003, 0.005]}

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/acoustic_guest_demand_mbps`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/resources/data_links/1`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`

### COM-04 — G4 selected video bitrate

Classification: `NARROWED_REFERENCE`

**Current choice:** 10 Mbps selected within source range 5–20 Mbps.

**Why:** Nominal is null; 10 is a chosen test point and is not the midpoint (12.5).

**Effect on results:** Actual selected video mode may pass or fail at the available LOS capacity.

**How to replace or verify it:** Select a supported encoder bitrate or reserve the declared maximum for admission.

**Suggested sensitivity inputs:** {"demand_mbps": [5, 10, 20]}

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/g4_los_nominal_mbps`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/resources/data_links/0`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`

### COM-05 — G5 SATCOM reservation by power mode

Classification: `CONSERVATIVE_BOUND`

**Current choice:** Reserve the manifest maximum (currently 6 Mbps) in both full and low-power modes. Former 1.8 Mbps value removed.

**Why:** The 0.3 capability fraction does not quantify bandwidth. Using the declared upper bound avoids inventing a linear scaling benefit.

**Effect on results:** No guaranteed SATCOM relief is claimed from power throttling; low-power actual demand stays unknown.

**How to replace or verify it:** Supply a measured mode-specific bandwidth profile to replace the bound.

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G5/satcom_demand_policy`
- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/resources/data_links`
- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/resources/power_modes/1/capability_fraction`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`

### COM-06 — Guest latency tolerances

Classification: `SYNTHETIC_DEMO_INPUT`

**Current choice:** Tolerance inputs: backbone 1 ms, SATCOM 800 ms, LOS 20 ms, acoustic 60000 ms; example LOS observed latency is separately 10 ms.

**Why:** Ship-link latency describes transport performance, not the guest maximum acceptable delay. All source processing deadlines are also null and distinct from transport tolerance.

**Effect on results:** Latency PASS only compares simulated observations against assumed tolerances; it cannot establish application deadlines.

**How to replace or verify it:** Declare guest message deadlines, jitter and data-freshness requirements; measure transport performance independently.

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/link_latency_ms`
- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/links`
- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/resources/response_time`
- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/resources/response_time`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/resources/response_time`
- [data/guests/G1_passive_radio_sensor.json](../data/guests/G1_passive_radio_sensor.json) at `/resources/response_time`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/resources/response_time`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`, `physical_model/resource_models/datalinks.py:evaluate`

### MODE-01 — G3 deployed survey electrical load

Classification: `SYNTHETIC_DEMO_INPUT`

**Current choice:** Explicit profile survey_power_kw=1.0, separate from canonical standby=1 kW and charging=25 kW.

**Why:** G3 explicitly says deployed ship-side power is unspecified. The profile value is a demo placeholder, not supported merely because standby has the same number.

**Effect on results:** Power and loop margins during surveying depend directly on this estimate. Charging plus surveying is rejected.

**How to replace or verify it:** Obtain deployed-load requirements or keep source-supported power UNKNOWN. No justified numerical survey-power range is available.

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/guest_resource_profiles/G3/survey_power_kw`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/resources/power_modes`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/operational_modes/0/notes`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`

### MODE-07 — Canonical peak scope restriction

Classification: `MODEL_SCOPE_RESTRICTION`

**Current choice:** For null source peaks the sustained simulation uses zero extra peak, while source evidence stays UNKNOWN. A supplied peak is read; any positive extra peak needs a separate peak_duration_s_by_mode profile entry.

**Why:** The previous register omitted this behavior. Zero is not a physical declaration of no startup/peak load.

**Effect on results:** A simulated electrical PASS cannot establish peak adequacy; report source evidence UNKNOWN.

**How to replace or verify it:** Provide real peak power and duration evidence. A sustained-mode duration is never reused as an electrical-peak duration.

Source references:

- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/resources/power_modes`
- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/resources/power_modes`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/resources/power_modes`
- [data/guests/G1_passive_radio_sensor.json](../data/guests/G1_passive_radio_sensor.json) at `/resources/power_modes`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/resources/power_modes`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`

### TIME-01 — Illustrative execution-time evidence

Classification: `SYNTHETIC_DEMO_INPUT`

**Current choice:** 3000/200/500/6000/20 ms estimates, verified=false; host deadlines remain 30000/2000/5000/60000/200 ms.

**Why:** No target-machine measurements or WCET arguments are included. The previous Qualcomm claim had no evidence in these files and is removed.

**Effect on results:** Physical simulation status excludes timing. UNKNOWN timing must still gate any final deadline-dependent decision.

**How to replace or verify it:** Collect independently supported timing evidence on the intended platform; do not merely flip verified to true.

Source references:

- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/timing`
- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/timing_ms`

Implementation: `physical_model/resource_models/timing.py:evaluate`, `physical_model/resource_models/__init__.py:evaluate_all`

### STATE-01 — Demonstration operating snapshot

Classification: `SCENARIO_ASSIGNMENT`

**Current choice:** Base snapshot: 24 C, sea state 3, wind 22 kn, speed 3 kn, steady/quiet, crew14; runtime overlays scenario fields.

**Why:** These are declared fictional inputs, not measured state or proof of the entire mission envelope. Original reference to Annex B for Scenario B was imprecise.

**Effect on results:** A single favorable snapshot can pass while degraded or hot cases fail.

**How to replace or verify it:** Evaluate each selected mission state and record what is varied; verify reachable combinations.

Source references:

- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/seawater_c`
- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/sea_state`
- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/wind_kn`
- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/speed_kn`
- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/crew`

Implementation: `physical_model/ship_state.py:ShipState`, `physical_model/snapshot.py:build_snapshot`

### STATE-02 — Simulated connectivity and positive readiness flags

Classification: `SCENARIO_ASSIGNMENT`

**Current choice:** Connected links and capacities/latencies are synthetic; sample runtime asserts roof availability, drone clearance and manoeuvre freedom.

**Why:** The program checks input assertions; it does not establish that these conditions are true or geometrically supported.

**Effect on results:** Default true readiness flags may permit operations that lack evidence.

**How to replace or verify it:** Use measured/simulated truth with timestamps and quality; missing clearance must not be replaced by an assumed true.

Source references:

- [physical_model/data/example_state.json](../physical_model/data/example_state.json) at `/links`
- [physical_model/data/sample_runtime.json](../physical_model/data/sample_runtime.json) at `/hangar_roof_available`
- [physical_model/data/sample_runtime.json](../physical_model/data/sample_runtime.json) at `/drone_clearance_verified`
- [physical_model/data/sample_runtime.json](../physical_model/data/sample_runtime.json) at `/manoeuvre_freedom`

Implementation: `physical_model/ship_state.py:ShipState`, `physical_model/snapshot.py:build_snapshot`

### MODE-05 — Crew timing ranges

Classification: `MODEL_APPROXIMATION`

**Current choice:** 14 crew: clear deck 3–5 min, confirm 15–60 s. 6: 8–12 min / 60–180 s. 0: no manual clearing/confirmation.

**Why:** These inherited planning ranges are not structured requirements in ship_specs or the supplied G1–G5 files. They are now editable in operational_policy rather than hidden constants.

**Effect on results:** Pre-cleared deck is necessary but not sufficient proof of autonomous recovery permission.

**How to replace or verify it:** Provide explicit automation policy and crew task scheduling; no automatic authority inferred.

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/operational_policy/deck_clearance_minutes`
- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/operational_policy/human_confirmation_seconds`

Implementation: `physical_model/resource_models/operational.py:evaluate`

### MODE-08 — Operations with null power mapping

Classification: `SCENARIO_ASSIGNMENT`

**Current choice:** G3 survey/launch and G4 flight/recovery have null power_mode_id. An explicit runtime power_mode is required. G3 deployed power additionally uses MODE-01 until a source mapping is supplied.

**Why:** Null means not specified. It cannot be auto-filled from an operation name or treated as zero load.

**Effect on results:** Selected nominal power permits conditional demonstration; it does not prove actual operation power or temporal feasibility.

**How to replace or verify it:** Supply measured operation power profiles and allowed combinations.

Source references:

- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/operational_modes`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/operational_modes`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`

### OP-01 — Inherited operational screening policy

Classification: `UNVERIFIED_HOST_PLACEHOLDER`

**Current choice:** {"at_sea_installation": {"max_sea_state": 3, "max_speed_kn": 8, "max_wind_kn": 20, "min_speed_kn": 4}, "crew_levels": [0, 6, 14], "deck_clearance_minutes": {"0": null, "14": [3, 5], "6": [8, 12]}, "drone_mass_limit_kg": 150, "g4_endurance_minutes": 90, "human_confirmation_seconds": {"0": null, "14": [15, 60], "6": [60, 180]}, "status": "Inherited demonstration screening constants; not supplied as structured host specifications. See OP-01."}

**Why:** 150 kg drone limit and at-sea weather limits were constants in the uploaded engine but are absent as structured ship_specs requirements. G4 endurance 90 min is in its free-text operation note. Values are retained visibly in profiles; this is not independent source verification.

**Effect on results:** Changes can alter eligibility of swaps, drone mass and endurance screening. Crew planning ranges are explained in MODE-05.

**How to replace or verify it:** Add supported structured operational limits to the authoritative host data and remove the corresponding profile constants.

Source references:

- [physical_model/data/resource_profiles.json](../physical_model/data/resource_profiles.json) at `/operational_policy`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/operational_modes/1/notes`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/installation`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/installation`

Implementation: `physical_model/resource_models/operational.py:evaluate`, `physical_model/resource_models/operational.py:_install_checks`


## Facts and rules retained from source inputs

### PHY-09 — G5 installed mass

Classification: `DERIVED_FROM_MANIFEST`

**Current choice:** {"antenna_kg": 25, "main_kg": 3000, "total_kg": 3025}

**Why:** Sum the components explicitly declared by the supplied G5 file once. This is not a new mass assumption relative to that file.

**Effect on results:** Correct mass and placement-dependent weighted moment accounting.

**How to replace or verify it:** If organizer interpretation of the 3 t figure changes, revise the authoritative manifest first. Do not silently subtract 25 kg.

Source references:

- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/assembly/components`

Implementation: `physical_model/manifest_adapter.py:_placing`, `physical_model/resource_models/mass.py:evaluate`

### PHY-10 — Added mass and weighted stability screen

Classification: `SOURCE_CONFIGURED_RULE`

**Current choice:** 10,000 kg added mass; 12,000 kg-equivalent; deck ×1, hangar/roof ×1.2, mast ×3.

**Why:** These quantities are explicit in ship_specs and the challenge model.

**Effect on results:** Produces a challenge budget check only; naval stability remains NOT_VERIFIED.

**How to replace or verify it:** No hydrostatic or stability certification can be inferred from these multipliers.

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/mass`
- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/bay1/stability_multiplier`
- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/bay2/stability_multiplier`
- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/hangar/stability_multiplier`
- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/roof/stability_multiplier`
- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/positions/mast3/stability_multiplier`

Implementation: `physical_model/resource_models/mass.py:evaluate`

### MODE-02 — G5 heat allocation correction

Classification: `DERIVED_FROM_MANIFEST`

**Current choice:** 45 kW full / 8 kW low power go entirely to the selected bay chilled-water path; former 1 kW antenna split removed.

**Why:** The supplied G5 cooling rule explicitly says chilled-water load equals electrical kW. An extra antenna split contradicted it.

**Effect on results:** Adds 1 kW to loop load relative to the uploaded implementation: 105 instead of 104 kW in the full-charge combination, 68 instead of 67 after G5 throttle.

**How to replace or verify it:** If actual antenna power is separately declared later, revise the manifest and balance explicitly; this does not establish zero physical antenna dissipation.

Source references:

- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/resources/cooling`
- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/resources/power_modes`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`, `physical_model/resource_models/cooling.py:evaluate`

### MODE-03 — Operating activity and electrical mode are distinct

Classification: `SOURCE_IMPLEMENTATION_RULE`

**Current choice:** Updated operation power_mode_id maps G1 active, G2 continuous/winch, G3 standby/charge, G4 standby/initial/followup. G5 permits full or low_power. Null mapping requires explicit runtime selection.

**Why:** Consume the explicit operation-to-power mappings in the updated guests. Reject contradictory selections. Read sustained load/duration directly from the selected power mode.

**Effect on results:** Correct load accounting; selecting standby during a launch activity does not establish actual launch electrical demand.

**How to replace or verify it:** Null mappings remain unresolved; a selected ship-side mode is only a conditional simulation.

Source references:

- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/operational_modes`
- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/operational_modes`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/operational_modes`
- [data/guests/G1_passive_radio_sensor.json](../data/guests/G1_passive_radio_sensor.json) at `/operational_modes`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/operational_modes`
- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/resources/power_modes`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/resources/power_modes`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/resources/power_modes`

Implementation: `physical_model/manifest_adapter.py:normalize_guests`, `physical_model/resource_models/operational.py:evaluate`

### MODE-04 — Drone recovery deadline

Classification: `SOURCE_RULE_WITH_LIMITED_IMPLEMENTATION`

**Current choice:** Read G4 battery threshold/deadline from the event. Evaluate minutes_since_low_battery + eta_to_landing_min <= recovery_deadline_minutes. Missing battery/origin/ETA is UNKNOWN when needed.

**Why:** Threshold/deadline is explicit in G4. Supplied ETA alone is not proof of a realizable recovery plan.

**Effect on results:** The deadline no longer restarts every snapshot. A supplied ETA does not establish a reachable recovery trajectory.

**How to replace or verify it:** Persist the threshold-crossing time in the state source and validate the planned recovery transitions.

Source references:

- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/special_events/0`

Implementation: `physical_model/resource_models/operational.py:evaluate`

### MODE-06 — Physical versus logical reconfiguration

Classification: `SOURCE_RULE_WITH_LIMITED_IMPLEMENTATION`

**Current choice:** Select one manifest installation record by operation and component/target; use its crew and duration. G3 swap_vehicle_only keeps the cradle; G4 swap_component targets the drone.

**Why:** The updated G3 operation_target removes the vehicle-versus-assembly ambiguity. Port-only and at-sea records are distinct.

**Effect on results:** Insufficient crew or time fails; missing installation time budget is UNKNOWN. Existing roof availability is taken from state, without an invented G4 admission dependency.

**How to replace or verify it:** Model cranes, fastening/service access and time-varying weather/crew reservations before full installation admission.

Source references:

- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/installation`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/installation`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/installation`
- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/installation`

Implementation: `physical_model/resource_models/operational.py:_install_checks`

### SRC-COOL — Configured cooling curve and routes

Classification: `SOURCE_CONFIGURED_RULE`

**Current choice:** 160 kW at12 C, linearly to120 at30 C; fault removes40%; electric-to-heat1:1; G1 air and G2–G5 loop per manifests.

**Why:** Configured source rule, not an additional estimate. Roof/hangar geometry remains separately qualified.

**Effect on results:** 30 C fault capacity is72 kW. G1 air load does not consume that loop.

**How to replace or verify it:** Preserve thermal path semantics; no extrapolation outside the provided curve.

Source references:

- [physical_model/data/ship_specs.json](../physical_model/data/ship_specs.json) at `/cooling`
- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/resources/cooling`
- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/resources/cooling`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/resources/cooling`
- [data/guests/G1_passive_radio_sensor.json](../data/guests/G1_passive_radio_sensor.json) at `/resources/cooling`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/resources/cooling`

Implementation: `physical_model/resource_models/cooling.py:evaluate`

### SRC-MAPPING — Placement completeness and power mapping integrity

Classification: `SOURCE_IMPLEMENTATION_RULE`

**Current choice:** Every assembly component appears exactly once in a chosen configuration; explicit fixed/allowed power references are validated.

**Why:** Avoid double-counting or omitting source mass and rejecting updated operation names.

**Effect on results:** Invalid component coverage or contradictory operation power fails input validation before simulation.

**How to replace or verify it:** Update the authoritative guest file when a component or valid operation changes.

Source references:

- [data/guests/G5_emergency_communications_and_edge_compute_node.json](../data/guests/G5_emergency_communications_and_edge_compute_node.json) at `/placement`
- [data/guests/G2_ocean_and_weather_module.json](../data/guests/G2_ocean_and_weather_module.json) at `/placement`
- [data/guests/G3_seabed_inspection_vehicle_and_cradle.json](../data/guests/G3_seabed_inspection_vehicle_and_cradle.json) at `/placement`
- [data/guests/G1_passive_radio_sensor.json](../data/guests/G1_passive_radio_sensor.json) at `/placement`
- [data/guests/G4_vtol_rescue_drone_and_hangar.json](../data/guests/G4_vtol_rescue_drone_and_hangar.json) at `/placement`

Implementation: `physical_model/manifest_adapter.py:validate_manifest_references`, `physical_model/manifest_adapter.py:_placing`

## Unresolved inputs

- **U01 — All guest compute requirements:** Benchmark or obtain declared demands; demo profiles are not evidence.
- **U02 — All guest electrical peak/minimum needs:** Preserve null; sustained check does not validate peaks.
- **U03 — Processing and per-link latency requirements:** Guest processing deadline and link tolerance require separate inputs.
- **U04 — G3 deployed power/acoustic demand:** Do not infer requirements from standby or host acoustic capacity.
- **U05 — Equipment dimensions and actual hangar/roof limits:** Replace unverified boxes/limits with supported data.
- **U06 — G1/G2 shore transport and buffering:** G1 buffering not established; G2 capacity/duration unknown.
- **U07 — G4 charging followup and low-G5 bandwidth:** No duration/rate scaling invented; explicit selected upper-bound policy only.

## Updating this register

assumptions.json is the reviewable evidence register; executable values live in resource_profiles.json and ship_specs.json. Guest files override demo fields where source values exist. Use ShipState and snapshot.build_snapshot for live dict inputs, or snapshot.load_snapshot for files. After deliberate source edits review this ledger, refresh affected source_refs/hashes, regenerate docs, then run scripts/audit_assumptions.py. Do not blindly refresh source hashes to conceal stale assumptions.

```bash
python3 scripts/render_assumption_docs.py
python3 scripts/audit_assumptions.py
python3 scripts/run_sensitivity.py
```

The sensitivity JSON contains actual model evaluations. Scenario values are explicit test inputs, not confidence intervals or measured variability.
