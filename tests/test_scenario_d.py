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
        last = engine.tick(perimeter_motion=True)
    assert last["g4_state"] == "Awaiting approval"
    for _ in range(4):
        last = engine.tick(perimeter_motion=True)
    assert last["g4_state"] == "Awaiting approval"
    assert last["operator_authorized"] is False
    assert engine.tick(approve=True)["g4_state"] == "Simulated launch"


def test_scenario_d_obstructed_flight_deck_blocks_launch():
    engine = ScenarioD(scripted=False)
    engine.tick(perimeter_motion=True)
    engine.tick(perimeter_motion=True)
    for _ in range(8):
        engine.tick(perimeter_motion=True)
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


def test_live_five_valid_no_motion_samples_power_g4_off():
    engine = ScenarioD(scripted=False)
    engine.tick(perimeter_motion=True)
    engine.tick(perimeter_motion=True)
    for _ in range(8):
        engine.tick(perimeter_motion=True)
    assert engine.state == "Awaiting approval"
    for n in range(1, 5):
        row = engine.tick(perimeter_motion=False, observation_valid=True)
        assert row["g4_state"] == "Awaiting approval"
        assert row["no_motion_seconds"] == n
    row = engine.tick(perimeter_motion=False, observation_valid=True)
    assert row["g4_state"] == "Powering off"
    assert row["power"]["g4_kw"] == 0
    assert row["g7_status"] == "MONITORING"
    row = engine.tick(perimeter_motion=False, observation_valid=True)
    assert row["g4_state"] == "Off"
    assert row["power"]["g4_kw"] == 0
    engine.tick(perimeter_motion=True)
    row = engine.tick(perimeter_motion=True)
    assert row["g4_state"] == "Starting"
    assert row["power"]["g4_kw"] == 3


def test_live_no_motion_streak_resets_on_motion_or_camera_failure():
    engine = ScenarioD(scripted=False)
    engine.tick(perimeter_motion=True)
    engine.tick(perimeter_motion=True)
    row = engine.tick(perimeter_motion=False)
    assert row["no_motion_seconds"] == 1
    row = engine.tick(perimeter_motion=False, observation_valid=False)
    assert row["no_motion_seconds"] == 0
    assert row["g4_state"] == "Starting"
    row = engine.tick(perimeter_motion=False)
    assert row["no_motion_seconds"] == 1
    row = engine.tick(perimeter_motion=True)
    assert row["no_motion_seconds"] == 0


def test_live_no_motion_does_not_abort_authorized_takeoff():
    engine = ScenarioD(scripted=False)
    engine.tick(perimeter_motion=True)
    engine.tick(perimeter_motion=True)
    for _ in range(8):
        engine.tick(perimeter_motion=True)
    engine.tick(perimeter_motion=True, approve=True)
    assert engine.state == "Simulated launch"
    for _ in range(5):
        row = engine.tick(perimeter_motion=False)
    assert row["g4_state"] == "In flight"
    assert row["power"]["g4_kw"] == 2


def test_scenario_d_per_system_power_breakdown():
    """Keep the synthetic 46 kW baseline distinct from G4 and G7."""
    rows = replay()["timeline"]
    for second, expected in [
        (0, (46.0, 2.0, 0.04, 48.04)),
        (21, (46.0, 3.0, 0.065, 49.065)),
    ]:
        p = rows[second]["power"]
        assert (p["background_kw"], p["g4_kw"], p["g7_kw"], p["total_kw"]) == expected
        assert round(p["background_kw"] + p["g4_kw"] + p["g7_kw"], 3) == p["total_kw"]

    engine = ScenarioD(scripted=False)
    engine.tick(perimeter_motion=True)
    engine.tick(perimeter_motion=True)
    for _ in range(5):
        off_row = engine.tick(perimeter_motion=False, observation_valid=True)
    assert off_row["g4_state"] == "Powering off"
    p = off_row["power"]
    assert (p["background_kw"], p["g4_kw"], p["g7_kw"], p["total_kw"]) == (
        46.0, 0.0, 0.04, 46.04
    )


def test_g7_optional_checkbox_a_ap_b_and_live_gate():
    """Regression: original v3 page plus opt-in G7 across A/A′ and B."""
    from dashboard.app import app
    client = app.test_client()
    page = client.get("/").get_data(as_text=True)
    assert 'data-tab="A"' in page
    assert 'data-tab="AP"' in page
    assert 'data-tab="B"' in page
    assert 'id="gauges"' in page
    assert 'id="opGauges"' in page
    assert 'id="g7Integrated"' in page
    assert 'g === "G7"' in page  # G7 is selectable in B
    assert "g7SelectionChanged()" in page
    assert 'id="scenarioDCard"' not in page
    meta = client.get("/api/meta").get_json()
    assert "G7" in meta["guests"]
    for weights in meta["priorities"].values():
        assert "G7" in weights

    assert client.post("/api/g7-enabled", json={"enabled": "yes"}).status_code == 400
    assert client.post("/api/g7-enabled", json={"enabled": True}).get_json()["enabled"] is True
    assert client.get("/api/g7-enabled").get_json()["enabled"] is True
    assert client.post("/api/g7-enabled", json={"enabled": False}).get_json()["enabled"] is False
    assert client.get("/api/g7-enabled").get_json()["enabled"] is False


def test_g7_camera_alert_changes_only_g7_guest_resource_mode(monkeypatch):
    """Alert reservation: 0.040 → 0.065 kW without changing base cards."""
    from dashboard import app as dashboard_module
    from vision import g7_state
    before = dashboard_module.RAW["card"]["G7"]["resources"]["power_modes"][0]["power_kw"]["nominal"]
    monkeypatch.setattr(g7_state, "load_camera_status", lambda root: {
        "camera_online": True, "deck_activity": "MOVEMENT_DETECTED"
    })
    raw = dashboard_module._g7_camera_resource_raw(dashboard_module.RAW)
    card_mode = next(m for m in raw["card"]["G7"]["resources"]["power_modes"] if m["id"] == "active")
    assert card_mode["power_kw"]["nominal"] == 0.065
    assert dashboard_module.RAW["card"]["G7"]["resources"]["power_modes"][0]["power_kw"]["nominal"] == before
