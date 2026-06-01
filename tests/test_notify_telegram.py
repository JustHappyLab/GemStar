"""Tests for Telegram notification sink without network access."""

import json
from datetime import datetime

import pytest

from src.notify.message import NotificationMessageV1
from src.notify.telegram import TelegramNotificationSink, build_telegram_payload


def _message() -> NotificationMessageV1:
    return NotificationMessageV1(
        message_id="msg-1",
        created_at=datetime(2026, 5, 27, 10, 0, 0),
        severity="warning",
        title="BUY 300750.SZ",
        body="chinext_lstm_mf8: buy 200 shares near 100.50",
        decision_id="20260527-300750.SZ-buy-200",
        action="buy",
        symbols=["300750.SZ"],
        symbol_names={"300750.SZ": "宁德时代"},
    )


def test_build_telegram_payload_contains_actionable_fields():
    payload = build_telegram_payload(_message(), chat_id="chat-1")

    assert payload["chat_id"] == "chat-1"
    assert payload["disable_web_page_preview"] is True
    assert "[警告] BUY 300750.SZ" in payload["text"]
    assert "标的：300750.SZ 宁德时代" in payload["text"]
    assert "决策ID：20260527-300750.SZ-buy-200" in payload["text"]


def test_telegram_sink_rejects_missing_credentials():
    with pytest.raises(ValueError):
        TelegramNotificationSink(bot_token="", chat_id="chat-1")

    with pytest.raises(ValueError):
        TelegramNotificationSink(bot_token="token", chat_id="")


def test_telegram_sink_posts_json_with_injected_opener():
    captured = {}

    class FakeResponse:
        def read(self):
            return b'{"ok": true, "result": {"message_id": 123}}'

    def fake_opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    sink = TelegramNotificationSink(
        bot_token="token-123",
        chat_id="chat-1",
        timeout=3.0,
        opener=fake_opener,
    )

    response = sink.send(_message())

    assert response["ok"] is True
    assert captured["url"] == "https://api.telegram.org/bottoken-123/sendMessage"
    assert captured["timeout"] == 3.0
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["payload"]["chat_id"] == "chat-1"
    assert "[警告] BUY 300750.SZ" in captured["payload"]["text"]
    assert "标的：300750.SZ 宁德时代" in captured["payload"]["text"]
