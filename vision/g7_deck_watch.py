"""G7 Logitech BRIO 101 CPU motion prototype.

Captures the *perimeter* zone only. MOG2 identifies changes in a fixed ROI,
not object class or identity. The latest annotated JPEG is overwritten on disk
to let the local VesselOS Flask dashboard show a privacy-conscious preview.
No recorded video, remote inference or drone hardware commands.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATUS_PATH = BASE / "g7_status.json"
EVENTS_PATH = BASE / "g7_events.jsonl"
PREVIEW_PATH = BASE / "g7_preview.jpg"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_status(data):
    tmp = STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATUS_PATH)


def record_event(data):
    """Keep the last 200 activity transitions, no full camera recordings."""
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


def publish(activity, online, previous, pixels=None, reason=None, positive_sample=False):
    data = {
        "guest_id": "G7",
        "camera_online": online,
        "deck_activity": activity,
        "movement_detected": online and activity == "MOVEMENT_DETECTED",
        # Raw most-recent threshold sample, not the 1.5-second display latch.
        "positive_motion_sample": bool(positive_sample and online),
        "changed_pixels": pixels,
        "timestamp_utc": utc_now(),
        "safety_certified": False,
        "zone": "perimeter_surveillance_only",
        "note": "Advisory. No-motion in perimeter does NOT certify the launch deck clear.",
    }
    if reason:
        data["reason"] = reason
    save_status(data)
    if activity != previous:
        record_event(data)
    return activity


def save_preview(cv2, frame):
    """Atomically replace just the latest 640x480-or-smaller annotated frame."""
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
    if not ok:
        return
    temp = PREVIEW_PATH.with_suffix(".jpg.tmp")
    temp.write_bytes(jpg.tobytes())
    os.replace(temp, PREVIEW_PATH)


def run():
    try:
        import cv2
    except ImportError:
        raise SystemExit("Install OpenCV: py -m pip install opencv-python")

    parser = argparse.ArgumentParser(description="G7 local perimeter activity camera")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--threshold", type=int, default=900, help="Changed-pixel threshold in ROI")
    parser.add_argument("--no-window", action="store_true", help="Show preview only in dashboard")
    args = parser.parse_args()
    if args.threshold < 1:
        parser.error("--threshold must be at least 1")

    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    if not cap.isOpened() and os.name == "nt":
        cap.release()
        cap = cv2.VideoCapture(args.camera, cv2.CAP_MSMF)
    if not cap.isOpened():
        publish("UNKNOWN", False, None, reason="Camera unavailable: USB / permissions / index")
        cap.release()
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 15)
    subtractor = cv2.createBackgroundSubtractorMOG2(
        history=120, varThreshold=28, detectShadows=False
    )
    previous, frames, last_motion, last_publish = None, 0, 0.0, 0.0
    last_preview = 0.0
    print("G7 perimeter camera: initialize 40 frames; press Q in preview to exit.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                previous = publish("UNKNOWN", False, previous, reason="Frame read failed")
                return 1
            frames += 1
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = int(w * .2), int(h * .25), int(w * .8), int(h * .85)
            roi = frame[y1:y2, x1:x2]
            gray = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (9, 9), 0)
            mask = subtractor.apply(gray)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, None, iterations=2)
            pixels = int(cv2.countNonZero(mask))
            now = time.monotonic()
            positive = frames > 40 and pixels >= args.threshold
            if positive:
                last_motion = now
            activity = ("INITIALIZING" if frames <= 40
                        else "MOVEMENT_DETECTED" if now - last_motion < 1.5
                        else "NO_MOVEMENT_DETECTED")
            if activity != previous or now - last_publish >= .25:
                previous = publish(activity, True, previous, pixels=pixels,
                                   positive_sample=positive)
                last_publish = now

            color = (0, 0, 255) if activity == "MOVEMENT_DETECTED" else (0, 210, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, "G7 PERIMETER: " + activity, (12, 27),
                        cv2.FONT_HERSHEY_SIMPLEX, .58, color, 2)
            cv2.putText(frame, f"Changed pixels: {pixels} / trigger: {args.threshold}",
                        (12, h - 30), cv2.FONT_HERSHEY_SIMPLEX, .46,
                        (255, 255, 255), 1)
            cv2.putText(frame, "Not a flight-deck clearance camera", (12, h - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1)
            if now - last_preview >= .5:
                save_preview(cv2, frame)
                last_preview = now
            if not args.no_window:
                cv2.imshow("VesselOS G7 - Perimeter Watch", frame)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if not args.no_window:
            cv2.destroyAllWindows()
        publish("UNKNOWN", False, previous, reason="Camera stopped")
        try:
            PREVIEW_PATH.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
