"""gemstar run CLI command tests.

CALLING SPEC:
    pytest tests/test_cli_run.py

    Verifies CLI argument/config handling without touching Tushare or running
    the full daily pipeline.

SIDE EFFECTS:
    Writes temporary config and strategy YAML files under pytest tmp_path only.
"""

from __future__ import annotations

import pandas as pd
import yaml
from typer.testing import CliRunner

from src.cli.app import app
from src.cli.config import EngineeringConfig, GemStarConfig, LLMConfig, RoleOverride
from src.cli.commands.run_cmd import _role_overrides


runner = CliRunner()


def test_run_keeps_llm_off_unless_explicitly_enabled(tmp_path, monkeypatch):
    """gemstar run is deterministic by default; research owns LLM exploration."""
    strategy_path = tmp_path / "strategy.yaml"
    strategy_path.write_text(yaml.dump({
        "version": "StrategyConfigV1",
        "name": "cli_run_test",
        "universe": "chinext",
        "factors": [{"factor_id": "roe", "weight": 1.0}],
        "backtest": {"start": "20220101", "end": "20220301"},
    }))
    config_path = tmp_path / "gemstar.yaml"
    config_path.write_text(yaml.dump({
        "tushare_token": "test-token",
        "benchmark": "399006.SZ",
        "pool_path": str(tmp_path / "pool.json"),
        "db_path": str(tmp_path / "state.db"),
        "artifacts_dir": str(tmp_path / "artifacts"),
        "data_cache_dir": str(tmp_path / "data"),
        "llm": {"enabled": True},
        "strategy_generation": {
            "target_count": 3,
            "max_iterations": 10,
            "cooldown_seconds": 300,
        },
        "strategies": [str(strategy_path)],
    }))

    stock_basic = pd.DataFrame({
        "ts_code": ["300001.SZ"],
        "name": ["TestStock"],
        "list_date": ["20200101"],
        "delist_date": [None],
    })
    trade_cal = pd.DataFrame({"cal_date": ["20220103", "20220104"]})
    index_daily = pd.DataFrame({
        "trade_date": ["20220103", "20220104"],
        "close": [1000.0, 1001.0],
    })
    daily = pd.DataFrame({
        "ts_code": ["300001.SZ", "300001.SZ"],
        "trade_date": ["20220103", "20220104"],
        "open": [10.0, 10.1],
        "high": [10.2, 10.3],
        "low": [9.9, 10.0],
        "close": [10.1, 10.2],
        "pre_close": [10.0, 10.1],
        "vol": [1000.0, 1000.0],
        "amount": [10000.0, 10000.0],
    })
    daily_basic = pd.DataFrame({
        "ts_code": ["300001.SZ", "300001.SZ"],
        "trade_date": ["20220103", "20220104"],
        "pe_ttm": [20.0, 20.0],
        "pb": [2.0, 2.0],
        "turnover_rate": [1.0, 1.0],
    })
    adj_factor = pd.DataFrame({
        "ts_code": ["300001.SZ", "300001.SZ"],
        "trade_date": ["20220103", "20220104"],
        "adj_factor": [1.0, 1.0],
    })
    fina = pd.DataFrame({
        "ts_code": ["300001.SZ"],
        "ann_date": ["20220101"],
        "end_date": ["20211231"],
        "roe": [10.0],
    })

    monkeypatch.setattr("src.data.fetcher.init_tushare", lambda token=None: object())
    monkeypatch.setattr("src.data.fetcher.fetch_trade_calendar", lambda *args, **kwargs: trade_cal)
    monkeypatch.setattr("src.data.fetcher.fetch_stock_basic", lambda *args, **kwargs: stock_basic)
    monkeypatch.setattr("src.data.fetcher.fetch_index_daily", lambda *args, **kwargs: index_daily)
    monkeypatch.setattr("src.data.fetcher.fetch_daily_all", lambda *args, **kwargs: daily)
    monkeypatch.setattr("src.data.fetcher.fetch_daily_basic", lambda *args, **kwargs: daily_basic)
    monkeypatch.setattr("src.data.fetcher.fetch_adj_factor", lambda *args, **kwargs: adj_factor)
    monkeypatch.setattr("src.data.fetcher.fetch_fina_indicator", lambda *args, **kwargs: fina)
    monkeypatch.setattr("src.data.fetcher.fetch_disclosure_date", lambda *args, **kwargs: pd.DataFrame())

    captured = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return {"run_status": "completed", "run_id": kwargs["run_id"]}

    monkeypatch.setattr("src.orchestrator.pipeline.run_daily_pipeline", fake_pipeline)

    result = runner.invoke(app, ["run", "--config", str(config_path), "--date", "20260503"])

    assert result.exit_code == 0, result.output
    assert "LLM:  off" in result.output
    assert captured["llm_available"] is False
    assert captured["role_overrides"]["macro_analyst"]["provider"] == "claude_code"
    assert captured["engineering_config"].enabled is False


def test_run_help_shows_only_daily_options():
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--date" in result.output
    assert "--config" in result.output
    assert "--llm" not in result.output
    assert "--no-llm" not in result.output
    assert "--strategy" not in result.output


def test_run_rejects_removed_llm_option():
    result = runner.invoke(app, ["run", "--llm"])

    assert result.exit_code != 0


def test_role_overrides_apply_global_llm_provider():
    """llm.provider is the default provider for run-time LLM roles."""
    config = GemStarConfig(llm=LLMConfig(provider="claude_code"))

    overrides = _role_overrides(config)

    assert overrides["macro_analyst"]["provider"] == "claude_code"
    assert overrides["strategy_architect"]["provider"] == "claude_code"
    assert overrides["reviewer"]["provider"] == "claude_code"
    assert "event_scanner" not in overrides
    assert "research_analyst" not in overrides
    assert "factor_miner" not in overrides


def test_role_overrides_keep_explicit_role_model():
    """Per-role overrides in gemstar.yaml keep role-specific model settings."""
    config = GemStarConfig(
        llm=LLMConfig(provider="claude_code"),
        roles={"reviewer": RoleOverride(provider="claude_code", model="opus")},
    )

    overrides = _role_overrides(config)

    assert overrides["macro_analyst"]["provider"] == "claude_code"
    assert overrides["reviewer"]["provider"] == "claude_code"
    assert overrides["reviewer"]["model"] == "opus"


def test_role_overrides_drop_deprecated_local_roles():
    """Old role overrides for local deterministic stages are ignored."""
    config = GemStarConfig(
        llm=LLMConfig(provider="claude_code"),
        roles={
            "event_scanner": RoleOverride(provider="claude_code", model="opus"),
            "research_analyst": RoleOverride(provider="claude_code", model="opus"),
            "factor_miner": RoleOverride(provider="claude_code", model="opus"),
        },
    )

    overrides = _role_overrides(config)

    assert "event_scanner" not in overrides
    assert "research_analyst" not in overrides
    assert "factor_miner" not in overrides


def test_role_overrides_apply_engineering_provider_when_enabled():
    """engineering.provider is the default provider for engineering roles."""
    config = GemStarConfig(
        engineering=EngineeringConfig(enabled=True, provider="claude_code"),
    )

    overrides = _role_overrides(config)

    assert overrides["engineer"]["provider"] == "claude_code"
    assert overrides["bugfix"]["provider"] == "claude_code"


def test_role_overrides_keep_explicit_engineering_role_model():
    """Per-role engineering overrides keep role-specific model settings."""
    config = GemStarConfig(
        engineering=EngineeringConfig(enabled=True, provider="claude_code"),
        roles={"bugfix": RoleOverride(provider="claude_code", model="opus")},
    )

    overrides = _role_overrides(config)

    assert overrides["engineer"]["provider"] == "claude_code"
    assert overrides["bugfix"]["provider"] == "claude_code"
    assert overrides["bugfix"]["model"] == "opus"
