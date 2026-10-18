"""G7 Logitech BRIO 101 CPU camera prototype.

Fixed-region motion detection with OpenCV MOG2. No face identification,
NPU, cloud connection, raw-video storage, or autonomous deck clearance.
Writes current JSON state + bounded event history for the VesselOS dashboard.

Run: py vision/g7_deck_watch.py --camera 0
Try --camera 1 if Windows selects a laptop's built-in camera. Press Q to exit.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

STATUS_PATH = Path(__file__).with_name("g7_status.json")
EVENTS_PATH = Path(__file__).with_name("g7_events.jsonl")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_status(data):
    tmp = STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATUS_PATH)


def record_event(data):
    """Store state changes only; retain last 200 events (no video/images)."""
    event = {
        "timestamp_utc": data["timestamp_utc"],
        "deck_activity": data["deck_activity"],
        "camera_online": data["camera_online"],
        "changed_pixels": data.get("changed_pixels"),
        "safety_certified": False,
    }
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines() if EVENTS_PATH.exists() else []
    except OSError:
        lines = []
    lines.append(json.dumps(event))
    EVENTS_PATH.write_text("\n".join(lines[-200:]) + "\n", encoding="utf-8")


def publish(activity, online, previous, pixels=None, reason=None):
    data = {
        "guest_id": "G7", "camera_online": online, "deck_activity": activity,
        "movement_detected": activity == "MOVEMENT_DETECTED",
        "changed_pixels": pixels, "timestamp_utc": utc_now(),
        "safety_certified": False,
        "note": "Advisory only. No-motion does NOT certify a clear deck.",
    }
    if reason:
        data["reason"] = reason
    save_status(data)
    if activity != previous:
        record_event(data)
    return activity


def run():
    try:
        import cv2
    except ImportError:
        raise SystemExit("Install OpenCV first: py -m pip install opencv-python")

    p = argparse.ArgumentParser(description="G7 advisory deck activity camera")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--threshold", type=int, default=900, help="ROI changed-pixel threshold")
    p.add_argument("--no-window", action="store_true", help="Run until Ctrl+C without preview")
    args = p.parse_args()

    if args.threshold < 1:
        p.error("--threshold must be at least 1")

    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    if not cap.isOpened() and os.name == "nt":
        cap.release()
        cap = cv2.VideoCapture(args.camera, cv2.CAP_MSMF)
    if not cap.isOpened():
        publish("UNKNOWN", False, None, reason="Camera not available; check USB, permissions, and camera index")
        cap.release()
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 15)
    subtractor = cv2.createBackgroundSubtractorMOG2(
        history=120, varThreshold=28, detectShadows=False
    )
    previous, frames, last_motion, last_publish = None, 0, 0.0, 0.0
    print("G7 live camera: allow 40 frames to initialize; press Q to stop.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                previous = publish("UNKNOWN", False, previous, reason="USB camera frame read failed")
                return 1
            frames += 1
            height, width = frame.shape[:2]
            x1, y1 = int(width * .20), int(height * .25)
            x2, y2 = int(width * .80), int(height * .85)
            roi = frame[y1:y2, x1:x2]
            gray = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (9, 9), 0)
            mask = subtractor.apply(gray)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, None, iterations=2)
            pixels = int(cv2.countNonZero(mask))
            now = time.monotonic()
            if frames > 40 and pixels >= args.threshold:
                last_motion = now
            activity = ("INITIALIZING" if frames <= 40
                        else "MOVEMENT_DETECTED" if now - last_motion < 1.5
                        else "NO_MOVEMENT_DETECTED")
            if activity != previous or now - last_publish >= .5:
                previous = publish(activity, True, previous, pixels=pixels)
                last_publish = now
            if not args.no_window:
                color = (0, 0, 255) if activity == "MOVEMENT_DETECTED" else (0, 210, 255)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, "G7: " + activity, (12, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, .64, color, 2)
                cv2.putText(frame, "Advisory only - operator must verify deck",
                            (12, height - 12), cv2.FONT_HERSHEY_SIMPLEX,
                            .45, (255, 255, 255), 1)
                cv2.imshow("VesselOS G7 - BRIO 101", frame)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if not args.no_window:
            cv2.destroyAllWindows()
        publish("UNKNOWN", False, previous, reason="Camera stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
