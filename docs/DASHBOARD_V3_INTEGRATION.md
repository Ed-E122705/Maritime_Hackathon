# Dashboard v3 integration (partner's maritime_hacks_v3)

This branch selectively incorporates the partner's updated Scenario A candidate-to-embark capacity-check dashboard and Scenario B activity lanes, without replacing the existing ship physical model, canonical G1–G6 manifests, admission safety guard, or independent selected-state cross-check.

## Source of truth

- `physical_model/data/ship_specs.json` remains the ship authority. `governor.loader.load_raw()` overlays these facts onto the legacy optimizer YAML.
- `data/guests/G*.json` remains the only canonical guest manifest directory.
- `config/priorities/*.yaml` now includes G6 weight **10**, matching the partner's v3 dashboard. This is an **invented mission-utility choice** for the custom guest, not a source-specified weight or a replacement for its separate safety-critical no-shed rule. Teams/jury can change this input.
- Existing `governor.admission.classify_admission` keeps its G6 *NOT-NOW* installation guard until port authorization, required crew, and duration are defined.
- `governor.integration.crosscheck_admission` stays enabled; no physical approval is inferred from an optimizer score.

## Interfaces

- `GET /api/meta`: includes six guest cards, configured priorities, and tooltip source/assumption metadata.
- `POST /api/check`: a **hypothetical capacity-only screen** for an installed set and ticked candidates. It may indicate that a combination fits a simulated resource envelope, but that does *not* authorize installation or demonstrate source-evidence/full-mission admission. It returns `admission_status=NOT-NOW` and `installation_warning` when a selected candidate (notably G6) has incomplete installation evidence.
- `GET /api/physical-g6`: remains available from the dashboard for a separately qualified physical snapshot.
- `POST /api/admit`: remains the actual D1 admission decision API and must be used before implementing any new guest. G6 returns NOT-NOW with incomplete installation evidence.
- `POST /api/b`: includes additional per-minute ship posture/crew-relevant fields for v3's activity lanes, without altering the decision policy.

## Tests on Qualcomm

```bash
cd ~/Maritime_Hackathon_integration
git pull --ff-only
.venv/bin/python -m unittest discover -s physical_model/tests -q
.venv/bin/python -m unittest discover -s integration_tests -q
.venv/bin/python -m pytest -q tests
.venv/bin/python -m pytest -q verification/d1_reference/tests
.venv/bin/python dashboard/app.py --port 5050
```

Open `http://127.0.0.1:5050` on the Qualcomm in Firefox, refresh with Ctrl+Shift+R. Scenario A should display six survey weights (G1=1, G2=5, G3=10, G4=1, G5=1, G6=10) and a candidate-to-embark panel. Changing the G4 checkbox should issue `POST /api/check` and update the capacity gauges. Scenario B should provide colored guest-activity lanes. The Flask development-server warning is expected for a hackathon demo.

A GET `/api/meta` HTTP 200 alone proves that metadata loaded, not that the decision runs. Check for successful `POST /api/check` HTTP 200 in the terminal; if not, inspect the dashboard's `status` error text and browser console before changing resource rules.

**Limits:** Full D1/D2 solver tests and Flask interaction were not run in the packaging environment because OR-Tools and Flask were not available. The new endpoint must be tested on the Qualcomm. Runtime timing results cannot be claimed from source-only checks.

## Scenario A: explicit D1/D2 proposal (review-branch extension)

With exactly one candidate selected, `POST /api/check` now includes a `d1` object
sourced from `classify_admission` (not inferred from capacity fitting). It includes
`verdict`, `sentence`, required `actions`, the proposed `placement` with power-line
wiring, governor `usage`, `value`, `elapsed_s`, operational restrictions, and an
independent physical evidence status when present. With multiple candidates,
`d1=null` and the UI explicitly says single-guest D1 admission is not evaluated.

Scenario A presents the requested full-load capacity screen separately from the
conditional D1 admission decision and D2 post-decision placement. The Stage 1
resource table always shows the original request (e.g. 10.09 t, above the 10 t
margin). In the G1+G2+G3 with G4 candidate survey example, a `YES-IF` proposal
removes G2; Stage 3 shows G1/G3/G4, their location/power lines, and the
post-proposal mass (6.59 t). G2 is explicitly marked displaced, rather than
being silently absent from the placement table. The gauges default to the D1
proposal if an admissible proposal exists, with buttons to compare the original
request against D1. The initial over-capacity result stays visible.

The proposal is not an executed ship action. G6's incomplete installation
prerequisites continue to yield D1 `NOT-NOW`. An independent physical-screen
`UNKNOWN`/`FAIL` is displayed as evidence, not converted into a full-mission
approval. The candidate screen does not certify transition timelines.
