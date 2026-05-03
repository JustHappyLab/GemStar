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

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from src.data_quality.gate import run_data_quality_gate
from src.factors.monitor import analyze_factor_health
from src.judge.rules import evaluate as evaluate_rules
from src.llm.adapter import LLMAdapter
from src.orchestrator.artifact_store import write_artifact
from src.reviewer.analysis import review_verdict
from src.schemas.review import ReviewNotesV1
from src.orchestrator.fsm_daily import DailyFSM
from src.orchestrator.run_manifest import finalize_run, start_run
from src.research.analyst import generate_tickets
from src.reporter.builder import build_report, ReportStrategyEntry
from src.roles.registry import RoleRegistry
from src.scanner.event_scanner import scan_events
from src.scanner.macro_analyst import analyze_market_regime
from src.schemas.metrics import BacktestResultV1
from src.schemas.verdict import VerdictV1
from src.strategies.architect import draft_strategy
from src.strategies.runner import run_strategy_from_yaml
from src.strategies.validator import validate_strategy

logger = logging.getLogger(__name__)


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
    index_df: pd.DataFrame | None = None,
    llm_available: bool = False,
    registry: RoleRegistry | None = None,
    role_overrides: dict[str, dict] | None = None,
    llm_base_url: str | None = None,
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
    index_df : pd.DataFrame, optional
        ChiNext index daily data for MacroAnalyst.  If None, LLM ideation is skipped.
    llm_available : bool
        If True, run LLM-based strategy ideation (MacroAnalyst, EventScanner,
        ResearchAnalyst, StrategyArchitect).  Requires ANTHROPIC_API_KEY.
    registry : RoleRegistry, optional
        Role registry for provider dispatch.  If None and llm_available=True,
        a default registry is created.
    role_overrides : dict, optional
        Per-role config overrides from gemstar.yaml (e.g. {"engineer": {"provider": "gemini_cli"}}).
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
    strategies = list(strategies)  # avoid mutating caller's list

    result: dict = {
        "run_id": run_id,
        "run_status": "running",
        "quality_report": None,
        "factor_health": None,
        "regime": None,
        "events": [],
        "tickets": [],
        "review_notes": [],
        "incident": None,
        "backtest_results": [],
        "verdicts": [],
        "report": None,
        "markdown": "",
    }

    # Resolve registry once for all LLM stages
    _reg = registry or (RoleRegistry(overrides=role_overrides, base_url=llm_base_url) if llm_available else None)

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
            fsm.transition("manual_attention")
            result["run_status"] = "manual_attention"
            finalize_run(run_id, "manual_attention", db_path=db_path, artifacts_dir=artifacts_dir)
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

        # --- STRATEGY_IDEATION ---
        fsm.transition("strategy_ideation")
        daily_df = data.get("daily", pd.DataFrame())
        regime = None
        events = []
        tickets = []

        if llm_available and _reg is not None and index_df is not None and not daily_df.empty:
            provider_name = _reg.get_role("macro_analyst").provider
            llm = LLMAdapter(_reg.get_provider(provider_name))
            try:
                regime = analyze_market_regime(daily_df, index_df, reference_date, llm)
                write_artifact(run_id, "market_regime", regime.model_dump(), base_dir=artifacts_dir, step_id="strategy_ideation")

                events = scan_events(data, reference_date, llm)
                write_artifact(run_id, "event_signals", [e.model_dump() for e in events], base_dir=artifacts_dir, step_id="strategy_ideation")

                tickets = generate_tickets(regime, events, factor_health, pool_path, llm)
                write_artifact(run_id, "research_tickets", [t.model_dump() for t in tickets], base_dir=artifacts_dir, step_id="strategy_ideation")

                for ticket in tickets:
                    if ticket.status != "draft":
                        continue
                    try:
                        draft_path = draft_strategy([ticket], pool_path, reference_date, llm, output_dir=str(Path(artifacts_dir) / run_id / "drafts"))
                        strategies.append(draft_path)
                    except Exception:
                        logger.warning("Failed to draft strategy for ticket %s", ticket.ticket_id, exc_info=True)
            except Exception:
                logger.warning("LLM ideation failed, continuing with existing strategies", exc_info=True)

        result["regime"] = regime
        result["events"] = events
        result["tickets"] = tickets

        # --- STRATEGY_VALIDATION ---
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

        # --- REVIEWING (LLM, best-effort) ---
        review_notes: list[ReviewNotesV1] = []
        if llm_available and _reg is not None and verdicts:
            try:
                provider_name = _reg.get_role("reviewer").provider
                llm = LLMAdapter(_reg.get_provider(provider_name))
                for bt_result, verdict in zip(backtest_results, verdicts):
                    try:
                        notes = review_verdict(bt_result, verdict, factor_health, llm)
                        review_notes.append(notes)
                        write_artifact(run_id, f"review_{bt_result.strategy_name}", notes.model_dump(), base_dir=artifacts_dir, step_id="judging")
                    except Exception:
                        logger.warning("Failed to review verdict for %s", bt_result.strategy_name, exc_info=True)
            except Exception:
                logger.warning("LLM review unavailable", exc_info=True)
        result["review_notes"] = review_notes

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

        # Classify and record incident
        from src.ops.classifier import classify_failure
        incident = classify_failure(
            error=exc,
            step_id=fsm.current(),
            context={"module": "pipeline", "run_id": run_id},
            run_id=run_id,
        )
        result["incident"] = incident
        write_artifact(run_id, "incident", incident.model_dump(), base_dir=artifacts_dir, step_id="failed")

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
