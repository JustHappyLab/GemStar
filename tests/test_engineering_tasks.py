"""Tests for engineering task creation."""

from __future__ import annotations

from pathlib import Path

from src.cli.config import EngineeringConfig
from src.engineering.tasks import artifact_name, task_from_exception, task_from_validation_failure
from src.schemas.verdict import VerdictV1


def test_validation_missing_factor_creates_engineer_task(tmp_path):
    verdict = VerdictV1(
        strategy_id="missing_factor",
        recommended_state="rejected",
        blocking_issues=["Factor 'new_alpha' not found in factor pool."],
    )

    task = task_from_validation_failure(
        run_id="run_001",
        strategy_path=tmp_path / "missing_factor.yaml",
        verdict=verdict,
        engineering_config=EngineeringConfig(enabled=True),
    )

    assert task is not None
    assert task.role == "engineer"
    assert task.reason == "unsupported_capability"
    assert task.source_step == "strategy_validation"
    assert "src/engine/**" in task.forbidden_paths
    assert artifact_name(task).startswith("engineering_task_")


def test_validation_plain_invalid_strategy_does_not_create_task(tmp_path):
    verdict = VerdictV1(
        strategy_id="empty",
        recommended_state="rejected",
        blocking_issues=["Strategy has no factors defined (empty factors list)."],
    )

    task = task_from_validation_failure(
        run_id="run_001",
        strategy_path=tmp_path / "empty.yaml",
        verdict=verdict,
        engineering_config=EngineeringConfig(enabled=True),
    )

    assert task is None


def test_exception_in_backtest_creates_bugfix_task(tmp_path):
    task = task_from_exception(
        run_id="run_001",
        strategy_path=Path("strategies/test.yaml"),
        source_step="backtesting",
        error=ValueError("Benchmark NAV is missing for the start of the backtest window"),
        traceback_text="Traceback ...",
        engineering_config=EngineeringConfig(enabled=True),
    )

    assert task is not None
    assert task.role == "bugfix"
    assert task.reason == "code_bug"
    assert "smallest regression fix" in task.instructions


def test_disabled_engineering_creates_no_task(tmp_path):
    verdict = VerdictV1(
        strategy_id="missing_factor",
        recommended_state="rejected",
        blocking_issues=["Factor 'new_alpha' not found in factor pool."],
    )

    task = task_from_validation_failure(
        run_id="run_001",
        strategy_path=tmp_path / "missing_factor.yaml",
        verdict=verdict,
        engineering_config=EngineeringConfig(enabled=False),
    )

    assert task is None
