"""Scenario D simulation only: motion confirmation -> resource check -> simulated G4 preflight.

No hardware commands are issued. Launch requires distinct deck checks and explicit
software operator approval. Perimeter alerts cannot establish launch-deck clearance.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "scenarios" / "D_g7_g4.json"


def config():
    return json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))


def safety_checks(cfg, deck_obstructed=False):
    s = cfg["ship"]
    checks = {
        "perimeter_separate_from_deck": True,
        "flight_deck_verified_clear": s["flight_deck_verified_clear"] and not deck_obstructed,
        "g4_ready": s["g4_ready"],
        "sea_state_lte_4": s["sea_state"] <= 4,
        "wind_lte_25_kn": s["wind_knots"] <= 25,
        "speed_5_to_12_kn": 5 <= s["speed_knots"] <= 12,
        "course_steady": s["course_keeping"] == "steady",
        "stern_ramp_idle": not s["stern_ramp_in_use"],
        "crew_available": s["crew_available"] > 0,
    }
    return checks


def demand(cfg, seconds, alert, preflight, g4_off=False):
    background = cfg["background_ship_load_kw"]
    g7 = cfg["g7_alert_kw"] if alert else cfg["g7_monitoring_kw"]
    g4 = (0.0 if g4_off else
          cfg["g4_preflight_kw"] if preflight else cfg["g4_standby_kw"])
    total = background + g7 + g4
    # Conservative screening: synthetic all-electrical-to-heat total; the
    # real vessel physical checker allocates cooling to paths and positions.
    limit = cfg["ship"]["continuous_guest_capacity_kw"]
    cooling = cfg["ship"]["cooling_capacity_kw"]
    checks = {
        "continuous_power": total <= limit,
        "thermal_screen": total <= cooling,
        "port_branch": background + g7 <= cfg["ship"]["power_branch_capacity_kw"],
        "starboard_branch": g4 <= cfg["ship"]["power_branch_capacity_kw"],
    }
    return {
        "background_kw": round(background, 3), "g7_kw": round(g7, 3),
        "g4_kw": round(g4, 3), "total_kw": round(total, 3),
        "thermal_demand_kw": round(total, 3),
        "power_capacity_kw": limit, "cooling_capacity_kw": cooling,
        "power_margin_kw": round(limit-total, 3),
        "cooling_margin_kw": round(cooling-total, 3),
        "checks": checks,
    }


class ScenarioD:
    def __init__(self, settings=None, scripted=True):
        self.cfg = settings or config()
        self.scripted = scripted
        self.time = -1
        self.confirm = 0
        self.alert = False
        self.start_time = None
        self.state = "Standby"
        self.authorized = False
        self.launch_time = None
        self.deck_obstructed = False
        self.no_motion_seconds = 0
        self.events = []
        self.timeline = []

    def tick(self, perimeter_motion=False, deck_obstructed=False, approve=False,
             observation_valid=True, g7_alert=None):
        self.time += 1
        t = self.time
        self.deck_obstructed = bool(deck_obstructed)
        notes = []
        valid_motion = bool(perimeter_motion)
        if self.scripted:
            valid_motion = t in (20, 21)
            approve = t == self.cfg["operator_approval_at_s"]
        # Live only: five consecutive *valid* no-motion observations power G4 down.
        # Unknown/stale camera frames do not count as an empty surveillance zone.
        # This is a DEMO power policy, not evidence an object has left the scene.
        if self.state == "Powering off":
            self.state = "Off"
            notes.append("Simulated G4 shutdown complete (0 kW ship-side draw)")
        self.confirm = self.confirm + 1 if valid_motion and observation_valid else 0
        if not self.scripted:
            if valid_motion and observation_valid:
                self.no_motion_seconds = 0
            elif observation_valid and self.state in ("Starting", "Awaiting approval"):
                self.no_motion_seconds += 1
                if self.no_motion_seconds >= self.cfg.get("no_motion_shutdown_seconds", 5):
                    self.state = "Powering off"
                    self.start_time = None
                    self.authorized = False
                    self.alert = False
                    self.confirm = 0
                    notes.append("Five valid seconds without motion: cancel G4 preparation and power off")
            else:
                # Invalid camera readings interrupt the streak; do not call them no-motion.
                self.no_motion_seconds = 0
        # G7's alert-mode power follows the camera's latched activity status;
        # G4 startup still requires consecutive *raw* positive motion samples.
        # A missing g7_alert preserves behavior for the scripted replay and
        # callers of the original tick interface.
        active_alert = valid_motion if g7_alert is None else bool(g7_alert)
        if not self.scripted and observation_valid and not active_alert and self.alert:
            self.alert = False
            notes.append("G7 motion alert ended: return to monitoring power")
        if observation_valid and active_alert and not self.alert:
            self.alert = True
            notes.append("G7 unclassified perimeter-motion candidate")
        if (self.confirm >= self.cfg["required_consecutive_positive_samples"]
                and self.start_time is None and self.state in ("Standby", "Off")):
            startup_demand = demand(self.cfg, t, True, True)
            checks = safety_checks(self.cfg, self.deck_obstructed)
            # Readiness + resources can permit PREPARATION; deck clearance is
            # independently mandatory for launch, but not for safe preparation.
            if all(startup_demand["checks"].values()) and checks["g4_ready"]:
                self.start_time = t
                self.state = "Starting"
                notes.append("Two positive observations: simulated G4 startup begins")
            else:
                notes.append("Simulated startup held: G4 not ready or resources unavailable")
        if self.state == "Starting" and t >= self.start_time + self.cfg["g4_startup_seconds"]:
            self.state = "Awaiting approval"
            notes.append("Simulated G4 startup complete; await operator clearance")
        if approve and self.state == "Awaiting approval":
            checks = safety_checks(self.cfg, self.deck_obstructed)
            d = demand(self.cfg, t, self.alert, True)
            if all(checks.values()) and all(d["checks"].values()):
                self.authorized = True
                self.state = "Simulated launch"
                self.launch_time = t
                notes.append("Operator approved: simulated launch only (no drone command)")
            else:
                notes.append("Launch held: " + ", ".join(k for k,v in {**checks,**d["checks"]}.items() if not v))
        if self.state == "Simulated launch" and not safety_checks(self.cfg, self.deck_obstructed)["flight_deck_verified_clear"]:
            self.state = "Launch held"
            notes.append("Flight deck became obstructed: stop simulated takeoff, require new operator decision")
        if self.state == "Simulated launch" and t >= (self.launch_time or 0) + 5:
            self.state = "In flight"
            notes.append("Simulated takeoff complete; G4 ship-side returns to standby load")
        if self.state == "In flight" and self.scripted and t >= self.cfg["recon_complete_at_s"]:
            self.state = "Mission complete"
            self.alert = False
            notes.append("Reconnaissance simulation complete")
        preflight = self.state in ("Starting", "Awaiting approval", "Simulated launch")
        d = demand(self.cfg, t, self.alert, preflight,
                   g4_off=self.state in ("Powering off", "Off"))
        check = safety_checks(self.cfg, self.deck_obstructed)
        if not check["flight_deck_verified_clear"] and self.state in ("Awaiting approval", "Simulated launch"):
            notes.append("Flight deck obstruction: HOLD launch; perimeter is a different zone")
        for note in notes:
            self.events.append({"second":t,"event":note})
        row = {
            "second":t,
            "g7_status": "ALERT" if self.alert else "MONITORING",
            "consecutive_positive_samples":self.confirm,
            "no_motion_seconds":self.no_motion_seconds,
            "no_motion_shutdown_seconds":self.cfg.get("no_motion_shutdown_seconds", 5),
            "g4_state":self.state,
            "g4_battery_percent":self.cfg["g4_initial_battery_percent"],
            "operator_authorized":self.authorized,
            "flight_deck_obstructed":self.deck_obstructed,
            "power":d,
            "launch_checks":check,
            "events":notes,
            "safety_certified":False,
        }
        self.timeline.append(row)
        return row


def replay(settings=None):
    engine = ScenarioD(settings=settings, scripted=True)
    return {
        "scenario":"D",
        "parameters":engine.cfg,
        "timeline":[engine.tick() for _ in range(engine.cfg["duration_seconds"]+1)],
        "events":engine.events,
        "scope":"simulation_only_no_physical_drone_commands",
    }
