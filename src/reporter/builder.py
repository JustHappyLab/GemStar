"""Daily report builder — deterministic Markdown template rendering.

CALLING SPEC:
    build_report(report_date, run_id, leaderboard, verdicts, factor_health)
    → (DailyReportV1, str).

    Accepts verified inputs from ranker, judge, and factor monitor.
    Produces a DailyReportV1 schema object and a formatted Markdown string.
    No LLM dependency; pure template rendering.

SIDE EFFECTS:
    None.
"""

from datetime import date
from pathlib import Path

from src.schemas.factor import FactorHealthReportV1
from src.schemas.report import DailyReportV1, ReportStrategyEntry
from src.schemas.verdict import VerdictV1

_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "daily_report.txt"
_TEMPLATE_CACHE: str | None = None


def _rank_change_symbol(change: str) -> str:
    """Map rank_change string to a display symbol."""
    return {
        "new": "[NEW]",
        "up": "[UP]",
        "down": "[DN]",
        "stable": "[--]",
    }.get(change, "")


def _build_leaderboard_lines(entries: list[ReportStrategyEntry]) -> str:
    if not entries:
        return "_No strategies on the leaderboard._\n"
    lines = ["| Rank | Strategy | Sharpe | CAGR | MaxDD | Alpha | Trend |", "|---:|:---|---:|---:|---:|---:|:---:|"]
    for e in sorted(entries, key=lambda x: x.rank):
        sym = _rank_change_symbol(e.rank_change)
        lines.append(
            f"| {e.rank} | {e.name} | {e.sharpe:.2f} | {e.cagr:.2%} "
            f"| {e.max_drawdown:.2%} | {e.alpha:.2%} | {sym} |"
        )
    return "\n".join(lines) + "\n"


def _render_markdown(report: DailyReportV1) -> str:
    """Render a DailyReportV1 into a Markdown string using the template."""
    global _TEMPLATE_CACHE
    if _TEMPLATE_CACHE is None:
        _TEMPLATE_CACHE = _TEMPLATE_PATH.read_text()
    template = _TEMPLATE_CACHE

    leaderboard_md = _build_leaderboard_lines(report.leaderboard)

    universe_md = ""
    if report.universe_notes:
        universe_md = "\n".join(f"- {n}" for n in report.universe_notes) + "\n"
    else:
        universe_md = "_No universe resolution recorded._\n"

    benchmark_md = ""
    if report.benchmark_notes:
        benchmark_md = "\n".join(f"- {n}" for n in report.benchmark_notes) + "\n"
    else:
        benchmark_md = "_No benchmark resolution recorded._\n"

    # Build verdicts-like section from signals_summary
    signals_md = ""
    if report.signals_summary:
        signals_md = "\n".join(f"- {s}" for s in report.signals_summary) + "\n"

    factor_md = ""
    if report.factor_notes:
        factor_md = "\n".join(f"- {n}" for n in report.factor_notes) + "\n"

    health_md = ""
    if report.health_notes:
        health_md = "\n".join(f"- {n}" for n in report.health_notes) + "\n"

    return template.format(
        report_date=report.report_date.isoformat(),
        run_id=report.run_id,
        market_summary=report.market_summary,
        universe_notes=universe_md,
        benchmark_notes=benchmark_md,
        leaderboard=leaderboard_md,
        signals_summary=signals_md,
        factor_notes=factor_md,
        health_status=report.health_status,
        health_notes=health_md,
    )


def build_report(
    report_date: date,
    run_id: str,
    leaderboard: list[ReportStrategyEntry],
    verdicts: list[VerdictV1] | None = None,
    factor_health: FactorHealthReportV1 | None = None,
    universe_notes: list[str] | None = None,
    benchmark_notes: list[str] | None = None,
) -> tuple[DailyReportV1, str]:
    """Build a daily report from verified downstream artifacts.

    Parameters
    ----------
    report_date:
        The date this report covers.
    run_id:
        Unique run identifier tying this report to a pipeline execution.
    leaderboard:
        Ranked strategy entries from the ranker.
    verdicts:
        Optional verdicts from the judge module.
    factor_health:
        Optional factor health report from the factor monitor.

    Returns
    -------
    tuple[DailyReportV1, str]
        Structured schema object and formatted Markdown string.
    """
    # Derive factor notes from factor health
    factor_notes: list[str] = []
    health_notes: list[str] = []
    health_status = "ok"

    if factor_health is not None:
        for entry in factor_health.entries:
            if entry.status == "critical":
                factor_notes.append(f"CRITICAL: {entry.factor_name} — {entry.note}")
                health_status = "warning"
            elif entry.status == "degraded":
                factor_notes.append(f"Degraded: {entry.factor_name} — {entry.note}")
                if health_status == "ok":
                    health_status = "warning"
            else:
                factor_notes.append(f"Healthy: {entry.factor_name}")
        if factor_health.watchlist_triggers:
            health_notes.extend(factor_health.watchlist_triggers)

    # Derive signals summary from verdicts
    signals_summary: list[str] = []
    if verdicts:
        for v in verdicts:
            sig = f"{v.strategy_id} → {v.recommended_state}"
            if v.blocking_issues:
                sig += f" (blocked: {', '.join(v.blocking_issues)})"
            signals_summary.append(sig)

    report = DailyReportV1(
        report_date=report_date,
        run_id=run_id,
        leaderboard=leaderboard,
        universe_notes=universe_notes or [],
        benchmark_notes=benchmark_notes or [],
        signals_summary=signals_summary,
        factor_notes=factor_notes,
        health_status=health_status,
        health_notes=health_notes,
    )

    markdown = _render_markdown(report)
    return report, markdown
