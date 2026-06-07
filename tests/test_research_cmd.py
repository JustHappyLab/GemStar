"""Tests for gemstar research command."""

from __future__ import annotations

from typer.testing import CliRunner

from src.cli.app import app
from src.cli.commands import research_cmd as mod


def test_research_cmd_executes_run_with_llm(monkeypatch):
    captured = {}

    def fake_execute_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(mod, "execute_run", fake_execute_run)

    mod.research_cmd(date="20260607", config_path="gemstar.yaml")

    assert captured["date"] == "20260607"
    assert captured["config_path"] == "gemstar.yaml"
    assert captured["llm_available"] is True


def test_research_help_is_small():
    result = CliRunner().invoke(app, ["research", "--help"])

    assert result.exit_code == 0
    assert "--date" in result.output
    assert "--config" in result.output
    assert "--llm" not in result.output
