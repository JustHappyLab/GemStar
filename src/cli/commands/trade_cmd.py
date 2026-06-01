"""gemstar trade — single-command pipeline: research → targets → live alerts.

CALLING SPEC:
    trade_cmd(
        once=bool,
        config_path=str | None,
        top_n=int,
        capital=float,
        active_interval=int,
        idle_interval=int,
        max_cycles=int | None,
    ) -> None

SIDE EFFECTS:
    Subprocesses `gemstar run`. Reads cached parquet data and the run's
    leaderboard artifact. Appends notifications to alerts/live.jsonl and,
    when TELEGRAM_BOT_TOKEN/CHAT_ID are set, posts to Telegram.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import typer
import yaml

from src.cli.config import load_config
from src.cli.output import console
from src.live.ledger import append_paper_trade, read_paper_trades
from src.live.loop import run_live_loop
from src.live.signal_engine import build_live_decisions
from src.live.snapshot import snapshots_from_daily_df
from src.live.symbols import symbol_names_from_dataframe
from src.notify.local_file import LocalFileNotificationSink
from src.notify.message import NotificationMessageV1, format_symbol_labels
from src.notify.telegram import TelegramNotificationSink
from src.schemas.live import (
    LiveAccountStateV1,
    LiveDecisionV1,
    LivePositionV1,
    MarketSnapshotV1,
    TargetHoldingV1,
)

logger = logging.getLogger(__name__)


def trade_cmd(
    once: bool = typer.Option(
        False, "--once", help="Run one research-then-watch cycle and exit."
    ),
    config_path: str = typer.Option(
        None, "--config", "-c", help="Config file path."
    ),
    top_n: int = typer.Option(
        3, "--top", help="Number of top leaderboard strategies to track live."
    ),
    capital: float = typer.Option(
        100000.0, "--capital", help="Paper-trading capital used for sizing targets."
    ),
    active_interval: int = typer.Option(
        30, "--active-interval", help="Polling seconds during trading sessions."
    ),
    idle_interval: int = typer.Option(
        300, "--idle-interval", help="Polling seconds outside trading sessions."
    ),
    max_cycles: int | None = typer.Option(
        None, "--max-cycles", help="Stop the live loop after N cycles (smoke tests)."
    ),
    notifications_path: str = typer.Option(
        "alerts/live.jsonl", "--notifications", help="Append-only notification JSONL path."
    ),
    ledger_path: str = typer.Option(
        "alerts/ledger.jsonl", "--ledger", help="Paper-trading ledger path (appends executed trades)."
    ),
) -> None:
    """One-command research → live monitor → notify.

    On the first run, starts a fresh paper account with --capital (default 100k CNY).
    Every trade confirmed by the signal engine is appended to --ledger. On subsequent
    runs, the account state is reconstructed from the ledger so you see cumulative
    position-aware signals (buy/add/reduce/sell), not just fresh buys every time.
    """
    config = load_config(Path(config_path) if config_path else None)
    notifier = _build_notifier(notifications_path)
    tracker = _LedgerTracker(ledger_path, capital)

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)

    cycle = 0
    while not stop_event.is_set():
        cycle += 1
        ref_date = _today_str()
        console.print(f"\n[cyan]GemStar trade[/cyan] cycle={cycle} date={ref_date}")
        account = tracker.load_account()
        console.print(
            f"  capital={account.total_value:.0f} positions={len(account.positions)} "
            f"cash={account.cash:.0f}"
        )

        run_id = _run_research(config_path, stop_event)
        if run_id is None:
            _emit(notifier, _alert(
                "warning", f"研究失败 ({ref_date})",
                "每日研究管线未完成，将复用上次成功的运行结果。",
                symbols=[],
            ))
            run_id = _latest_completed_run(config.db_path)

        if run_id is None:
            console.print("[red]没有可用运行记录，无法生成目标持仓。[/red]")
            if once:
                raise typer.Exit(1)
            _wait_until_tomorrow(stop_event)
            continue

        targets, strategies, symbol_names = _build_targets(config, run_id, ref_date, top_n, capital)
        if not targets:
            console.print(f"[yellow]运行 {run_id} 无可执行目标。[/yellow]")
            _emit(notifier, _alert(
                "info", f"{run_id} 无目标",
                "今日排名靠前策略未产出有效持仓，继续等待。",
                symbols=[],
            ))
            if once:
                return
            _wait_until_tomorrow(stop_event)
            continue

        symbols = sorted({t.ts_code for t in targets})
        display_symbols = format_symbol_labels(symbols, symbol_names)
        console.print(
            f"[green]目标持仓就绪[/green] 策略={','.join(strategies)} "
            f"标的数={len(symbols)}"
        )
        _emit(notifier, _alert(
            "info",
            f"GemStar 交易目标已就绪 ({ref_date})",
            "跟踪标的： " + ", ".join(display_symbols[:10])
            + (f" 等{len(symbols)}只" if len(symbols) > 10 else "")
            + f"\n策略：{'、'.join(strategies)}",
            symbols=symbols,
            symbol_names=symbol_names,
        ))

        snapshot_loader = _make_snapshot_loader(config, symbols)

        # Wrap notifier so confirmed trades land in the ledger.
        notified_decisions: list[LiveDecisionV1] = []
        def _tracking_notify(notification: NotificationMessageV1) -> None:
            notifier(notification)
            # Rebuild the source decision for ledger tracking.
            snapshots = snapshot_loader()
            prices = {s.ts_code: s.last_price for s in snapshots}
            for d in build_live_decisions(
                account=tracker.load_account(),
                targets=targets,
                snapshots=snapshots,
                strategy_name=strategies[0] if strategies else "trade",
            ):
                if d.decision_id == notification.decision_id:
                    notified_decisions.append(d)
                    break

        result = run_live_loop(
            account_loader=lambda: tracker.load_account(),
            targets_loader=lambda: targets,
            snapshots_loader=snapshot_loader,
            notify=_tracking_notify,
            strategy_name=strategies[0] if strategies else "trade",
            symbol_names=symbol_names,
            stop_event=stop_event,
            active_interval=active_interval,
            idle_interval=idle_interval,
            max_cycles=max_cycles,
            heartbeat_fn=_heartbeat,
        )
        # Record confirmed trades to ledger so the next cycle sees updated positions.
        for d in notified_decisions:
            if d.intent.action in ("buy", "add", "sell", "reduce"):
                tracker.record(d, snapshots=snapshot_loader())

        console.print(
            f"[green]Live cycle done.[/green] cycles={result.cycles} "
            f"decisions={result.decisions} notifications={result.notifications} "
            f"deduped={result.deduped} ledger={len(tracker._trades)}"
        )
        if once or stop_event.is_set():
            break
        _wait_until_tomorrow(stop_event)


# ── notifier ────────────────────────────────────────────────────


def _build_notifier(jsonl_path: str):
    """Return a notify(message) callable that fans out to Telegram + JSONL."""
    file_sink = LocalFileNotificationSink(jsonl_path)
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or ""
    telegram_sink: TelegramNotificationSink | None = None
    if bot_token and chat_id:
        try:
            telegram_sink = TelegramNotificationSink(bot_token=bot_token, chat_id=chat_id)
            console.print("[dim]Telegram notifications enabled.[/dim]")
        except ValueError as exc:
            console.print(f"[yellow]Telegram disabled: {exc}[/yellow]")
    else:
        console.print("[dim]Telegram disabled (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set); using JSONL only.[/dim]")

    def _notify(message: NotificationMessageV1) -> None:
        file_sink.send(message)
        if telegram_sink is None:
            return
        try:
            telegram_sink.send(message)
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)

    return _notify


def _alert(
    severity: str,
    title: str,
    body: str,
    symbols: list[str],
    symbol_names: dict[str, str] | None = None,
) -> NotificationMessageV1:
    symbol_set = set(symbols)
    return NotificationMessageV1(
        message_id=f"trade-{datetime.now().strftime('%Y%m%dT%H%M%S%f')}",
        severity=severity,
        title=title,
        body=body,
        symbols=symbols,
        symbol_names={
            code: name
            for code, name in (symbol_names or {}).items()
            if code in symbol_set
        },
    )


def _emit(notifier, message: NotificationMessageV1) -> None:
    try:
        notifier(message)
    except Exception as exc:
        logger.warning("notifier failed: %s", exc)


def _heartbeat(event: dict) -> None:
    console.print(
        "[dim]live heartbeat "
        f"cycle={event['cycle']} decisions={event['decisions']} "
        f"notifications={event['notifications']} sleep={event['sleep_seconds']}s[/dim]"
    )


# ── research orchestration ──────────────────────────────────────


def _run_research(config_path: str | None, stop_event: threading.Event) -> str | None:
    """Subprocess `gemstar run --llm`. Returns the latest completed run_id or None."""
    cmd = [sys.executable, "-m", "src.cli.app", "run", "--llm"]
    if config_path:
        cmd.extend(["--config", str(Path(config_path).resolve())])

    console.print(f"[cyan]Running daily research[/cyan] (this may take a while)...")
    try:
        proc = subprocess.Popen(cmd)
        while proc.poll() is None:
            if stop_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return None
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode != 0:
            console.print(f"[yellow]Research subprocess exited with code {proc.returncode}[/yellow]")
            return None
    except Exception as exc:
        console.print(f"[red]Research subprocess error: {exc}[/red]")
        return None

    # Pick up the run_id of the just-completed run.
    config = load_config(Path(config_path) if config_path else None)
    return _latest_completed_run(config.db_path)


def _latest_completed_run(db_path: str) -> str | None:
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE status = 'completed' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ── target derivation ───────────────────────────────────────────


def _build_targets(config, run_id: str, ref_date: str, top_n: int, capital: float):
    """Compose live targets from the run's leaderboard + cached data."""
    artifacts_dir = Path(config.artifacts_dir) / run_id
    leaderboard_path = artifacts_dir / "leaderboard.json"
    if not leaderboard_path.exists():
        console.print(f"[yellow]No leaderboard.json under {artifacts_dir}.[/yellow]")
        return [], [], {}

    entries = json.loads(leaderboard_path.read_text()).get("entries", [])
    accepted = [e for e in entries if e.get("sharpe", 0.0) > 0][:top_n]
    if not accepted:
        return [], [], {}

    daily_df, index_df, fina_df, stock_basic = _load_cached_market_data(config, ref_date)
    symbol_names = symbol_names_from_dataframe(stock_basic)
    if daily_df is None or daily_df.empty:
        console.print("[yellow]No cached daily data available; cannot derive targets.[/yellow]")
        return [], [], symbol_names

    # Most recent trade_date present in cache
    last_trade_date = str(daily_df["trade_date"].max())
    snapshots = snapshots_from_daily_df(daily_df, trade_date=last_trade_date)
    prices = {s.ts_code: s.last_price for s in snapshots}

    capital_per_strategy = capital / max(1, len(accepted))
    all_targets: list[TargetHoldingV1] = []
    used_strategies: list[str] = []

    for entry in accepted:
        strat_name = entry["name"]
        yaml_path = _find_strategy_yaml(strat_name, run_id, artifacts_dir)
        if yaml_path is None:
            console.print(f"[dim]  skip {strat_name} (yaml not found)[/dim]")
            continue
        try:
            strategy_top = _rank_strategy(
                yaml_path=yaml_path,
                daily_df=daily_df,
                index_df=index_df,
                fina_df=fina_df,
                stock_basic=stock_basic,
                trade_date=last_trade_date,
            )
        except Exception as exc:
            console.print(f"[yellow]  ranking failed for {strat_name}: {exc}[/yellow]")
            continue
        if not strategy_top:
            continue

        from src.live.planner import plan_live_targets
        targets = plan_live_targets(
            top_stocks=strategy_top,
            prices=prices,
            total_capital=capital_per_strategy,
            position_pct=1.0,
            reason=f"top from {strat_name} (rank #{entry.get('rank')})",
        )
        all_targets.extend(targets)
        used_strategies.append(strat_name)

    # Deduplicate by ts_code; sum target_shares so the user sees combined exposure.
    merged: dict[str, TargetHoldingV1] = {}
    total_value = sum(t.target_shares * (prices.get(t.ts_code) or 0.0) for t in all_targets) or 1.0
    for t in all_targets:
        if t.ts_code in merged:
            base = merged[t.ts_code]
            shares = base.target_shares + t.target_shares
            merged[t.ts_code] = TargetHoldingV1(
                ts_code=t.ts_code,
                target_weight=(shares * (prices.get(t.ts_code) or 0.0)) / total_value,
                target_shares=shares,
                reason=base.reason + " + " + t.reason,
            )
        else:
            merged[t.ts_code] = t
    return list(merged.values()), used_strategies, symbol_names


def _find_strategy_yaml(strat_name: str, run_id: str, artifacts_dir: Path) -> Path | None:
    """Find the strategy YAML in active strategies/ or the run's drafts/ dir."""
    drafts_dir = artifacts_dir / "drafts"
    candidates: list[Path] = []
    if drafts_dir.is_dir():
        candidates.extend(drafts_dir.glob(f"{strat_name}_*.yaml"))
        candidates.extend(drafts_dir.glob(f"{strat_name}.yaml"))
    strategies_root = Path("strategies")
    if strategies_root.is_dir():
        candidates.append(strategies_root / strat_name / "config.yaml")
        candidates.extend(strategies_root.rglob(f"{strat_name}.yaml"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def _rank_strategy(
    yaml_path: Path,
    daily_df,
    index_df,
    fina_df,
    stock_basic,
    trade_date: str,
) -> list[str]:
    from src.orchestrator.rankings import build_rankings
    from src.orchestrator.universe import resolve_strategy_universe
    from src.schemas.strategy import StrategyConfigV1

    strategy = StrategyConfigV1.from_yaml(yaml_path)
    resolution = resolve_strategy_universe(strategy)
    rankings = build_rankings(
        daily_df=daily_df,
        index_daily=index_df,
        fina_df=fina_df,
        factors=strategy.factors,
        top_n=strategy.top_n,
        trade_dates=[trade_date],
        universe=resolution,
        stock_basic=stock_basic,
    )
    return rankings.get(trade_date, [])


# ── data plumbing (read-only, cache-only) ──────────────────────


def _load_cached_market_data(config, ref_date: str):
    """Load daily / index / fina / stock_basic frames from caches.

    Calls Tushare fetchers with a short window: when the parquet cache exists,
    they return the cached frame; otherwise they fetch (one-time cost).
    """
    import pandas as pd
    from src.data.fetcher import (
        init_tushare,
        fetch_trade_calendar,
        fetch_stock_basic,
        fetch_index_daily,
        fetch_daily_all,
        fetch_daily_basic,
        fetch_adj_factor,
    )
    from src.orchestrator.benchmark import resolve_benchmark_for_strategies
    from src.schemas.strategy import StrategyConfigV1

    cache_dir = config.data_cache_dir
    pro = init_tushare(config.tushare_token or None)

    lookback = max(2, config.data.lookback_years)
    start = (datetime.strptime(ref_date, "%Y%m%d") - timedelta(days=365 * lookback)).strftime("%Y%m%d")

    # Pull configured strategies for benchmark resolution; ignore failures.
    strat_configs = []
    for strategy_path in config.strategies:
        try:
            strat_configs.append(StrategyConfigV1.from_yaml(strategy_path))
        except Exception:
            continue
    benchmark_resolution = resolve_benchmark_for_strategies(config.benchmark, strat_configs)

    fetch_trade_calendar(pro, start, ref_date, cache_dir=cache_dir)
    stock_basic = fetch_stock_basic(pro, cache_dir=cache_dir)
    index_df = pd.DataFrame()
    for candidate in benchmark_resolution.candidates:
        df = fetch_index_daily(pro, candidate, start, ref_date, cache_dir=cache_dir)
        if df is not None and not df.empty:
            index_df = df
            break

    daily_all = fetch_daily_all(pro, start, ref_date, cache_dir=cache_dir)
    daily_basic = fetch_daily_basic(pro, start, ref_date, cache_dir=cache_dir)
    fetch_adj_factor(pro, start, ref_date, cache_dir=cache_dir)

    if daily_all is None or daily_all.empty:
        return None, None, None, None

    # Reuse fina_indicator only if pre-cached on disk.
    fina_df = _load_cached_fina(cache_dir)

    daily_merged = daily_all.merge(
        daily_basic[["ts_code", "trade_date", "pe_ttm", "pb", "turnover_rate"]],
        on=["ts_code", "trade_date"],
        how="left",
    )
    return daily_merged, index_df, fina_df, stock_basic


def _load_cached_fina(cache_dir: str):
    """Best-effort load of any cached fina_indicator parquet bundle."""
    import pandas as pd

    cache_path = Path(cache_dir)
    if not cache_path.is_dir():
        return pd.DataFrame()
    frames = []
    for path in sorted(cache_path.glob("fina_indicator_*.parquet"))[-200:]:
        try:
            frames.append(pd.read_parquet(path))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _make_snapshot_loader(config, symbols: list[str]):
    """Build a loader that returns market snapshots for the watched symbols."""
    import pandas as pd

    cache_dir = Path(config.data_cache_dir)
    symbol_set = set(symbols)

    def _load() -> list[MarketSnapshotV1]:
        latest_path = _latest_daily_parquet(cache_dir)
        if latest_path is None:
            return []
        df = pd.read_parquet(latest_path)
        if symbol_set:
            df = df[df["ts_code"].isin(symbol_set)]
        return snapshots_from_daily_df(df)

    return _load


def _latest_daily_parquet(cache_dir: Path) -> Path | None:
    if not cache_dir.is_dir():
        return None
    candidates = sorted(cache_dir.glob("daily_all_*.parquet"))
    return candidates[-1] if candidates else None


# ── ledger-backed account tracker ─────────────────────────────


class _LedgerTracker:
    """Load / save account state from a JSONL paper-trading ledger.

    On first invocation with an empty ledger, creates a fresh account
    with *capital* cash and zero positions. Each confirmed trade is
    appended to the ledger, and subsequent load_account() calls
    reconstruct the account from all recorded trades.
    """

    def __init__(self, path: str, capital: float) -> None:
        self._path = Path(path)
        self._capital = capital
        self._trades: list[object] = []  # PaperTradeRecordV1 instances

    def load_account(self) -> LiveAccountStateV1:
        """Reconstruct account state from the ledger (or fresh capital)."""
        self._trades = read_paper_trades(self._path)
        if not self._trades:
            return LiveAccountStateV1(
                cash=self._capital,
                total_value=self._capital,
                positions=[],
            )
        # Replay trades to compute current positions and cost basis.
        positions: dict[str, LivePositionV1] = {}
        cash_used = 0.0
        for trade in self._trades:
            code = trade.ts_code
            if trade.action in ("buy", "add"):
                pos = positions.get(code)
                if pos is None:
                    positions[code] = LivePositionV1(
                        ts_code=code,
                        shares=trade.shares,
                        avg_cost=trade.fill_price,
                        last_price=trade.fill_price,
                        market_value=trade.shares * trade.fill_price,
                    )
                else:
                    total_shares = pos.shares + trade.shares
                    total_cost = pos.avg_cost * pos.shares + trade.fill_price * trade.shares
                    positions[code] = LivePositionV1(
                        ts_code=code,
                        shares=total_shares,
                        avg_cost=total_cost / total_shares,
                        last_price=trade.fill_price,
                        market_value=total_shares * trade.fill_price,
                    )
                cash_used += trade.shares * trade.fill_price
            else:
                # sell / reduce
                pos = positions.get(code)
                if pos is None:
                    continue
                remaining = pos.shares - trade.shares
                if remaining <= 0:
                    positions.pop(code, None)
                else:
                    positions[code] = LivePositionV1(
                        ts_code=code,
                        shares=remaining,
                        avg_cost=pos.avg_cost,
                        last_price=trade.fill_price,
                        market_value=remaining * trade.fill_price,
                    )
                cash_used -= trade.shares * trade.fill_price

        market_value = sum(p.market_value for p in positions.values())
        cash = self._capital - cash_used
        return LiveAccountStateV1(
            cash=max(0.0, cash),
            total_value=cash + market_value,
            positions=list(positions.values()),
        )

    def record(self, decision: LiveDecisionV1, *, snapshots: list[MarketSnapshotV1]) -> None:
        """Append an executed trade decision to the ledger."""
        from src.live.ledger import build_paper_trade_record
        from uuid import uuid4

        prices = {s.ts_code: s.last_price for s in snapshots}
        fill_price = prices.get(decision.ts_code, decision.intent.reference_price or 0.0)
        if fill_price <= 0:
            return  # can't record without a price

        account = self.load_account()
        try:
            record = build_paper_trade_record(
                account=account,
                decision=decision,
                execution_id=uuid4().hex[:12],
                trade_date=datetime.now().strftime("%Y%m%d"),
                fill_price=fill_price,
                confirmed=True,
            )
            append_paper_trade(self._path, record)
            self._trades.append(record)
        except ValueError:
            pass  # T+1 violation or duplicate — skip


# ── account / signals / scheduling ─────────────────────────────


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


def _wait_until_tomorrow(stop_event: threading.Event) -> None:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    seconds = (tomorrow - now).total_seconds()
    while seconds > 0 and not stop_event.is_set():
        chunk = min(60.0, seconds)
        stop_event.wait(chunk)
        seconds -= chunk


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handle(signum, frame):
        del frame
        console.print(f"[yellow]Received signal {signum}, stopping trade...[/yellow]")
        stop_event.set()

    try:
        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)
    except ValueError:
        # Not in main thread; let the parent runner manage signals.
        pass
