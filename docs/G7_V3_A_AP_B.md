# G7 live integration in original v3 A / A′ / B dashboard

The dashboard now uses the v3 UI supplied in `maritime_hacks_v3_final.zip` as the baseline. It adds an optional G7 checkbox and an opt-in live camera pane. There is **no Scenario D tab/panel**; internal `/api/scenario/d/live` remains a simulation-only service used for the G4 readiness state.

## Run on Ubuntu / Snapdragon

From repository root, update **once**:

```bash
git switch feature/g7-camera-dashboard
git pull --ff-only origin feature/g7-camera-dashboard
```

Open three terminals:

```bash
# Terminal 1 — dashboard (.venv)
cd ~/Maritime_Hackathon
source .venv/bin/activate
python dashboard/app.py --port 5051
```

```bash
# Terminal 2 — camera (.camera-venv with compatible system OpenCV and NumPy)
cd ~/Maritime_Hackathon
source .camera-venv/bin/activate
python vision/g7_deck_watch.py --camera 0 --no-window
```

```bash
# Terminal 3 — checkbox-gated continuous bridge
cd ~/Maritime_Hackathon
source .camera-venv/bin/activate
python -m vision.scenario_d_live_bridge --port 5051
```

Open `http://127.0.0.1:5051/` and hard refresh. Tick G7 in the A/A′ installed set, or in the B fleet. The original GUI remains alongside a new G7 live pane with a JPEG preview and G4 status. The live bridge stays running until stopped; it **only** feeds G4 when G7 is checked in the active tab. G4 preparation is simulated, with separate operator approval and a five-valid-second no-motion power-off rule.

### Resources

The existing resource governor already has a G7 guest manifest, solver overlay and mission weights. Adding G7 through the checkbox puts its mass, mast placement, CPU/RAM, metadata bandwidth and 0.040 kW monitoring load into existing A/A′ and B resource evaluation. While a current G7 detection is active, its evaluated active-mode load is changed in memory to 0.065 kW; no manifest is overwritten. In the A/A′ eight dials, power and other resources follow engine results. In B, power, data, compute, and static fleet checks incorporate G7; the four operational dials remain the original scenario-specific measures.

The G4 live readiness panel's 0/2/3 kW loads and 46 kW ship baseline are synthetic demo telemetry, **not additional loads summed into the governor's G4 full-mode card** (which models different charging/operational modes). They are shown separately to prevent double-counting. Existing B G4 rescue simulation behavior is unchanged.

### Known limitations

- G7 uses unclassified background-subtraction motion, not object identity.
- Stale/invalid camera readings never mean deck clear or count toward the no-motion shutdown timeout.
- All G4 launch statuses are simulated; no physical drone commands are sent.
- Operator approval is required; the simulated launch-deck-clear condition is not a real sensor.
- Hardware power numbers and installation values for G7 are assumed, not measured on BRIO/Qualcomm hardware.
- This integration is **not** a certified vessel power/thermal safety analysis.
- If a guest is denied by the governor due to resource limits, the webcam panel remains an advisory software demonstration; it does not establish that G7 was physically installed or admitted.

## Checks

```bash
python -m pytest -q tests/test_scenario_d.py tests/test_g7_camera.py
```

To confirm the new v3 UI is served by Flask:

```bash
curl -s http://127.0.0.1:5051/ | grep 'id="g7Integrated"'
```
