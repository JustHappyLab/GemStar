"""gemstar fetch — pull/update Tushare data."""

from __future__ import annotations

import typer
import pandas as pd

from src.cli.app import get_output_format
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
        fetch_fina_indicator, fetch_adj_factor,
    )

    fmt = get_output_format()
    config = load_config()
    pro = init_tushare(config.tushare_token or None)

    if not start or not end:
        from datetime import date, timedelta
        end = end or date.today().strftime("%Y%m%d")
        start = start or (date.today() - timedelta(days=730)).strftime("%Y%m%d")

    console.print(f"[cyan]Fetching data[/cyan] {start} ~ {end} ...")

    tables = {}

    console.print("  Trade calendar...")
    tables["trade_cal"] = fetch_trade_calendar(pro, start, end)

    console.print("  Stock basic...")
    tables["stock_basic"] = fetch_stock_basic(pro)

    console.print("  Index daily...")
    tables["index_daily"] = fetch_index_daily(pro, config.benchmark, start, end)

    console.print("  Daily bars...")
    tables["daily_all"] = fetch_daily_all(pro, start, end)

    console.print("  Daily basic...")
    tables["daily_basic"] = fetch_daily_basic(pro, start, end)

    console.print("  Adj factors...")
    tables["adj_factor"] = fetch_adj_factor(pro, start, end)

    stock_basic = tables["stock_basic"]
    codes = stock_basic["ts_code"].tolist()
    console.print(f"  Financial indicators ({len(codes)} stocks)...")
    fina_frames = []
    for i, code in enumerate(codes):
        if (i + 1) % 200 == 0:
            console.print(f"    {i + 1}/{len(codes)}")
        df = fetch_fina_indicator(pro, code)
        if len(df) > 0:
            fina_frames.append(df)
    tables["fina_all"] = pd.concat(fina_frames, ignore_index=True) if fina_frames else pd.DataFrame()

    summary = {k: len(v) for k, v in tables.items()}
    console.print(f"[green]Done.[/green] {summary}")

    if fmt == "json":
        emit({"status": "ok", "tables": summary}, format="json")
