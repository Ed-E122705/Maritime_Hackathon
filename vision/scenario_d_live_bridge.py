"""Bridge local G7 webcam observations to G4 simulated readiness on A/A′/B.

The camera checkbox on the active dashboard tab controls whether samples are
submitted. No drone hardware commands. Valid no-motion samples power the
simulated G4 down after five samples while awaiting approval.
"""
from __future__ import annotations

import argparse
import json
import time
from urllib.request import Request, urlopen

from vision.g7_state import load_camera_status


def submit(url, data):
    req = Request(url, data=json.dumps(data).encode("utf-8"),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=3) as response:
        return json.load(response)


def get_json(url):
    with urlopen(url, timeout=3) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5051)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval < 0.5:
        parser.error("Interval must be at least 0.5 seconds")
    base = f"http://127.0.0.1:{args.port}/api/scenario/d/live"
    gate = f"http://127.0.0.1:{args.port}/api/g7-enabled"
    print("G7 live bridge for A/A′/B, localhost only. Ctrl+C to stop.")
    print("Enable the G7 checkbox on the dashboard; camera cannot approve launch.")
    last_enabled = None
    try:
        while True:
            enabled = bool(get_json(gate)["enabled"])
            if enabled != last_enabled:
                if last_enabled is not None:
                    submit(base+"/reset", {})
                print("G7 event bridge: " + ("ENABLED" if enabled else "DISABLED"))
                last_enabled = enabled
            if enabled:
                status = load_camera_status()
                movement = (status["camera_online"] and
                            status.get("positive_motion_sample", False))
                valid = (status["camera_online"] and
                         status["deck_activity"] not in ("UNKNOWN", "INITIALIZING"))
                payload = {
                    "perimeter_motion": bool(movement),
                    "deck_obstructed": False,
                    "operator_approval": False,
                    "observation_valid": bool(valid),
                    "g7_alert": bool(status.get("movement_detected", False)),
                }
                result = submit(base+"/sample", payload)
                print(f"{result['second']:03d}s G7={status['deck_activity']} "
                      f"G4={result['g4_state']} G4={result['power']['g4_kw']:.3f}kW "
                      f"G7={result['power']['g7_kw']:.3f}kW")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("G7 bridge stopped. No flight-deck safety claims or drone commands.")


if __name__ == "__main__":
    main()
