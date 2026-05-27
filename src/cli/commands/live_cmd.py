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
from pathlib import Path

import typer

from src.cli.output import console
from src.live.signal_engine import build_live_decisions
from src.notify.local_file import LocalFileNotificationSink
from src.notify.message import NotificationMessageV1
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
        sink.send(_message_from_decision(decision))
        notified += 1

    console.print(
        f"[green]Live once complete.[/green] "
        f"decisions={len(decisions)} notifications={notified}"
    )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_list(path: Path) -> list:
    data = _read_json(path)
    if not isinstance(data, list):
        raise typer.BadParameter(f"{path} must contain a JSON list")
    return data


def _message_from_decision(decision) -> NotificationMessageV1:
    action = decision.intent.action
    shares = decision.intent.shares
    price = decision.intent.reference_price
    price_text = "n/a" if price is None else f"{price:.2f}"
    return NotificationMessageV1(
        message_id=f"notify-{decision.decision_id}",
        created_at=decision.created_at,
        severity=decision.severity,
        title=f"{action.upper()} {decision.ts_code}",
        body=(
            f"{decision.strategy_name}: {action} {shares} shares "
            f"of {decision.ts_code} near {price_text}. "
            f"Reason: {decision.intent.reason}"
        ),
        decision_id=decision.decision_id,
        action=action,
        symbols=[decision.ts_code],
    )
