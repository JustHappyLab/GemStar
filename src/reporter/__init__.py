"""Reporter module — builds daily report from verified downstream artifacts.

CALLING SPEC:
    build_report(report_date, run_id, leaderboard, verdicts, factor_health)
    returns (DailyReportV1, markdown_str).
    Deterministic template rendering; no LLM calls.

SIDE EFFECTS:
    None.
"""

from src.reporter.builder import build_report

__all__ = ["build_report"]
