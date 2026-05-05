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

from src.data.cleaner import apply_adjusted_prices
from src.data_quality.gate import run_data_quality_gate
from src.factors.monitor import analyze_factor_health
from src.judge.rules import evaluate as evaluate_rules
from src.orchestrator.benchmark import describe_benchmark_resolution
from src.llm.adapter import RoleLLMAdapter
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
from src.schemas.strategy import StrategyConfigV1
from src.schemas.verdict import VerdictV1
from src.orchestrator.rankings import build_rankings
from src.orchestrator.signals import build_signals
from src.orchestrator.universe import UniverseResolution, describe_resolution, resolve_strategy_universe
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
    benchmark_info: dict | None = None,
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
    gen_target_count: int = 0,
    gen_max_iterations: int = 10,
    gen_cooldown_seconds: int = 300,
    auto_build_strategy_inputs: bool = False,
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
    auto_build_strategy_inputs : bool
        If True, build signals and rankings separately for each strategy from
        the strategy YAML.  CLI runs use this so each strategy gets its own
        timer/factor/top_n settings; tests and lower-level callers can still
        pass explicit signals/rankings.

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
        "universe_resolutions": [],
        "benchmark_resolution": benchmark_info,
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
            "benchmark": benchmark_info,
        }, base_dir=artifacts_dir, step_id="collecting")
        if benchmark_info:
            write_artifact(
                run_id,
                "benchmark_resolution",
                benchmark_info,
                base_dir=artifacts_dir,
                step_id="collecting",
            )

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
        daily_df = apply_adjusted_prices(
            data.get("daily", pd.DataFrame()),
            data.get("adj_factor"),
        )
        data = dict(data)
        data["daily"] = daily_df
        regime = None
        events = []
        tickets = []

        # --- LLM IDEATION (context gathering, once) ---
        llm_ready = False
        strategy_llm = None
        if llm_available and _reg is not None and index_df is not None and not daily_df.empty:
            try:
                regime = analyze_market_regime(
                    daily_df,
                    index_df,
                    reference_date,
                    RoleLLMAdapter(_reg, "macro_analyst"),
                )
                write_artifact(run_id, "market_regime", regime.model_dump(), base_dir=artifacts_dir, step_id="strategy_ideation")

                events = scan_events(data, reference_date, RoleLLMAdapter(_reg, "event_scanner"))
                write_artifact(run_id, "event_signals", [e.model_dump() for e in events], base_dir=artifacts_dir, step_id="strategy_ideation")

                tickets = generate_tickets(regime, events, factor_health, pool_path, RoleLLMAdapter(_reg, "research_analyst"))
                write_artifact(run_id, "research_tickets", [t.model_dump() for t in tickets], base_dir=artifacts_dir, step_id="strategy_ideation")
                strategy_llm = RoleLLMAdapter(_reg, "strategy_architect")
                llm_ready = True
            except Exception:
                logger.warning("LLM ideation context gathering failed", exc_info=True)

        result["regime"] = regime
        result["events"] = events
        result["tickets"] = tickets

        # --- ITERATIVE STRATEGY GENERATION LOOP ---
        # Pre-existing strategies are always evaluated; LLM generates new ones in a loop
        # until we have enough candidates (gen_target_count) or hit max_iterations.
        import time as _time

        backtest_results: list[BacktestResultV1] = []
        verdicts: list[VerdictV1] = []
        universe_resolutions: list[dict] = []
        universe_notes: list[str] = []
        collected_candidates: list[tuple[Path, BacktestResultV1, VerdictV1]] = []
        can_backtest = signals is not None and rankings is not None
        can_auto_backtest = auto_build_strategy_inputs and index_df is not None and "trade_cal" in data
        use_loop = llm_ready and strategy_llm is not None and gen_target_count > 0 and (can_backtest or can_auto_backtest)

        # First pass: evaluate pre-existing strategies (no loop needed)
        for strat_path in strategies:
            verdict_v = validate_strategy(strat_path, pool_path, strategy_id=strat_path.stem)
            write_artifact(run_id, f"validation_{strat_path.stem}", verdict_v.model_dump(), base_dir=artifacts_dir, step_id="strategy_validation")
            if verdict_v.recommended_state == "rejected":
                continue
            strat_signals, strat_rankings, universe_resolution = _strategy_inputs(
                strat_path=strat_path,
                data=data,
                daily_df=daily_df,
                index_df=index_df,
                reference_date=reference_date,
                explicit_signals=signals,
                explicit_rankings=rankings,
                auto_build=auto_build_strategy_inputs,
            )
            _record_universe_resolution(
                run_id,
                strat_path.stem,
                universe_resolution,
                universe_resolutions,
                universe_notes,
                artifacts_dir,
            )
            if strat_signals is not None and strat_rankings is not None:
                bt = run_strategy_from_yaml(path=strat_path, daily_df=daily_df, signals=strat_signals, rankings=strat_rankings, benchmark_nav=benchmark_nav, ic_df=ic_df)
                bt.run_id = run_id
                backtest_results.append(bt)
                write_artifact(run_id, f"backtest_{strat_path.stem}", bt.model_dump(), base_dir=artifacts_dir, step_id="backtesting")
                j = evaluate_rules(bt, strategy_id=bt.strategy_name)
                j.run_id = run_id
                verdicts.append(j)
                write_artifact(run_id, f"verdict_{bt.strategy_name}", j.model_dump(), base_dir=artifacts_dir, step_id="judging")
                if j.recommended_state == "candidate":
                    collected_candidates.append((strat_path, bt, j))

        # Iterative LLM generation loop
        if use_loop:
            draft_dir = str(Path(artifacts_dir) / run_id / "drafts")
            iteration = 0
            while len(collected_candidates) < gen_target_count and iteration < gen_max_iterations:
                iteration += 1
                logger.info("Strategy generation iteration %d/%d (candidates: %d/%d)",
                            iteration, gen_max_iterations, len(collected_candidates), gen_target_count)
                try:
                    # Generate new tickets for this iteration
                    iter_tickets = generate_tickets(regime, events, factor_health, pool_path, RoleLLMAdapter(_reg, "research_analyst"))
                    for ticket in iter_tickets:
                        if ticket.status != "draft":
                            continue
                        try:
                            draft_path = draft_strategy([ticket], pool_path, reference_date, strategy_llm, output_dir=draft_dir)
                        except Exception:
                            logger.warning("Failed to draft strategy for ticket %s", ticket.ticket_id, exc_info=True)
                            continue

                        # Validate
                        verdict_v = validate_strategy(draft_path, pool_path, strategy_id=draft_path.stem)
                        write_artifact(run_id, f"validation_{draft_path.stem}", verdict_v.model_dump(), base_dir=artifacts_dir, step_id="strategy_validation")
                        if verdict_v.recommended_state == "rejected":
                            continue

                        # Backtest
                        strat_signals, strat_rankings, universe_resolution = _strategy_inputs(
                            strat_path=draft_path,
                            data=data,
                            daily_df=daily_df,
                            index_df=index_df,
                            reference_date=reference_date,
                            explicit_signals=signals,
                            explicit_rankings=rankings,
                            auto_build=auto_build_strategy_inputs,
                        )
                        _record_universe_resolution(
                            run_id,
                            draft_path.stem,
                            universe_resolution,
                            universe_resolutions,
                            universe_notes,
                            artifacts_dir,
                        )
                        if strat_signals is None or strat_rankings is None:
                            continue

                        bt = run_strategy_from_yaml(path=draft_path, daily_df=daily_df, signals=strat_signals, rankings=strat_rankings, benchmark_nav=benchmark_nav, ic_df=ic_df)
                        bt.run_id = run_id
                        backtest_results.append(bt)
                        write_artifact(run_id, f"backtest_{draft_path.stem}", bt.model_dump(), base_dir=artifacts_dir, step_id="backtesting")

                        # Judge
                        j = evaluate_rules(bt, strategy_id=bt.strategy_name)
                        j.run_id = run_id
                        verdicts.append(j)
                        write_artifact(run_id, f"verdict_{bt.strategy_name}", j.model_dump(), base_dir=artifacts_dir, step_id="judging")

                        if j.recommended_state == "candidate":
                            collected_candidates.append((draft_path, bt, j))
                            if len(collected_candidates) >= gen_target_count:
                                break

                except Exception:
                    logger.warning("Iteration %d failed", iteration, exc_info=True)

                # Cooldown between iterations (skip if we already have enough)
                if len(collected_candidates) < gen_target_count and iteration < gen_max_iterations:
                    _time.sleep(gen_cooldown_seconds)

            result["gen_iterations"] = iteration
            result["gen_candidates_found"] = len(collected_candidates)

        result["backtest_results"] = backtest_results
        result["verdicts"] = verdicts
        result["universe_resolutions"] = universe_resolutions

        # --- FSM transitions for validation/backtest/judging phases ---
        fsm.transition("strategy_validation")
        fsm.transition("backtesting")
        fsm.transition("judging")

        # --- REVIEWING (LLM, best-effort) ---
        review_notes: list[ReviewNotesV1] = []
        if llm_available and _reg is not None and verdicts:
            try:
                reviewer_llm = RoleLLMAdapter(_reg, "reviewer")
                for bt_result, verdict in zip(backtest_results, verdicts):
                    try:
                        notes = review_verdict(bt_result, verdict, factor_health, reviewer_llm)
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
            universe_notes=universe_notes,
            benchmark_notes=[describe_benchmark_resolution(benchmark_info)] if benchmark_info else [],
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


def _record_universe_resolution(
    run_id: str,
    strategy_id: str,
    resolution: UniverseResolution | None,
    resolutions: list[dict],
    notes: list[str],
    artifacts_dir: str,
) -> None:
    if resolution is None:
        return
    payload = {"strategy_id": strategy_id, **resolution.model_dump()}
    if payload in resolutions:
        return
    resolutions.append(payload)
    notes.append(describe_resolution(strategy_id, resolution))
    write_artifact(
        run_id,
        f"universe_{strategy_id}",
        payload,
        base_dir=artifacts_dir,
        step_id="strategy_validation",
    )


def _strategy_inputs(
    *,
    strat_path: Path,
    data: dict[str, pd.DataFrame | None],
    daily_df: pd.DataFrame,
    index_df: pd.DataFrame | None,
    reference_date: str,
    explicit_signals: pd.DataFrame | None,
    explicit_rankings: dict[str, list[str]] | None,
    auto_build: bool,
) -> tuple[pd.DataFrame | None, dict[str, list[str]] | None, UniverseResolution | None]:
    """Resolve signals/rankings for one strategy."""
    try:
        config = StrategyConfigV1.from_yaml(strat_path)
        resolution = resolve_strategy_universe(config)
    except Exception:
        return explicit_signals, explicit_rankings, None

    if not auto_build:
        return explicit_signals, explicit_rankings, resolution

    if index_df is None or daily_df.empty:
        return explicit_signals, explicit_rankings, resolution

    trade_dates = _strategy_trade_dates(data, daily_df, config.backtest.start, config.backtest.end, reference_date)
    if not trade_dates:
        return explicit_signals, explicit_rankings, resolution

    fina_df = data.get("fina_indicator")
    if fina_df is None:
        fina_df = pd.DataFrame()

    signals = build_signals(index_df, trade_dates, config.timer)
    rankings = build_rankings(
        daily_df=daily_df,
        index_daily=index_df,
        fina_df=fina_df,
        factors=config.factors,
        top_n=config.top_n,
        trade_dates=trade_dates,
        universe=resolution,
        stock_basic=data.get("stock_basic"),
    )
    return signals, rankings, resolution


def _strategy_trade_dates(
    data: dict[str, pd.DataFrame | None],
    daily_df: pd.DataFrame,
    start: str,
    end: str,
    reference_date: str,
) -> list[str]:
    """Get calendar dates for a strategy, capped at the current reference date."""
    capped_end = min(end, reference_date)
    trade_cal = data.get("trade_cal")
    if trade_cal is not None and not trade_cal.empty:
        col = "cal_date" if "cal_date" in trade_cal.columns else "trade_date"
        dates = trade_cal[col].astype(str).tolist()
    elif "trade_date" in daily_df.columns:
        dates = daily_df["trade_date"].astype(str).unique().tolist()
    else:
        dates = []
    return sorted(d for d in dates if start <= d <= capped_end)
