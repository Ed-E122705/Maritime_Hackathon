"""Connect the existing G7 webcam status to Scenario D's simulated controller.

Run in the G7 checkout with Flask and vision/g7_deck_watch.py running:
    py vision/scenario_d_live_bridge.py --port 5051
No physical drone commands; G7 watches a perimeter area, never launch deck.
Approval is intentionally NOT submitted by the camera bridge.
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5051)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval < 0.5:
        parser.error("Interval must be at least 0.5 seconds")
    base = f"http://127.0.0.1:{args.port}/api/scenario/d/live"
    print("G7 → Scenario D synthetic bridge, localhost only, Ctrl+C to stop.")
    print("Camera alone cannot approve launch; use dashboard operator control.")
    submit(base+"/reset", {})
    try:
        for tick in range(181):
            status = load_camera_status()
            # The webcam reports UNCLASSIFIED motion only. Two consecutive
            # submitted positive samples trigger simulated G4 startup.
            movement = status["camera_online"] and status.get("positive_motion_sample", False)
            payload = {
                "perimeter_motion": bool(movement),
                "deck_obstructed": False,
                "operator_approval": False,
            }
            result = submit(base+"/sample", payload)
            print(f"{result['second']:03d}s G7={status['deck_activity']} "
                  f"G4={result['g4_state']} power={result['power']['total_kw']:.3f} kW")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Bridge stopped. Simulation cannot be used to certify a deck is clear.")


if __name__ == "__main__":
    main()
