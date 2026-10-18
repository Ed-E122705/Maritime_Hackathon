# VesselOS integration — test and risk report

## What this package does

- Adds the other team's `governor/` D1–D6 code, Scenario A/A′/B YAML, Flask dashboard and priority configs, without overwriting any authoritative `data/` or `physical_model/` files.
- `governor.loader.load_raw()` now reads the **single canonical** `data/guests/G*.json` directory and `data/guest_schema.json`. Original duplicate guest files from the decision-team ZIP are intentionally excluded.
- `governor.integration.sync_ship_config()` takes overlapping host electrical/cooling/space/mass/communications/compute/timing limits from `physical_model/data/ship_specs.json`, overriding stale `config/ship.yaml` values. Optimizer-only YAML fields remain explicitly model policy assumptions.
- `governor.integration.sync_guest_profiles()` uses physical resource-profiles for conservative peak operating compute estimates and the selected deployed G3 survey-power assumption.
- D1's successful optimizer result includes a `physical_crosscheck` evaluated by the independent physical-model pipeline, visible in dashboard admission details. Unsupported off/standby mappings become UNKNOWN, not zero.
- G6 source data are read from **the user's current GitHub `data/guests/`**, not copied from an old ZIP. The custom G6 is protected from shedding; missing installation crew/time/permission yields NOT-NOW for new admission.
- `governor/account.py` D6 now explicitly points to the canonical physical-account register. D3/D4/D5 keep the original team's event-timeline simulator and priority/crew rules.

## Local tests completed

| Test | Result |
|---|---|
| Physical model regressions on provided updated ZIP (G1–G5 source snapshot) | **85 / 85 passed** |
| New bridge unit tests | **7 passed, 1 skipped** (live G6 only in newer GitHub) |
| Scenario B rescue / survey on synchronized inputs | **Ran**, different priority decisions as expected |
| Scenario B crew 14 vs 0 | **Ran**, human/automatic confirmation differs |
| Independent physical snapshot G1 example | **PASS, assessment UNKNOWN, admission NOT_EVALUATED** (correctly qualified) |
| Hypothetical altered ship reserve | **UNKNOWN** physical cross-check (not falsely accepted) |
| Dashboard JavaScript static syntax (`node --check`) | **Passed** |
| Python package syntax (`compileall`) | **Passed** |

## Not yet verified (blockers to release)

1. **OR-Tools CP-SAT/full D1/D2 tests:** OR-Tools could not be installed in this execution container because it lacks external package-index access. The other team's prior 34 solver tests therefore are **NOT verified after integration**. Run `python -m pytest -q tests` on an internet-connected ARM64 Qualcomm (or matching development machine).
2. **Flask live dashboard:** Flask is likewise absent here; the JS source passes syntax checking but API/UI operation is **NOT runtime-tested**. Launch with `python dashboard/app.py --port 5050` on the board, verify admission, timeline and priority switches.
3. **Live GitHub G6:** The model ZIP provided earlier predates G6; the current GitHub repository has it. The merged loader is designed for all six, but it must be validated on the live current checkout (`make smoke`).
4. **Assumption shifts change golden solver outputs:** slow-band reserve 250→200 kW, G3 deployment 2→1 kW and pooled compute profiles synchronize to the physical model. The inherited decision-team `tests/test_contract.py` assertions may need justified updates, **not blind expected-value changes**.
5. **Remaining mathematical mismatches:** D1 works with pooled compute, fixed installation/wiring/roof-assumption policies and CP-SAT duration windows. Physical model checks per-node compute and selected snapshots. The checker does NOT certify all reachable D1 envelope states or full D3 timeline. Jury overrides to ship capacities are not applied to the physical base specs and therefore return an UNKNOWN warning.
6. **Hardware timing and protection:** Verify D1 ≤30s, D3 ≤2s, D4 first action ≤5s and full sequence ≤60s on Qualcomm. Simulator logging is not real actuation. Validate watchdog/emergency actuation independently if used.

## Source divergence from old decision code

- Decision team's YAML originally uses 250 kW slow-speed reserve / 120 kW degraded; the authoritative current physical JSON uses **200 / 100** for both slow and cruise.
- Decision team's YAML originally pools 10,000 Mbps backbone; current ship specs configure **20,000 Mbps** (aggregation remains an unverified assumption in the physical account).
- Physical compute is tracked per node, with node4's guest accelerator disabled. The decision solver still uses a pooled approximation and the physical cross-check warns about it.
- Guest power is read from source cards; per-guest illustrative compute demands are read from the resource-model profile. G3 source-declared deployed electrical draw is not fixed, so the current illustrative profile chooses **1 kW**.

**Integration code is a reviewable candidate, not an accepted ship-control safety system. No GitHub changes were made while preparing this package.**


## Partner's independent D1 verifier included in this revision

`verification/d1_reference/` preserves the partner's isolated three-resource
CP-SAT/brute-force verification suite, explanations, and small input fixtures.
The reference suite has **not yet been run in this container** because OR-Tools
is unavailable here. Syntax and directory isolation are checked separately.
It is **not** evidence that the main integrated D1/D2 optimizer passes, nor
that its decisions are correct under all physical constraints.


## Re-run after adding the reference D1 source (this revision)

From a local checkout combining the original physical model and the updated overlay:

- `python -m unittest discover -s physical_model/tests -q`: **85 passed**.
- `python -m unittest discover -s integration_tests -v`: **7 passed, 1 skipped** (G6 fixture unavailable in this local checkout).
- `python -m governor.cli b --priority rescue`: **not run**; imported solver raises `ModuleNotFoundError: No module named 'ortools'` in this execution container.
- Partner `verification/d1_reference/tests`: **not run** for the same missing dependency; Python source compile checks passed.

The reference tests prove a three-resource *reference* implementation, not equivalence to the production integrated governor. The Qualcomm board should run both test suites after installing the requirements. All source files from the prior overlay except these integration Markdown documents remain unchanged.
