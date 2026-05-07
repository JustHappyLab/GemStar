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

import atexit
import json
import logging
import os
import signal
import sqlite3
import traceback
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.engineering.executor import execute_engineering_task
from src.data.cleaner import apply_adjusted_prices
from src.data_quality.gate import run_data_quality_gate
from src.engineering.tasks import (
    artifact_name as engineering_task_artifact_name,
    task_from_exception,
    task_from_validation_failure,
)
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
from src.schemas.engineering import EngineeringTaskV1
from src.schemas.engineering import EngineeringExecutionV1
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
    engineering_config: object | None = None,
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
        "engineering_tasks": [],
        "engineering_executions": [],
        "backtest_results": [],
        "verdicts": [],
        "universe_resolutions": [],
        "benchmark_resolution": benchmark_info,
        "report": None,
        "markdown": "",
    }

    # --- Signal / crash handlers ---
    # Guard against orphaned "running" rows when the pipeline process is killed
    # (SIGTERM, SIGINT, or unhandled exception that skips the normal finally path).
    _finalized = False
    _original_handlers: dict[int, object] = {}

    def _panic_finalize() -> None:
        nonlocal _finalized
        if not _finalized:
            _finalized = True
            try:
                if not fsm.is_terminal():
                    fsm.transition("failed")
            except Exception:
                pass
            try:
                finalize_run(run_id, "failed", db_path=db_path, artifacts_dir=artifacts_dir)
            except Exception:
                pass

    def _signal_handler(signum: int, frame: object) -> None:
        _panic_finalize()
        # Restore default and re-raise so the process exits with the right signal
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        _original_handlers[sig] = signal.signal(sig, _signal_handler)
    atexit.register(_panic_finalize)

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

        # --- FACTOR_MINING ---
        from src.factors.pool import load_pool, save_pool
        from src.schemas.factor import FactorPoolV1
        current_pool: FactorPoolV1 = load_pool(pool_path)
        mined_factor_entries: list = []

        daily_df_for_mining = apply_adjusted_prices(
            data.get("daily", pd.DataFrame()),
            data.get("adj_factor"),
        )
        mining_ready = (
            llm_available
            and _reg is not None
            and not daily_df_for_mining.empty
            and "factor_miner" in (_reg.list_roles() if hasattr(_reg, "list_roles") else [])
        )
        if mining_ready:
            try:
                from src.factors.miner import evaluate_proposals, mine_factors, register_accepted

                miner_llm = RoleLLMAdapter(_reg, "factor_miner")
                raw_fields = {c for c in daily_df_for_mining.columns if c not in {"ts_code", "trade_date"}}
                proposals = mine_factors(current_pool, sorted(raw_fields), miner_llm)
                logger.info("FactorMiner proposed %d factors", len(proposals))

                if proposals:
                    evaluations = evaluate_proposals(
                        proposals=proposals,
                        df=daily_df_for_mining.sort_values(["ts_code", "trade_date"]).reset_index(drop=True),
                        raw_fields=raw_fields,
                        daily_df=daily_df_for_mining,
                        min_ic_ir=0.2,
                        min_coverage=0.6,
                        max_redundancy=0.85,
                    )
                    accepted_count = sum(1 for e in evaluations if e.accepted)
                    logger.info("FactorMiner accepted %d/%d proposals", accepted_count, len(evaluations))

                    current_pool, mined_factor_entries = register_accepted(evaluations, current_pool, run_id)
                    if mined_factor_entries:
                        save_pool(current_pool, pool_path)
                        logger.info("Saved %d new candidate factors to pool", len(mined_factor_entries))

                    write_artifact(
                        run_id,
                        "factor_mining_report",
                        {
                            "proposed": len(proposals),
                            "accepted": accepted_count,
                            "entries": [e.model_dump() for e in mined_factor_entries],
                            "evaluations": [
                                {
                                    "name": ev.proposal.name,
                                    "accepted": ev.accepted,
                                    "reason": ev.reason,
                                    "ic_ir": ev.ic_ir,
                                    "coverage": ev.coverage,
                                }
                                for ev in evaluations
                            ],
                        },
                        base_dir=artifacts_dir,
                        step_id="factor_monitoring",
                    )
            except Exception:
                logger.warning("Factor mining failed; continuing without new factors", exc_info=True)

        result["mined_factors"] = mined_factor_entries

        # Build expression_factors list from all current candidates
        expression_factors: list[tuple[str, str]] = [
            (e.name, e.expression)
            for e in current_pool.candidates
            if e.expression
        ]

        # --- STRATEGY_IDEATION ---
        fsm.transition("strategy_ideation")
        daily_df = daily_df_for_mining
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
        engineering_tasks: list[EngineeringTaskV1] = result["engineering_tasks"]
        engineering_executions: list[EngineeringExecutionV1] = result["engineering_executions"]
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
                _record_engineering_task(
                    task_from_validation_failure(
                        run_id=run_id,
                        strategy_path=strat_path,
                        verdict=verdict_v,
                        engineering_config=engineering_config,
                    ),
                    engineering_tasks,
                    engineering_executions,
                    run_id,
                    artifacts_dir,
                    engineering_config,
                    role_overrides,
                )
                continue
            try:
                strat_signals, strat_rankings, universe_resolution = _strategy_inputs(
                    strat_path=strat_path,
                    data=data,
                    daily_df=daily_df,
                    index_df=index_df,
                    reference_date=reference_date,
                    explicit_signals=signals,
                    explicit_rankings=rankings,
                    auto_build=auto_build_strategy_inputs,
                    expression_factors=expression_factors,
                )
            except Exception as exc:
                task = task_from_exception(
                    run_id=run_id,
                    strategy_path=strat_path,
                    source_step="strategy_inputs",
                    error=exc,
                    traceback_text=traceback.format_exc(),
                    engineering_config=engineering_config,
                )
                if task is None:
                    raise
                logger.warning("Strategy input build failed for %s; engineering task created", strat_path, exc_info=True)
                _record_engineering_task(
                    task,
                    engineering_tasks,
                    engineering_executions,
                    run_id,
                    artifacts_dir,
                    engineering_config,
                    role_overrides,
                )
                continue
            _record_universe_resolution(
                run_id,
                strat_path.stem,
                universe_resolution,
                universe_resolutions,
                universe_notes,
                artifacts_dir,
            )
            if strat_signals is not None and strat_rankings is not None:
                try:
                    bt = run_strategy_from_yaml(path=strat_path, daily_df=daily_df, signals=strat_signals, rankings=strat_rankings, benchmark_nav=benchmark_nav, ic_df=ic_df)
                except Exception as exc:
                    task = task_from_exception(
                        run_id=run_id,
                        strategy_path=strat_path,
                        source_step="backtesting",
                        error=exc,
                        traceback_text=traceback.format_exc(),
                        engineering_config=engineering_config,
                    )
                    if task is None:
                        raise
                    logger.warning("Backtest failed for %s; engineering task created", strat_path, exc_info=True)
                    _record_engineering_task(
                        task,
                        engineering_tasks,
                        engineering_executions,
                        run_id,
                        artifacts_dir,
                        engineering_config,
                        role_overrides,
                    )
                    continue
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
                            _record_engineering_task(
                                task_from_validation_failure(
                                    run_id=run_id,
                                    strategy_path=draft_path,
                                    verdict=verdict_v,
                                    engineering_config=engineering_config,
                                ),
                                engineering_tasks,
                                engineering_executions,
                                run_id,
                                artifacts_dir,
                                engineering_config,
                                role_overrides,
                            )
                            continue

                        # Backtest
                        try:
                            strat_signals, strat_rankings, universe_resolution = _strategy_inputs(
                                strat_path=draft_path,
                                data=data,
                                daily_df=daily_df,
                                index_df=index_df,
                                reference_date=reference_date,
                                explicit_signals=signals,
                                explicit_rankings=rankings,
                                auto_build=auto_build_strategy_inputs,
                                expression_factors=expression_factors,
                            )
                        except Exception as exc:
                            task = task_from_exception(
                                run_id=run_id,
                                strategy_path=draft_path,
                                source_step="strategy_inputs",
                                error=exc,
                                traceback_text=traceback.format_exc(),
                                engineering_config=engineering_config,
                            )
                            if task is None:
                                raise
                            logger.warning("Strategy input build failed for %s; engineering task created", draft_path, exc_info=True)
                            _record_engineering_task(
                                task,
                                engineering_tasks,
                                engineering_executions,
                                run_id,
                                artifacts_dir,
                                engineering_config,
                                role_overrides,
                            )
                            continue
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

                        try:
                            bt = run_strategy_from_yaml(path=draft_path, daily_df=daily_df, signals=strat_signals, rankings=strat_rankings, benchmark_nav=benchmark_nav, ic_df=ic_df)
                        except Exception as exc:
                            task = task_from_exception(
                                run_id=run_id,
                                strategy_path=draft_path,
                                source_step="backtesting",
                                error=exc,
                                traceback_text=traceback.format_exc(),
                                engineering_config=engineering_config,
                            )
                            if task is None:
                                raise
                            logger.warning("Backtest failed for %s; engineering task created", draft_path, exc_info=True)
                            _record_engineering_task(
                                task,
                                engineering_tasks,
                                engineering_executions,
                                run_id,
                                artifacts_dir,
                                engineering_config,
                                role_overrides,
                            )
                            continue
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
        prev_lb = _load_previous_leaderboard(run_id, db_path, artifacts_dir)
        leaderboard = _build_leaderboard(backtest_results, verdicts, previous_leaderboard=prev_lb)
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
        _finalized = True
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

        _finalized = True
        finalize_run(run_id, "failed", db_path=db_path, artifacts_dir=artifacts_dir)

    finally:
        for sig, handler in _original_handlers.items():
            signal.signal(sig, handler)


def _record_engineering_task(
    task: EngineeringTaskV1 | None,
    tasks: list[EngineeringTaskV1],
    executions: list[EngineeringExecutionV1],
    run_id: str,
    artifacts_dir: str,
    engineering_config: object | None,
    role_overrides: dict[str, dict] | None,
) -> None:
    if task is None:
        return
    if any(existing.task_id == task.task_id for existing in tasks):
        return
    tasks.append(task)
    task_uri = write_artifact(
        run_id,
        engineering_task_artifact_name(task),
        task.model_dump(),
        base_dir=artifacts_dir,
        step_id="engineering_task_created",
    )
    if not _should_auto_execute_engineering(engineering_config):
        return

    execution_config = SimpleNamespace(
        artifacts_dir=artifacts_dir,
        engineering=engineering_config,
        roles={},
    )
    execution = execute_engineering_task(
        task_path=task_uri,
        config=execution_config,
        registry=RoleRegistry(overrides=role_overrides),
        repo_root=Path.cwd(),
        artifacts_dir=artifacts_dir,
    )
    executions.append(execution)


def _should_auto_execute_engineering(engineering_config: object | None) -> bool:
    return bool(
        engineering_config
        and getattr(engineering_config, "enabled", False)
        and getattr(engineering_config, "auto_execute", False)
    )


def _load_previous_leaderboard(
    current_run_id: str, db_path: str, artifacts_dir: str
) -> list[dict] | None:
    """Load the leaderboard entries from the most recent completed run before this one."""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT run_id FROM runs WHERE status = 'completed' AND run_id != ? "
            "ORDER BY started_at DESC LIMIT 1",
            (current_run_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        prev_run_id = row[0]
        lb_path = Path(artifacts_dir) / prev_run_id / "leaderboard.json"
        if not lb_path.exists():
            return None
        return json.loads(lb_path.read_text()).get("entries", [])
    except Exception:
        return None


def _build_leaderboard(
    backtest_results: list[BacktestResultV1],
    verdicts: list[VerdictV1],
    previous_leaderboard: list[dict] | None = None,
) -> list[ReportStrategyEntry]:
    """Rank strategies by Sharpe and build leaderboard entries.

    All backtested strategies are included regardless of Judge verdict.
    The ``status`` field reflects Judge outcome; ``rank_change`` is computed
    by comparing against the previous run's leaderboard.
    """
    verdict_map = {v.strategy_id: v for v in verdicts}

    # Build previous rank lookup: strategy_name -> rank
    prev_rank_map: dict[str, int] = {}
    if previous_leaderboard:
        for entry in previous_leaderboard:
            prev_rank_map[entry["name"]] = entry["rank"]

    # Sort by Sharpe descending, tie-break by name for determinism
    sorted_results = sorted(
        backtest_results,
        key=lambda r: (-r.metrics.sharpe, r.strategy_name),
    )

    entries: list[ReportStrategyEntry] = []
    for i, bt in enumerate(sorted_results, start=1):
        v = verdict_map.get(bt.strategy_name)
        status = v.recommended_state if v else "rejected"

        # Determine rank change relative to previous leaderboard
        if bt.strategy_name not in prev_rank_map:
            rank_change = "new"
        else:
            prev_rank = prev_rank_map[bt.strategy_name]
            if i < prev_rank:
                rank_change = "up"
            elif i > prev_rank:
                rank_change = "down"
            else:
                rank_change = "stable"

        entries.append(ReportStrategyEntry(
            name=bt.strategy_name,
            rank=i,
            sharpe=bt.metrics.sharpe,
            cagr=bt.metrics.cagr,
            max_drawdown=bt.metrics.max_drawdown,
            alpha=bt.metrics.alpha,
            rank_change=rank_change,
            status=status,
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
    expression_factors: list[tuple[str, str]] | None = None,
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
        expression_factors=expression_factors,
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
