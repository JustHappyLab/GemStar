"""Smoke test for trade_cmd — exercises target-derivation and live loop.

Patches _run_research to return an existing artifact run, then runs one
live cycle. Skips when the cached daily parquet has no rows.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import typer

from src.live.snapshot import snapshots_from_daily_df
from src.schemas.live import LiveAccountStateV1, LivePositionV1, MarketSnapshotV1, TargetHoldingV1


def test_trade_cmd_forwards_discovered_config_to_research(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    config_path = tmp_path / "gemstar.yaml"
    config_path.write_text(
        "strategies:\n"
        "  - strategies/chinext_lstm_mf8/config.yaml\n"
        "db_path: state.db\n"
        "artifacts_dir: artifacts\n",
        encoding="utf-8",
    )
    captured = {}

    def fake_run_research(path, _stop_event, ref_date=None):
        captured["config_path"] = path
        captured["ref_date"] = ref_date
        return None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "")
    monkeypatch.setenv("FEISHU_WEBHOOK_SECRET", "")
    with (
        patch.object(mod, "_run_research", side_effect=fake_run_research),
        patch.object(mod, "_latest_completed_run", return_value=None),
        pytest.raises(typer.Exit),
    ):
        mod.trade_cmd(
            once=True,
            config_path=None,
            top_n=1,
            capital=100000.0,
            active_interval=1,
            idle_interval=1,
            max_cycles=1,
            notifications_path=str(tmp_path / "alerts.jsonl"),
            ledger_path=str(tmp_path / "ledger.jsonl"),
            status_dir=str(tmp_path / "status"),
        )

    assert captured["config_path"] == str(config_path.resolve())
    assert captured["ref_date"]


def test_trade_cmd_uses_project_config_when_launched_outside_repo(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    config_path = repo_dir / "gemstar.yaml"
    config_path.write_text(
        "strategies:\n"
        "  - strategies/chinext_lstm_mf8/config.yaml\n"
        "db_path: state.db\n"
        "artifacts_dir: artifacts\n",
        encoding="utf-8",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    captured = {}

    def fake_run_research(path, _stop_event, ref_date=None):
        captured["config_path"] = path
        captured["cwd"] = Path.cwd()
        captured["ref_date"] = ref_date
        return None

    monkeypatch.chdir(outside)
    monkeypatch.setattr(mod, "_project_config_path", lambda: config_path)
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "")
    monkeypatch.setenv("FEISHU_WEBHOOK_SECRET", "")
    with (
        patch.object(mod, "_run_research", side_effect=fake_run_research),
        patch.object(mod, "_latest_completed_run", return_value=None),
        pytest.raises(typer.Exit),
    ):
        mod.trade_cmd(
            once=True,
            config_path=None,
            top_n=1,
            capital=100000.0,
            active_interval=1,
            idle_interval=1,
            max_cycles=1,
            notifications_path=str(tmp_path / "alerts.jsonl"),
            ledger_path=str(tmp_path / "ledger.jsonl"),
            status_dir=str(tmp_path / "status"),
        )

    assert captured["config_path"] == str(config_path.resolve())
    assert captured["cwd"] == repo_dir
    assert captured["ref_date"]


def test_trade_cmd_reuses_today_completed_run(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    captured = {"research_called": False}

    def fake_run_research(*_args, **_kwargs):
        captured["research_called"] = True
        return "fresh-run"

    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "")
    monkeypatch.setenv("FEISHU_WEBHOOK_SECRET", "")
    with (
        patch.object(mod, "_latest_completed_run", return_value="20260603-existing"),
        patch.object(mod, "_run_research", side_effect=fake_run_research),
        patch.object(mod, "_today_str", return_value="20260603"),
        patch.object(mod, "_build_targets", return_value=([], [], {})),
    ):
        mod.trade_cmd(
            once=True,
            config_path=None,
            top_n=1,
            capital=100000.0,
            active_interval=1,
            idle_interval=1,
            max_cycles=1,
            notifications_path=str(tmp_path / "alerts.jsonl"),
            ledger_path=str(tmp_path / "ledger.jsonl"),
            status_dir=str(tmp_path / "status"),
        )

    assert captured["research_called"] is False


def test_trade_cmd_emits_leaderboard_even_without_trade_targets(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    run_id = "20260604-run"
    artifacts = tmp_path / "artifacts"
    run_dir = artifacts / run_id
    run_dir.mkdir(parents=True)
    draft_dir = run_dir / "drafts"
    draft_dir.mkdir()
    (draft_dir / "strategy_a_20260604.yaml").write_text(
        "version: StrategyConfigV1\n"
        "name: strategy_a\n"
        "timer:\n"
        "  mode: full\n"
        "factors:\n"
        "  - factor_id: momentum_20d\n"
        "    weight: 1\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "gemstar.yaml"
    config_path.write_text(
        "strategies: []\n"
        f"db_path: {tmp_path / 'state.db'}\n"
        f"artifacts_dir: {artifacts}\n",
        encoding="utf-8",
    )
    (run_dir / "leaderboard.json").write_text(
        json.dumps({
            "entries": [
                {
                    "name": "strategy_a",
                    "rank": 1,
                    "sharpe": 1.25,
                    "cagr": 0.18,
                    "max_drawdown": -0.08,
                    "alpha": 0.06,
                    "rank_change": "new",
                    "status": "rejected",
                }
            ]
        }),
        encoding="utf-8",
    )
    (run_dir / "verdict_strategy_a.json").write_text(
        json.dumps({
            "strategy_id": "strategy_a",
            "recommended_state": "rejected",
            "blocking_issues": ["max_drawdown failed"],
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "")
    monkeypatch.setenv("FEISHU_WEBHOOK_SECRET", "")
    def fail_wait(*_args):
        raise AssertionError("--once should not wait for leaderboard notification time")

    monkeypatch.setattr(mod, "_wait_until_or_now", fail_wait)
    with (
        patch.object(mod, "_latest_completed_run", return_value=run_id),
        patch.object(mod, "_run_research", return_value=run_id),
        patch.object(mod, "_today_str", return_value="20260604"),
        patch.object(mod, "_build_targets", return_value=([], [], {})),
    ):
        mod.trade_cmd(
            once=True,
            config_path=str(config_path),
            top_n=1,
            capital=100000.0,
            active_interval=1,
            idle_interval=1,
            max_cycles=1,
            notifications_path=str(tmp_path / "alerts.jsonl"),
            ledger_path=str(tmp_path / "ledger.jsonl"),
            status_dir=str(tmp_path / "status"),
            leaderboard_notify_time="08:30",
            leaderboard_notify_top=5,
        )

    lines = (tmp_path / "alerts.jsonl").read_text(encoding="utf-8").splitlines()
    messages = [json.loads(line) for line in lines]
    assert any(message["action"] == "leaderboard" for message in messages)
    leaderboard = next(message for message in messages if message["action"] == "leaderboard")
    assert leaderboard["message_id"] == f"leaderboard-20260604-{run_id}"
    assert "研究观察摘要，不是下单建议" in leaderboard["body"]
    assert "LLM策略生成：草稿 1，通过 0，拒绝 1，未知 0" in leaderboard["body"]
    assert "- max_drawdown failed: 1" in leaderboard["body"]
    assert "#1 strategy_a [rejected]" in leaderboard["body"]


def test_daily_leaderboard_notification_dedupes_existing_message(tmp_path):
    from src.cli.commands import trade_cmd as mod

    run_id = "20260604-run"
    artifacts = tmp_path / "artifacts"
    run_dir = artifacts / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "leaderboard.json").write_text(
        json.dumps({
            "entries": [{
                "name": "strategy_a",
                "rank": 1,
                "sharpe": 1.25,
                "cagr": 0.18,
                "max_drawdown": -0.08,
                "alpha": 0.06,
                "status": "rejected",
            }]
        }),
        encoding="utf-8",
    )
    notifications_path = tmp_path / "alerts.jsonl"
    notifications_path.write_text(
        json.dumps({"message_id": f"leaderboard-20260604-{run_id}"}) + "\n",
        encoding="utf-8",
    )
    messages = []
    config = type("Config", (), {"artifacts_dir": str(artifacts)})()

    mod._emit_daily_leaderboard(
        notifier=messages.append,
        config=config,
        run_id=run_id,
        ref_date="20260604",
        top_n=10,
        notifications_path=notifications_path,
    )

    assert messages == []


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
    target_run = next(
        (
            run
            for run in runs
            if any(
                entry.get("status") in mod._LIVE_ALLOWED_STRATEGY_STATUSES
                and entry.get("sharpe", 0.0) > 0
                for entry in json.loads(
                    (Path("artifacts") / run / "leaderboard.json").read_text(encoding="utf-8")
                ).get("entries", [])
            )
        ),
        None,
    )
    if target_run is None:
        pytest.skip("needs a completed run with live-eligible leaderboard entries")

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

    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "")
    monkeypatch.setenv("FEISHU_WEBHOOK_SECRET", "")
    with (
        patch.object(mod, "_latest_completed_run", return_value=None),
        patch.object(mod, "_run_research", return_value=target_run),
        patch.object(mod, "_find_strategy_yaml", return_value=strategy_path),
        patch.object(
            mod,
            "_load_cached_market_data",
            return_value=(daily_df, index_df, pd.DataFrame(), stock_basic),
        ),
        patch.object(mod, "_rank_strategy", return_value=["300750.SZ"]),
        patch.object(mod, "_timer_position_pct", return_value=1.0),
        patch.object(mod, "_make_snapshot_loader", return_value=lambda: snapshots),
        patch.object(mod, "_today_str", return_value="20260601"),
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
            status_dir=str(tmp_path / "status"),
        )

    assert notif_path.exists(), "no notifications written"
    lines = notif_path.read_text().strip().splitlines()
    assert lines, "notification file is empty"
    assert (tmp_path / "status" / "trade_status.json").exists()
    assert (tmp_path / "status" / "trade_status.md").exists()


def test_trade_cmd_watches_current_positions_not_only_targets(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    account = LiveAccountStateV1(
        cash=80_000.0,
        total_value=100_000.0,
        positions=[
            LivePositionV1(
                ts_code="000001.SZ",
                shares=100,
                avg_cost=100.0,
                last_price=100.0,
                market_value=10_000.0,
            )
        ],
    )
    target = TargetHoldingV1(
        ts_code="300750.SZ",
        target_weight=0.5,
        target_shares=100,
        reason="test target",
    )
    snapshots = [
        *snapshots_from_daily_df(pd.DataFrame([{
            "ts_code": "000001.SZ",
            "trade_date": "20260601",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "pre_close": 99.0,
            "vol": 1000.0,
        }])),
        *snapshots_from_daily_df(pd.DataFrame([{
            "ts_code": "300750.SZ",
            "trade_date": "20260601",
            "open": 200.0,
            "high": 201.0,
            "low": 199.0,
            "close": 200.0,
            "pre_close": 199.0,
            "vol": 1000.0,
        }])),
    ]
    watched_symbols = {}

    def fake_snapshot_loader(_config, symbols, snapshot_source="auto"):
        del snapshot_source
        watched_symbols["symbols"] = set(symbols)
        return lambda: snapshots

    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "")
    monkeypatch.setenv("FEISHU_WEBHOOK_SECRET", "")
    with (
        patch.object(mod, "_latest_completed_run", return_value=None),
        patch.object(mod, "_run_research", return_value="run-1"),
        patch.object(
            mod,
            "_build_targets",
            return_value=([target], ["strategy-1"], {"000001.SZ": "平安银行", "300750.SZ": "宁德时代"}),
        ),
        patch.object(mod, "_make_snapshot_loader", side_effect=fake_snapshot_loader),
        patch.object(mod._LedgerTracker, "load_account", return_value=account),
        patch.object(mod._LedgerTracker, "record", return_value=None) as record_mock,
        patch.object(mod, "_today_str", return_value="20260601"),
    ):
        mod.trade_cmd(
            once=True,
            config_path=None,
            top_n=1,
            capital=100000.0,
            active_interval=1,
            idle_interval=1,
            max_cycles=1,
            notifications_path=str(tmp_path / "alerts.jsonl"),
            ledger_path=str(tmp_path / "ledger.jsonl"),
            status_dir=str(tmp_path / "status"),
        )

    assert watched_symbols["symbols"] == {"000001.SZ", "300750.SZ"}
    record_mock.assert_not_called()
    status_md = (tmp_path / "status" / "trade_status.md").read_text(encoding="utf-8")
    assert "000001.SZ 平安银行" in status_md
    assert "sell" in status_md


def test_build_targets_scales_exposure_by_timer_position(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    run_id = "run-1"
    artifacts = tmp_path / "artifacts"
    run_dir = artifacts / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "leaderboard.json").write_text(
        '{"entries":[{"name":"strategy_a","rank":1,"sharpe":1.2,"status":"candidate"}]}',
        encoding="utf-8",
    )
    strategy_path = tmp_path / "strategy.yaml"
    strategy_path.write_text("name: strategy_a\n", encoding="utf-8")
    daily_df = pd.DataFrame([
        {
            "ts_code": "300750.SZ",
            "trade_date": "20260604",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "pre_close": 99.0,
            "vol": 1000.0,
            "pe_ttm": 20.0,
            "pb": 2.0,
            "turnover_rate": 1.0,
        },
        {
            "ts_code": "300059.SZ",
            "trade_date": "20260604",
            "open": 50.0,
            "high": 51.0,
            "low": 49.0,
            "close": 50.0,
            "pre_close": 49.0,
            "vol": 1000.0,
            "pe_ttm": 20.0,
            "pb": 2.0,
            "turnover_rate": 1.0,
        },
    ])
    config = type("Config", (), {"artifacts_dir": str(artifacts)})()

    monkeypatch.setattr(
        mod,
        "_load_cached_market_data",
        lambda _config, _ref_date: (daily_df, pd.DataFrame({"trade_date": ["20260604"], "close": [1000.0]}), pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(mod, "_find_strategy_yaml", lambda *_args: strategy_path)
    monkeypatch.setattr(mod, "_rank_strategy", lambda **_kwargs: ["300750.SZ", "300059.SZ"])
    monkeypatch.setattr(mod, "_timer_position_pct", lambda **_kwargs: 0.5)

    targets, strategies, _names = mod._build_targets(
        config,
        run_id,
        "20260604",
        top_n=1,
        capital=100_000.0,
    )

    assert strategies == ["strategy_a"]
    assert [target.ts_code for target in targets] == ["300750.SZ", "300059.SZ"]
    assert [target.target_shares for target in targets] == [200, 500]
    assert all("timer position 50%" in target.reason for target in targets)


def test_build_targets_keeps_zero_share_targets_for_timer_exit(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    run_id = "run-1"
    artifacts = tmp_path / "artifacts"
    run_dir = artifacts / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "leaderboard.json").write_text(
        '{"entries":[{"name":"strategy_a","rank":1,"sharpe":1.2,"status":"candidate"}]}',
        encoding="utf-8",
    )
    strategy_path = tmp_path / "strategy.yaml"
    strategy_path.write_text("name: strategy_a\n", encoding="utf-8")
    daily_df = pd.DataFrame([{
        "ts_code": "300750.SZ",
        "trade_date": "20260604",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "pre_close": 99.0,
        "vol": 1000.0,
        "pe_ttm": 20.0,
        "pb": 2.0,
        "turnover_rate": 1.0,
    }])
    config = type("Config", (), {"artifacts_dir": str(artifacts)})()

    monkeypatch.setattr(
        mod,
        "_load_cached_market_data",
        lambda _config, _ref_date: (daily_df, pd.DataFrame({"trade_date": ["20260604"], "close": [1000.0]}), pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(mod, "_find_strategy_yaml", lambda *_args: strategy_path)
    monkeypatch.setattr(mod, "_rank_strategy", lambda **_kwargs: ["300750.SZ"])
    monkeypatch.setattr(mod, "_timer_position_pct", lambda **_kwargs: 0.0)

    targets, strategies, _names = mod._build_targets(
        config,
        run_id,
        "20260604",
        top_n=1,
        capital=100_000.0,
    )

    assert strategies == ["strategy_a"]
    assert len(targets) == 1
    assert targets[0].ts_code == "300750.SZ"
    assert targets[0].target_shares == 0
    assert targets[0].target_weight == 0.0
    assert "timer position 0%" in targets[0].reason


def test_build_targets_ignores_rejected_leaderboard_entries(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    run_id = "run-1"
    artifacts = tmp_path / "artifacts"
    run_dir = artifacts / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "leaderboard.json").write_text(
        '{"entries":[{"name":"strategy_a","rank":1,"sharpe":3.0,"status":"rejected"}]}',
        encoding="utf-8",
    )
    config = type("Config", (), {"artifacts_dir": str(artifacts)})()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("rejected strategies must not load market data")

    monkeypatch.setattr(mod, "_load_cached_market_data", fail_if_called)

    targets, strategies, names = mod._build_targets(
        config,
        run_id,
        "20260604",
        top_n=1,
        capital=100_000.0,
    )

    assert targets == []
    assert strategies == []
    assert names == {}


def test_timer_position_uses_latest_available_index_date(tmp_path):
    from src.cli.commands import trade_cmd as mod

    strategy_path = tmp_path / "strategy.yaml"
    strategy_path.write_text(
        "name: timer_ma\n"
        "timer:\n"
        "  mode: ma\n",
        encoding="utf-8",
    )
    dates = pd.date_range("2026-04-20", periods=30, freq="B").strftime("%Y%m%d")
    index_df = pd.DataFrame({
        "trade_date": dates,
        "close": [100.0 + idx for idx in range(len(dates))],
    })

    position = mod._timer_position_pct(
        strategy_path,
        index_df,
        trade_date="20260604",
    )

    assert position == 1.0


def test_timer_position_full_mode_does_not_require_index_data(tmp_path):
    from src.cli.commands import trade_cmd as mod

    strategy_path = tmp_path / "strategy.yaml"
    strategy_path.write_text(
        "name: timer_full\n"
        "timer:\n"
        "  mode: full\n",
        encoding="utf-8",
    )

    assert mod._timer_position_pct(strategy_path, pd.DataFrame(), "20260604") == 1.0


def test_timer_position_non_full_fails_closed_without_index_data(tmp_path):
    from src.cli.commands import trade_cmd as mod

    strategy_path = tmp_path / "strategy.yaml"
    strategy_path.write_text(
        "name: timer_lstm\n"
        "timer:\n"
        "  mode: lstm\n",
        encoding="utf-8",
    )

    assert mod._timer_position_pct(strategy_path, pd.DataFrame(), "20260604") == 0.0


def test_timer_position_fails_closed_when_signal_builder_errors(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod
    from src.orchestrator import signals as signals_mod

    strategy_path = tmp_path / "strategy.yaml"
    strategy_path.write_text(
        "name: timer_ma\n"
        "timer:\n"
        "  mode: ma\n",
        encoding="utf-8",
    )
    index_df = pd.DataFrame({
        "trade_date": ["20260603"],
        "close": [1000.0],
    })

    def fail_build_signals(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(signals_mod, "build_signals", fail_build_signals)

    assert mod._timer_position_pct(strategy_path, index_df, "20260604") == 0.0


def test_trade_snapshot_loader_prefers_realtime_during_trading(tmp_path, monkeypatch):
    from src.cli.commands import trade_cmd as mod

    cache_dir = tmp_path / "data"
    cache_dir.mkdir()
    pd.DataFrame([
        {
            "ts_code": "000001.SZ",
            "trade_date": "20260603",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.0,
            "pre_close": 9.9,
            "vol": 1000.0,
        },
        {
            "ts_code": "300750.SZ",
            "trade_date": "20260603",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "pre_close": 99.0,
            "vol": 1000.0,
        },
    ]).to_parquet(cache_dir / "daily_all_20240603_20260603.parquet", index=False)
    config = type("Config", (), {"data_cache_dir": str(cache_dir)})()
    realtime = [
        MarketSnapshotV1(
            ts_code="000001.SZ",
            trade_date="20260604",
            last_price=10.8,
            pre_close=10.0,
            source="tushare_realtime",
        )
    ]

    monkeypatch.setattr(mod, "is_trading_time", lambda _now: True)
    monkeypatch.setattr(mod, "_load_realtime_snapshots", lambda _symbols: realtime)

    snapshots = mod._make_snapshot_loader(
        config,
        ["000001.SZ", "300750.SZ"],
        snapshot_source="auto",
    )()
    by_code = {snapshot.ts_code: snapshot for snapshot in snapshots}

    assert by_code["000001.SZ"].last_price == 10.8
    assert by_code["000001.SZ"].source == "tushare_realtime"
    assert by_code["300750.SZ"].last_price == 100.0
    assert by_code["300750.SZ"].source == "daily_cache"


def test_price_alert_fn_only_uses_realtime_snapshots():
    from src.cli.commands import trade_cmd as mod

    alert_fn = mod._make_price_alert_fn(
        threshold_pct=0.03,
        symbol_names={"000001.SZ": "平安银行"},
    )
    account = LiveAccountStateV1(
        cash=90_000.0,
        total_value=100_000.0,
        positions=[
            LivePositionV1(
                ts_code="000001.SZ",
                shares=100,
                avg_cost=10.0,
                last_price=10.0,
                market_value=1000.0,
            )
        ],
    )
    snapshots = [
        MarketSnapshotV1(
            ts_code="000001.SZ",
            trade_date="20260604",
            last_price=10.4,
            pre_close=10.0,
            source="tushare_realtime",
        ),
        MarketSnapshotV1(
            ts_code="300750.SZ",
            trade_date="20260604",
            last_price=104.0,
            pre_close=100.0,
            source="daily_cache",
        ),
    ]

    messages = alert_fn(account, [], snapshots, datetime(2026, 6, 4, 10, 0, 0))

    assert len(messages) == 1
    assert messages[0].title == "[涨跌提醒] 000001.SZ 平安银行 +4.00%"
    assert messages[0].action == "price_alert"
    assert messages[0].symbol_names == {"000001.SZ": "平安银行"}


def test_load_cached_market_data_uses_latest_window_not_after_ref_date(tmp_path):
    from src.cli.commands import trade_cmd as mod

    cache_dir = tmp_path / "raw"
    cache_dir.mkdir()
    pd.DataFrame({
        "ts_code": ["300001.SZ"],
        "name": ["A"],
        "list_date": ["20200101"],
        "delist_date": [None],
    }).to_parquet(cache_dir / "stock_basic_a_share.parquet", index=False)
    pd.DataFrame({
        "ts_code": ["300001.SZ"],
        "trade_date": ["20260604"],
        "open": [10.0],
        "high": [11.0],
        "low": [9.0],
        "close": [10.5],
        "pre_close": [10.0],
        "vol": [1000.0],
        "amount": [10000.0],
    }).to_parquet(cache_dir / "daily_all_20240604_20260604.parquet", index=False)
    pd.DataFrame({
        "ts_code": ["300001.SZ"],
        "trade_date": ["20260604"],
        "pe_ttm": [20.0],
        "pb": [2.0],
        "turnover_rate": [1.5],
    }).to_parquet(cache_dir / "daily_basic_20240604_20260604.parquet", index=False)
    pd.DataFrame({
        "trade_date": ["20260604"],
        "close": [1000.0],
    }).to_parquet(cache_dir / "index_daily_399006.SZ_20240604_20260604.parquet", index=False)
    pd.DataFrame({
        "ts_code": ["300001.SZ"],
        "ann_date": ["20260430"],
        "end_date": ["20260331"],
        "roe": [10.0],
        "revenue_yoy": [20.0],
        "netprofit_yoy": [30.0],
    }).to_parquet(cache_dir / "fina_300001_SZ.parquet", index=False)
    pd.DataFrame({
        "ts_code": ["300001.SZ"],
        "end_date": ["20260331"],
        "actual_date": ["20260430"],
    }).to_parquet(cache_dir / "disclosure_date_300001_SZ.parquet", index=False)
    config = type(
        "Config",
        (),
        {
            "data_cache_dir": str(cache_dir),
            "strategies": [],
            "benchmark": "399006.SZ",
        },
    )()

    daily_df, index_df, fina_df, stock_basic = mod._load_cached_market_data(config, "20260605")

    assert daily_df["trade_date"].tolist() == ["20260604"]
    assert daily_df["pe_ttm"].tolist() == [20.0]
    assert index_df["trade_date"].tolist() == ["20260604"]
    assert stock_basic["ts_code"].tolist() == ["300001.SZ"]
    assert fina_df["ts_code"].tolist() == ["300001.SZ"]
    assert "disclosure_date" in fina_df.columns


def test_latest_daily_parquet_uses_window_end_date(tmp_path):
    from src.cli.commands import trade_cmd as mod

    cache_dir = tmp_path / "raw"
    cache_dir.mkdir()
    older = cache_dir / "daily_all_20240604_20260604.parquet"
    newer = cache_dir / "daily_all_20210101_20260605.parquet"
    older.write_text("older", encoding="utf-8")
    newer.write_text("newer", encoding="utf-8")

    assert mod._latest_daily_parquet(cache_dir) == newer


def test_leaderboard_alert_fn_emits_when_notify_time_is_due(tmp_path):
    from src.cli.commands import trade_cmd as mod

    run_id = "20260604-alert"
    artifacts = tmp_path / "artifacts"
    run_dir = artifacts / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "leaderboard.json").write_text(
        json.dumps({
            "entries": [
                {
                    "name": "strategy_a",
                    "rank": 1,
                    "sharpe": 1.2,
                    "cagr": 0.2,
                    "max_drawdown": 0.1,
                    "alpha": 0.05,
                    "rank_change": "new",
                    "status": "candidate",
                }
            ]
        }),
        encoding="utf-8",
    )
    config = type("Config", (), {"artifacts_dir": str(artifacts)})()
    alerts = tmp_path / "alerts.jsonl"
    alert_fn = mod._make_leaderboard_alert_fn(
        config=config,
        run_id=run_id,
        ref_date="20260604",
        top_n=10,
        notify_time="08:30",
        notifications_path=alerts,
    )

    early = alert_fn(None, [], [], datetime(2026, 6, 4, 8, 29))
    due = alert_fn(None, [], [], datetime(2026, 6, 4, 8, 30))

    assert early == []
    assert len(due) == 1
    assert due[0].action == "leaderboard"


def test_premarket_plan_alert_fn_emits_summary_for_stale_snapshots(tmp_path):
    from src.cli.commands import trade_cmd as mod

    account = LiveAccountStateV1(
        cash=90_000.0,
        total_value=100_000.0,
        positions=[
            LivePositionV1(
                ts_code="000001.SZ",
                shares=600,
                avg_cost=10.0,
                last_price=10.0,
                market_value=6000.0,
            )
        ],
    )
    targets = [
        TargetHoldingV1(
            ts_code="000001.SZ",
            target_weight=0.0,
            target_shares=0,
            reason="top from strategy_a",
        ),
        TargetHoldingV1(
            ts_code="300001.SZ",
            target_weight=0.2,
            target_shares=200,
            reason="top from strategy_a",
        ),
    ]
    snapshots = [
        MarketSnapshotV1(
            ts_code="000001.SZ",
            trade_date="20260604",
            last_price=10.0,
            pre_close=9.8,
            source="daily_cache",
        ),
        MarketSnapshotV1(
            ts_code="300001.SZ",
            trade_date="20260604",
            last_price=40.0,
            pre_close=39.0,
            source="daily_cache",
        ),
    ]
    alert_fn = mod._make_premarket_plan_alert_fn(
        run_id="20260605-plan",
        ref_date="20260605",
        strategy_name="strategy_a",
        symbol_names={"000001.SZ": "平安银行", "300001.SZ": "特锐德"},
        min_trade_value=5000.0,
        notifications_path=tmp_path / "alerts.jsonl",
    )

    messages = alert_fn(account, targets, snapshots, datetime(2026, 6, 5, 8, 45))

    assert len(messages) == 1
    message = messages[0]
    assert message.message_id == "pretrade-plan-20260605-20260605-plan-20260604"
    assert message.action == "pretrade_plan"
    assert message.title == "GemStar 盘前计划 (20260605)"
    assert "价格基准：20260604 收盘缓存价" in message.body
    assert "不是可执行交易信号" in message.body
    assert "300001.SZ 特锐德: 买入 200 股" in message.body
    assert "000001.SZ 平安银行: 卖出 600 股" in message.body


def test_premarket_plan_alert_fn_skips_current_day_snapshots(tmp_path):
    from src.cli.commands import trade_cmd as mod

    alert_fn = mod._make_premarket_plan_alert_fn(
        run_id="20260605-plan",
        ref_date="20260605",
        strategy_name="strategy_a",
        symbol_names={},
        min_trade_value=0.0,
        notifications_path=tmp_path / "alerts.jsonl",
    )

    messages = alert_fn(
        LiveAccountStateV1(cash=100_000.0, total_value=100_000.0, positions=[]),
        [TargetHoldingV1(ts_code="300001.SZ", target_weight=0.2, target_shares=200)],
        [MarketSnapshotV1(ts_code="300001.SZ", trade_date="20260605", last_price=40.0)],
        datetime(2026, 6, 5, 9, 35),
    )

    assert messages == []
