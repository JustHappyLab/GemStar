"""Long-running live radar loop.

CALLING SPEC:
    result = run_live_loop(
        account_loader=Callable[[], LiveAccountStateV1],
        targets_loader=Callable[[], list[TargetHoldingV1]],
        snapshots_loader=Callable[[], list[MarketSnapshotV1]],
        notify=Callable[[NotificationMessageV1], None],
        strategy_name=str,
        stop_event=threading.Event | None,
        now_fn=Callable[[], datetime],
        sleep_fn=Callable[[int], None],
        is_trading_day_fn=Callable[[datetime], bool],
        active_interval=int,
        idle_interval=int,
        max_cycles=int | None,
    ) -> LiveLoopResult

SIDE EFFECTS:
    Calls the injected loaders, notification sink, heartbeat callback, and
    sleep function. This module does not read files or perform network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading
import time
from typing import Callable

from src.live.decision_messages import notification_from_decision
from src.live.market_clock import next_poll_seconds
from src.live.signal_engine import build_live_decisions
from src.notify.message import NotificationMessageV1
from src.schemas.live import LiveAccountStateV1, MarketSnapshotV1, TargetHoldingV1


@dataclass(frozen=True)
class LiveLoopResult:
    cycles: int
    decisions: int
    notifications: int
    deduped: int


HeartbeatFn = Callable[[dict], None]
NotifyFn = Callable[[NotificationMessageV1], None]


def run_live_loop(
    account_loader: Callable[[], LiveAccountStateV1],
    targets_loader: Callable[[], list[TargetHoldingV1]],
    snapshots_loader: Callable[[], list[MarketSnapshotV1]],
    notify: NotifyFn,
    strategy_name: str,
    stop_event: threading.Event | None = None,
    now_fn: Callable[[], datetime] = datetime.now,
    sleep_fn: Callable[[int], None] = time.sleep,
    is_trading_day_fn: Callable[[datetime], bool] | None = None,
    active_interval: int = 30,
    idle_interval: int = 300,
    max_cycles: int | None = None,
    heartbeat_fn: HeartbeatFn | None = None,
) -> LiveLoopResult:
    """Run the live radar loop until stopped or *max_cycles* is reached."""
    if max_cycles is not None and max_cycles <= 0:
        raise ValueError("max_cycles must be positive when provided")

    stop = stop_event or threading.Event()
    trading_day_fn = is_trading_day_fn or (lambda _now: True)
    seen_decision_ids: set[str] = set()
    cycles = 0
    decisions_count = 0
    notifications_count = 0
    deduped_count = 0

    while not stop.is_set():
        now = now_fn()
        decisions = build_live_decisions(
            account=account_loader(),
            targets=targets_loader(),
            snapshots=snapshots_loader(),
            strategy_name=strategy_name,
            created_at=now,
        )
        cycles += 1
        decisions_count += len(decisions)

        for decision in decisions:
            if not decision.notify:
                continue
            if decision.decision_id in seen_decision_ids:
                deduped_count += 1
                continue
            notify(notification_from_decision(decision))
            seen_decision_ids.add(decision.decision_id)
            notifications_count += 1

        is_trading_day = trading_day_fn(now)
        sleep_seconds = next_poll_seconds(
            now,
            active_interval=active_interval,
            idle_interval=idle_interval,
            is_trading_day=is_trading_day,
        )
        if heartbeat_fn is not None:
            heartbeat_fn({
                "now": now.isoformat(),
                "cycle": cycles,
                "decisions": len(decisions),
                "notifications": notifications_count,
                "deduped": deduped_count,
                "sleep_seconds": sleep_seconds,
                "is_trading_day": is_trading_day,
            })

        if max_cycles is not None and cycles >= max_cycles:
            break
        if stop.is_set():
            break
        sleep_fn(sleep_seconds)

    return LiveLoopResult(
        cycles=cycles,
        decisions=decisions_count,
        notifications=notifications_count,
        deduped=deduped_count,
    )
