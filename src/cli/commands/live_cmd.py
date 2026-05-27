"""gemstar live — run live trading radar commands.

CALLING SPEC:
    live_once_cmd(
        account_path=str,
        targets_path=str,
        snapshots_path=str,
        notifications_path=str,
        strategy_name=str,
    ) -> None

SIDE EFFECTS:
    Reads local JSON files and appends actionable notifications to JSONL.
"""

from __future__ import annotations

import json
import signal
import threading
from pathlib import Path

import typer

from src.cli.output import console
from src.live.decision_messages import notification_from_decision
from src.live.loop import run_live_loop
from src.live.signal_engine import build_live_decisions
from src.notify.local_file import LocalFileNotificationSink
from src.schemas.live import LiveAccountStateV1, MarketSnapshotV1, TargetHoldingV1


def live_once_cmd(
    account_path: str = typer.Option(..., "--account", help="LiveAccountStateV1 JSON path."),
    targets_path: str = typer.Option(..., "--targets", help="List[TargetHoldingV1] JSON path."),
    snapshots_path: str = typer.Option(..., "--snapshots", help="List[MarketSnapshotV1] JSON path."),
    notifications_path: str = typer.Option(
        "alerts/live.jsonl",
        "--notifications",
        help="Append-only notification JSONL path.",
    ),
    strategy_name: str = typer.Option("live", "--strategy-name", help="Strategy name for decision metadata."),
) -> None:
    """Run one local live decision cycle."""
    account = LiveAccountStateV1.model_validate(_read_json(Path(account_path)))
    targets = [
        TargetHoldingV1.model_validate(item)
        for item in _read_json_list(Path(targets_path))
    ]
    snapshots = [
        MarketSnapshotV1.model_validate(item)
        for item in _read_json_list(Path(snapshots_path))
    ]

    decisions = build_live_decisions(
        account=account,
        targets=targets,
        snapshots=snapshots,
        strategy_name=strategy_name,
    )

    sink = LocalFileNotificationSink(notifications_path)
    notified = 0
    for decision in decisions:
        if not decision.notify:
            continue
        sink.send(notification_from_decision(decision))
        notified += 1

    console.print(
        f"[green]Live once complete.[/green] "
        f"decisions={len(decisions)} notifications={notified}"
    )


def live_start_cmd(
    account_path: str = typer.Option(..., "--account", help="LiveAccountStateV1 JSON path."),
    targets_path: str = typer.Option(..., "--targets", help="List[TargetHoldingV1] JSON path."),
    snapshots_path: str = typer.Option(..., "--snapshots", help="List[MarketSnapshotV1] JSON path."),
    notifications_path: str = typer.Option(
        "alerts/live.jsonl",
        "--notifications",
        help="Append-only notification JSONL path.",
    ),
    strategy_name: str = typer.Option("live", "--strategy-name", help="Strategy name for decision metadata."),
    active_interval: int = typer.Option(30, "--active-interval", help="Polling seconds during trading sessions."),
    idle_interval: int = typer.Option(300, "--idle-interval", help="Polling seconds outside trading sessions."),
    max_cycles: int | None = typer.Option(None, "--max-cycles", help="Stop after N cycles; useful for smoke tests."),
) -> None:
    """Run the live radar loop until stopped."""
    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        del frame
        console.print(f"[yellow]Received signal {signum}, stopping live radar...[/yellow]")
        stop_event.set()

    old_term = signal.signal(signal.SIGTERM, _handle_signal)
    old_int = signal.signal(signal.SIGINT, _handle_signal)

    sink = LocalFileNotificationSink(notifications_path)
    try:
        result = run_live_loop(
            account_loader=lambda: _load_account(Path(account_path)),
            targets_loader=lambda: _load_targets(Path(targets_path)),
            snapshots_loader=lambda: _load_snapshots(Path(snapshots_path)),
            notify=sink.send,
            strategy_name=strategy_name,
            stop_event=stop_event,
            active_interval=active_interval,
            idle_interval=idle_interval,
            max_cycles=max_cycles,
            heartbeat_fn=lambda event: console.print(
                "[dim]live heartbeat "
                f"cycle={event['cycle']} decisions={event['decisions']} "
                f"notifications={event['notifications']} sleep={event['sleep_seconds']}s[/dim]"
            ),
        )
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)

    console.print(
        f"[green]Live radar stopped.[/green] cycles={result.cycles} "
        f"decisions={result.decisions} notifications={result.notifications} "
        f"deduped={result.deduped}"
    )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_list(path: Path) -> list:
    data = _read_json(path)
    if not isinstance(data, list):
        raise typer.BadParameter(f"{path} must contain a JSON list")
    return data


def _load_account(path: Path) -> LiveAccountStateV1:
    return LiveAccountStateV1.model_validate(_read_json(path))


def _load_targets(path: Path) -> list[TargetHoldingV1]:
    return [
        TargetHoldingV1.model_validate(item)
        for item in _read_json_list(path)
    ]


def _load_snapshots(path: Path) -> list[MarketSnapshotV1]:
    return [
        MarketSnapshotV1.model_validate(item)
        for item in _read_json_list(path)
    ]
