"""G7 camera source and dashboard contract. Does not require an attached webcam."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone

from governor import loader
from vision.g7_state import load_camera_status


def test_g7_loads_into_governor():
    raw = loader.load_raw()
    guests = loader.load_guest_data(raw)
    assert "G7" in guests
    g7 = guests["G7"]
    assert not g7.safety_critical
    assert abs(g7.modes["full"]["kw"] - .1) < 1e-8
    assert g7.configs[0].id == "mast_camera"
    assert all("G7" in p["weights"] for p in raw["priority"].values())


def test_g7_dashboard_status_when_not_started(tmp_path):
    data = load_camera_status(tmp_path)
    assert data["deck_activity"] == "UNKNOWN"
    assert data["camera_online"] is False
    assert data["safety_certified"] is False


def test_g7_stale_data_cannot_clear_deck(tmp_path):
    base = tmp_path / "vision"
    base.mkdir()
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    (base / "g7_status.json").write_text(json.dumps({
        "camera_online": True, "deck_activity": "NO_MOVEMENT_DETECTED",
        "timestamp_utc": stamp, "safety_certified": True,
    }), encoding="utf-8")
    data = load_camera_status(tmp_path)
    assert data["deck_activity"] == "UNKNOWN"
    assert data["camera_online"] is False
    assert data["safety_certified"] is False


def test_g7_status_endpoint():
    from dashboard.app import app
    client = app.test_client()
    response = client.get("/api/g7-camera")
    assert response.status_code == 200
    data = response.get_json()
    assert data["guest_id"] == "G7"
    assert data["safety_certified"] is False
    assert response.headers["Cache-Control"] == "no-store"


def test_g7_appears_in_dashboard_meta():
    from dashboard.app import app
    response = app.test_client().get("/api/meta")
    assert response.status_code == 200
    j = response.get_json()
    assert "G7" in j["guests"]
    assert all("G7" in weights for weights in j["priorities"].values())
