"""Tests for engineering task execution."""

from __future__ import annotations

import json
from pathlib import Path

from src.cli.config import EngineeringConfig, GemStarConfig
from src.engineering.executor import (
    build_execution_prompt,
    execute_engineering_task,
    load_engineering_task,
)
from src.llm.providers.base import AgentResult
from src.schemas.engineering import EngineeringTaskV1


class SequenceTracker:
    def __init__(self, snapshots: list[set[str]]) -> None:
        self._snapshots = snapshots
        self.calls = 0

    def changed_paths(self) -> set[str]:
        idx = min(self.calls, len(self._snapshots) - 1)
        self.calls += 1
        return self._snapshots[idx]


class StubRegistry:
    def __init__(self, output: str = "done", provider: str = "claude_code") -> None:
        self.output = output
        self.provider = provider
        self.calls: list[tuple[str, dict]] = []

    def execute_role(self, name: str, context: dict | None = None) -> AgentResult:
        self.calls.append((name, context or {}))
        return AgentResult(output=self.output, provider=self.provider, duration_seconds=0.1)


def _task() -> EngineeringTaskV1:
    return EngineeringTaskV1(
        task_id="task_001",
        run_id="run_001",
        role="engineer",
        reason="unsupported_capability",
        source_step="strategy_validation",
        strategy_id="s1",
        strategy_path="artifacts/run_001/drafts/s1.yaml",
        error_message="Factor 'new_alpha' not found in factor pool.",
        allowed_paths=["src/factors/**", "tests/**"],
        forbidden_paths=["src/engine/**"],
        instructions="Add factor support.",
    )


def _write_task(tmp_path: Path, task: EngineeringTaskV1 | None = None) -> Path:
    task = task or _task()
    path = tmp_path / "engineering_task.json"
    path.write_text(task.model_dump_json())
    return path


def test_load_engineering_task(tmp_path):
    path = _write_task(tmp_path)

    task = load_engineering_task(path)

    assert task.task_id == "task_001"
    assert task.role == "engineer"


def test_build_execution_prompt_includes_boundaries():
    prompt = build_execution_prompt(_task())

    assert "Allowed paths" in prompt
    assert "src/factors/**" in prompt
    assert "Forbidden paths" in prompt
    assert "src/engine/**" in prompt
    assert "new_alpha" in prompt


def test_execute_task_completed_when_changed_paths_allowed(tmp_path):
    task_path = _write_task(tmp_path)
    config = GemStarConfig(
        artifacts_dir=str(tmp_path / "artifacts"),
        engineering=EngineeringConfig(enabled=True),
    )
    registry = StubRegistry()
    tracker = SequenceTracker([set(), {"src/factors/new_alpha.py", "tests/test_new_alpha.py"}])

    result = execute_engineering_task(
        task_path=task_path,
        config=config,
        registry=registry,
        change_tracker=tracker,
    )

    assert result.status == "completed"
    assert result.changed_paths == ["src/factors/new_alpha.py", "tests/test_new_alpha.py"]
    assert result.violations == []
    assert registry.calls[0][0] == "engineer"
    artifact = tmp_path / "artifacts" / "run_001" / "engineering_execution_task_001.json"
    assert artifact.exists()
    assert json.loads(artifact.read_text())["status"] == "completed"


def test_execute_task_rejected_when_changed_paths_forbidden(tmp_path):
    task_path = _write_task(tmp_path)
    config = GemStarConfig(
        artifacts_dir=str(tmp_path / "artifacts"),
        engineering=EngineeringConfig(enabled=True),
    )
    tracker = SequenceTracker([set(), {"src/engine/backtest.py"}])

    result = execute_engineering_task(
        task_path=task_path,
        config=config,
        registry=StubRegistry(),
        change_tracker=tracker,
    )

    assert result.status == "rejected"
    assert result.violations[0].path == "src/engine/backtest.py"
    assert result.violations[0].reason == "forbidden path"


def test_execute_task_requires_clean_worktree_by_default(tmp_path):
    task_path = _write_task(tmp_path)
    config = GemStarConfig(
        artifacts_dir=str(tmp_path / "artifacts"),
        engineering=EngineeringConfig(enabled=True),
    )
    tracker = SequenceTracker([{"README.md"}])
    registry = StubRegistry()

    result = execute_engineering_task(
        task_path=task_path,
        config=config,
        registry=registry,
        change_tracker=tracker,
    )

    assert result.status == "failed"
    assert "clean git worktree" in result.error_message
    assert registry.calls == []


def test_execute_task_dry_run_does_not_call_registry(tmp_path):
    task_path = _write_task(tmp_path)
    config = GemStarConfig(artifacts_dir=str(tmp_path / "artifacts"))
    registry = StubRegistry()

    result = execute_engineering_task(
        task_path=task_path,
        config=config,
        registry=registry,
        change_tracker=SequenceTracker([{"README.md"}]),
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert "Engineering task: task_001" in result.prompt
    assert registry.calls == []


def test_execute_task_requires_engineering_enabled(tmp_path):
    task_path = _write_task(tmp_path)
    config = GemStarConfig(artifacts_dir=str(tmp_path / "artifacts"))
    registry = StubRegistry()

    result = execute_engineering_task(
        task_path=task_path,
        config=config,
        registry=registry,
        change_tracker=SequenceTracker([set()]),
    )

    assert result.status == "failed"
    assert "engineering.enabled is false" in result.error_message
    assert registry.calls == []
