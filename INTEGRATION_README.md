# VesselOS — decision + physical model integration (overlay)

This overlay contains the other team's **D1–D6 decision governor and Flask dashboard** with a single-source bridge into the current **VesselOS GitHub** `physical_model/` and `data/guests/`.

## Apply only after pulling the current GitHub main branch

The ZIP is structured so you can extract it **directly into the root of the current repository**. It adds `governor/`, `dashboard/`, `config/`, `integration_tests/`, the decision-team `tests/`, the separate `scenarios/*.yaml` files, `docs/`, `Makefile`, and `requirements.txt`. **It does not contain or replace** any files from `physical_model/`, `data/`, `scenarios/*.json`, or the existing root `README.md`.

For safety and collaboration, do this on a new branch, not directly on `main`. On your Mac, download the ZIP and run:

```bash
cd /path/to/Maritime_Hackathon
git pull --ff-only
git switch -c integrate-decision-governor
unzip -o /path/to/VesselOS_D1-D6_Integration_Overlay.zip -d .
git status --short
```

Review the diff with your teammates before committing or opening a PR.

```bash
# on the Qualcomm or your workstation
cd ~/Maritime_Hackathon
git pull --ff-only
# Copy extracted overlay contents into this checkout, preserving existing files
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s physical_model/tests -v
.venv/bin/python -m pytest -q tests
.venv/bin/python -m governor.cli admit --candidate G4 --priority rescue --alternatives 0
.venv/bin/python -m governor.cli b --priority rescue
.venv/bin/python dashboard/app.py --port 5050
```

Google publishes OR-Tools 9.15 wheels for **CPython 3.12 on Linux aarch64** (the Qualcomm board configuration we observed). Install normally with pip from an internet-connected Qualcomm board. Verify all imports and solver behavior on the board. **No performance or execution-time deadline is certified by these instructions.**

## Source of truth

- `data/guests/G*.json` and `data/guest_schema.json` — one canonical source for all guest cards, including G6 when present.
- `physical_model/data/ship_specs.json` — authoritative overlapping host capacities. `loader.load_raw()` automatically overlays these onto the decision team's YAML.
- `physical_model/data/resource_profiles.json` — source for illustrative guest compute allocations and G3 survey load.
- `config/ship.yaml` — optimizer-only envelope, wiring, crane/installation timing, transition policy; values overlapping with `ship_specs.json` are replaced at load time.
- `config/guest_overlays.yaml` — role-to-manifest mappings and declared demonstration behavior, never a second copy of the manifest.
- `config/ops.yaml` and `config/priorities/` — D3/D4/D5 operation policy and swappable mission priorities.

## Important caveats

- D1's CP-SAT solver uses **pooled compute and duration-window approximations**. Our physical model checks **per-node compute, cooling and resource fit** for a selected operating state. These are complementary but **not mathematically equivalent**.
- An optimizer's `YES` and a physical snapshot's `PASS` are not evidence of full mission-envelope approval. The dashboard visibly labels the independent check and reports unknown source/timing evidence.
- The snapshot currently does not enact the 90-minute D3/D4 timeline or arbitrate reachable transitions. The decision team's B simulator remains the timeline authority; its decision is not independently certified by the selected-state checker.
- The custom G6 manifest in current GitHub has **undefined installation authorization/crew/duration**. D1 returns **NOT-NOW** rather than silently treating those fields as zeros; fill reviewed values before attempting to admit G6. When already installed, G6 is conservatively modelled at its 8 kW suppression demand and is non-sheddable because safety-critical.
- Jury `--set` overrides to ship/guest power are in-memory hypothetical changes to the optimizer. The physical cross-check uses on-disk canonical resource specs and will not certify those overrides as shared truth. A full shared override plumbing layer remains future work.
- The original governor tests assume legacy 250 kW slow speed and other choices; some expected verdicts can legitimately change under the physical model's authoritative 200 kW slow-speed budget. Record the changed outputs before updating their assertions.

## Diagnostics

```bash
python3 - <<'PYCODE'
from governor.loader import load_raw
r=load_raw()
print('Guests:',sorted(r['card']))
print('Slow (normal/degraded):',r['ship']['power']['reserve_kw']['slow'],r['ship']['power']['degraded_reserve_kw']['slow'])
print('Backbone Mbps:',r['ship']['data']['backbone_mbps'])
print('Source harmonizations:')
for item in r['source_notes']:print('  -',item)
PYCODE
```

## Partner `marinetime_hacks.zip` — selective additions

This version also includes `verification/d1_reference/`, a deliberately isolated
**D1 reference test harness** extracted from the partner's new standalone Scenario A
implementation. Its source module is renamed to `d1_reference` to avoid
shadowing the main `governor` module. The included reference tests check
exhaustive brute-force versus CP-SAT optimality, deterministic replay, minimal
binding-resource explanations, in-memory overrides, and timing smoke tests.

**No original files from the prior overlay were replaced.** The reference's
platform/card YAML are only internal fixtures: they must never overwrite
`physical_model/data/ship_specs.json`, `data/guests/`, or `config/ship.yaml`.
Its three-resource results are **not** equivalent to full eight-resource
VesselOS admission. No new dashboard or D3–D6 functions were needed; those
were already present in the earlier integrated package.

To test on the Qualcomm after extracting the overlay into a fresh branch:

```bash
.venv/bin/python -m unittest discover -s physical_model/tests -v
.venv/bin/python -m unittest discover -s integration_tests -v
.venv/bin/python -m pytest -q tests
.venv/bin/python -m pytest -q verification/d1_reference/tests
```

Do not extract the `marinetime_hacks.zip` parent ZIP into the project; it
contains an old repo, duplicate manifests, Git metadata, and an embedded venv.

## Latest combined branch enhancements

- Added `dashboard` **G6 monitoring** button backed by the existing `physical_model.snapshot.load_snapshot` and canonical `scenarios/G6_monitoring.json`. This is a physical snapshot, not an automatic fire-detection or suppression controller.
- Retained the existing governor D1 G6 **NOT-NOW** safety interlock when installation permission/crew/duration are undefined. Do not replace it with the alternative demo-install assumption.
- Retained the existing proposal-level `governor.integration.crosscheck_admission` and its physical evidence warnings; did not overwrite it with the separate Section-2 bridge.
- Added `docs/SCENARIO_C_CREW_POLICY.md` and a dashboard endpoint contract test.
- Retained `verification/d1_reference/` as an isolated reference test suite; no `src/governor` or duplicate canonical guest copies added.
