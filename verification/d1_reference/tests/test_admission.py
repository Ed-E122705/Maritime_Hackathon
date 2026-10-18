"""Acceptance tests for Scenario A admission (D1)."""
import hashlib
import json
import time
from pathlib import Path

import pytest

from d1_reference.admission import Mode, decide, enumerate_plans
from d1_reference.explain import to_dict, to_json
from d1_reference.model import load_bundle
from d1_reference.resources import active_resources

ROOT = Path(__file__).resolve().parents[1]


def run(candidate, priority, *overrides):
    bundle = load_bundle(ROOT, overrides=list(overrides))
    return bundle, decide(bundle, candidate, priority)


def plan_of(d):
    return {g: m.value for g, m in d.plan.plan.items()}


# 1
def test_g3_survey_primary_yes_if_mass_remove_g5():
    _, d = run("G3", "survey_primary")
    assert d.verdict == "YES-IF"
    assert d.binding == ("mass",)
    assert plan_of(d) == {"G1": "FULL", "G2": "FULL", "G5": "REMOVE", "G3": "FULL"}
    assert [c.guest for c in d.changes] == ["G5"]
    # stability is also over budget at baseline and must be reported, but it is not the binding one
    assert "stability" in d.violated


# 2
def test_g3_sar_primary_yes_if_mass_remove_g2():
    _, d = run("G3", "sar_primary")
    assert d.verdict == "YES-IF"
    assert d.binding == ("mass",)
    assert plan_of(d) == {"G1": "FULL", "G2": "REMOVE", "G5": "FULL", "G3": "FULL"}


# 3
def test_g4_default_yes_power_tightest():
    for prio in ("survey_primary", "sar_primary"):
        _, d = run("G4", prio)
        assert d.verdict == "YES"
        assert d.binding == ()
        assert d.plan.tightest == "power"
        assert d.plan.mi == pytest.approx(12.5, abs=1e-6)
        assert d.plan.usage["power"].free_frac * 100 == pytest.approx(12.5, abs=1e-6)
        assert all(m is Mode.FULL for m in d.plan.plan.values())


# 4
def test_g4_power_60_sar_primary_yes_if_power_g5_low():
    _, d = run("G4", "sar_primary", "guests.G4.power_kw=60")
    assert d.verdict == "YES-IF"
    assert d.binding == ("power",)
    assert d.violated == ("power",)
    assert plan_of(d) == {"G1": "FULL", "G2": "FULL", "G5": "LOW", "G3": "FULL"} or \
           plan_of(d) == {"G1": "FULL", "G2": "FULL", "G5": "LOW", "G4": "FULL"}
    assert plan_of(d)["G5"] == "LOW"
    assert [(c.guest, c.to) for c in d.changes] == [("G5", Mode.LOW)]


# 5
def test_g4_power_110_no_power_only():
    _, d = run("G4", "sar_primary", "guests.G4.power_kw=110")
    assert d.verdict == "NO"
    assert d.binding == ("power",)
    assert d.plan is None
    assert d.violated == ("power",)


# 6
def test_g3_mass_11_no_mass_only():
    _, d = run("G3", "survey_primary", "guests.G3.parts.0.mass_t=11")
    assert d.verdict == "NO"
    assert d.binding == ("mass",)   # stability 11 t-eq <= 12 is fine, must not appear
    assert d.violated == ("mass",)


# 7
@pytest.mark.parametrize("candidate", ["G3", "G4"])
@pytest.mark.parametrize("priority", ["survey_primary", "sar_primary"])
@pytest.mark.parametrize("overrides", [(), ("guests.G4.power_kw=60",), ("guests.G3.parts.0.mass_t=4",),
                                       ("platform.power_reserve_kw=60",), ("guests.G2.low_power_kw=2",)])
def test_cpsat_optimum_equals_brute_force(candidate, priority, overrides):
    bundle, d = run(candidate, priority, *overrides)
    brute = enumerate_plans(bundle, candidate, priority, active_resources(bundle.resource_names))
    if d.verdict == "NO":
        assert brute == []
        return
    best = brute[0]
    assert d.plan.ci == pytest.approx(best.ci, abs=1e-6)
    assert d.plan.mi == pytest.approx(best.mi, abs=1e-6)
    assert d.plan.feasible


# 8
def test_determinism_same_input_identical_output():
    outs = []
    for _ in range(2):
        bundle = load_bundle(ROOT, overrides=["guests.G4.power_kw=60"])
        payload = [to_dict(bundle, decide(bundle, c, p)) for c in ("G3", "G4") for p in bundle.priority_names()]
        for item in payload:
            item["solver"].pop("wall_ms")   # timing is the only thing allowed to differ
        outs.append(json.dumps(payload, sort_keys=True))
    assert outs[0] == outs[1]


# 9
def test_overrides_do_not_touch_card_files():
    cards = sorted((ROOT / "cards").glob("*.yaml"))
    before = {c: hashlib.sha256(c.read_bytes()).hexdigest() for c in cards}
    mtimes = {c: c.stat().st_mtime_ns for c in cards}
    bundle, d = run("G4", "sar_primary", "guests.G4.power_kw=110", "guests.G3.parts.0.mass_t=11")
    assert bundle.guests["G4"].power_kw == 110
    assert d.verdict == "NO"
    after = {c: hashlib.sha256(c.read_bytes()).hexdigest() for c in cards}
    assert before == after
    assert mtimes == {c: c.stat().st_mtime_ns for c in cards}
    # a fresh load without overrides sees the original card value again
    assert load_bundle(ROOT).guests["G4"].power_kw == 35


# extras: explainability and timing
def test_rationale_carries_live_numbers_not_canned_strings():
    bundle, d = run("G3", "survey_primary")
    j = to_dict(bundle, d)
    assert "mass needs 12.07 t vs 10 t available" in j["headline"]
    assert j["binding_detail"] == ["mass needs 12.07 t vs 10 t available"]
    _, d2 = run("G4", "sar_primary", "guests.G4.power_kw=110")
    assert "power needs 110 kW vs 100 kW available" in to_dict(bundle, d2)["headline"]
    _, d3 = run("G4", "sar_primary", "guests.G4.power_kw=60")
    assert "power needs 112.5 kW vs 100 kW available" in to_dict(bundle, d3)["headline"]


def test_full_demo_under_two_seconds():
    t0 = time.perf_counter()
    bundle = load_bundle(ROOT)
    for c in bundle.scenario.candidates:
        for p in bundle.priority_names():
            to_json(bundle, decide(bundle, c, p))
    assert time.perf_counter() - t0 < 2.0


def test_json_is_serialisable_and_complete():
    bundle, d = run("G3", "sar_primary")
    j = json.loads(to_json(bundle, d))
    for key in ("verdict", "headline", "binding", "recommended", "alternatives", "baseline_all_full", "solver"):
        assert key in j
    assert j["recommended"]["summary"] == "remove G2"
    assert len(j["alternatives"]) == 5
