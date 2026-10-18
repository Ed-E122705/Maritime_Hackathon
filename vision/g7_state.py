"""Safe, read-only G7 dashboard data access; no OpenCV dependency.

Camera status older than 5 seconds is UNKNOWN, never evidence of a clear deck.
Only local event metadata is read. Does not command other vessel guests.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_camera_status(root=ROOT, now=None, ttl_seconds=5):
    base = Path(root) / "vision"
    result = {
        "guest_id": "G7", "camera_online": False, "deck_activity": "UNKNOWN",
        "movement_detected": False, "safety_certified": False,
        "reason": "Camera not started", "timestamp_utc": None,
        "age_seconds": None, "events": [],
        "integration_scope": "advisory_only_no_automatic_ship_commands",
    }
    if now is None:
        now = datetime.now(timezone.utc)
    events = base / "g7_events.jsonl"
    try:
        if events.exists():
            rows = events.read_text(encoding="utf-8").splitlines()[-30:]
            result["events"] = [json.loads(x) for x in rows if x.strip()]
    except (OSError, ValueError, TypeError):
        result["events"] = []
    status = base / "g7_status.json"
    try:
        raw = json.loads(status.read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(raw["timestamp_utc"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Camera timestamp lacks timezone")
        age = (now - stamp).total_seconds()
        result["timestamp_utc"] = raw["timestamp_utc"]
        result["age_seconds"] = max(0, round(age, 1))
        if age < -3 or age > ttl_seconds:
            result["reason"] = "Camera status stale; latest event is not current"
            return result
        if not isinstance(raw.get("camera_online"), bool):
            raise ValueError("Invalid camera_online flag")
        activity = raw.get("deck_activity")
        if activity not in (
            "MOVEMENT_DETECTED", "NO_MOVEMENT_DETECTED", "INITIALIZING", "UNKNOWN"
        ):
            raise ValueError("Invalid deck_activity value")
        result.update(
            camera_online=raw["camera_online"],
            deck_activity=activity if raw["camera_online"] else "UNKNOWN",
            movement_detected=activity == "MOVEMENT_DETECTED" and raw["camera_online"],
            changed_pixels=raw.get("changed_pixels"),
            reason=raw.get("reason", "") if raw["camera_online"] else "Camera stopped",
        )
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, AttributeError):
        result["reason"] = "No valid camera status available"
    result["safety_certified"] = False
    return result
