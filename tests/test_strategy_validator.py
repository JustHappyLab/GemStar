"""Tests for StrategyValidator — schema + factor-pool cross-check."""

import tempfile
from pathlib import Path

import yaml

from src.schemas.factor import FactorPoolV1, FactorRegistryEntryV1
from src.schemas.verdict import VerdictV1
from src.strategies.validator import validate_strategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_pool(path: Path, pool: FactorPoolV1) -> None:
    path.write_text(pool.model_dump_json(indent=2))


def _write_strategy_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, default_flow_style=False))


def _make_pool(
    active: list[str] | None = None,
    candidate: list[str] | None = None,
    retired: list[str] | None = None,
    watchlist: list[str] | None = None,
) -> FactorPoolV1:
    """Build a FactorPoolV1 from simple name lists."""
    return FactorPoolV1(
        active=[
            FactorRegistryEntryV1(name=n, status="active")
            for n in (active or [])
        ],
        candidates=[
            FactorRegistryEntryV1(name=n, status="candidate")
            for n in (candidate or [])
        ],
        retired=[
            FactorRegistryEntryV1(name=n, status="retired")
            for n in (retired or [])
        ],
        watchlist=[
            FactorRegistryEntryV1(name=n, status="watchlist")
            for n in (watchlist or [])
        ],
    )


def _base_strategy_data(factors: list[dict] | None = None) -> dict:
    """Return minimal valid strategy YAML dict."""
    if factors is None:
        factors = [{"factor_id": "roe", "weight": 0.5}]
    return {
        "version": "StrategyConfigV1",
        "name": "test_strat",
        "factors": factors,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_valid_strategy_passes() -> None:
    """Valid strategy referencing active factors -> no blocking issues."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = Path(tmpdir) / "pool.json"
        yaml_path = Path(tmpdir) / "strategy.yaml"

        _write_pool(pool_path, _make_pool(active=["roe", "momentum_20d"]))
        _write_strategy_yaml(yaml_path, _base_strategy_data([
            {"factor_id": "roe", "weight": 0.5},
            {"factor_id": "momentum_20d", "weight": 0.5},
        ]))

        verdict = validate_strategy(yaml_path, pool_path, strategy_id="s001")

        assert isinstance(verdict, VerdictV1)
        assert verdict.version == "VerdictV1"
        assert verdict.strategy_id == "s001"
        assert verdict.recommended_state == "candidate"
        assert verdict.blocking_issues == []


def test_candidate_factor_also_passes() -> None:
    """Factors with status 'candidate' should also be accepted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = Path(tmpdir) / "pool.json"
        yaml_path = Path(tmpdir) / "strategy.yaml"

        _write_pool(pool_path, _make_pool(candidate=["new_alpha"]))
        _write_strategy_yaml(yaml_path, _base_strategy_data([
            {"factor_id": "new_alpha", "weight": 1.0},
        ]))

        verdict = validate_strategy(yaml_path, pool_path)

        assert verdict.recommended_state == "candidate"
        assert verdict.blocking_issues == []


def test_nonexistent_factor_fails() -> None:
    """Strategy referencing a factor not in pool -> rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = Path(tmpdir) / "pool.json"
        yaml_path = Path(tmpdir) / "strategy.yaml"

        _write_pool(pool_path, _make_pool(active=["roe"]))
        _write_strategy_yaml(yaml_path, _base_strategy_data([
            {"factor_id": "roe", "weight": 0.5},
            {"factor_id": "nonexistent_factor", "weight": 0.5},
        ]))

        verdict = validate_strategy(yaml_path, pool_path, strategy_id="s_bad")

        assert verdict.recommended_state == "rejected"
        assert len(verdict.blocking_issues) == 1
        assert "nonexistent_factor" in verdict.blocking_issues[0]
        assert "not found" in verdict.blocking_issues[0]


def test_retired_factor_fails() -> None:
    """Strategy referencing a retired factor -> rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = Path(tmpdir) / "pool.json"
        yaml_path = Path(tmpdir) / "strategy.yaml"

        _write_pool(pool_path, _make_pool(
            active=["roe"],
            retired=["old_momentum"],
        ))
        _write_strategy_yaml(yaml_path, _base_strategy_data([
            {"factor_id": "old_momentum", "weight": 1.0},
        ]))

        verdict = validate_strategy(yaml_path, pool_path)

        assert verdict.recommended_state == "rejected"
        assert len(verdict.blocking_issues) == 1
        assert "old_momentum" in verdict.blocking_issues[0]
        assert "retired" in verdict.blocking_issues[0]


def test_watchlist_factor_fails() -> None:
    """Factors in watchlist are neither active nor candidate -> rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = Path(tmpdir) / "pool.json"
        yaml_path = Path(tmpdir) / "strategy.yaml"

        _write_pool(pool_path, _make_pool(watchlist=["risky_factor"]))
        _write_strategy_yaml(yaml_path, _base_strategy_data([
            {"factor_id": "risky_factor", "weight": 1.0},
        ]))

        verdict = validate_strategy(yaml_path, pool_path)

        assert verdict.recommended_state == "rejected"
        assert len(verdict.blocking_issues) == 1
        assert "risky_factor" in verdict.blocking_issues[0]
        assert "watchlist" in verdict.blocking_issues[0]


def test_empty_factors_list_fails() -> None:
    """Strategy with empty factors -> rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = Path(tmpdir) / "pool.json"
        yaml_path = Path(tmpdir) / "strategy.yaml"

        _write_pool(pool_path, _make_pool(active=["roe"]))
        _write_strategy_yaml(yaml_path, _base_strategy_data(factors=[]))

        verdict = validate_strategy(yaml_path, pool_path)

        assert verdict.recommended_state == "rejected"
        assert len(verdict.blocking_issues) == 1
        assert "no factors" in verdict.blocking_issues[0].lower()


def test_invalid_yaml_fails() -> None:
    """Malformed YAML -> rejected with schema error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = Path(tmpdir) / "pool.json"
        yaml_path = Path(tmpdir) / "strategy.yaml"

        _write_pool(pool_path, _make_pool(active=["roe"]))
        # Write invalid YAML (missing required 'name' won't be caught
        # by yaml parser, but invalid version will fail pydantic)
        yaml_path.write_text("version: BadVersion\nname: x\nfactors: []\n")

        verdict = validate_strategy(yaml_path, pool_path)

        assert verdict.recommended_state == "rejected"
        assert len(verdict.blocking_issues) >= 1
        assert "schema validation failed" in verdict.blocking_issues[0].lower()


def test_verdict_is_json_serializable() -> None:
    """Returned VerdictV1 round-trips through JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_path = Path(tmpdir) / "pool.json"
        yaml_path = Path(tmpdir) / "strategy.yaml"

        _write_pool(pool_path, _make_pool(active=["roe"]))
        _write_strategy_yaml(yaml_path, _base_strategy_data())

        verdict = validate_strategy(yaml_path, pool_path, strategy_id="s_rt")

        # Should serialize and deserialize cleanly
        j = verdict.model_dump_json()
        parsed = VerdictV1.model_validate_json(j)
        assert parsed.strategy_id == "s_rt"
        assert parsed.version == "VerdictV1"
        assert parsed.blocking_issues == verdict.blocking_issues


def test_manual_earnings_quality_guard_strategy_is_backtest_eligible() -> None:
    """Manual focus strategy should remain schema/factor-pool eligible."""
    repo_root = Path(__file__).resolve().parent.parent
    verdict = validate_strategy(
        repo_root / "strategies" / "manual_earnings_quality_guard_v1.yaml",
        repo_root / "factors" / "pool.json",
        strategy_id="manual_earnings_quality_guard_v1",
    )

    assert verdict.recommended_state == "candidate"
    assert verdict.blocking_issues == []
