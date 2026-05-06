"""Create bounded engineering tasks from strategy failures.

CALLING SPEC:
    task = task_from_validation_failure(...)
    task = task_from_exception(...)

SIDE EFFECTS:
    None.  Callers decide whether and where to persist the returned task.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.schemas.engineering import EngineeringRole, EngineeringTaskV1
from src.schemas.verdict import VerdictV1


def task_from_validation_failure(
    *,
    run_id: str,
    strategy_path: Path,
    verdict: VerdictV1,
    engineering_config: Any,
) -> EngineeringTaskV1 | None:
    """Return an Engineer task for validation failures that imply missing capability."""
    if not _engineering_enabled(engineering_config):
        return None

    issue_text = "\n".join(verdict.blocking_issues)
    lowered = issue_text.lower()
    if "not found in factor pool" in lowered:
        reason = "unsupported_capability"
        role: EngineeringRole = "engineer"
        instructions = (
            "The strategy references factor(s) not registered in the factor pool. "
            "Determine whether they are valid new factor ideas. If valid, add the "
            "factor registry entry and computation support inside the allowed "
            "extension surface. Do not change the backtest engine or rule judge."
        )
    elif "yaml schema validation failed" in lowered and _looks_like_schema_capability_gap(lowered):
        reason = "unsupported_capability"
        role = "engineer"
        instructions = (
            "The strategy YAML appears to use a template or schema option that "
            "GemStar does not currently support. Add support only if the new "
            "semantics are explicit and testable. Do not relax validation just "
            "to make an invalid draft pass."
        )
    else:
        return None

    return _build_task(
        run_id=run_id,
        role=role,
        reason=reason,
        source_step="strategy_validation",
        strategy_id=verdict.strategy_id or strategy_path.stem,
        strategy_path=strategy_path,
        error_message=issue_text,
        traceback="",
        engineering_config=engineering_config,
        instructions=instructions,
    )


def task_from_exception(
    *,
    run_id: str,
    strategy_path: Path,
    source_step: str,
    error: Exception,
    traceback_text: str,
    engineering_config: Any,
) -> EngineeringTaskV1 | None:
    """Return an EngineeringTaskV1 if a strategy exception is safe to route."""
    if not _engineering_enabled(engineering_config):
        return None

    role_reason = _classify_exception(source_step, error)
    if role_reason is None:
        return None
    role, reason = role_reason

    if role == "engineer":
        instructions = (
            "The strategy appears to require unsupported strategy, signal, ranking, "
            "universe, or factor capability. Implement the missing extension only "
            "inside the allowed paths, then add focused tests and rerun the failed "
            "strategy."
        )
    else:
        instructions = (
            "A valid strategy path failed in existing code. Diagnose the traceback "
            "and make the smallest regression fix inside the allowed paths. Do not "
            "change strategy semantics or frozen evaluation core files."
        )

    return _build_task(
        run_id=run_id,
        role=role,
        reason=reason,
        source_step=source_step,
        strategy_id=strategy_path.stem,
        strategy_path=strategy_path,
        error_message=str(error),
        traceback=traceback_text,
        engineering_config=engineering_config,
        instructions=instructions,
    )


def artifact_name(task: EngineeringTaskV1) -> str:
    """Return a stable artifact basename for an engineering task."""
    return f"engineering_task_{_slug(task.task_id)}"


def _build_task(
    *,
    run_id: str,
    role: EngineeringRole,
    reason: str,
    source_step: str,
    strategy_id: str,
    strategy_path: Path,
    error_message: str,
    traceback: str,
    engineering_config: Any,
    instructions: str,
) -> EngineeringTaskV1:
    role_policy = getattr(engineering_config, role)
    task_id = _slug(f"{run_id}_{source_step}_{strategy_id}_{role}")
    return EngineeringTaskV1(
        task_id=task_id,
        run_id=run_id,
        role=role,
        reason=reason,
        source_step=source_step,
        strategy_id=strategy_id,
        strategy_path=str(strategy_path),
        error_message=error_message[:1000],
        traceback=traceback[:4000],
        context={
            "strategy_path": str(strategy_path),
            "source_step": source_step,
        },
        allowed_paths=list(role_policy.allowed_paths),
        forbidden_paths=list(engineering_config.forbidden_paths),
        auto_apply=bool(engineering_config.auto_apply),
        max_attempts=int(engineering_config.max_attempts),
        instructions=instructions,
    )


def _engineering_enabled(engineering_config: Any) -> bool:
    return bool(engineering_config and getattr(engineering_config, "enabled", False))


def _looks_like_schema_capability_gap(message: str) -> bool:
    return any(
        marker in message
        for marker in (
            "literal_error",
            "extra_forbidden",
            "input should be",
            "universe",
            "timer",
            "rebalance",
        )
    )


def _classify_exception(
    source_step: str,
    error: Exception,
) -> tuple[EngineeringRole, str] | None:
    message = str(error).lower()

    unsupported_markers = (
        "unsupported",
        "not implemented",
        "unknown timer",
        "unknown universe",
        "unknown factor",
        "no factor",
        "not found in factor pool",
    )
    if any(marker in message for marker in unsupported_markers):
        return "engineer", "unsupported_capability"

    if source_step in {"strategy_inputs", "strategy_validation"} and isinstance(
        error,
        (KeyError, AttributeError, NotImplementedError),
    ):
        return "engineer", "unsupported_capability"

    if source_step in {"strategy_inputs", "backtesting"} and isinstance(
        error,
        (KeyError, TypeError, AttributeError, ValueError),
    ):
        return "bugfix", "code_bug"

    return None


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_")[:120]
