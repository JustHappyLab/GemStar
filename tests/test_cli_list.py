"""Tests for CLI list commands: roles, strategies, factors."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli.app import app

runner = CliRunner()


def _reset_output_format() -> None:
    """Reset the module-level global to avoid test pollution."""
    import src.cli.app as app_mod

    app_mod._output_format = "table"


# -- roles ------------------------------------------------------------------

def test_roles_table(tmp_path, monkeypatch):
    """gemstar roles lists role names."""
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "analyst.yaml").write_text(
        "name: analyst\nprovider: api\nskills:\n  - research\napproval: false\n"
    )
    (roles_dir / "coder.yaml").write_text(
        "name: coder\nprovider: claude_code\nskills:\n  - write_code\napproval: true\n"
    )
    monkeypatch.chdir(tmp_path)
    _reset_output_format()

    result = runner.invoke(app, ["roles"])
    assert result.exit_code == 0
    # RoleRegistry.list_roles() returns name strings; emit falls back to str()
    assert "analyst" in result.output
    assert "coder" in result.output


def test_roles_json(tmp_path, monkeypatch):
    """gemstar -o json roles outputs a JSON array of role names."""
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "analyst.yaml").write_text(
        "name: analyst\nprovider: api\nskills:\n  - research\napproval: false\n"
    )
    monkeypatch.chdir(tmp_path)
    _reset_output_format()

    result = runner.invoke(app, ["-o", "json", "roles"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    # RoleRegistry.list_roles() returns list of name strings
    assert isinstance(data, list)
    assert "analyst" in data


# -- strategies --------------------------------------------------------------

def test_strategies_table(tmp_path, monkeypatch):
    """gemstar strategies lists strategies in table format."""
    sdir = tmp_path / "strategies" / "alpha_v1"
    sdir.mkdir(parents=True)
    (sdir / "config.yaml").write_text(
        "name: alpha_v1\nuniverse: chinext\ntimer:\n  mode: lstm\nfactors:\n  - factor_id: roe\n    weight: 0.5\ntop_n: 5\n"
    )
    monkeypatch.chdir(tmp_path)
    _reset_output_format()

    result = runner.invoke(app, ["strategies"])
    assert result.exit_code == 0
    assert "alpha_v1" in result.output
    assert "Strategies" in result.output


def test_strategies_json(tmp_path, monkeypatch):
    """gemstar -o json strategies outputs a JSON array."""
    sdir = tmp_path / "strategies" / "alpha_v1"
    sdir.mkdir(parents=True)
    (sdir / "config.yaml").write_text(
        "name: alpha_v1\nuniverse: chinext\ntimer:\n  mode: lstm\nfactors:\n  - factor_id: roe\n    weight: 0.5\ntop_n: 5\n"
    )
    monkeypatch.chdir(tmp_path)
    _reset_output_format()

    result = runner.invoke(app, ["-o", "json", "strategies"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "alpha_v1"


# -- factors -----------------------------------------------------------------

def test_factors_table(tmp_path, monkeypatch):
    """gemstar factors lists factors in table format."""
    pool_file = tmp_path / "pool.json"
    pool_file.write_text(json.dumps({
        "version": 2,
        "active": [
            {"name": "roe", "source": "tushare", "ic_ir": 0.8, "coverage": 0.95}
        ],
        "watchlist": [],
        "candidates": [],
        "retired": [],
    }))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.factors.pool._POOL_PATH", pool_file)
    _reset_output_format()

    result = runner.invoke(app, ["factors"])
    assert result.exit_code == 0
    assert "roe" in result.output
    assert "Factor Pool" in result.output


def test_factors_json(tmp_path, monkeypatch):
    """gemstar -o json factors outputs a JSON array."""
    pool_file = tmp_path / "pool.json"
    pool_file.write_text(json.dumps({
        "version": 2,
        "active": [
            {"name": "roe", "source": "tushare", "ic_ir": 0.8, "coverage": 0.95}
        ],
        "watchlist": [
            {"name": "momentum", "source": "custom", "ic_ir": 0.3, "coverage": 0.80}
        ],
        "candidates": [],
        "retired": [],
    }))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.factors.pool._POOL_PATH", pool_file)
    _reset_output_format()

    result = runner.invoke(app, ["-o", "json", "factors"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    names = [e["name"] for e in data]
    assert "roe" in names
    assert "momentum" in names


def test_factors_no_pool_file(tmp_path, monkeypatch):
    """gemstar factors shows a graceful message when pool.json is missing."""
    missing = tmp_path / "pool.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.factors.pool._POOL_PATH", missing)
    _reset_output_format()

    result = runner.invoke(app, ["factors"])
    assert result.exit_code == 0
    assert "No factor pool found" in result.output


# ---------------------------------------------------------------------------
# Role provider validation
# ---------------------------------------------------------------------------

def test_engineer_role_rejects_api_provider(tmp_path):
    """RoleRegistry raises ValueError when a filesystem role uses 'api' provider."""
    import yaml
    from src.roles.registry import RoleRegistry

    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    roles_dir.joinpath("engineer.yaml").write_text(yaml.dump({
        "name": "engineer",
        "provider": "api",
        "skills": ["write_code"],
    }))

    import pytest
    with pytest.raises(ValueError, match="requires file system access"):
        RoleRegistry(roles_dir=roles_dir, skills_dir=tmp_path / "skills")


def test_override_rejects_api_for_engineer(tmp_path):
    """RoleRegistry raises ValueError when override sets 'api' for a filesystem role."""
    import yaml
    from src.roles.registry import RoleRegistry

    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    roles_dir.joinpath("engineer.yaml").write_text(yaml.dump({
        "name": "engineer",
        "provider": "claude_code",
        "skills": ["write_code"],
    }))

    import pytest
    with pytest.raises(ValueError, match="requires file system access"):
        RoleRegistry(
            roles_dir=roles_dir,
            skills_dir=tmp_path / "skills",
            overrides={"engineer": {"provider": "api"}},
        )


def test_engineer_accepts_cli_providers(tmp_path):
    """RoleRegistry accepts CLI providers for filesystem roles."""
    import yaml
    from src.roles.registry import RoleRegistry

    for provider in ("claude_code", "gemini_cli", "codex_cli"):
        roles_dir = tmp_path / "roles"
        if roles_dir.exists():
            import shutil
            shutil.rmtree(roles_dir)
        roles_dir.mkdir()
        roles_dir.joinpath("engineer.yaml").write_text(yaml.dump({
            "name": "engineer",
            "provider": provider,
            "skills": ["write_code"],
        }))
        # Should not raise
        reg = RoleRegistry(roles_dir=roles_dir, skills_dir=tmp_path / "skills")
        assert reg.get_role("engineer").provider == provider
