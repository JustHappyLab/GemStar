"""gemstar alerts — inspect generated notification messages.

CALLING SPEC:
    alerts_latest_cmd(
        notifications_path=str,
        limit=int,
    ) -> None

SIDE EFFECTS:
    Reads an append-only notification JSONL file and prints a human-readable
    summary or JSON output.
"""

from __future__ import annotations

from pathlib import Path

import typer

from src.cli.output import console, emit, get_output_format
from src.notify.message import NotificationMessageV1


def alerts_latest_cmd(
    notifications_path: str = typer.Option(
        "alerts/live.jsonl",
        "--notifications",
        help="Append-only notification JSONL path.",
    ),
    limit: int = typer.Option(5, "--limit", "-n", help="Number of latest alerts to show."),
) -> None:
    """Show the latest GemStar alert messages."""
    if limit <= 0:
        raise typer.BadParameter("limit must be positive")

    path = Path(notifications_path)
    messages = read_latest_notifications(path, limit=limit)

    if get_output_format() == "json":
        emit([m.model_dump(mode="json") for m in messages], format="json")
        return

    console.print(format_latest_notifications(messages, path=path))


def read_latest_notifications(path: str | Path, limit: int = 5) -> list[NotificationMessageV1]:
    """Read the last *limit* valid notification records from JSONL."""
    p = Path(path)
    if not p.exists():
        return []

    records: list[NotificationMessageV1] = []
    for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(NotificationMessageV1.model_validate_json(line))
        except Exception as exc:
            raise ValueError(f"invalid notification JSONL at {p}:{line_no}") from exc
    return records[-limit:]


def format_latest_notifications(
    messages: list[NotificationMessageV1],
    path: str | Path = "alerts/live.jsonl",
) -> str:
    """Format latest alerts for chat-style channels like QClaw/WeChat."""
    if not messages:
        return f"GemStar 暂无提醒（{Path(path)} 不存在或为空）。"

    lines = [f"GemStar 最新提醒（{len(messages)} 条）"]
    for index, message in enumerate(messages, start=1):
        lines.extend([
            "",
            f"{index}. {message.title}",
            f"时间：{message.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
            message.body,
        ])
        if message.decision_id:
            lines.append(f"决策ID：{message.decision_id}")
    return "\n".join(lines)
