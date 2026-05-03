"""Daily pipeline orchestrator — wires all modules via the FSM.

CALLING SPEC:
    run_daily_pipeline(
        run_id=str,
        data=dict[str, pd.DataFrame],
        strategies=list[Path],
        pool_path=Path,
        reference_date=str,
        benchmark_nav=pd.Series,
        ic_df=pd.DataFrame | None,
        signals=pd.DataFrame | None,
        rankings=dict[str, list[str]] | None,
        db_path=str,
    ) -> dict

    Executes the full daily pipeline through the FSM:
      COLLECTING → QUALITY_CHECKING → FACTOR_MONITORING →
      STRATEGY_VALIDATION → BACKTESTING → JUDGING →
      LEADERBOARD_BUILDING → REPORTING → COMPLETED

    Returns a dict with: report (DailyReportV1), markdown (str),
    verdicts (list[VerdictV1]), backtest_results (list[BacktestResultV1]),
    quality_report (DataQualityReport), factor_health (FactorHealthReportV1 | None),
    run_status (str).

SIDE EFFECTS:
    Writes to state.db (via record_step) and artifacts/<run_id>/.
"""

from datetime import date
from pathlib import Path

import pandas as pd

from src.data_quality.gate import DataQualityReport, run_data_quality_gate
from src.factors.monitor import analyze_factor_health
from src.judge.rules import evaluate as evaluate_rules
from src.orchestrator.artifact_store import write_artifact
from src.orchestrator.fsm_daily import DailyFSM
from src.orchestrator.run_manifest import finalize_run, start_run
from src.reporter.builder import build_report
from src.reporter.builder import DailyReportV1, ReportStrategyEntry
from src.schemas.metrics import BacktestResultV1
from src.schemas.verdict import VerdictV1
from src.strategies.runner import run_strategy_from_yaml
from src.strategies.validator import validate_strategy


def run_daily_pipeline(
    run_id: str,
    data: dict[str, pd.DataFrame | None],
    strategies: list[Path],
    pool_path: Path,
    reference_date: str,
    benchmark_nav: pd.Series,
    ic_df: pd.DataFrame | None = None,
    signals: pd.DataFrame | None = None,
    rankings: dict[str, list[str]] | None = None,
    db_path: str = "state.db",
    artifacts_dir: str = "artifacts",
) -> dict:
    """Execute the full daily pipeline.

    Parameters
    ----------
    run_id : str
        Unique identifier for this run.
    data : dict
        Tushare table name → DataFrame mapping (already fetched).
    strategies : list[Path]
        Paths to strategy YAML files to evaluate.
    pool_path : Path
        Path to factors/pool.json.
    reference_date : str
        Current trading date as YYYYMMDD.
    benchmark_nav : pd.Series
        Benchmark NAV series indexed by trade_date.
    ic_df : pd.DataFrame, optional
        Daily IC DataFrame for factor monitoring.
    signals : pd.DataFrame, optional
        Position signal DataFrame (trade_date, position).  If None, backtesting is skipped.
    rankings : dict, optional
        trade_date → ranked stock codes mapping.  If None, backtesting is skipped.
    db_path : str
        Path to SQLite state database.
    artifacts_dir : str
        Base directory for artifacts.

    Returns
    -------
    dict
        Pipeline results including report, markdown, verdicts, etc.
    """
    # --- Initialize ---
    start_run(run_id, db_path=db_path, artifacts_dir=artifacts_dir)
    fsm = DailyFSM(run_id, db_path=db_path)

    result: dict = {
        "run_id": run_id,
        "run_status": "running",
        "quality_report": None,
        "factor_health": None,
        "backtest_results": [],
        "verdicts": [],
        "report": None,
        "markdown": "",
    }

    try:
        # --- COLLECTING ---
        fsm.transition("collecting")
        # Data is already fetched by the caller; just write a manifest.
        write_artifact(run_id, "data_manifest", {
            "tables": list(data.keys()),
            "reference_date": reference_date,
        }, base_dir=artifacts_dir, step_id="collecting")

        # --- QUALITY_CHECKING ---
        fsm.transition("quality_checking")
        dq_report = run_data_quality_gate(data, reference_date)
        result["quality_report"] = dq_report
        write_artifact(run_id, "data_quality_report", dq_report.model_dump(), base_dir=artifacts_dir, step_id="quality_checking")

        if dq_report.mode == "abort":
            fsm.transition("failed")
            result["run_status"] = "failed"
            finalize_run(run_id, "failed", db_path=db_path, artifacts_dir=artifacts_dir)
            return result

        if dq_report.mode == "degraded":
            fsm.transition("degraded")
            # degraded can still report; continue pipeline but skip promotions

        # --- FACTOR_MONITORING ---
        fsm.transition("factor_monitoring")
        factor_health = None
        if ic_df is not None and not ic_df.empty:
            factor_health = analyze_factor_health(
                ic_df=ic_df,
                run_id=run_id,
                as_of_date=date.today(),
            )
            result["factor_health"] = factor_health
            write_artifact(run_id, "factor_health_report", factor_health.model_dump(), base_dir=artifacts_dir, step_id="factor_monitoring")

        # --- STRATEGY_VALIDATION ---
        fsm.transition("strategy_ideation")
        fsm.transition("strategy_validation")

        valid_strategies: list[tuple[Path, VerdictV1]] = []
        for strat_path in strategies:
            verdict = validate_strategy(strat_path, pool_path, strategy_id=strat_path.stem)
            write_artifact(run_id, f"validation_{strat_path.stem}", verdict.model_dump(), base_dir=artifacts_dir, step_id="strategy_validation")
            if verdict.recommended_state != "rejected":
                valid_strategies.append((strat_path, verdict))

        # --- BACKTESTING ---
        fsm.transition("backtesting")
        backtest_results: list[BacktestResultV1] = []
        if signals is not None and rankings is not None:
            for strat_path, _ in valid_strategies:
                bt_result = run_strategy_from_yaml(
                    path=strat_path,
                    daily_df=data.get("daily", pd.DataFrame()),
                    signals=signals,
                    rankings=rankings,
                    benchmark_nav=benchmark_nav,
                    ic_df=ic_df,
                )
                bt_result.run_id = run_id
                backtest_results.append(bt_result)
                write_artifact(run_id, f"backtest_{strat_path.stem}", bt_result.model_dump(), base_dir=artifacts_dir, step_id="backtesting")
        result["backtest_results"] = backtest_results

        # --- JUDGING ---
        fsm.transition("judging")
        verdicts: list[VerdictV1] = []
        for bt_result in backtest_results:
            verdict = evaluate_rules(bt_result, strategy_id=bt_result.strategy_name)
            verdict.run_id = run_id
            verdicts.append(verdict)
            write_artifact(run_id, f"verdict_{bt_result.strategy_name}", verdict.model_dump(), base_dir=artifacts_dir, step_id="judging")
        result["verdicts"] = verdicts

        # --- LEADERBOARD_BUILDING ---
        fsm.transition("leaderboard_building")
        leaderboard = _build_leaderboard(backtest_results, verdicts)
        write_artifact(run_id, "leaderboard", {"entries": [e.model_dump() for e in leaderboard]}, base_dir=artifacts_dir, step_id="leaderboard_building")

        # --- REPORTING ---
        fsm.transition("reporting")
        report, markdown = build_report(
            report_date=date.today(),
            run_id=run_id,
            leaderboard=leaderboard,
            verdicts=verdicts,
            factor_health=factor_health,
        )
        result["report"] = report
        result["markdown"] = markdown
        write_artifact(run_id, "daily_report", report.model_dump(), base_dir=artifacts_dir, step_id="reporting")

        # --- COMPLETED ---
        fsm.transition("completed")
        result["run_status"] = "completed"
        finalize_run(run_id, "completed", db_path=db_path, artifacts_dir=artifacts_dir)

    except Exception as exc:
        if not fsm.is_terminal():
            try:
                fsm.transition("failed")
            except ValueError:
                pass
        result["run_status"] = "failed"
        result["error"] = str(exc)
        finalize_run(run_id, "failed", db_path=db_path, artifacts_dir=artifacts_dir)

    return result


def _build_leaderboard(
    backtest_results: list[BacktestResultV1],
    verdicts: list[VerdictV1],
) -> list[ReportStrategyEntry]:
    """Rank strategies by Sharpe and build leaderboard entries."""
    verdict_map = {v.strategy_id: v for v in verdicts}
    entries: list[ReportStrategyEntry] = []
    for i, bt in enumerate(sorted(backtest_results, key=lambda r: r.metrics.sharpe, reverse=True), start=1):
        v = verdict_map.get(bt.strategy_name)
        rank_change = "new" if v and v.recommended_state == "candidate" else "stable"
        entries.append(ReportStrategyEntry(
            name=bt.strategy_name,
            rank=i,
            sharpe=bt.metrics.sharpe,
            cagr=bt.metrics.cagr,
            max_drawdown=bt.metrics.max_drawdown,
            alpha=bt.metrics.alpha,
            rank_change=rank_change,
        ))
    return entries
