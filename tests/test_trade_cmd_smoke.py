"""Smoke test for trade_cmd — exercises target-derivation and live loop.

Patches _run_research to return an existing artifact run, then runs one
live cycle. Skips when the cached daily parquet has no rows.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.skipif(
    not Path("artifacts").is_dir() or not any(Path("artifacts").glob("*/leaderboard.json")),
    reason="needs an existing run with leaderboard.json",
)
def test_trade_cmd_one_cycle(tmp_path):
    from src.cli.commands import trade_cmd as mod

    # Pick the most recent leaderboard.json so target derivation has fresh data.
    runs = sorted(
        (p.parent.name for p in Path("artifacts").glob("*/leaderboard.json")),
        reverse=True,
    )
    assert runs, "no completed runs found"
    target_run = runs[0]

    notif_path = tmp_path / "alerts.jsonl"

    with patch.object(mod, "_run_research", return_value=target_run):
        # Disable Telegram for the test.
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
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
