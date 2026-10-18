# G7 BRIO 101 camera + live dashboard (feature branch)

Base: integrate-governor-verifier. G7 is a new, **non-safety-critical** synthetic guest. This branch leaves the original D1–D4 solver, G1–G6, and their scenarios untouched. The Scenario D contract is **pending** and is not implemented in this branch.

## What was added

- data/guests/G7_deck_activity_monitor.json — G7 B.0 guest manifest, simulated mast placement.
- vision/g7_deck_watch.py — USB Logitech BRIO 101 camera processing via OpenCV MOG2 motion detection, CPU only.
- vision/g7_state.py — stale-aware current state and last 30 camera state transitions, no OpenCV dependency.
- tests/test_g7_camera.py — guest, status and dashboard API smoke tests.

What changed: physical_model/data/resource_profiles.json (G7 compute on node4); config/guest_overlays.yaml (G7 normal/on and off roles); all four config/priorities/*.yaml (G7 weights); dashboard/app.py (GET /api/g7-camera); dashboard/templates/index.html (live camera panel with 1-second polling); physical_model/tests/test_canonical_integration.py (expect G1–G7); .gitignore (generated camera JSON).

## Run multiple Git branches concurrently on the Dell Snapdragon X Elite

**Do not use git switch in the same folder to run two branches simultaneously.**
From the original repository checkout:

    git fetch origin
    git worktree add ../Maritime_G7 -b local-g7 origin/feature/g7-camera-dashboard

That checks out the remote G7 branch in another working folder. If local-g7 already exists, use the existing worktree instead.

Window / terminal 1, original combined branch:

    cd Maritime_Hackathon
    py dashboard/app.py --port 5050

Window / terminal 2, G7 branch:

    cd ../Maritime_G7
    py -m pip install -r requirements.txt
    py -m pip install opencv-python
    py dashboard/app.py --port 5051

Window / terminal 3, G7 branch, with webcam plugged into the Dell:

    cd ../Maritime_G7
    py vision/g7_deck_watch.py --camera 0

On Windows, try --camera 1 if index 0 is the internal laptop camera. Use a USB-C data adapter if needed. Avoid two processes opening the webcam simultaneously. Press Q to stop the video window. See http://127.0.0.1:5051 for the G7 dashboard and http://127.0.0.1:5051/api/g7-camera for its JSON status.

The two *branches* are not what executes in parallel: two separate working directories and running Python processes are. The Snapdragon has capacity to multitask, but measured performance is not guaranteed. If native ARM64 OpenCV wheels are unavailable, use compatible x64 Python under Windows-on-Arm emulation.

## Demo

1. Start both G7 Python processes. The new dashboard will show G7 available among admission candidates.
2. Mount the BRIO 101 **stationary** watching the marked deck area. Allow ~40 captured frames for warmup.
3. Move a hand/object inside the central region. Dashboard displays MOVEMENT_DETECTED, recent timestamp and event history.
4. Stop moving: after about 1.5 seconds, NO_MOVEMENT_DETECTED. This is not proof of a clear or safe deck.
5. Stop camera / unplug: event/status becomes UNKNOWN. If the process dies unexpectedly, the dashboard marks stale status UNKNOWN after 5 seconds.

Privacy: no video frames are saved; only recent motion state transitions and changed-pixel counts are written locally. No cloud inference, face recognition, or Snapdragon NPU is required.

## Tests (from G7 checkout)

    py -m pytest -q tests/test_g7_camera.py
    py -m pytest -q tests
    py -m unittest discover -s physical_model/tests -v

Review all tests before merging. A full webcam hardware test and all end-to-end solver tests have **not** been verified in this change authoring environment.

## Explicit limitations

- G7 physical masses, 0.1 kW power, 0.01 Mbit/s status bandwidth, node4 compute, mast placement and installation minutes are **team assumptions**, not measured sensor/host specifications.
- The *real* webcam runs plugged into the Dell workstation. It is not connected to the simulated vessel's computing node or power bus.
- The live camera feed does not actuate G4, G6, deck machinery or the governor's safety policies.
- The dashboard's new panel is an **advisory telemetry view**. The simulation engine still handles resource admission separately.
- Scenario D has not been supplied; when it arrives, implement its semantics separately and only then connect G7 events into explicit scenario state and decision outcomes.
- Update the existing physical assumption/evidence register for G7 before representing this as a reviewed shipboard installation.
