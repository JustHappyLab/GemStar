"""Tests for local JSONL notification sink."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.notify.local_file import LocalFileNotificationSink
from src.notify.message import NotificationMessageV1


def _message(message_id: str, title: str = "Buy signal") -> NotificationMessageV1:
    return NotificationMessageV1(
        message_id=message_id,
        created_at=datetime(2026, 5, 27, 10, 0, 0),
        severity="warning",
        title=title,
        body="300750.SZ buy 100 shares",
        decision_id=f"decision-{message_id}",
        action="buy",
        symbols=["300750.SZ"],
    )


def test_notification_message_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        NotificationMessageV1(
            message_id="msg-1",
            title="Buy signal",
            body="body",
            unexpected=True,
        )


def test_local_file_sink_writes_one_json_line(tmp_path):
    path = tmp_path / "alerts" / "live.jsonl"
    sink = LocalFileNotificationSink(path)

    written = sink.send(_message("msg-1"))

    assert written == path
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["message_id"] == "msg-1"
    assert payload["severity"] == "warning"
    assert payload["symbols"] == ["300750.SZ"]


def test_local_file_sink_preserves_append_order(tmp_path):
    path = tmp_path / "alerts" / "live.jsonl"
    sink = LocalFileNotificationSink(path)

    sink.send(_message("msg-1", title="First"))
    sink.send(_message("msg-2", title="Second"))

    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["message_id"] for row in rows] == ["msg-1", "msg-2"]
    assert [row["title"] for row in rows] == ["First", "Second"]


def test_local_file_sink_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "alerts" / "live.jsonl"

    LocalFileNotificationSink(path).send(_message("msg-1"))

    assert path.exists()
