"""Contract tests. Expected values come from the PDF annexes or from hand arithmetic shown in comments.
Never edit an expected value to make a test pass — fix the model or explain the change first."""
import hashlib
import itertools
import json
from pathlib import Path

import pytest

from governor import loader
from governor.admission import classify_admission, degraded_floor, evaluate
from governor.defaults import place_set

ROOT = loader.ROOT
A = {"G1": "mast", "G2": "bay2", "G5": "half_bay1_hangar_roof"}          # Annex B jury-use set
SURVEY_MAX = {"G1": "mast", "G2": "bay2", "G3": "bay1"}
RESCUE_MAX = {"G2": "bay2", "G4": "flight_deck_hangar", "G5": "half_bay1_hangar_roof"}   # best rescue set of G1–G5
FOUR = {"G1": "mast", "G2": "bay2", "G4": "flight_deck_hangar", "G5": "half_bay1_hangar_roof"}


@pytest.fixture(scope="module")
def raw():
    return loader.load_raw()


def admit(raw, installed, cand, pr, overrides=(), **state):
    r2 = loader.apply_overrides(raw, list(overrides))
    scn = {"installed": dict(installed), "candidate": cand}
    if state:
        scn["state"] = state
    return classify_admission(r2, scn, pr, n_alternatives=0)


# ---------------------------------------------------------------- manifests
def test_all_cards_validate_against_repo_schema(raw):
    for gid, card in raw["card"].items():
        assert loader.validate_manifest(card, raw["schema"]) == [], gid


# ---------------------------------------------------------------- Annex arithmetic
def test_annex_all_five_fit_200kw_at_cruise(raw):
    G = loader.load_guest_data(raw)
    five = ["G1", "G2", "G3", "G4", "G5"]
    base = sum(G[g].modes["full"]["kw"] for g in five)            # 1.5+6+2+10+45 = 64.5
    worst = base + sum(w["delta_kw"] for g in five for w in G[g].windows)   # +14 +23 +25 = 126.5
    assert worst == pytest.approx(126.5)
    assert worst <= 200


def test_annex_genset_down_g5_g4_g3_charging_is_105kw(raw):
    G = loader.load_guest_data(raw)
    assert G["G5"].modes["full"]["kw"] + G["G4"].windows[0]["total_kw"] + G["G3"].windows[0]["total_kw"] == 105


def test_annex_claim_any_four_exceed_mass_is_false_for_two_sets(raw):
    """Annex B 'jury use' says any four guests exceed the 10 t margin. Two four-sets do not."""
    G = loader.load_guest_data(raw)
    fit = [s for s in itertools.combinations(["G1", "G2", "G3", "G4", "G5"], 4)
           if sum(G[g].mass_kg for g in s) <= 10000]
    assert sorted(fit) == [("G1", "G2", "G4", "G5"), ("G1", "G3", "G4", "G5")]


def test_cooling_capacity_linear_12_to_30c(raw):
    assert loader.cooling_capacity_kw(raw["ship"], 12) == 160
    assert loader.cooling_capacity_kw(raw["ship"], 30) == 120
    assert loader.cooling_capacity_kw(raw["ship"], 21) == pytest.approx(140)


# ---------------------------------------------------------------- Scenario A verdicts
def test_A_G3_yes_if_remove_G5_binding_mass_and_deck(raw):
    r = admit(raw, A, "G3", "survey")
    assert r["verdict"] == "YES-IF"
    assert [a["guest"] for a in r["actions"]] == ["G5"]
    assert {"mass", "deck_space"} <= set(r["binding"])


def test_A_G4_yes_and_survey_defers_drone_charge_on_genset_trip(raw):
    r = admit(raw, A, "G4", "survey")
    assert r["verdict"] == "YES"
    assert "G4.charge deferred" in r["degraded"]["changes"]["genset_down"]


def test_A_G4_rescue_defers_winch_instead(raw):
    r = admit(raw, A, "G4", "rescue")
    assert r["verdict"] == "YES"
    assert "G2.winch deferred" in r["degraded"]["changes"]["genset_down"]


def test_jury_override_G4_charge_70kw_cooling_binds_throttle_G5(raw):
    r = admit(raw, A, "G4", "survey", ["card.G4.resources.power_modes.charging_initial.power_kw.nominal=70"])
    assert r["verdict"] == "YES-IF"
    assert r["binding"] == ["cooling_normal"]                     # 61 + 14 + 60 = 135 kW heat > 120 kW
    assert [(a["type"], a["guest"]) for a in r["actions"]] == [("throttle", "G5")]


def test_jury_override_impossible_card_is_NO_naming_cooling(raw):
    # G4 continuous draw 130 kW: even alone it exceeds the 120 kW loop at 30 °C
    r = admit(raw, A, "G4", "survey", ["card.G4.resources.power_modes.charging_followup.power_kw.nominal=130"])
    assert r["verdict"] == "NO"
    assert r["binding"] == ["cooling_normal"]


def test_priority_swap_changes_who_is_displaced(raw):
    s = admit(raw, SURVEY_MAX, "G4", "survey")
    r = admit(raw, SURVEY_MAX, "G4", "rescue")
    assert [a["guest"] for a in s["actions"]] == ["G2"]          # survey keeps G3 (weight 10)
    assert [a["guest"] for a in r["actions"]] == ["G3"]          # rescue keeps G2 (weight 5 vs 1)


def test_net_value_warning_when_admission_costs_more_than_it_brings(raw):
    r = admit(raw, SURVEY_MAX, "G5", "survey")
    assert r["value"]["before"] == 16 and r["value"]["after"] == 12
    assert "recommendation" in r


def test_safety_critical_flag_blocks_removal(raw):
    # no Annex card is safety-critical; flip the flag on G5 to prove the schema field is honoured
    r = admit(raw, A, "G3", "survey", ["card.G5.criticality.safety_critical=true"])
    assert "G5" not in [a["guest"] for a in r.get("actions", [])]
    assert r["verdict"] in ("NOT-NOW", "YES-IF")


def test_solver_agrees_with_independent_evaluator(raw):
    for inst in (A, SURVEY_MAX, RESCUE_MAX):
        for c in ("G1", "G2", "G3", "G4", "G5"):
            if c in inst:
                continue
            for pr in raw["priority"]:
                r = admit(raw, inst, c, pr)
                assert r.get("solver_crosscheck", []) == [], (inst, c, pr)
                assert r["elapsed_s"] < 30


# ---------------------------------------------------------------- A′ under way
def test_A_prime_port_only_card_is_not_now_with_next_port_verdict(raw):
    r = admit(raw, A, "G4", "survey", location="at_sea", crew=6)
    assert r["verdict"] == "NOT-NOW" and r["next_port_verdict"] == "YES"


def test_A_prime_crew_zero_offers_logical_reconfiguration(raw):
    r = admit(raw, A, "G4", "survey", location="at_sea", crew=0)
    assert r["verdict"] == "NOT-NOW" and "Logical reconfiguration" in r["sentence"]


def test_A_prime_drone_swap_window(raw):
    base = {"installed": FOUR, "candidate": "G4", "swap": "G4.drone"}
    closed = classify_admission(raw, {**base, "state": {"location": "at_sea", "crew": 6, "speed_kn": 12,
                                "course": "free", "deck": "occupied", "sea_state": 3, "wind_kn": 15}}, "rescue")
    opened = classify_admission(raw, {**base, "state": {"location": "at_sea", "crew": 6, "speed_kn": 6,
                                "course": "steady", "deck": "clear", "sea_state": 3, "wind_kn": 15}}, "rescue")
    assert closed["verdict"] == "NOT-NOW" and "12 min with 6 crew" in closed["sentence"]
    assert opened["verdict"] == "YES"


# ---------------------------------------------------------------- defaults & reproducibility
def test_survey_default_G1_G2_G3_all_full_and_G2_G3_G4_infeasible(raw):
    G = loader.load_guest_data(raw)
    plan, core, _ = place_set(raw, G, ("G1", "G2", "G3"), "survey")
    assert plan["objective"]["U_normal"] == 16
    plan, core, _ = place_set(raw, G, ("G2", "G3", "G4"), "survey")
    assert plan is None and core == ["mass"]                      # 3.5 + 5.5 + 1.04 = 10.04 t


def test_deterministic_replay(raw):
    a = admit(raw, A, "G3", "rescue")
    b = admit(raw, A, "G3", "rescue")
    for r in (a, b):
        r.pop("elapsed_s"); r.pop("within_30s", None)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_overrides_never_touch_files(raw):
    files = sorted((ROOT / "guests").glob("*.json")) + sorted((ROOT / "config").rglob("*.yaml"))
    before = {f: hashlib.md5(f.read_bytes()).hexdigest() for f in files}
    admit(raw, A, "G4", "survey", ["card.G4.resources.power_modes.charging_initial.power_kw.nominal=70",
                                   "ship.power.reserve_kw.cruise=150"])
    assert before == {f: hashlib.md5(f.read_bytes()).hexdigest() for f in files}


def test_crane_time_limit_gives_not_now_with_hours_needed(raw):
    # G3 needs G5 removed (8 h) + its own install (6 h) = 14 h; a 6 h port call is too short
    r = admit(raw, A, "G3", "survey", ["ship.installation.port_window_hours=6"])
    assert r["verdict"] == "NOT-NOW"
    assert "14 h" in r["sentence"]


def test_overlay_role_keys_are_strings_and_safety_guests_cannot_be_shed(raw):
    # YAML may read bare `off:` as boolean False: all role keys must be strings.
    for gid, ov in raw["overlay"].items():
        assert all(isinstance(k, str) for k in ov), gid
    G = loader.load_guest_data(raw)
    for gid, guest in G.items():
        if guest.safety_critical:
            # D4 may never shed or park safety-critical guests in standby.
            assert "off" not in guest.modes, gid
            assert "standby" not in guest.modes, gid
        else:
            assert "off" in guest.modes, gid


def test_lost_line_stress_sheds_instead_of_removing(raw):
    r = admit(raw, A, "G4", "survey", ["ship.power.degraded_lost_line=port"])
    assert r["verdict"] == "YES"
    assert any("→off" in c for c in r["degraded"]["changes"]["genset_down"])


def test_half_up_rounding_in_sentences(raw):
    r = admit(raw, A, "G3", "survey")
    assert "stability 12.17 t-eq" in r["sentence"]            # 12.165 rounds half-up
