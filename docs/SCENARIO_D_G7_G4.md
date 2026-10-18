# Scenario D — G7 perimeter motion to G4 simulated drone reconnaissance

Scenario D is implemented on feature/g7-camera-dashboard, based on integrate-governor-verifier. Existing A–C, G1–G6 and their optimization logic remain intact.

## Features

- Scripted 0–180 second (181-step) replay through GET /api/scenario/d.
- G7 monitoring 0.040 kW, alert 0.065 kW; installed mass 1.2 kg and metadata bandwidth 0.02 Mbps: all simulated assumptions.
- Two consecutive unclassified motion samples trigger simulated G4 startup, not actual drone actuation.
- G4 standby 2 kW and startup/preflight 3 kW, with 8-second startup.
- Independent launch-deck verification and operator software approval required before simulated takeoff.
- Replay, constraints, event history, G7 and G4 states and power/cooling gauges integrated into the existing dashboard at /scenario/D.
- Camera live relay uses existing OpenCV G7 readings and posts samples to the Scenario D local Flask app. No approval is granted by the relay.

## Expected deterministic checkpoints

| Second | G4 state | Synthetic total ship load |
| ---: | --- | ---: |
| 0 | Standby | 48.040 kW |
| 20 | Standby | 48.065 kW |
| 21 | Starting | 49.065 kW |
| 29 | Awaiting approval | 49.065 kW |
| 32 | Simulated launch | 49.065 kW |
| 37 | In flight | 48.065 kW |
| 77 | Mission complete | 48.040 kW |

The additional 46 kW background baseline exists to reproduce the supplied checkpoints and is NOT a verified ship load. The cooling estimate is illustrative 1:1 all-load heat, not a certified physical thermal-path check.

## Run from the G7 branch/worktree on Snapdragon X Elite

Install solver/dashboard requirements:

    py -m pip install -r requirements.txt

Start the dashboard:

    py dashboard/app.py --port 5051

Open http://127.0.0.1:5051/scenario/D then click Load 181-step replay, Play, or scrub the time slider.

To run with webcam motion, use two additional terminals in the SAME G7 worktree:

    py -m pip install opencv-python
    py vision/g7_deck_watch.py --camera 0

In the third terminal:

    py -m vision.scenario_d_live_bridge --port 5051

Try camera index 1 if camera 0 selects the internal webcam. On the dashboard use Refresh live status. Once awaiting approval, click Operator approve (simulated); camera never authorizes launches.

## Tests

    py -m pytest -q tests/test_scenario_d.py tests/test_g7_camera.py
    py -m pytest -q tests
    py -m unittest discover -s physical_model/tests -v

## Explicit limitations

- The Dell Snapdragon X Elite runs OpenCV CPU inference; Qualcomm Dragonwing hardware deployment and NPU object classification are NOT implemented.
- G7 senses movement only, not classifiable object identities.
- G7 perimeter and G4 flight deck are separate zones. No-motion from perimeter is not deck-clearance proof.
- Scripted operator approval at second 32 is a demo event, not automatic launch authority.
- There are no physical drone/motor commands. All G4 launch states are simulated.
- The simplified Scenario D resource checks are separate from the full Section 1 physical checker; they do not verify end-to-end admission or certified timing.
- Live camera observations advance simulation time approximately once per relay call, not hard real-time.
