"""Feishu custom-bot notification sink.

CALLING SPEC:
    payload = build_feishu_payload(message=NotificationMessageV1)
    sink = FeishuNotificationSink(webhook_url=str, secret=str | None)
    response = sink.send(message=NotificationMessageV1) -> dict

SIDE EFFECTS:
    FeishuNotificationSink.send performs an HTTPS POST through the injected
    opener. Tests should inject a fake opener and must not hit the network.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Callable
from urllib.request import Request, urlopen

from src.notify.message import NotificationMessageV1, format_symbol_labels


UrlOpen = Callable[[Request, float], object]


def build_feishu_payload(
    message: NotificationMessageV1,
    *,
    timestamp: int | None = None,
    secret: str | None = None,
) -> dict:
    """Build a Feishu custom-bot text payload for one notification."""
    payload = {
        "msg_type": "text",
        "content": {
            "text": _feishu_text(message),
        },
    }
    if secret:
        ts = int(time.time()) if timestamp is None else int(timestamp)
        payload["timestamp"] = str(ts)
        payload["sign"] = _sign(ts, secret)
    return payload


class FeishuNotificationSink:
    """Send notifications to a Feishu group through a custom-bot webhook."""

    def __init__(
        self,
        webhook_url: str,
        secret: str | None = None,
        timeout: float = 10.0,
        opener: UrlOpen = urlopen,
    ) -> None:
        if not webhook_url:
            raise ValueError("webhook_url is required")
        if not webhook_url.startswith("https://"):
            raise ValueError("webhook_url must be an https URL")
        self.webhook_url = webhook_url
        self.secret = secret or None
        self.timeout = timeout
        self.opener = opener

    def send(self, message: NotificationMessageV1) -> dict:
        payload = build_feishu_payload(message, secret=self.secret)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url=self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = self.opener(request, timeout=self.timeout)
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def _sign(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _feishu_text(message: NotificationMessageV1) -> str:
    severity_label = {"info": "信息", "warning": "警告", "critical": "严重"}
    label = severity_label.get(message.severity, message.severity)
    symbol_labels = format_symbol_labels(message.symbols, message.symbol_names)
    symbols = ", ".join(symbol_labels) if symbol_labels else "无"
    lines = [
        f"[{label}] {message.title}",
        f"时间：{message.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
        message.body,
    ]
    if "标的：" not in message.body:
        lines.append(f"标的：{symbols}")
    if message.decision_id:
        lines.append(f"决策ID：{message.decision_id}")
    return "\n".join(lines)
