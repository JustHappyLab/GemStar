"""gemstar alerts CLI command tests."""

import json
from datetime import datetime

from typer.testing import CliRunner

from src.cli.app import app


runner = CliRunner()


def _reset_output_format() -> None:
    import src.cli.app as app_mod
    app_mod._output_format = "table"


def test_alerts_latest_shows_chat_friendly_text(tmp_path):
    notifications_path = tmp_path / "alerts" / "live.jsonl"
    notifications_path.parent.mkdir(parents=True)
    notifications_path.write_text(
        json.dumps({
            "version": "NotificationMessageV1",
            "message_id": "msg-1",
            "created_at": "2026-06-02T10:00:00",
            "severity": "warning",
            "title": "[买入] 300750.SZ 宁德时代",
            "body": "标的：300750.SZ 宁德时代\n操作：买入 200 股\n状态：可执行",
            "decision_id": "20260602-300750.SZ-buy-200",
            "action": "buy",
            "symbols": ["300750.SZ"],
            "symbol_names": {"300750.SZ": "宁德时代"},
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    _reset_output_format()
    result = runner.invoke(app, [
        "alerts",
        "latest",
        "--notifications",
        str(notifications_path),
    ])

    assert result.exit_code == 0, result.output
    assert "GemStar 最新提醒（1 条）" in result.output
    assert "[买入] 300750.SZ 宁德时代" in result.output
    assert "状态：可执行" in result.output
    assert "决策ID：20260602-300750.SZ-buy-200" in result.output


def test_alerts_latest_json_output(tmp_path):
    notifications_path = tmp_path / "alerts.jsonl"
    notifications_path.write_text(
        json.dumps({
            "message_id": "msg-1",
            "created_at": datetime(2026, 6, 2, 10, 0, 0).isoformat(),
            "severity": "warning",
            "title": "[买入] 300750.SZ 宁德时代",
            "body": "body",
            "symbols": ["300750.SZ"],
            "symbol_names": {"300750.SZ": "宁德时代"},
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    _reset_output_format()
    result = runner.invoke(app, [
        "--output",
        "json",
        "alerts",
        "latest",
        "--notifications",
        str(notifications_path),
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["message_id"] == "msg-1"
    assert payload[0]["symbol_names"] == {"300750.SZ": "宁德时代"}


def test_alerts_latest_handles_missing_file(tmp_path):
    _reset_output_format()
    result = runner.invoke(app, [
        "alerts",
        "latest",
        "--notifications",
        str(tmp_path / "missing.jsonl"),
    ])

    assert result.exit_code == 0, result.output
    assert "暂无提醒" in result.output
