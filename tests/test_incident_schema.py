"""Tests for IncidentV1 schema — round-trip JSON serialization."""

from datetime import datetime

from src.schemas.incident import IncidentV1


def test_incident_roundtrip():
    """IncidentV1 survives JSON round-trip."""
    incident = IncidentV1(
        incident_id="inc_20260503_001",
        run_id="run_001",
        detected_at=datetime(2026, 5, 3, 22, 0, 0),
        state="classified",
        severity="high",
        category="data_missing",
        error_message="Core table 'daily' is missing",
        traceback="Traceback (most recent call last): ...",
        context={"step_id": "quality_checking", "module": "data_quality_gate"},
    )

    json_str = incident.model_dump_json()
    restored = IncidentV1.model_validate_json(json_str)

    assert restored.incident_id == incident.incident_id
    assert restored.run_id == incident.run_id
    assert restored.detected_at == incident.detected_at
    assert restored.state == incident.state
    assert restored.severity == incident.severity
    assert restored.category == incident.category
    assert restored.error_message == incident.error_message
    assert restored.context == incident.context
    assert restored.resolved_at is None


def test_incident_defaults():
    """IncidentV1 has sensible defaults."""
    incident = IncidentV1(
        incident_id="inc_001",
        run_id="run_001",
        detected_at=datetime(2026, 5, 3),
    )
    assert incident.version == "IncidentV1"
    assert incident.state == "detected"
    assert incident.severity == "medium"
    assert incident.category == "unknown"
    assert incident.error_message == ""
    assert incident.context == {}
    assert incident.resolution_notes == ""
    assert incident.resolved_at is None


def test_incident_state_enum():
    """state must be one of the 7 allowed values."""
    for s in ("detected", "classified", "retrying", "degraded",
              "manual_attention", "engineering_task_created", "resolved"):
        incident = IncidentV1(
            incident_id="i1", run_id="r1",
            detected_at=datetime(2026, 5, 3), state=s,
        )
        assert incident.state == s


def test_incident_severity_enum():
    """severity must be one of the 4 allowed values."""
    for sev in ("low", "medium", "high", "critical"):
        incident = IncidentV1(
            incident_id="i1", run_id="r1",
            detected_at=datetime(2026, 5, 3), severity=sev,
        )
        assert incident.severity == sev
