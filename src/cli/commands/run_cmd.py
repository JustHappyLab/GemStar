"""gemstar run — execute the daily pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pandas as pd
import typer

from src.cli.output import get_output_format
from src.cli.config import load_config
from src.cli.output import console, emit

_LLM_RUN_ROLES = (
    "macro_analyst",
    "event_scanner",
    "research_analyst",
    "strategy_architect",
    "reviewer",
)
_ENGINEERING_ROLES = ("engineer", "bugfix")


def run_cmd(
    date: str = typer.Option(None, "--date", "-d", help="Trading date (YYYYMMDD). Default: today."),
    llm: bool = typer.Option(False, "--llm", help="Enable LLM ideation stages."),
    strategies: list[str] = typer.Option(None, "--strategy", "-s", help="Strategy YAML path(s)."),
    config_path: str = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Run the daily research pipeline."""
    from src.data.fetcher import (
        init_tushare, fetch_trade_calendar, fetch_stock_basic,
        fetch_index_daily, fetch_daily_all, fetch_daily_basic,
        fetch_fina_indicator, fetch_adj_factor, fetch_disclosure_date,
        attach_disclosure_dates,
    )
    from src.orchestrator.benchmark import BenchmarkResolution, resolve_benchmark_for_universes
    from src.orchestrator.universe import eligible_codes_from_stock_basic, resolve_strategy_universe
    from src.orchestrator.pipeline import run_daily_pipeline
    from src.schemas.strategy import StrategyConfigV1

    config = load_config(Path(config_path) if config_path else None)
    ref_date = date or _today_str()
    run_id = f"{ref_date}-{uuid4().hex[:8]}"

    # --- Resolve strategies before fetching so the data window covers their backtests. ---
    strat_paths = [Path(s) for s in (strategies or config.strategies)]
    if not strat_paths:
        console.print("[yellow]No strategies specified. Use --strategy or set strategies in gemstar.yaml[/yellow]")
        raise typer.Exit(1)
    strat_configs = [StrategyConfigV1.from_yaml(p) for p in strat_paths]

    effective_llm = llm or config.llm.enabled

    console.print(f"[cyan]GemStar run[/cyan] {run_id}")
    console.print(f"  Date: {ref_date}")
    console.print(f"  LLM:  {'on' if effective_llm else 'off'}")

    # --- Fetch data ---
    console.print("[cyan]Fetching data...[/cyan]")
    pro = init_tushare(config.tushare_token or None)
    train_start = _data_start(ref_date, strat_configs, config.data.lookback_years)
    cache_dir = config.data_cache_dir

    resolved_universes = [resolve_strategy_universe(strategy) for strategy in strat_configs]
    benchmark_resolution = resolve_benchmark_for_universes(config.benchmark, resolved_universes)

    trade_cal = fetch_trade_calendar(pro, train_start, ref_date, cache_dir=cache_dir)
    stock_basic = fetch_stock_basic(pro, cache_dir=cache_dir)
    index_daily, benchmark_resolution = _fetch_benchmark_index_daily(
        fetch_index_daily,
        pro,
        benchmark_resolution,
        train_start,
        ref_date,
        cache_dir,
    )
    daily_all = fetch_daily_all(pro, train_start, ref_date, cache_dir=cache_dir)
    daily_basic = fetch_daily_basic(pro, train_start, ref_date, cache_dir=cache_dir)
    adj_factor = fetch_adj_factor(pro, train_start, ref_date, cache_dir=cache_dir)

    code_sets = [
        eligible_codes_from_stock_basic(stock_basic, ref_date, resolution)
        for resolution in resolved_universes
    ]
    codes = sorted(set().union(*(codes for codes in code_sets if codes)))
    if not codes:
        codes = stock_basic["ts_code"].tolist()
    fina_frames = []
    for i, code in enumerate(codes):
        if (i + 1) % 200 == 0:
            console.print(f"  fina: {i + 1}/{len(codes)}")
        df = attach_disclosure_dates(
            fetch_fina_indicator(pro, code, cache_dir=cache_dir),
            fetch_disclosure_date(pro, code, cache_dir=cache_dir),
        )
        if len(df) > 0:
            fina_frames.append(df)
    fina_all = pd.concat(fina_frames, ignore_index=True) if fina_frames else pd.DataFrame()

    # Merge daily OHLCV with basic data (pe_ttm, pb, turnover_rate) for ranker
    daily_merged = daily_all.merge(
        daily_basic[["ts_code", "trade_date", "pe_ttm", "pb", "turnover_rate"]],
        on=["ts_code", "trade_date"],
        how="left",
    )

    data = dict(
        trade_cal=trade_cal, stock_basic=stock_basic, index_daily=index_daily,
        daily=daily_merged, daily_basic=daily_basic, fina_indicator=fina_all, adj_factor=adj_factor,
    )

    # --- Benchmark NAV ---
    bench = index_daily.set_index("trade_date")["close"].sort_index()
    benchmark_nav = bench.ffill()
    benchmark_nav = benchmark_nav / benchmark_nav.iloc[0] * 100000

    # --- Run pipeline ---
    role_overrides = _role_overrides(config)
    console.print(f"[cyan]Running pipeline[/cyan] ({len(strat_paths)} strategies, per-strategy inputs)...")
    console.print(f"  Benchmark: {benchmark_resolution.resolved} ({benchmark_resolution.name})")
    result = run_daily_pipeline(
        run_id=run_id,
        data=data,
        strategies=strat_paths,
        pool_path=Path(config.pool_path),
        reference_date=ref_date,
        benchmark_nav=benchmark_nav,
        benchmark_info=benchmark_resolution.model_dump(),
        index_df=index_daily,
        llm_available=effective_llm,
        role_overrides=role_overrides,
        db_path=config.db_path,
        artifacts_dir=config.artifacts_dir,
        gen_target_count=config.strategy_generation.target_count,
        gen_max_iterations=config.strategy_generation.max_iterations,
        gen_cooldown_seconds=config.strategy_generation.cooldown_seconds,
        auto_build_strategy_inputs=True,
        engineering_config=config.engineering,
    )

    # --- Output ---
    status = result.get("run_status", "unknown")
    console.print(f"\n[{'green' if status == 'completed' else 'red'}]Status: {status}[/]")

    fmt = get_output_format()
    if fmt == "json":
        emit(_json_summary(result), format="json")
    else:
        _print_summary(result)


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


def _role_overrides(config) -> dict[str, dict] | None:
    """Build role provider overrides for run-time LLM stages."""
    overrides = {k: v.model_dump(exclude_none=True) for k, v in config.roles.items()}
    default_provider = (config.llm.provider or "").strip()
    if default_provider:
        for role_name in _LLM_RUN_ROLES:
            overrides.setdefault(role_name, {}).setdefault("provider", default_provider)
    if config.engineering.enabled:
        engineering_provider = (config.engineering.provider or "").strip()
        if engineering_provider:
            for role_name in _ENGINEERING_ROLES:
                overrides.setdefault(role_name, {}).setdefault("provider", engineering_provider)
    return overrides or None


def _fetch_benchmark_index_daily(
    fetch_index_daily,
    pro,
    resolution: "BenchmarkResolution",
    start_date: str,
    end_date: str,
    cache_dir: str,
) -> tuple[pd.DataFrame, "BenchmarkResolution"]:
    from src.orchestrator.benchmark import BenchmarkResolution

    last_df = pd.DataFrame()
    for candidate in resolution.candidates:
        df = fetch_index_daily(pro, candidate, start_date, end_date, cache_dir=cache_dir)
        if df is not None and not df.empty:
            if candidate == resolution.resolved:
                return df, resolution
            return df, BenchmarkResolution(
                requested=resolution.requested,
                resolved=candidate,
                name=f"{resolution.name} fallback",
                reason=f"{resolution.reason} Primary benchmark returned no data; using fallback {candidate}.",
                candidates=resolution.candidates,
            )
        last_df = df if df is not None else pd.DataFrame()
    return last_df, resolution


def _data_start(ref_date: str, strategies: list[StrategyConfigV1], lookback_years: int) -> str:
    """Earliest data date needed for configured strategy backtests."""
    starts = [_offset_years(ref_date, -lookback_years)]
    for strategy in strategies:
        starts.append(_offset_years(strategy.backtest.start, -1))
    return min(starts)


def _offset_years(yyyymmdd: str, years: int) -> str:
    ts = pd.to_datetime(yyyymmdd, format="%Y%m%d") + pd.DateOffset(years=years)
    return ts.strftime("%Y%m%d")


def _json_summary(result: dict) -> dict:
    """Build a JSON-serializable summary from pipeline result."""
    summary: dict = {
        "status": result.get("run_status"),
        "run_id": result.get("run_id"),
    }
    if result.get("benchmark_resolution"):
        summary["benchmark"] = result["benchmark_resolution"]
    if result.get("universe_resolutions"):
        summary["universes"] = result["universe_resolutions"]
    report = result.get("report")
    if report and hasattr(report, "model_dump"):
        summary["report"] = report.model_dump()
    verdicts = result.get("verdicts", [])
    if verdicts:
        summary["verdicts"] = [v.model_dump() for v in verdicts]
    incident = result.get("incident")
    if incident and hasattr(incident, "model_dump"):
        summary["incident"] = incident.model_dump()
    return summary


def _print_summary(result: dict) -> None:
    """Print human-readable summary."""
    report = result.get("report")
    if report and hasattr(report, "leaderboard"):
        console.print("\n[bold]Leaderboard:[/bold]")
        for entry in report.leaderboard:
            console.print(
                f"  #{entry.rank} {entry.name}  "
                f"Sharpe={entry.sharpe:.2f}  CAGR={entry.cagr:.2%}  MaxDD={entry.max_drawdown:.2%}"
            )
    verdicts = result.get("verdicts", [])
    if verdicts:
        console.print("\n[bold]Verdicts:[/bold]")
        for v in verdicts:
            console.print(f"  {v.strategy_id}: {v.recommended_state}")
    incident = result.get("incident")
    if incident:
        console.print(f"\n[red]Incident:[/red] {incident}")
