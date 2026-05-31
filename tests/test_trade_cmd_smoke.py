"""Smoke test for trade_cmd — exercises target-derivation and live loop.

Patches _run_research to return an existing artifact run, then runs one
live cycle. Skips when the cached daily parquet has no rows.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.live.snapshot import snapshots_from_daily_df


@pytest.mark.skipif(
    not Path("artifacts").is_dir() or not any(Path("artifacts").glob("*/leaderboard.json")),
    reason="needs an existing run with leaderboard.json",
)
def test_trade_cmd_one_cycle(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    # Pick the most recent leaderboard.json so target derivation has fresh data.
    runs = sorted(
        (p.parent.name for p in Path("artifacts").glob("*/leaderboard.json")),
        reverse=True,
    )
    assert runs, "no completed runs found"
    target_run = runs[0]

    notif_path = tmp_path / "alerts.jsonl"
    strategy_path = tmp_path / "strategy.yaml"
    strategy_path.write_text("name: smoke_strategy\n")
    daily_df = pd.DataFrame([{
        "ts_code": "300750.SZ",
        "trade_date": "20260601",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "pre_close": 100.0,
        "vol": 1000.0,
        "pe_ttm": 20.0,
        "pb": 2.0,
        "turnover_rate": 1.0,
    }])
    index_df = pd.DataFrame({"trade_date": ["20260601"], "close": [1000.0]})
    stock_basic = pd.DataFrame({
        "ts_code": ["300750.SZ"],
        "name": ["CATL"],
        "list_date": ["20180101"],
        "delist_date": [None],
    })
    snapshots = snapshots_from_daily_df(daily_df)

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with (
        patch.object(mod, "_run_research", return_value=target_run),
        patch.object(mod, "_find_strategy_yaml", return_value=strategy_path),
        patch.object(
            mod,
            "_load_cached_market_data",
            return_value=(daily_df, index_df, pd.DataFrame(), stock_basic),
        ),
        patch.object(mod, "_rank_strategy", return_value=["300750.SZ"]),
        patch.object(mod, "_make_snapshot_loader", return_value=lambda: snapshots),
    ):
        mod.trade_cmd(
            once=True,
            config_path=None,
            top_n=2,
            capital=100000.0,
            active_interval=1,
            idle_interval=1,
            max_cycles=1,
            notifications_path=str(notif_path),
            ledger_path=str(tmp_path / "ledger.jsonl"),
        )

    assert notif_path.exists(), "no notifications written"
    lines = notif_path.read_text().strip().splitlines()
    assert lines, "notification file is empty"
