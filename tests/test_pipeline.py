"""Integration test for the daily pipeline orchestrator.

Tests the full FSM flow with synthetic data, verifying each stage
produces correct artifacts and the pipeline reaches COMPLETED.
"""

import json
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import yaml

from src.orchestrator.pipeline import run_daily_pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_strategy_yaml(tmpdir: str, name: str = "test_strat") -> Path:
    """Create a minimal valid strategy YAML in tmpdir."""
    config = {
        "version": "StrategyConfigV1",
        "name": name,
        "universe": "chinext",
        "timer": {"mode": "full"},
        "factors": [
            {"factor_id": "roe", "weight": 0.5},
            {"factor_id": "momentum_20d", "weight": 0.5},
        ],
        "top_n": 3,
        "rebalance": "daily",
        "backtest": {
            "start": "20220101",
            "end": "20220301",
            "capital": 100000.0,
        },
    }
    path = Path(tmpdir) / f"{name}.yaml"
    path.write_text(yaml.dump(config))
    return path


def _make_pool_json(tmpdir: str) -> Path:
    """Create a minimal valid factor pool JSON."""
    pool = {
        "version": 2,
        "last_updated": "2026-05-03",
        "active": [
            {"name": "roe", "source": "fina_indicator", "status": "active"},
            {"name": "momentum_20d", "source": "daily.close", "status": "active"},
        ],
        "watchlist": [],
        "retired": [],
        "candidates": [],
    }
    path = Path(tmpdir) / "pool.json"
    import json
    path.write_text(json.dumps(pool))
    return path


def _make_synthetic_data(reference_date: str = "20220301") -> dict[str, pd.DataFrame]:
    """Create synthetic DataFrames for the pipeline."""
    dates = pd.bdate_range("20220101", reference_date).strftime("%Y%m%d").tolist()
    codes = ["300001.SZ", "300002.SZ", "300003.SZ", "300004.SZ", "300005.SZ"]

    trade_cal = pd.DataFrame({
        "cal_date": dates,
        "is_open": [1] * len(dates),
    })

    stock_basic = pd.DataFrame({
        "ts_code": codes,
        "name": [f"Stock{i}" for i in range(len(codes))],
        "list_date": ["20200101"] * len(codes),
    })

    daily_rows = []
    for code in codes:
        for d in dates:
            daily_rows.append({
                "ts_code": code,
                "trade_date": d,
                "open": 10.0 + np.random.randn(),
                "high": 11.0 + np.random.randn(),
                "low": 9.0 + np.random.randn(),
                "close": 10.5 + np.random.randn(),
                "pre_close": 10.0 + np.random.randn(),
                "vol": 1000000.0,
                "amount": 10000000.0,
            })
    daily = pd.DataFrame(daily_rows)

    daily_basic = pd.DataFrame({
        "ts_code": codes * len(dates),
        "trade_date": dates * len(codes),
        "pe_ttm": [20.0] * (len(codes) * len(dates)),
        "pb": [2.0] * (len(codes) * len(dates)),
        "turnover_rate": [0.05] * (len(codes) * len(dates)),
    })

    adj_factor = pd.DataFrame({
        "ts_code": codes * len(dates),
        "trade_date": dates * len(codes),
        "adj_factor": [1.0] * (len(codes) * len(dates)),
    })

    fina_indicator = pd.DataFrame({
        "ts_code": codes,
        "ann_date": [reference_date] * len(codes),
        "roe": [15.0 + i for i in range(len(codes))],
        "revenue_yoy": [10.0 + i for i in range(len(codes))],
        "netprofit_yoy": [8.0 + i for i in range(len(codes))],
        "grossprofit_margin": [30.0] * len(codes),
    })

    return {
        "trade_cal": trade_cal,
        "stock_basic": stock_basic,
        "daily": daily,
        "daily_basic": daily_basic,
        "adj_factor": adj_factor,
        "fina_indicator": fina_indicator,
    }


def _make_signals_and_rankings(dates: list[str], codes: list[str]):
    """Create synthetic signals and rankings."""
    signals = pd.DataFrame({
        "trade_date": dates,
        "position": [1.0] * len(dates),
    })
    rankings = {d: codes[:3] for d in dates}
    return signals, rankings


def _make_benchmark_nav(dates: list[str]) -> pd.Series:
    """Create a simple upward-sloping benchmark."""
    values = [1000.0 + i * 0.5 for i in range(len(dates))]
    return pd.Series(values, index=dates)


def _make_ic_df(dates: list[str]) -> pd.DataFrame:
    """Create synthetic IC data."""
    return pd.DataFrame({
        "trade_date": dates,
        "roe": np.random.randn(len(dates)) * 0.03,
        "momentum_20d": np.random.randn(len(dates)) * 0.03,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_full_pipeline_completes():
    """Full pipeline with valid data reaches COMPLETED status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        strategy_path = _make_strategy_yaml(tmpdir)
        pool_path = _make_pool_json(tmpdir)
        data = _make_synthetic_data()
        dates = sorted(data["daily"]["trade_date"].unique().tolist())
        codes = data["stock_basic"]["ts_code"].tolist()
        signals, rankings = _make_signals_and_rankings(dates, codes)
        benchmark_nav = _make_benchmark_nav(dates)
        ic_df = _make_ic_df(dates)

        db_path = str(Path(tmpdir) / "test.db")
        artifacts_dir = str(Path(tmpdir) / "artifacts")

        result = run_daily_pipeline(
            run_id="run_test_001",
            data=data,
            strategies=[strategy_path],
            pool_path=pool_path,
            reference_date="20220301",
            benchmark_nav=benchmark_nav,
            ic_df=ic_df,
            signals=signals,
            rankings=rankings,
            db_path=db_path,
            artifacts_dir=artifacts_dir,
        )

        assert result["run_status"] == "completed", f"Pipeline failed: {result.get('error', 'unknown')}"
        assert result["quality_report"] is not None
        assert result["quality_report"].mode in ("normal", "degraded")
        assert result["factor_health"] is not None
        assert len(result["backtest_results"]) == 1
        assert len(result["verdicts"]) == 1
        assert result["report"] is not None
        assert len(result["markdown"]) > 0


def test_pipeline_aborts_on_missing_core_data():
    """Pipeline aborts when core data is missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        strategy_path = _make_strategy_yaml(tmpdir)
        pool_path = _make_pool_json(tmpdir)
        # Missing 'daily' — core table
        data = _make_synthetic_data()
        del data["daily"]

        dates = pd.bdate_range("20220101", "20220301").strftime("%Y%m%d").tolist()
        benchmark_nav = _make_benchmark_nav(dates)

        result = run_daily_pipeline(
            run_id="run_test_002",
            data=data,
            strategies=[strategy_path],
            pool_path=pool_path,
            reference_date="20220301",
            benchmark_nav=benchmark_nav,
            db_path=str(Path(tmpdir) / "test.db"),
            artifacts_dir=str(Path(tmpdir) / "artifacts"),
        )

        assert result["run_status"] == "failed"
        assert result["quality_report"].mode == "abort"


def test_pipeline_skips_backtest_without_signals():
    """Pipeline completes but skips backtesting when signals are None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        strategy_path = _make_strategy_yaml(tmpdir)
        pool_path = _make_pool_json(tmpdir)
        data = _make_synthetic_data()
        dates = sorted(data["daily"]["trade_date"].unique().tolist())
        benchmark_nav = _make_benchmark_nav(dates)

        result = run_daily_pipeline(
            run_id="run_test_003",
            data=data,
            strategies=[strategy_path],
            pool_path=pool_path,
            reference_date="20220301",
            benchmark_nav=benchmark_nav,
            signals=None,
            rankings=None,
            db_path=str(Path(tmpdir) / "test.db"),
            artifacts_dir=str(Path(tmpdir) / "artifacts"),
        )

        assert result["run_status"] == "completed"
        assert len(result["backtest_results"]) == 0
        assert len(result["verdicts"]) == 0


def test_pipeline_rejects_invalid_strategy():
    """Pipeline validates strategies; rejected ones are skipped for backtest."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Strategy references a factor not in pool
        bad_config = {
            "version": "StrategyConfigV1",
            "name": "bad_strat",
            "universe": "chinext",
            "timer": {"mode": "full"},
            "factors": [
                {"factor_id": "nonexistent_factor", "weight": 1.0},
            ],
            "top_n": 3,
            "rebalance": "daily",
            "backtest": {"start": "20220101", "end": "20220301", "capital": 100000.0},
        }
        bad_path = Path(tmpdir) / "bad.yaml"
        bad_path.write_text(yaml.dump(bad_config))

        pool_path = _make_pool_json(tmpdir)
        data = _make_synthetic_data()
        dates = sorted(data["daily"]["trade_date"].unique().tolist())
        codes = data["stock_basic"]["ts_code"].tolist()
        signals, rankings = _make_signals_and_rankings(dates, codes)
        benchmark_nav = _make_benchmark_nav(dates)

        result = run_daily_pipeline(
            run_id="run_test_004",
            data=data,
            strategies=[bad_path],
            pool_path=pool_path,
            reference_date="20220301",
            benchmark_nav=benchmark_nav,
            signals=signals,
            rankings=rankings,
            db_path=str(Path(tmpdir) / "test.db"),
            artifacts_dir=str(Path(tmpdir) / "artifacts"),
        )

        # Pipeline completes, but no backtests run
        assert result["run_status"] == "completed"
        assert len(result["backtest_results"]) == 0


def _make_index_df() -> pd.DataFrame:
    """Create a simple upward-sloping ChiNext index DataFrame."""
    dates = pd.bdate_range("20220101", "20220301").strftime("%Y%m%d").tolist()
    return pd.DataFrame({
        "trade_date": dates,
        "close": [1000.0 + i * 2 for i in range(len(dates))],
        "open": [999.0 + i * 2 for i in range(len(dates))],
        "high": [1001.0 + i * 2 for i in range(len(dates))],
        "low": [998.0 + i * 2 for i in range(len(dates))],
        "vol": [50000000.0] * len(dates),
    })


def _make_llm_response(text: str) -> SimpleNamespace:
    """Build a fake Anthropic API response."""
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


def test_pipeline_runs_strategy_ideation_with_llm():
    """Pipeline runs LLM ideation when llm_available=True and index_df is provided."""
    with tempfile.TemporaryDirectory() as tmpdir:
        strategy_path = _make_strategy_yaml(tmpdir)
        pool_path = _make_pool_json(tmpdir)
        data = _make_synthetic_data()
        dates = sorted(data["daily"]["trade_date"].unique().tolist())
        codes = data["stock_basic"]["ts_code"].tolist()
        signals, rankings = _make_signals_and_rankings(dates, codes)
        benchmark_nav = _make_benchmark_nav(dates)
        ic_df = _make_ic_df(dates)
        index_df = _make_index_df()

        regime_json = json.dumps({
            "version": "MarketRegimeV1",
            "as_of_date": "2022-03-01",
            "regime": "bullish",
            "confidence": 0.8,
            "key_drivers": ["成交量放大"],
            "style_bias": "成长",
        })
        events_json = json.dumps([{
            "version": "SignalEventV1",
            "event_date": "2022-03-01",
            "event_id": "evt_001",
            "event_type": "earnings_surprise",
            "severity": "medium",
            "summary": "某公司利润超预期",
            "affected_sectors": [],
            "affected_symbols": [],
            "source_refs": [],
            "confidence": 0.7,
            "recommended_next_action": "检查持仓",
        }])
        tickets_json = json.dumps([{
            "version": "ResearchTicketV1",
            "ticket_id": "ticket_001",
            "created_date": "2022-03-01",
            "ticket_type": "weight_rebalance",
            "hypothesis": "提升动量因子权重",
            "rationale": "牛市环境",
            "affected_factors": ["momentum_20d"],
            "affected_sectors": [],
            "confidence": 0.7,
            "source_regime": "bullish",
            "source_events": ["evt_001"],
            "status": "draft",
        }])

        call_count = 0
        def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            responses = [regime_json, events_json, tickets_json]
            idx = min(call_count - 1, len(responses) - 1)
            return _make_llm_response(responses[idx])

        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.side_effect = _side_effect

            result = run_daily_pipeline(
                run_id="run_test_005",
                data=data,
                strategies=[strategy_path],
                pool_path=pool_path,
                reference_date="20220301",
                benchmark_nav=benchmark_nav,
                ic_df=ic_df,
                signals=signals,
                rankings=rankings,
                index_df=index_df,
                llm_available=True,
                db_path=str(Path(tmpdir) / "test.db"),
                artifacts_dir=str(Path(tmpdir) / "artifacts"),
            )

        assert result["run_status"] == "completed"
        assert result["regime"] is not None
        assert result["regime"].regime == "bullish"
        assert len(result["events"]) == 1
        assert result["events"][0].event_id == "evt_001"
        assert len(result["tickets"]) == 1
        assert result["tickets"][0].ticket_id == "ticket_001"


def test_pipeline_runs_reviewer_with_llm():
    """Pipeline runs Reviewer LLM when llm_available=True and verdicts exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        strategy_path = _make_strategy_yaml(tmpdir)
        pool_path = _make_pool_json(tmpdir)
        data = _make_synthetic_data()
        dates = sorted(data["daily"]["trade_date"].unique().tolist())
        codes = data["stock_basic"]["ts_code"].tolist()
        signals, rankings = _make_signals_and_rankings(dates, codes)
        benchmark_nav = _make_benchmark_nav(dates)
        ic_df = _make_ic_df(dates)
        index_df = _make_index_df()

        # --- LLM responses for ideation (4 calls) + review (1 call) ---
        regime_json = json.dumps({
            "version": "MarketRegimeV1",
            "as_of_date": "2022-03-01",
            "regime": "bullish",
            "confidence": 0.8,
            "key_drivers": ["成交量放大"],
            "style_bias": "成长",
        })
        events_json = json.dumps([{
            "version": "SignalEventV1",
            "event_date": "2022-03-01",
            "event_id": "evt_001",
            "event_type": "earnings_surprise",
            "severity": "medium",
            "summary": "某公司利润超预期",
            "affected_sectors": [],
            "affected_symbols": [],
            "source_refs": [],
            "confidence": 0.7,
            "recommended_next_action": "检查持仓",
        }])
        tickets_json = json.dumps([{
            "version": "ResearchTicketV1",
            "ticket_id": "ticket_001",
            "created_date": "2022-03-01",
            "ticket_type": "weight_rebalance",
            "hypothesis": "提升动量因子权重",
            "rationale": "牛市环境",
            "affected_factors": ["momentum_20d"],
            "affected_sectors": [],
            "confidence": 0.7,
            "source_regime": "bullish",
            "source_events": ["evt_001"],
            "status": "draft",
        }])
        # MacroAnalyst may also produce a draft call, but we handle that
        # generically via the side_effect index.  Call 4 = StrategyArchitect
        # (returns a YAML-like string that gets saved to disk).
        architect_yaml = (
            "version: StrategyConfigV1\n"
            "name: llm_strat\n"
            "universe: chinext\n"
            "timer: {mode: full}\n"
            "factors:\n"
            "  - {factor_id: momentum_20d, weight: 1.0}\n"
            "top_n: 3\n"
            "rebalance: daily\n"
            "backtest: {start: '20220101', end: '20220301', capital: 100000}\n"
        )
        review_json = json.dumps({
            "version": "ReviewNotesV1",
            "strategy_id": "test_strat",
            "run_id": "run_test_006",
            "verdict_summary": "candidate — 全部硬门通过",
            "explanation": "该策略通过所有5项硬门检查。",
            "risk_highlights": [],
            "confidence": 0.9,
        })

        call_count = 0

        def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            # Ideation: calls 1-4, Review: call 5+
            ideation_responses = [regime_json, events_json, tickets_json, architect_yaml]
            if call_count <= len(ideation_responses):
                return _make_llm_response(ideation_responses[call_count - 1])
            return _make_llm_response(review_json)

        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.side_effect = _side_effect

            result = run_daily_pipeline(
                run_id="run_test_006",
                data=data,
                strategies=[strategy_path],
                pool_path=pool_path,
                reference_date="20220301",
                benchmark_nav=benchmark_nav,
                ic_df=ic_df,
                signals=signals,
                rankings=rankings,
                index_df=index_df,
                llm_available=True,
                db_path=str(Path(tmpdir) / "test.db"),
                artifacts_dir=str(Path(tmpdir) / "artifacts"),
            )

        assert result["run_status"] == "completed"
        # 2 strategies (original + LLM-drafted) → 2 backtests → 2 verdicts → 2 reviews
        assert len(result["review_notes"]) >= 1
        note = result["review_notes"][0]
        assert note.version == "ReviewNotesV1"
        assert note.strategy_id == "test_strat"
        assert note.confidence == 0.9
        assert "硬门" in note.verdict_summary


def test_pipeline_creates_incident_on_failure():
    """Pipeline creates an IncidentV1 when an exception occurs during execution."""
    from src.ops.classifier import VALID_CATEGORIES

    valid_severities = ("low", "medium", "high", "critical")

    with tempfile.TemporaryDirectory() as tmpdir:
        strategy_path = _make_strategy_yaml(tmpdir)
        pool_path = _make_pool_json(tmpdir)
        data = _make_synthetic_data()
        dates = sorted(data["daily"]["trade_date"].unique().tolist())
        benchmark_nav = _make_benchmark_nav(dates)

        db_path = str(Path(tmpdir) / "test.db")
        artifacts_dir = str(Path(tmpdir) / "artifacts")

        # Force the quality gate to raise so the except block fires
        with patch(
            "src.orchestrator.pipeline.run_data_quality_gate",
            side_effect=RuntimeError("simulated quality gate crash"),
        ):
            result = run_daily_pipeline(
                run_id="run_test_incident",
                data=data,
                strategies=[strategy_path],
                pool_path=pool_path,
                reference_date="20220301",
                benchmark_nav=benchmark_nav,
                db_path=db_path,
                artifacts_dir=artifacts_dir,
            )

        assert result["run_status"] == "failed"
        assert result["incident"] is not None
        assert result["incident"].state == "classified"
        assert result["incident"].category in VALID_CATEGORIES
        assert result["incident"].severity in valid_severities
        assert "simulated quality gate crash" in result["incident"].error_message
