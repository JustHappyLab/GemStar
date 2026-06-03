"""Tests for Feishu notification sink without network access."""

import json
from datetime import datetime

import pytest

from src.notify.feishu import FeishuNotificationSink, build_feishu_payload
from src.notify.message import NotificationMessageV1


def _message() -> NotificationMessageV1:
    return NotificationMessageV1(
        message_id="msg-1",
        created_at=datetime(2026, 5, 27, 10, 0, 0),
        severity="warning",
        title="BUY 300750.SZ",
        body=(
            "结论：建议买入 200 股（可执行）\n"
            "标的：300750.SZ 宁德时代\n"
            "策略：chinext_lstm_mf8"
        ),
        decision_id="20260527-300750.SZ-buy-200",
        action="buy",
        symbols=["300750.SZ"],
        symbol_names={"300750.SZ": "宁德时代"},
    )


def test_build_feishu_payload_contains_actionable_fields():
    payload = build_feishu_payload(_message())

    assert payload["msg_type"] == "text"
    text = payload["content"]["text"]
    assert "[警告] BUY 300750.SZ" in text
    assert "时间：2026-05-27 10:00:00" in text
    assert "标的：300750.SZ 宁德时代" in text
    assert text.count("标的：300750.SZ 宁德时代") == 1
    assert "决策ID：20260527-300750.SZ-buy-200" in text


def test_build_feishu_payload_can_sign_custom_bot_request():
    payload = build_feishu_payload(_message(), timestamp=1234567890, secret="secret-1")

    assert payload["timestamp"] == "1234567890"
    assert payload["sign"]


def test_feishu_sink_rejects_missing_or_insecure_webhook():
    with pytest.raises(ValueError):
        FeishuNotificationSink(webhook_url="")

    with pytest.raises(ValueError):
        FeishuNotificationSink(webhook_url="http://example.test/hook")


def test_feishu_sink_posts_json_with_injected_opener():
    captured = {}

    class FakeResponse:
        def read(self):
            return b'{"StatusCode": 0, "msg": "success"}'

    def fake_opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    sink = FeishuNotificationSink(
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/token-123",
        timeout=3.0,
        opener=fake_opener,
    )

    response = sink.send(_message())

    assert response["StatusCode"] == 0
    assert captured["url"] == "https://open.feishu.cn/open-apis/bot/v2/hook/token-123"
    assert captured["timeout"] == 3.0
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["payload"]["msg_type"] == "text"
    assert "[警告] BUY 300750.SZ" in captured["payload"]["content"]["text"]
