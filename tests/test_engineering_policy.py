"""Tests for engineering agent path policy checks."""

from __future__ import annotations

import pytest

from src.cli.config import EngineeringConfig
from src.cli.config import GemStarConfig
from src.engineering.policy import validate_changed_paths, validate_engineering_changes


def test_engineer_allows_configured_extension_paths():
    cfg = EngineeringConfig()

    decision = validate_changed_paths(
        role="engineer",
        changed_paths=[
            "src/factors/pool.py",
            "src/schemas/strategy.py",
            "tests/test_factor_pool.py",
        ],
        allowed_paths=cfg.engineer.allowed_paths,
        forbidden_paths=cfg.forbidden_paths,
    )

    assert decision.allowed is True


def test_forbidden_paths_win_over_allowed_paths():
    decision = validate_changed_paths(
        role="engineer",
        changed_paths=["src/engine/backtest.py"],
        allowed_paths=["src/**"],
        forbidden_paths=["src/engine/**"],
    )

    assert decision.allowed is False
    assert decision.violations[0].reason == "forbidden path"
    assert decision.violations[0].pattern == "src/engine/**"


def test_bugfix_rejects_frozen_core_paths():
    cfg = EngineeringConfig()

    decision = validate_changed_paths(
        role="bugfix",
        changed_paths=["src/judge/rules.py"],
        allowed_paths=cfg.bugfix.allowed_paths,
        forbidden_paths=cfg.forbidden_paths,
    )

    assert decision.allowed is False
    assert decision.violations[0].reason == "forbidden path"


def test_bugfix_rejects_paths_outside_allowlist():
    cfg = EngineeringConfig()

    decision = validate_changed_paths(
        role="bugfix",
        changed_paths=["README.md"],
        allowed_paths=cfg.bugfix.allowed_paths,
        forbidden_paths=cfg.forbidden_paths,
    )

    assert decision.allowed is False
    assert decision.violations[0].reason == "not in allowed paths"


def test_absolute_paths_are_normalized_against_repo_root(tmp_path):
    repo_file = tmp_path / "src" / "data" / "fetcher.py"
    repo_file.parent.mkdir(parents=True)
    repo_file.write_text("")
    cfg = EngineeringConfig()

    decision = validate_changed_paths(
        role="bugfix",
        changed_paths=[repo_file],
        allowed_paths=cfg.bugfix.allowed_paths,
        forbidden_paths=cfg.forbidden_paths,
        repo_root=tmp_path,
    )

    assert decision.allowed is True
    assert decision.changed_paths == ("src/data/fetcher.py",)


def test_absolute_paths_outside_repo_are_rejected(tmp_path):
    outside = tmp_path.parent / "outside.py"
    cfg = EngineeringConfig()

    decision = validate_changed_paths(
        role="bugfix",
        changed_paths=[outside],
        allowed_paths=cfg.bugfix.allowed_paths,
        forbidden_paths=cfg.forbidden_paths,
        repo_root=tmp_path,
    )

    assert decision.allowed is False
    assert decision.violations[0].reason == "outside repository"


def test_raise_for_violations_reports_role_and_path():
    decision = validate_changed_paths(
        role="bugfix",
        changed_paths=["src/engine/backtest.py"],
        allowed_paths=["src/**"],
        forbidden_paths=["src/engine/**"],
    )

    with pytest.raises(ValueError, match="bugfix.*src/engine/backtest.py"):
        decision.raise_for_violations()


def test_validate_engineering_changes_uses_config_role_policy():
    cfg = GemStarConfig()

    decision = validate_engineering_changes(
        config=cfg,
        role="bugfix",
        changed_paths=["src/data/cleaner.py"],
    )

    assert decision.allowed is True
