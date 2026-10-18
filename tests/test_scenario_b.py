"""Scenario B contract: D3 right of way + D4 degradation. Expected values follow from the PDF and the cards;
hand arithmetic in comments."""
import json

import pytest

from governor import loader
from governor.rightofway import load_ops, right_of_way

SCN = loader.ROOT / "scenarios/B_right_of_way.yaml"


@pytest.fixture(scope="module")
def raw():
    return loader.load_raw()


def run(raw, pr, crew=None, raw_ov=(), scn_ov=()):
    scn = loader.apply_overrides(loader.load_scenario(SCN), list(scn_ov))
    return right_of_way(loader.apply_overrides(raw, list(raw_ov)), scn, pr, crew=crew)


def test_conflict_is_expressed_as_ship_state_conditions(raw):
    d = run(raw, "survey")
    fields = {c.split(":")[0] for c in d["conflicts"]}
    assert {"speed_knots", "noise_level", "course_keeping"} <= fields      # 3 kn quiet steady vs 5–12 kn manoeuvring


def test_hard_deadline_first_wait_is_rejected_under_both_priorities(raw):
    for pr in ("survey", "rescue"):
        d = run(raw, pr)
        wait = next(o for o in d["options"] if o["option"] == "wait_for_leg_end")
        assert not wait["feasible"]                                        # leg ends min 40 > deadline min 20
        assert d["deadline"] == 20                                         # report at min 8 + 12 min
        assert d["sim"].lost["G4_landed"] <= d["deadline"]


def test_two_priority_files_give_different_coherent_outcomes(raw):
    s, r = run(raw, "survey"), run(raw, "rescue")
    assert s["decision"] == "recover_then_resume" and r["decision"] == "suspend_survey"
    assert s["sim"].lost["G3_legs_done"] == 1                               # survey keeps its re-run leg
    assert r["sim"].lost["G3_legs_done"] == 0                               # rescue abandons it
    assert r["options"][2]["cap_minutes"]["G4"] > s["options"][1]["cap_minutes"]["G4"] - 1e-9


def test_rescue_protects_drone_charge_and_throttles_g5_when_uuv_charge_starts(raw):
    d = run(raw, "rescue")
    d4 = [l for l in d["sim"].log if l["kind"] == "D4" and l["text"].startswith("[")]
    assert d4 and "throttle G5 full→low" in d4[0]["text"]                  # 45+6+35+25 = 111 > 100 → 74 kW
    assert not any(" G4 " in l["text"] for l in d4)                         # protected winner
    assert not any(" G3 " in l["text"] for l in d4)                         # non-interruptible charge


def test_d4_timing_ceilings(raw):
    ops = load_ops()["d4"]
    for pr in ("survey", "rescue"):
        d = run(raw, pr, scn_ov=["timeline.1.reserve_kw=50"])
        steps = [l for l in d["sim"].log if l["kind"] == "D4" and l["text"].startswith("[")]
        by_minute = {}
        for l in steps:
            by_minute.setdefault(l["t"], []).append(l)
        for seq in by_minute.values():
            assert ops["first_action_s"] <= 5                               # A.8 first shed ≤ 5 s
            assert ops["first_action_s"] + (len(seq) - 1) * ops["step_interval_s"] <= 60   # full sequence ≤ 60 s
            assert all(l["compute_ms"] < 5000 for l in seq)


def test_d3_within_2_seconds(raw):
    for pr in ("survey", "rescue"):
        assert run(raw, pr)["elapsed_s"] < 2


def test_crew_rule_auto_when_confirmation_would_break_deadline(raw):
    assert run(raw, "rescue", crew=14)["confirmation"].startswith("human confirms")
    assert run(raw, "rescue", crew=6)["confirmation"].startswith("automatic: waiting 3 min")   # 8+3+10 = 21 > 20
    assert run(raw, "rescue", crew=0)["confirmation"].startswith("automatic (no crew")


def test_no_feasible_option_states_drone_risk(raw):
    d = run(raw, "rescue", crew=6, scn_ov=["initial.deck=occupied"])        # 12 min to clear the deck with 6 crew
    assert "drone risk accepted" in d["rationale"]


def test_jury_override_tight_reserve_sheds_in_survey_case(raw):
    d = run(raw, "survey", scn_ov=["timeline.1.reserve_kw=60"])
    d4 = [l["text"] for l in d["sim"].log if l["kind"] == "D4" and l["text"].startswith("[")]
    assert d4 and "throttle G5" in d4[0]                                   # 88 kW at landing > 60 kW


def test_replay_is_deterministic(raw):
    a, b = run(raw, "rescue"), run(raw, "rescue")
    strip = lambda d: json.dumps([{k: v for k, v in l.items() if k != "compute_ms"} for l in d["sim"].log], default=str)
    assert strip(a) == strip(b) and a["sim"].rows == b["sim"].rows
