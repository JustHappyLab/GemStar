"""OpsClassifier — classifies pipeline failures into incidents.

CALLING SPEC:
    classify_failure(error, step_id, context, run_id) -> IncidentV1

SIDE EFFECTS:
    None — pure function.
"""

import traceback
import uuid
from datetime import datetime

from src.schemas.incident import IncidentV1


def _classify_category(error: Exception) -> str:
    """Map an exception to a failure category string."""
    msg = str(error).lower()
    etype = type(error).__name__

    if etype == "KeyError" or any(w in msg for w in ("missing", "empty", "abort")):
        return "data_missing"

    if etype == "ValueError" or any(
        w in msg for w in ("llm", "apierror", "timeout", "parse", "json")
    ):
        return "llm_failure"

    if any(w in msg for w in ("backtest", "nav", "trade")):
        return "backtest_error"

    if any(w in msg for w in ("quality", "abort", "stale")):
        return "quality_gate_abort"

    return "unknown"


_SEVERITY_MAP: dict[str, str] = {
    "data_missing": "critical",
    "backtest_error": "high",
    "quality_gate_abort": "high",
    "llm_failure": "medium",
    "unknown": "low",
}


def classify_failure(
    error: Exception,
    step_id: str,
    context: dict[str, str],
    run_id: str,
) -> IncidentV1:
    """Classify a pipeline failure into an IncidentV1.

    Pure function — no side effects.
    """
    category = _classify_category(error)
    severity = _SEVERITY_MAP[category]

    incident_id = (
        f"inc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )

    return IncidentV1(
        incident_id=incident_id,
        run_id=run_id,
        detected_at=datetime.now(),
        state="classified",
        severity=severity,
        category=category,
        error_message=str(error)[:500],
        traceback=traceback.format_exc()[:2000],
        context={**context, "step_id": step_id},
    )
