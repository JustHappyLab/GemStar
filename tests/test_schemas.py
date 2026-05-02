"""Round-trip JSON serialization for all schemas."""

import json
from datetime import date, datetime

from src.schemas.manifest import (
    ArtifactEntry,
    ArtifactManifestV1,
    RunManifestV1,
    TaskEnvelopeV1,
)
from src.schemas.strategy import (
    BacktestConfigV1,
    FactorWeightV1,
    StrategyConfigV1,
    TimerConfigV1,
)
from src.schemas.factor import (
    FactorHealthEntry,
    FactorHealthReportV1,
    FactorPoolV1,
    FactorRegistryEntryV1,
)
from src.schemas.metrics import (
    BacktestResultV1,
    ICReportEntry,
    ICReportV1,
    MetricsV1,
    SegmentMetricV1,
)
from src.schemas.verdict import HardGateResultV1, VerdictV1
from src.schemas.signal import MarketRegimeV1, SignalEventV1
from src.schemas.report import DailyReportV1, ReportStrategyEntry


def _roundtrip(model):
    j = model.model_dump_json()
    parsed = type(model).model_validate_json(j)
    assert parsed.model_dump() == model.model_dump()
    # verify json.loads also works
    raw = json.loads(j)
    assert isinstance(raw, dict)


def test_manifest_schemas():
    _roundtrip(ArtifactManifestV1(
        run_id="run_001", step_id="collector",
        created_at=datetime(2026, 5, 3, 22, 0, 0),
        inputs=[ArtifactEntry(uri="a.json", sha256="abc")],
        outputs=[ArtifactEntry(uri="b.json", sha256="def")],
    ))
    _roundtrip(RunManifestV1(
        run_id="run_001",
        started_at=datetime(2026, 5, 3, 22, 0, 0),
        finished_at=datetime(2026, 5, 3, 22, 5, 0),
        status="completed",
        step_statuses={"collecting": "started", "reporting": "started"},
    ))
    _roundtrip(TaskEnvelopeV1(
        run_id="run_001", task_id="scanner_001", role="Scanner",
    ))


def test_strategy_schemas():
    _roundtrip(StrategyConfigV1(
        name="test_strat",
        factors=[FactorWeightV1(factor_id="roe", weight=0.15)],
        timer=TimerConfigV1(mode="lstm"),
        backtest=BacktestConfigV1(start="20220101", end="20260101"),
    ))
    _roundtrip(FactorWeightV1(factor_id="momentum_20d", weight=0.20))
    _roundtrip(TimerConfigV1())
    _roundtrip(BacktestConfigV1())


def test_factor_schemas():
    _roundtrip(FactorRegistryEntryV1(name="roe", source="fina_indicator", status="active"))
    _roundtrip(FactorPoolV1(
        active=[FactorRegistryEntryV1(name="roe", status="active")],
        watchlist=[FactorRegistryEntryV1(name="pb_inverse", status="watchlist")],
    ))
    _roundtrip(FactorHealthReportV1(
        run_id="run_001", as_of_date=date(2026, 5, 3),
        entries=[FactorHealthEntry(factor_name="roe")],
    ))


def test_metrics_schemas():
    _roundtrip(MetricsV1(cagr=0.28, sharpe=1.2, max_drawdown=-0.18))
    _roundtrip(SegmentMetricV1(segment="2022", days=243, cagr=0.15, sharpe=0.85))
    _roundtrip(ICReportEntry(factor="roe", IC_mean=0.028, IC_IR=0.45))
    _roundtrip(ICReportV1(factors=[ICReportEntry(factor="roe")]))
    _roundtrip(BacktestResultV1(
        strategy_name="test", capital=100000,
        metrics=MetricsV1(cagr=0.28),
        segments=[SegmentMetricV1(segment="2022")],
    ))


def test_verdict_schemas():
    _roundtrip(VerdictV1(
        strategy_id="test",
        recommended_state="candidate",
        hard_gates=[HardGateResultV1(name="sharpe", passed=True, value=1.2, threshold=1.0)],
        blocking_issues=[],
    ))
    _roundtrip(HardGateResultV1(name="max_dd", passed=False, value=-0.35, threshold=-0.30))


def test_signal_schemas():
    _roundtrip(SignalEventV1(
        event_date=date(2026, 5, 3), event_id="sig_001",
        event_type="earnings_surprise", severity="medium",
        summary="300750.SZ beat by 45%", confidence=0.7,
    ))
    _roundtrip(MarketRegimeV1(as_of_date=date(2026, 5, 3), regime="bullish"))


def test_report_schemas():
    _roundtrip(DailyReportV1(
        report_date=date(2026, 5, 3),
        market_summary="ChiNext up 1.2%",
        leaderboard=[
            ReportStrategyEntry(name="test", rank=1, sharpe=1.35, cagr=0.28),
        ],
    ))


def test_factor_pool_helpers():
    pool = FactorPoolV1(
        active=[FactorRegistryEntryV1(name="roe", status="active")],
        watchlist=[FactorRegistryEntryV1(name="pb_inv", status="watchlist")],
        retired=[FactorRegistryEntryV1(name="old_factor", status="retired")],
        candidates=[FactorRegistryEntryV1(name="new_factor", status="candidate")],
    )
    assert pool.is_registered("roe")
    assert pool.is_registered("pb_inv")
    assert not pool.is_registered("nonexistent")
    assert pool.is_active_or_candidate("roe")
    assert pool.is_active_or_candidate("new_factor")
    assert not pool.is_active_or_candidate("pb_inv")
    assert not pool.is_active_or_candidate("old_factor")
    assert len(pool.all_entries()) == 4
