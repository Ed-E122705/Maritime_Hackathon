# Resource governor — Scenario A admission (D1)

Software Defined Vessel hackathon. This slice implements **D1 admission** for Scenario A (The Landlord):
three guests installed, the jury presents a fourth card and may change one number. Resource classes
modelled so far: electrical power, mass, stability. Cooling and positions come next and plug into the
same solver through the resource registry.

## Run

```bash
make install        # python3 -m venv .venv && pip install -r requirements.txt -e .
make demo           # both candidates × both priority files, text + JSON
make test           # 31 pytest checks incl. the 9 acceptance tests
# the jury changes one number (card files are never modified):
.venv/bin/python -m governor.cli --candidate G4 --priority sar_primary --set guests.G4.power_kw=60
.venv/bin/python -m governor.cli --candidate G3 --set guests.G3.parts.0.mass_t=11 --format json
```

## Decision engine (what it optimises)

* **Variables**: for each installed guest FULL / LOW (only if the card declares `low_power_kw`) / REMOVE. The candidate is forced FULL.
* **Constraints**: Σ power ≤ reserve (one genset down), Σ mass ≤ margin, Σ mass × position multiplier ≤ stability budget. One assumption literal per constraint.
* **Objective, lexicographic**: maximise **CI** (mission-weighted capability kept, % of everyone-at-FULL; LOW keeps 30 %), then with CI fixed maximise **MI** (free share of the tightest resource).
* **Verdict**: YES (all at FULL fits) · YES-IF (fits after throttling/removal; ranked displacement list and capability lost) · NO (candidate alone does not fit).
* **Binding constraint**: from the solver's infeasibility core, shrunk by a deletion filter to a minimal core. When several resources would each alone refuse the card, the one furthest over its budget is named and the rest are reported as "also over budget".
* **Cross-check**: brute-force enumeration of all plans must agree with CP-SAT (test 7). Deterministic: one worker, fixed seed.

## Layout

```
config/platform.yaml          Annex A numbers (reserve, margin, multipliers)
config/governor.yaml          active resources, levels, LOW retention, solver params
config/priorities/*.yaml      swappable mission-priority files
cards/G1..G5.yaml             Annex B guest cards (one per file)
scenarios/a.yaml              installed set, candidates, scenario overrides
src/governor/model.py         YAML → overrides (in memory) → dataclasses
src/governor/resources.py     resource registry: capacity(platform), demand(guest, mode)
src/governor/admission.py     CP-SAT model, two-stage solve, minimal core, brute-force check
src/governor/explain.py       rationale sentences + JSON from the live numbers
src/governor/cli.py           python -m governor.cli
tests/test_admission.py       acceptance tests
PHYSICAL_ACCOUNT.md           every assumed value, with file:line
prototype/                    original reference prototype (kept for comparison)
```

## Adding a resource class

1. Add a `Resource(name, unit, capacity_fn, demand_fn)` to `REGISTRY` in `src/governor/resources.py`.
2. Add its capacity to `config/platform.yaml` and its per-guest demand to the cards.
3. List the name in `resources:` in `config/governor.yaml`. The solver, the explanations and the JSON pick it up with no further code.
