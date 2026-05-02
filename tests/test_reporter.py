"""Tests for src/reporter/builder.py — deterministic path only (no LLM)."""

from datetime import date

from src.reporter.builder import build_report
from src.schemas.factor import FactorHealthEntry, FactorHealthReportV1
from src.schemas.report import DailyReportV1, ReportStrategyEntry
from src.schemas.verdict import VerdictV1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_leaderboard(n: int = 3) -> list[ReportStrategyEntry]:
    return [
        ReportStrategyEntry(
            name=f"strat_{i}",
            rank=i + 1,
            sharpe=1.5 - i * 0.3,
            cagr=0.20 - i * 0.05,
            max_drawdown=-0.10 - i * 0.02,
            alpha=0.05 + i * 0.01,
            rank_change="stable",
        )
        for i in range(n)
    ]


def _make_verdicts() -> list[VerdictV1]:
    return [
        VerdictV1(
            strategy_id="strat_0",
            recommended_state="active",
        ),
        VerdictV1(
            strategy_id="strat_1",
            recommended_state="candidate",
            warnings=["low sample count"],
        ),
        VerdictV1(
            strategy_id="strat_2",
            recommended_state="rejected",
            blocking_issues=["max_drawdown > 20%"],
        ),
    ]


def _make_factor_health() -> FactorHealthReportV1:
    return FactorHealthReportV1(
        run_id="run-test-001",
        as_of_date=date(2026, 5, 3),
        entries=[
            FactorHealthEntry(
                factor_name="momentum_20d",
                ic_mean=0.035,
                status="healthy",
            ),
            FactorHealthEntry(
                factor_name="volatility_60d",
                ic_mean=0.002,
                status="degraded",
                note="IC below threshold",
            ),
            FactorHealthEntry(
                factor_name="turnover_5d",
                ic_mean=-0.001,
                status="critical",
                note="IC negative, coverage low",
            ),
        ],
        watchlist_triggers=["turnover_5d → watchlist"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyLeaderboard:
    def test_produces_valid_report(self):
        report, md = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-empty",
            leaderboard=[],
        )
        assert isinstance(report, DailyReportV1)
        assert report.report_date == date(2026, 5, 3)
        assert report.leaderboard == []
        assert "2026-05-03" in md
        assert "run-empty" in md

    def test_health_defaults_to_ok(self):
        report, _ = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-empty",
            leaderboard=[],
        )
        assert report.health_status == "ok"
        assert report.factor_notes == []


class TestFullLeaderboardWithVerdicts:
    def test_report_contains_strategy_names_and_metrics(self):
        lb = _make_leaderboard()
        verdicts = _make_verdicts()
        report, md = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-full",
            leaderboard=lb,
            verdicts=verdicts,
        )
        # Schema checks
        assert len(report.leaderboard) == 3
        assert report.leaderboard[0].name == "strat_0"
        assert report.leaderboard[0].rank == 1
        assert len(report.signals_summary) == 3

        # Markdown content checks
        assert "strat_0" in md
        assert "strat_1" in md
        assert "strat_2" in md
        assert "active" in md
        assert "rejected" in md

    def test_verdict_signals_summary_populated(self):
        verdicts = _make_verdicts()
        report, _ = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-v",
            leaderboard=_make_leaderboard(1),
            verdicts=verdicts,
        )
        assert any("strat_2" in s and "blocked" in s for s in report.signals_summary)

    def test_empty_verdicts_produces_no_signals(self):
        report, _ = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-nv",
            leaderboard=_make_leaderboard(1),
            verdicts=[],
        )
        assert report.signals_summary == []


class TestFactorHealthNotes:
    def test_factor_health_appears_in_report(self):
        fh = _make_factor_health()
        report, md = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-fh",
            leaderboard=_make_leaderboard(1),
            factor_health=fh,
        )
        assert len(report.factor_notes) == 3
        assert any("CRITICAL" in n for n in report.factor_notes)
        assert any("Degraded" in n for n in report.factor_notes)
        assert any("Healthy" in n for n in report.factor_notes)
        assert report.health_status == "warning"
        assert report.health_notes == ["turnover_5d → watchlist"]
        assert "turnover_5d" in md
        assert "momentum_20d" in md

    def test_all_healthy_factors_keep_ok_status(self):
        fh = FactorHealthReportV1(
            run_id="run-ok",
            as_of_date=date(2026, 5, 3),
            entries=[
                FactorHealthEntry(factor_name="alpha_10d", status="healthy"),
            ],
        )
        report, _ = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-ok",
            leaderboard=[],
            factor_health=fh,
        )
        assert report.health_status == "ok"

    def test_none_factor_health(self):
        report, _ = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-no-fh",
            leaderboard=[],
            factor_health=None,
        )
        assert report.factor_notes == []
        assert report.health_notes == []
        assert report.health_status == "ok"


class TestReportSchema:
    def test_report_version_field(self):
        report, _ = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-v",
            leaderboard=[],
        )
        assert report.version == "DailyReportV1"

    def test_report_roundtrip_json(self):
        report, _ = build_report(
            report_date=date(2026, 5, 3),
            run_id="run-json",
            leaderboard=_make_leaderboard(2),
            verdicts=_make_verdicts()[:1],
        )
        data = report.model_dump()
        restored = DailyReportV1.model_validate(data)
        assert restored.report_date == report.report_date
        assert len(restored.leaderboard) == 2
