"""Scenario D 181-step replay and explicit launch-authorization tests."""
from copy import deepcopy

from governor.scenario_d import ScenarioD, config, replay


def test_scenario_d_expected_checkpoints():
    data = replay()
    rows = data["timeline"]
    assert len(rows) == 181
    expected = {
        0: ("Standby", 48.040),
        20: ("Standby", 48.065),
        21: ("Starting", 49.065),
        29: ("Awaiting approval", 49.065),
        32: ("Simulated launch", 49.065),
        37: ("In flight", 48.065),
        77: ("Mission complete", 48.040),
    }
    for t,(state,kw) in expected.items():
        assert rows[t]["second"] == t
        assert rows[t]["g4_state"] == state
        assert rows[t]["power"]["total_kw"] == kw
        assert rows[t]["safety_certified"] is False


def test_scenario_d_needs_two_samples_and_operator():
    engine = ScenarioD(scripted=False)
    assert engine.tick(perimeter_motion=True)["g4_state"] == "Standby"
    assert engine.tick(perimeter_motion=True)["g4_state"] == "Starting"
    for _ in range(8):
        last = engine.tick()
    assert last["g4_state"] == "Awaiting approval"
    for _ in range(4):
        last = engine.tick()
    assert last["g4_state"] == "Awaiting approval"
    assert last["operator_authorized"] is False
    assert engine.tick(approve=True)["g4_state"] == "Simulated launch"


def test_scenario_d_obstructed_flight_deck_blocks_launch():
    engine = ScenarioD(scripted=False)
    engine.tick(perimeter_motion=True)
    engine.tick(perimeter_motion=True)
    for _ in range(8):
        engine.tick()
    row = engine.tick(deck_obstructed=True,approve=True)
    assert row["g4_state"] == "Awaiting approval"
    assert not row["operator_authorized"]
    assert any("Launch held" in e for e in row["events"])


def test_scenario_d_power_check_holds_startup():
    settings = deepcopy(config())
    settings["ship"]["continuous_guest_capacity_kw"] = 48
    engine = ScenarioD(settings=settings,scripted=False)
    engine.tick(perimeter_motion=True)
    row = engine.tick(perimeter_motion=True)
    assert row["g4_state"] == "Standby"
    assert any("held" in x for x in row["events"])


def test_scenario_d_dashboard_api():
    from dashboard.app import app
    client=app.test_client()
    replay_result=client.get("/api/scenario/d")
    assert replay_result.status_code == 200
    assert len(replay_result.get_json()["timeline"]) == 181
    assert client.get("/scenario/D").status_code == 200
    assert client.post("/api/scenario/d/live/reset").status_code == 200
    r=client.post("/api/scenario/d/live/sample",json={"perimeter_motion":True})
    assert r.status_code == 200
    assert r.get_json()["g4_state"] == "Standby"
