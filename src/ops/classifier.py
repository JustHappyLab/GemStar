"""OpsClassifier — classifies pipeline failures into IncidentV1 artifacts.

CALLING SPEC:
    classify_failure(
        error: Exception,
        step_id: str,
        context: dict[str, str],
        run_id: str,
    ) -> IncidentV1

    Classifies an exception raised during the daily pipeline, producing
    an IncidentV1 with category, severity, and state="classified".

SIDE EFFECTS:
    None — pure function.
"""

import traceback as tb
from datetime import datetime

from src.schemas.incident import IncidentV1

# ---------------------------------------------------------------------------
# Valid categories and severity mapping
# ---------------------------------------------------------------------------

VALID_CATEGORIES: list[str] = [
    "data_missing",
    "data_quality",
    "factor_error",
    "strategy_error",
    "backtest_error",
    "llm_error",
    "report_error",
    "internal_error",
]

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "data_missing": ["missing", "not found", "empty", "no data", "keyerror"],
    "data_quality": ["quality", "stale", "freshness", "pit", "abort"],
    "factor_error": ["factor", "ic", "monitor"],
    "strategy_error": ["strategy", "validate", "yaml", "config"],
    "backtest_error": ["backtest", "signal", "ranking", "engine"],
    "llm_error": ["llm", "anthropic", "claude", "timeout", "rate limit"],
    "report_error": ["report", "markdown", "render"],
}

# Severity mapping by step_id (earlier steps are more critical).
_STEP_SEVERITY: dict[str, str] = {
    "collecting": "critical",
    "quality_checking": "high",
    "factor_monitoring": "medium",
    "strategy_ideation": "medium",
    "strategy_validation": "medium",
    "backtesting": "high",
    "judging": "medium",
    "leaderboard_building": "medium",
    "reporting": "low",
    "failed": "high",
}


def classify_failure(
    error: Exception,
    step_id: str,
    context: dict[str, str],
    run_id: str,
) -> IncidentV1:
    """Classify a pipeline failure into an IncidentV1.

    Parameters
    ----------
    error : Exception
        The exception that caused the failure.
    step_id : str
        The FSM state when the failure occurred.
    context : dict
        Additional context (e.g., module, run_id).
    run_id : str
        The pipeline run identifier.

    Returns
    -------
    IncidentV1
        Classified incident with state="classified".
    """
    error_text = f"{type(error).__name__}: {error!s}".lower()
    category = _classify_category(error_text)
    severity = _STEP_SEVERITY.get(step_id, "medium")

    # Escalate severity for certain error types.
    if isinstance(error, (MemoryError, SystemExit)):
        severity = "critical"
    elif isinstance(error, (KeyError, TypeError, AttributeError)) and step_id in ("collecting", "quality_checking"):
        severity = "critical"

    incident_id = f"inc_{run_id}_{step_id}"

    return IncidentV1(
        incident_id=incident_id,
        run_id=run_id,
        detected_at=datetime.now(),
        state="classified",
        severity=severity,
        category=category,
        error_message=str(error),
        traceback="".join(tb.format_exception(type(error), error, error.__traceback__)),
        context={"step_id": step_id, **context},
    )


def _classify_category(error_text: str) -> str:
    """Match error text against keyword lists to pick a category."""
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in error_text for kw in keywords):
            return cat
    return "internal_error"
