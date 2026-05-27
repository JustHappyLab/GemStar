"""Append-only local JSONL notification sink.

CALLING SPEC:
    sink = LocalFileNotificationSink(path=Path("alerts/live.jsonl"))
    sink.send(message=NotificationMessageV1) -> Path

SIDE EFFECTS:
    Creates parent directories and appends one JSON line per message.
"""

from __future__ import annotations

from pathlib import Path

from src.notify.message import NotificationMessageV1


class LocalFileNotificationSink:
    """Write notifications to an append-only JSONL file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def send(self, message: NotificationMessageV1) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(message.model_dump_json() + "\n")
        return self.path
