"""Tests for gemstar promote-strategy."""

from __future__ import annotations

import yaml
from typer.testing import CliRunner

from src.cli.app import app


runner = CliRunner()


def _write_strategy(path, name: str = "promoted_alpha") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "version": "StrategyConfigV1",
                "name": name,
                "universe": "chinext",
                "timer": {"mode": "full"},
                "factors": [{"factor_id": "roe", "weight": 1.0}],
                "top_n": 5,
                "rebalance": "daily",
                "backtest": {"start": "20220101", "end": "20260531"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_promote_strategy_from_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gemstar.yaml").write_text("strategies: []\n", encoding="utf-8")
    source = tmp_path / "draft.yaml"
    _write_strategy(source)

    result = runner.invoke(app, ["promote-strategy", "--path", str(source), "--yes"])

    assert result.exit_code == 0, result.output
    target = tmp_path / "strategies" / "promoted_alpha" / "config.yaml"
    registry = tmp_path / "strategies" / "registry.yaml"
    assert target.exists()
    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    assert data["strategies"]["promoted_alpha"]["path"] == "strategies/promoted_alpha/config.yaml"
    assert data["strategies"]["promoted_alpha"]["scope"] == "production"
    assert data["strategies"]["promoted_alpha"]["lifecycle"] == "candidate"


def test_promote_strategy_from_run_draft(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gemstar.yaml").write_text("strategies: []\n", encoding="utf-8")
    draft = tmp_path / "artifacts" / "run-1" / "drafts" / "draft_alpha.yaml"
    _write_strategy(draft, name="draft_alpha")

    result = runner.invoke(
        app,
        ["promote-strategy", "--run", "run-1", "--strategy", "draft_alpha", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "strategies" / "draft_alpha" / "config.yaml").exists()
    registry = yaml.safe_load((tmp_path / "strategies" / "registry.yaml").read_text())
    assert registry["strategies"]["draft_alpha"]["source"] == "promoted"


def test_promote_strategy_writes_to_config_root_when_launched_from_subdir(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    subdir = repo / "nested"
    subdir.mkdir(parents=True)
    (repo / "gemstar.yaml").write_text("strategies: []\n", encoding="utf-8")
    source = repo / "draft.yaml"
    _write_strategy(source, name="subdir_alpha")
    monkeypatch.chdir(subdir)

    result = runner.invoke(app, ["promote-strategy", "--path", str(source), "--yes"])

    assert result.exit_code == 0, result.output
    assert (repo / "strategies" / "subdir_alpha" / "config.yaml").exists()
    assert not (subdir / "strategies").exists()


def test_promote_strategy_help_hides_registry_overrides():
    result = runner.invoke(app, ["promote-strategy", "--help"])

    assert result.exit_code == 0
    assert "--run" in result.output
    assert "--strategy" in result.output
    assert "--path" in result.output
    assert "--yes" in result.output
    assert "--scope" not in result.output
    assert "--lifecycle" not in result.output
    assert "--source" not in result.output
