"""gemstar fetch — pull/update Tushare data."""

from __future__ import annotations

from pathlib import Path

import typer
import pandas as pd

from src.cli.output import get_output_format
from src.cli.config import load_config
from src.cli.output import console, emit


def fetch_cmd(
    start: str = typer.Option(None, help="Start date (YYYYMMDD)."),
    end: str = typer.Option(None, help="End date (YYYYMMDD)."),
    config_path: str = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Fetch and cache Tushare data."""
    from src.data.fetcher import (
        init_tushare, fetch_trade_calendar, fetch_stock_basic,
        fetch_index_daily, fetch_daily_all, fetch_daily_basic,
        fetch_fina_indicator, fetch_adj_factor, fetch_disclosure_date,
        attach_disclosure_dates,
    )
    from src.orchestrator.benchmark import resolve_benchmark_for_strategies
    from src.schemas.strategy import StrategyConfigV1

    fmt = get_output_format()
    config = load_config(Path(config_path) if config_path else None)
    pro = init_tushare(config.tushare_token or None)
    cache_dir = config.data_cache_dir

    if not start or not end:
        from datetime import date, timedelta
        end = end or date.today().strftime("%Y%m%d")
        start = start or (date.today() - timedelta(days=730)).strftime("%Y%m%d")

    console.print(f"[cyan]Fetching data[/cyan] {start} ~ {end} ...")

    tables = {}

    console.print("  Trade calendar...")
    tables["trade_cal"] = fetch_trade_calendar(pro, start, end, cache_dir=cache_dir)

    console.print("  Stock basic...")
    tables["stock_basic"] = fetch_stock_basic(pro, cache_dir=cache_dir)

    console.print("  Index daily...")
    strategy_configs = []
    for strategy_path in config.strategies:
        try:
            strategy_configs.append(StrategyConfigV1.from_yaml(strategy_path))
        except Exception:
            continue
    benchmark_resolution = resolve_benchmark_for_strategies(config.benchmark, strategy_configs)
    tables["index_daily"], benchmark_resolution = _fetch_benchmark_index_daily(
        fetch_index_daily,
        pro,
        benchmark_resolution,
        start,
        end,
        cache_dir,
    )

    console.print("  Daily bars...")
    tables["daily_all"] = fetch_daily_all(pro, start, end, cache_dir=cache_dir)

    console.print("  Daily basic...")
    tables["daily_basic"] = fetch_daily_basic(pro, start, end, cache_dir=cache_dir)

    console.print("  Adj factors...")
    tables["adj_factor"] = fetch_adj_factor(pro, start, end, cache_dir=cache_dir)

    stock_basic = tables["stock_basic"]
    codes = stock_basic["ts_code"].tolist()
    console.print(f"  Financial indicators ({len(codes)} stocks)...")
    fina_frames = []
    for i, code in enumerate(codes):
        if (i + 1) % 200 == 0:
            console.print(f"    {i + 1}/{len(codes)}")
        df = attach_disclosure_dates(
            fetch_fina_indicator(pro, code, cache_dir=cache_dir),
            fetch_disclosure_date(pro, code, cache_dir=cache_dir),
        )
        if len(df) > 0:
            fina_frames.append(df)
    tables["fina_all"] = pd.concat(fina_frames, ignore_index=True) if fina_frames else pd.DataFrame()

    summary = {k: len(v) for k, v in tables.items()}
    console.print(f"[green]Done.[/green] {summary}")
    console.print(f"  Benchmark: {benchmark_resolution.resolved} ({benchmark_resolution.name})")

    if fmt == "json":
        emit({"status": "ok", "tables": summary, "benchmark": benchmark_resolution.model_dump()}, format="json")


def _fetch_benchmark_index_daily(
    fetch_index_daily,
    pro,
    resolution,
    start_date: str,
    end_date: str,
    cache_dir: str,
):
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
