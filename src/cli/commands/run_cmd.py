"""gemstar run — execute the daily pipeline."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd
import typer

from src.cli.app import get_output_format
from src.cli.config import load_config
from src.cli.output import console, emit


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
        fetch_fina_indicator, fetch_adj_factor,
    )
    from src.orchestrator.pipeline import run_daily_pipeline
    from src.orchestrator.rankings import build_rankings
    from src.orchestrator.signals import build_signals
    from src.schemas.strategy import StrategyConfigV1

    config = load_config()
    ref_date = date or _today_str()
    run_id = f"{ref_date}-{uuid4().hex[:8]}"

    console.print(f"[cyan]GemStar run[/cyan] {run_id}")
    console.print(f"  Date: {ref_date}")
    console.print(f"  LLM:  {'on' if llm else 'off'}")

    # --- Fetch data ---
    console.print("[cyan]Fetching data...[/cyan]")
    pro = init_tushare(config.tushare_token or None)
    train_start = _train_start(ref_date)

    trade_cal = fetch_trade_calendar(pro, train_start, ref_date)
    stock_basic = fetch_stock_basic(pro)
    index_daily = fetch_index_daily(pro, config.benchmark, train_start, ref_date)
    daily_all = fetch_daily_all(pro, train_start, ref_date)
    daily_basic = fetch_daily_basic(pro, train_start, ref_date)
    adj_factor = fetch_adj_factor(pro, train_start, ref_date)

    codes = stock_basic["ts_code"].tolist()
    fina_frames = []
    for i, code in enumerate(codes):
        if (i + 1) % 200 == 0:
            console.print(f"  fina: {i + 1}/{len(codes)}")
        df = fetch_fina_indicator(pro, code)
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

    # --- Resolve strategies ---
    strat_paths = [Path(s) for s in (strategies or config.strategies)]
    if not strat_paths:
        console.print("[yellow]No strategies specified. Use --strategy or set strategies in gemstar.yaml[/yellow]")
        raise typer.Exit(1)

    # --- Benchmark NAV ---
    bench = index_daily.set_index("trade_date")["close"].sort_index()
    bt_dates = sorted(
        trade_cal[(trade_cal["cal_date"] >= ref_date) & (trade_cal["cal_date"] <= ref_date)]["cal_date"].tolist()
    )
    if not bt_dates:
        bt_dates = sorted(trade_cal[trade_cal["cal_date"] <= ref_date]["cal_date"].tolist())
    benchmark_nav = bench.reindex(bt_dates).ffill()
    benchmark_nav = benchmark_nav / benchmark_nav.iloc[0] * 100000

    # --- Build signals and rankings from first strategy ---
    strat_cfg = StrategyConfigV1.from_yaml(strat_paths[0])
    console.print(f"[cyan]Building signals[/cyan] (LSTM timer, seq_len={strat_cfg.timer.seq_len})...")
    signals = build_signals(index_daily, bt_dates, strat_cfg.timer)
    console.print(f"  {len(signals)} signal dates, position range: {signals['position'].min():.2f}~{signals['position'].max():.2f}")

    console.print(f"[cyan]Building rankings[/cyan] ({len(strat_cfg.factors)} factors, top_n={strat_cfg.top_n})...")
    rankings = build_rankings(
        daily_merged, index_daily, fina_all,
        strat_cfg.factors, strat_cfg.top_n, bt_dates,
    )
    console.print(f"  {len(rankings)} ranking dates")

    # --- Run pipeline ---
    role_overrides = {k: v.model_dump(exclude_none=True) for k, v in config.roles.items()} if config.roles else None
    console.print(f"[cyan]Running pipeline[/cyan] ({len(strat_paths)} strategies)...")
    result = run_daily_pipeline(
        run_id=run_id,
        data=data,
        strategies=strat_paths,
        pool_path=Path(config.pool_path),
        reference_date=ref_date,
        benchmark_nav=benchmark_nav,
        signals=signals,
        rankings=rankings,
        index_df=index_daily,
        llm_available=llm or config.llm.available,
        role_overrides=role_overrides,
        llm_base_url=config.llm.base_url,
        db_path=config.db_path,
        artifacts_dir=config.artifacts_dir,
        gen_target_count=config.strategy_generation.target_count,
        gen_max_iterations=config.strategy_generation.max_iterations,
        gen_cooldown_seconds=config.strategy_generation.cooldown_seconds,
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


def _train_start(ref_date: str) -> str:
    """2 years before ref_date for training data."""
    y = int(ref_date[:4]) - 2
    return f"{y}{ref_date[4:]}"


def _json_summary(result: dict) -> dict:
    """Build a JSON-serializable summary from pipeline result."""
    summary: dict = {
        "status": result.get("run_status"),
        "run_id": result.get("run_id"),
    }
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
