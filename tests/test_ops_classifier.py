"""Tests for the OpsClassifier module."""

from src.ops.classifier import classify_failure


def _run_id() -> str:
    return "run-test-001"


# 1. KeyError -> data_missing / critical
def test_keyerror_classified_as_data_missing():
    try:
        raise KeyError("daily")
    except KeyError as exc:
        incident = classify_failure(exc, "step_fetch", {}, _run_id())
    assert incident.category == "data_missing"
    assert incident.severity == "critical"


# 2. ValueError("LLM ...") -> llm_failure / medium
def test_llm_valueerror_classified_as_llm_failure():
    try:
        raise ValueError("LLM response parse failed")
    except ValueError as exc:
        incident = classify_failure(exc, "step_llm", {}, _run_id())
    assert incident.category == "llm_failure"
    assert incident.severity == "medium"


# 3. Generic exception -> unknown / low
def test_generic_exception_classified_as_unknown():
    try:
        raise RuntimeError("something")
    except RuntimeError as exc:
        incident = classify_failure(exc, "step_misc", {}, _run_id())
    assert incident.category == "unknown"
    assert incident.severity == "low"


# 4. incident_id uniqueness
def test_incident_id_is_unique():
    ids = set()
    for _ in range(5):
        try:
            raise RuntimeError("dup test")
        except RuntimeError as exc:
            ids.add(classify_failure(exc, "s", {}, _run_id()).incident_id)
    assert len(ids) == 5


# 5. Context is preserved and step_id injected
def test_context_preserved():
    try:
        raise RuntimeError("ctx test")
    except RuntimeError as exc:
        incident = classify_failure(
            exc, "step_x", {"key": "value"}, _run_id()
        )
    assert incident.context["key"] == "value"
    assert incident.context["step_id"] == "step_x"


# 6. State is always "classified"
def test_state_is_classified():
    try:
        raise RuntimeError("state test")
    except RuntimeError as exc:
        incident = classify_failure(exc, "s", {}, _run_id())
    assert incident.state == "classified"


# 7. Error message truncated to 500 chars
def test_error_message_truncated():
    long_msg = "x" * 1000
    try:
        raise RuntimeError(long_msg)
    except RuntimeError as exc:
        incident = classify_failure(exc, "s", {}, _run_id())
    assert len(incident.error_message) == 500
