"""Execute bounded engineering tasks.

CALLING SPEC:
    result = execute_engineering_task(
        task_path=Path("artifacts/run/engineering_task_x.json"),
        config=load_config(),
        repo_root=Path.cwd(),
    )

SIDE EFFECTS:
    May execute an LLM CLI role that edits repository files.  Writes an
    engineering_execution_*.json artifact with the result.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Protocol

from src.engineering.policy import validate_changed_paths
from src.orchestrator.artifact_store import write_artifact
from src.roles.registry import RoleRegistry
from src.schemas.engineering import (
    EngineeringExecutionV1,
    EngineeringPathViolationV1,
    EngineeringTaskV1,
)


class ChangeTracker(Protocol):
    """Protocol for collecting changed repository paths."""

    def changed_paths(self) -> set[str]:
        ...


class GitChangeTracker:
    """Collect changed paths from git status porcelain output."""

    def __init__(self, repo_root: str | Path = ".") -> None:
        self._repo_root = Path(repo_root)

    def changed_paths(self) -> set[str]:
        result = subprocess.run(
            ["git", "-C", str(self._repo_root), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git status failed: {result.stderr.strip()}")
        paths: set[str] = set()
        for line in result.stdout.splitlines():
            paths.update(_parse_porcelain_path(line))
        return paths


def load_engineering_task(path: str | Path) -> EngineeringTaskV1:
    """Load an engineering task artifact from disk."""
    return EngineeringTaskV1.model_validate(json.loads(Path(path).read_text()))


def execute_engineering_task(
    *,
    task_path: str | Path,
    config,
    repo_root: str | Path = ".",
    registry: RoleRegistry | None = None,
    change_tracker: ChangeTracker | None = None,
    allow_dirty: bool = False,
    dry_run: bool = False,
    artifacts_dir: str | Path | None = None,
) -> EngineeringExecutionV1:
    """Execute an engineering task and validate resulting changed paths.

    The default requires a clean worktree before execution.  This protects user
    changes and makes post-run diff validation meaningful.
    """
    task = load_engineering_task(task_path)
    prompt = build_execution_prompt(task)
    started_at = datetime.now()
    tracker = change_tracker or GitChangeTracker(repo_root)
    artifacts_base = Path(artifacts_dir or config.artifacts_dir)

    preexisting = sorted(tracker.changed_paths())
    if not config.engineering.enabled and not dry_run:
        execution = EngineeringExecutionV1(
            task_id=task.task_id,
            run_id=task.run_id,
            role=task.role,
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(),
            prompt=prompt,
            preexisting_changed_paths=preexisting,
            error_message="engineering.enabled is false in gemstar.yaml.",
        )
        _write_execution_artifact(execution, artifacts_base)
        return execution

    if preexisting and not allow_dirty and not dry_run:
        execution = EngineeringExecutionV1(
            task_id=task.task_id,
            run_id=task.run_id,
            role=task.role,
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(),
            prompt=prompt,
            preexisting_changed_paths=preexisting,
            error_message=(
                "Engineering execution requires a clean git worktree. "
                "Commit, stash, or rerun with allow_dirty=True."
            ),
        )
        _write_execution_artifact(execution, artifacts_base)
        return execution

    if dry_run:
        execution = EngineeringExecutionV1(
            task_id=task.task_id,
            run_id=task.run_id,
            role=task.role,
            status="dry_run",
            started_at=started_at,
            finished_at=datetime.now(),
            prompt=prompt,
            preexisting_changed_paths=preexisting,
        )
        _write_execution_artifact(execution, artifacts_base)
        return execution

    active_registry = registry or _make_registry(config)
    try:
        agent_result = active_registry.execute_role(task.role, {"task": prompt})
    except Exception as exc:
        execution = EngineeringExecutionV1(
            task_id=task.task_id,
            run_id=task.run_id,
            role=task.role,
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(),
            prompt=prompt,
            preexisting_changed_paths=preexisting,
            error_message=str(exc),
        )
        _write_execution_artifact(execution, artifacts_base)
        return execution

    after = sorted(tracker.changed_paths())
    paths_to_validate = after if allow_dirty else sorted(set(after) - set(preexisting))
    decision = validate_changed_paths(
        role=task.role,
        changed_paths=paths_to_validate,
        allowed_paths=task.allowed_paths or getattr(config.engineering, task.role).allowed_paths,
        forbidden_paths=task.forbidden_paths or config.engineering.forbidden_paths,
        repo_root=repo_root,
    )
    violations = [
        EngineeringPathViolationV1(path=v.path, reason=v.reason, pattern=v.pattern)
        for v in decision.violations
    ]
    execution = EngineeringExecutionV1(
        task_id=task.task_id,
        run_id=task.run_id,
        role=task.role,
        status="completed" if decision.allowed else "rejected",
        started_at=started_at,
        finished_at=datetime.now(),
        provider=agent_result.provider,
        output=agent_result.output,
        prompt=prompt,
        changed_paths=paths_to_validate,
        preexisting_changed_paths=preexisting,
        violations=violations,
        error_message="" if decision.allowed else "Changed paths violated engineering policy.",
    )
    _write_execution_artifact(execution, artifacts_base)
    return execution


def build_execution_prompt(task: EngineeringTaskV1) -> str:
    """Build the user prompt passed to the engineer/bugfix role."""
    allowed = "\n".join(f"- {p}" for p in task.allowed_paths) or "- <none>"
    forbidden = "\n".join(f"- {p}" for p in task.forbidden_paths) or "- <none>"
    traceback_text = task.traceback or "<none>"
    return f"""Engineering task: {task.task_id}
Run: {task.run_id}
Role: {task.role}
Reason: {task.reason}
Source step: {task.source_step}
Strategy: {task.strategy_id}
Strategy path: {task.strategy_path}

Instructions:
{task.instructions}

Allowed paths:
{allowed}

Forbidden paths:
{forbidden}

Error message:
{task.error_message}

Traceback:
{traceback_text}

Rules:
- Modify only files covered by the allowed paths.
- Do not modify any forbidden path even if it seems necessary.
- If the fix requires a forbidden path, stop and explain why manual attention is required.
- Add or update focused tests for the change.
- Finish with a concise summary and list changed files.
"""


def execution_artifact_name(execution: EngineeringExecutionV1) -> str:
    return f"engineering_execution_{execution.task_id}"


def _make_registry(config) -> RoleRegistry:
    overrides = {k: v.model_dump(exclude_none=True) for k, v in config.roles.items()}
    if config.engineering.enabled:
        provider = config.engineering.provider
        overrides.setdefault("engineer", {}).setdefault("provider", provider)
        overrides.setdefault("bugfix", {}).setdefault("provider", provider)
    return RoleRegistry(overrides=overrides or None)


def _write_execution_artifact(
    execution: EngineeringExecutionV1,
    artifacts_dir: str | Path,
) -> None:
    write_artifact(
        execution.run_id,
        execution_artifact_name(execution),
        execution.model_dump(),
        base_dir=artifacts_dir,
        step_id="engineering_execution",
    )


def _parse_porcelain_path(line: str) -> set[str]:
    if not line:
        return set()
    raw = line[3:] if len(line) > 3 else ""
    raw = raw.strip()
    if not raw:
        return set()
    if " -> " in raw:
        old, new = raw.split(" -> ", 1)
        return {_unquote_status_path(old), _unquote_status_path(new)}
    return {_unquote_status_path(raw)}


def _unquote_status_path(path: str) -> str:
    path = path.strip()
    if len(path) >= 2 and path[0] == path[-1] == '"':
        try:
            return bytes(path[1:-1], "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            return path[1:-1]
    return path
