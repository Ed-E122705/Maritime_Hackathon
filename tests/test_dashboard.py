"""The dashboard is a view: it must return exactly what the engine returns."""
import pytest

flask = pytest.importorskip("flask")

from dashboard.app import app                     # noqa: E402
from governor import loader                       # noqa: E402
from governor.admission import classify_admission  # noqa: E402
from governor.rightofway import right_of_way       # noqa: E402


@pytest.fixture()
def client():
    return app.test_client()


def test_admit_matches_engine(client):
    j = client.post("/api/admit", json={"scenario": "A_landlord", "candidate": "G3", "priority": "survey"}).get_json()
    scn = loader.load_scenario(loader.ROOT / "scenarios/A_landlord.yaml") | {"candidate": "G3"}
    r = classify_admission(loader.load_raw(), scn, "survey")
    assert j["result"]["verdict"] == r["verdict"] == "YES-IF"
    assert j["result"]["sentence"] == r["sentence"]
    assert len(j["before"]) == len(j["after"]) > 0


def test_override_is_in_memory_and_reported(client):
    ov = "card.G4.resources.power_modes.charging_initial.power_kw.nominal=70"
    j = client.post("/api/admit", json={"candidate": "G4", "overrides": [ov]}).get_json()
    assert j["overrides"] == [ov] and j["result"]["verdict"] == "YES-IF"
    assert "cooling" in " ".join(j["result"]["binding"])
    # file on disk unchanged → plain call is still YES
    assert client.post("/api/admit", json={"candidate": "G4"}).get_json()["result"]["verdict"] == "YES"


def test_bad_override_is_400(client):
    r = client.post("/api/admit", json={"candidate": "G4", "overrides": ["ship.nope=1"]})
    assert r.status_code == 400 and "override" in r.get_json()["error"]


def test_at_sea_has_no_after(client):
    j = client.post("/api/admit", json={"scenario": "A_prime_underway", "state": {"crew": 0}}).get_json()
    assert j["result"]["verdict"] == "NOT-NOW" and j["after"] == [] and j["before"]


def test_b_matches_engine(client):
    for pr in ("survey", "rescue"):
        j = client.post("/api/b", json={"priority": pr, "crew": 14}).get_json()
        d = right_of_way(loader.load_raw(), loader.load_scenario(loader.ROOT / "scenarios/B_right_of_way.yaml"), pr, crew=14)
        assert j["decision"]["decision"] == d["decision"]
        assert len(j["rows"]) == len(d["sim"].rows)


def test_b_scenario_override(client):
    j = client.post("/api/b", json={"priority": "survey",
                                    "overrides": ["card.G4.special_events.0.recovery_deadline_minutes=6"]}).get_json()
    assert all(not o["feasible"] for o in j["decision"]["options"])


def test_board_g1g2g3_survey_keeps_rescue_adds():
    """Decision board from G1+G2+G3: under survey every addition costs value (keep);
    under rescue G4 then G5 is recommended. Verdicts are the engine's own."""
    c = app.test_client()
    inst = {"G1": "mast", "G2": "bay2", "G3": "bay1"}
    s = c.post("/api/board", json={"priority": "survey", "installed": inst}).get_json()
    assert [o["id"] for o in s["options"]][:3] == ["keep", "+G4", "+G5"]
    assert next(o for o in s["options"] if o["recommended"])["id"] == "keep"
    raw = loader.load_raw()
    for o in s["options"][1:3]:
        r = classify_admission(raw, {"installed": inst, "candidate": o["adds"][0]}, "survey", n_alternatives=0)
        assert o["verdict"] == r["verdict"] and o["steps"][0]["sentence"] == r["sentence"]
    r = c.post("/api/board", json={"priority": "rescue", "installed": inst}).get_json()
    rec = next(o for o in r["options"] if o["recommended"])
    assert set(rec["adds"]) == {"G4", "G5"} and rec["U"] > r["options"][0]["U"]
