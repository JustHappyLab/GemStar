"""Tests for leaderboard CLI filtering helpers."""

from __future__ import annotations

from typer.testing import CliRunner

from src.cli.app import app
from src.cli.commands import leaderboard_cmd as mod


def test_filter_entries_by_status():
    entries = [
        {"name": "prod", "status": "candidate"},
        {"name": "draft", "status": "rejected"},
    ]

    assert mod._filter_entries(entries, status="candidate") == [
        {"name": "prod", "status": "candidate"}
    ]


def test_filter_entries_by_scope(monkeypatch):
    entries = [
        {"name": "prod", "status": "candidate"},
        {"name": "draft", "status": "rejected"},
    ]
    monkeypatch.setattr(mod, "_production_names", lambda: {"prod"})

    assert mod._filter_entries(entries, scope="production") == [
        {"name": "prod", "status": "candidate"}
    ]
    assert mod._filter_entries(entries, scope="research") == [
        {"name": "draft", "status": "rejected"}
    ]


def test_leaderboard_meta_reports_missing_production_strategies(monkeypatch):
    monkeypatch.setattr(mod, "_production_names", lambda: {"prod", "missing_prod"})

    meta = mod._leaderboard_meta(
        [{"name": "prod", "status": "candidate"}],
        run_id="run-1",
        scope="production",
        status="all",
    )

    assert meta["production_registered"] == 2
    assert meta["production_in_run"] == 1
    assert meta["production_missing"] == ["missing_prod"]


def test_leaderboard_help_hides_status_filter():
    result = CliRunner().invoke(app, ["leaderboard", "--help"])

    assert result.exit_code == 0
    assert "--run" in result.output
    assert "--scope" in result.output
    assert "--status" not in result.output
