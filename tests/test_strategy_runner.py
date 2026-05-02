"""Tests for the strategy YAML adapter (run_strategy_from_yaml)."""

from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.schemas.metrics import BacktestResultV1, MetricsV1
from src.strategies.runner import (
    _build_metrics,
    _clean_float,
    run_strategy_from_yaml,
)

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

DATES = ["20240101", "20240102", "20240103", "20240104", "20240105"]
STOCKS = ["000001.SZ", "000002.SZ"]


def _make_daily_df() -> pd.DataFrame:
    rows = []
    for d in DATES:
        for s in STOCKS:
            rows.append({
                "ts_code": s,
                "trade_date": d,
                "open": 10.0,
                "close": 10.0,
                "high": 10.5,
                "low": 9.5,
                "pre_close": 10.0,
                "vol": 1_000_000,
            })
    return pd.DataFrame(rows)


def _make_benchmark_nav() -> pd.Series:
    return pd.Series(
        {d: 100_000.0 * (1 + 0.001 * i) for i, d in enumerate(DATES)},
        dtype=float,
    )


STRATEGY_YAML = {
    "version": "StrategyConfigV1",
    "name": "test_runner_strat",
    "hypothesis": "unit test strategy",
    "universe": "chinext",
    "factors": [{"factor_id": "roe", "weight": 0.5}],
    "top_n": 2,
    "rebalance": "daily",
    "backtest": {
        "start": "20240101",
        "end": "20240105",
        "capital": 100_000.0,
        "rf_annual": 0.025,
        "volume_limit_pct": 0.25,
        "cost_multiplier": 1.0,
    },
}


def _write_yaml(tmp_path: Path, overrides: dict | None = None) -> Path:
    data = {**STRATEGY_YAML}
    if overrides:
        data["backtest"] = {**data["backtest"], **overrides}
    p = tmp_path / "strat.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True))
    return p


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestCleanFloat:
    def test_normal_value(self):
        assert _clean_float(1.5) == 1.5

    def test_nan_returns_zero(self):
        assert _clean_float(float("nan")) == 0.0

    def test_inf_returns_zero(self):
        assert _clean_float(float("inf")) == 0.0

    def test_none_returns_zero(self):
        assert _clean_float(None) == 0.0


class TestBuildMetrics:
    def test_maps_all_fields(self):
        raw = {
            "cagr": 0.15,
            "sharpe": 1.2,
            "max_drawdown": -0.10,
            "peak_idx": "20240103",
            "trough_idx": "20240104",
            "calmar": 1.5,
            "win_rate": 0.6,
            "profit_factor": 2.0,
            "completed_trades": 5,
            "annual_turnover_ratio": 10.0,
            "alpha": 0.05,
            "longest_drawdown_days": 3,
        }
        m = _build_metrics(raw)
        assert isinstance(m, MetricsV1)
        assert m.cagr == 0.15
        assert m.completed_trades == 5
        assert m.peak_idx == "20240103"

    def test_sanitizes_nan(self):
        raw = {
            "cagr": 0.15,
            "sharpe": float("nan"),
            "max_drawdown": -0.10,
            "peak_idx": 0,
            "trough_idx": 1,
            "calmar": float("inf"),
            "win_rate": float("nan"),
            "profit_factor": float("nan"),
            "completed_trades": 0,
            "annual_turnover_ratio": float("nan"),
            "alpha": 0.05,
            "longest_drawdown_days": 0,
        }
        m = _build_metrics(raw)
        assert m.sharpe == 0.0
        assert m.calmar == 0.0
        assert m.win_rate == 0.0


# ---------------------------------------------------------------------------
# Integration tests: run_strategy_from_yaml
# ---------------------------------------------------------------------------


class TestRunStrategyFromYaml:
    def test_returns_backtest_result_v1(self, tmp_path):
        yaml_path = _write_yaml(tmp_path)
        result = run_strategy_from_yaml(
            yaml_path,
            daily_df=_make_daily_df(),
            signals=pd.DataFrame({"trade_date": DATES, "position": [1.0] * 5}),
            rankings={d: STOCKS for d in DATES},
            benchmark_nav=_make_benchmark_nav(),
        )
        assert isinstance(result, BacktestResultV1)
        assert result.version == "BacktestResultV1"
        assert result.strategy_name == "test_runner_strat"
        assert result.backtest_period == "20240101~20240105"
        assert result.capital == 100_000.0

    def test_metrics_are_sane(self, tmp_path):
        yaml_path = _write_yaml(tmp_path)
        result = run_strategy_from_yaml(
            yaml_path,
            daily_df=_make_daily_df(),
            signals=pd.DataFrame({"trade_date": DATES, "position": [1.0] * 5}),
            rankings={d: STOCKS for d in DATES},
            benchmark_nav=_make_benchmark_nav(),
        )
        m = result.metrics
        assert m.completed_trades >= 0
        assert m.annual_turnover_ratio >= 0
        assert isinstance(m.sharpe, float)
        assert isinstance(m.cagr, float)

    def test_segments_populated(self, tmp_path):
        yaml_path = _write_yaml(tmp_path)
        result = run_strategy_from_yaml(
            yaml_path,
            daily_df=_make_daily_df(),
            signals=pd.DataFrame({"trade_date": DATES, "position": [1.0] * 5}),
            rankings={d: STOCKS for d in DATES},
            benchmark_nav=_make_benchmark_nav(),
        )
        assert len(result.segments) >= 1
        seg = result.segments[0]
        assert seg.days > 0
        assert isinstance(seg.cagr, float)

    def test_zero_position_no_crash(self, tmp_path):
        yaml_path = _write_yaml(tmp_path)
        result = run_strategy_from_yaml(
            yaml_path,
            daily_df=_make_daily_df(),
            signals=pd.DataFrame({"trade_date": DATES, "position": [0.0] * 5}),
            rankings={d: STOCKS for d in DATES},
            benchmark_nav=_make_benchmark_nav(),
        )
        assert isinstance(result, BacktestResultV1)
        assert result.metrics.completed_trades == 0

    def test_with_ic_df(self, tmp_path):
        yaml_path = _write_yaml(tmp_path)
        ic_df = pd.DataFrame({
            "trade_date": DATES,
            "roe": [0.02, -0.01, 0.03, 0.01, -0.005],
        })
        result = run_strategy_from_yaml(
            yaml_path,
            daily_df=_make_daily_df(),
            signals=pd.DataFrame({"trade_date": DATES, "position": [1.0] * 5}),
            rankings={d: STOCKS for d in DATES},
            benchmark_nav=_make_benchmark_nav(),
            ic_df=ic_df,
        )
        assert result.ic_report is not None
        assert len(result.ic_report.factors) == 1
        entry = result.ic_report.factors[0]
        assert entry.factor == "roe"
        assert isinstance(entry.IC_mean, float)

    def test_without_ic_df(self, tmp_path):
        yaml_path = _write_yaml(tmp_path)
        result = run_strategy_from_yaml(
            yaml_path,
            daily_df=_make_daily_df(),
            signals=pd.DataFrame({"trade_date": DATES, "position": [1.0] * 5}),
            rankings={d: STOCKS for d in DATES},
            benchmark_nav=_make_benchmark_nav(),
        )
        assert result.ic_report is None

    def test_json_roundtrip(self, tmp_path):
        yaml_path = _write_yaml(tmp_path)
        result = run_strategy_from_yaml(
            yaml_path,
            daily_df=_make_daily_df(),
            signals=pd.DataFrame({"trade_date": DATES, "position": [1.0] * 5}),
            rankings={d: STOCKS for d in DATES},
            benchmark_nav=_make_benchmark_nav(),
        )
        j = result.model_dump_json()
        parsed = BacktestResultV1.model_validate_json(j)
        assert parsed.model_dump() == result.model_dump()
