"""Telegram notification sink.

CALLING SPEC:
    payload = build_telegram_payload(message=NotificationMessageV1, chat_id=str)
    sink = TelegramNotificationSink(bot_token=str, chat_id=str)
    response = sink.send(message=NotificationMessageV1) -> dict

SIDE EFFECTS:
    TelegramNotificationSink.send performs an HTTPS POST through the injected
    opener. Tests should inject a fake opener and must not hit the network.
"""

from __future__ import annotations

import json
from typing import Callable
from urllib.request import Request, urlopen

from src.notify.message import NotificationMessageV1


UrlOpen = Callable[[Request, float], object]


def build_telegram_payload(message: NotificationMessageV1, chat_id: str) -> dict:
    """Build a Telegram sendMessage payload for one GemStar notification."""
    return {
        "chat_id": chat_id,
        "text": _telegram_text(message),
        "disable_web_page_preview": True,
    }


class TelegramNotificationSink:
    """Send notifications to a Telegram chat via Bot API."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout: float = 10.0,
        opener: UrlOpen = urlopen,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token is required")
        if not chat_id:
            raise ValueError("chat_id is required")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self.opener = opener

    def send(self, message: NotificationMessageV1) -> dict:
        payload = build_telegram_payload(message, self.chat_id)
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url=f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = self.opener(request, timeout=self.timeout)
        body = response.read().decode("utf-8")
        return json.loads(body)


def _telegram_text(message: NotificationMessageV1) -> str:
    symbols = ", ".join(message.symbols) if message.symbols else "n/a"
    lines = [
        f"[{message.severity.upper()}] {message.title}",
        message.body,
        f"symbols: {symbols}",
    ]
    if message.decision_id:
        lines.append(f"decision: {message.decision_id}")
    return "\n".join(lines)
