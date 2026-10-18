# Independent D1 reference / brute-force oracle (non-production)

**Do not use this as the live VesselOS decision engine.** The production D1–D6 code is in
`governor/` at the repository root. This reference program is preserved from the new
`marinetime_hacks.zip` because it adds an independent, exhaustive check of the CP-SAT
optimum on a deliberately small instance.

## New verification capabilities

- Exhaustive enumeration of possible FULL / LOW / REMOVE plans for small instances;
  compare the reference CP-SAT solution against its independently evaluated optimum.
- Minimal infeasible-resource-core explanations and live-number rationales.
- Lexicographic CI (retained mission capability) then MI (minimum resource headroom).
- Deterministic replay, in-memory overrides that never mutate the cards, and timing smoke tests.
- Original partner acceptance suite (`tests/test_admission.py`) remains isolated.

**Limits:** The reference fixture checks only **power, installed mass, and stability**.
Its `config/` and `cards/` are **frozen reference examples**, NOT authoritative
ship specifications or guest manifests. In particular, those examples must not
replace `physical_model/data/ship_specs.json`, `data/guests/`, or the production
`governor/` settings. A reference solver PASS does not certify physical safety,
D1–D6 compliance, or timing on Qualcomm. These tests independently test their
own reference solver, not the production CP-SAT optimizer.

## Run on the Qualcomm from the combined repository root

```
.venv/bin/python -m pytest -q verification/d1_reference/tests
PYTHONPATH=verification/d1_reference/src .venv/bin/python -m d1_reference.cli \
  --root verification/d1_reference --candidate G3 --priority survey_primary
```

Existing repository dependencies already include OR-Tools, PyYAML, and pytest.
The module was renamed from the partner's `governor` to `d1_reference` to prevent
imports from silently shadowing the actual integrated governor.

## How to use the ideas in production

For the final D1 validator, extract the **brute-force cross-check approach** for
tractable scenarios from `src/d1_reference/admission.py::enumerate_plans`,
then compare normalized candidate sets using the *authoritative* physical model.
Do not compare this simplified fixture's verdicts numerically against live
VesselOS verdicts without accounting for omitted constraints and different data.

Original source and fixture assumptions are preserved for provenance in
`ORIGINAL_REFERENCE_README.md` and `ORIGINAL_REFERENCE_PHYSICAL_ACCOUNT.md`.
