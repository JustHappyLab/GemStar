"""Tests for gemstar engineering commands."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from src.cli.app import app
from src.schemas.engineering import EngineeringTaskV1


runner = CliRunner()


def _reset_output_format() -> None:
    import src.cli.app as app_mod

    app_mod._output_format = "table"


def test_engineering_run_dry_run_outputs_prompt(tmp_path):
    config_path = tmp_path / "gemstar.yaml"
    config_path.write_text(yaml.dump({
        "artifacts_dir": str(tmp_path / "artifacts"),
        "engineering": {"enabled": False},
    }))
    task_path = tmp_path / "engineering_task.json"
    task_path.write_text(EngineeringTaskV1(
        task_id="task_001",
        run_id="run_001",
        role="engineer",
        reason="unsupported_capability",
        source_step="strategy_validation",
        strategy_id="s1",
        strategy_path="draft.yaml",
        allowed_paths=["src/factors/**"],
        forbidden_paths=["src/engine/**"],
        instructions="Add factor support.",
    ).model_dump_json())
    _reset_output_format()

    result = runner.invoke(app, [
        "engineering", "run", str(task_path),
        "--config", str(config_path),
        "--dry-run",
    ])

    assert result.exit_code == 0, result.output
    assert "Engineering Execution" in result.output
    assert "Engineering task: task_001" in result.output
    artifact = tmp_path / "artifacts" / "run_001" / "engineering_execution_task_001.json"
    assert artifact.exists()
    assert json.loads(artifact.read_text())["status"] == "dry_run"
