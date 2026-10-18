"""G6 monitoring dashboard contract (requires Flask)."""
from pathlib import Path
import pytest
pytest.importorskip("flask")
from dashboard.app import app


def test_g6_endpoint_is_evidence_qualified():
    result = app.test_client().get("/api/physical-g6")
    assert result.status_code == 200
    report = result.get_json()
    assert report["status"] in ("PASS", "FAIL", "UNKNOWN")
    assert report["assessment_status"] in ("PASS", "FAIL", "UNKNOWN")
    assert report["full_admission_status"] == "NOT_EVALUATED"
    assert "note" in report
