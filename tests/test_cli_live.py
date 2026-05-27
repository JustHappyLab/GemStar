"""gemstar live CLI command tests."""

import json
from datetime import datetime

from typer.testing import CliRunner

from src.cli.app import app


runner = CliRunner()


def _reset_output_format() -> None:
    import src.cli.app as app_mod
    app_mod._output_format = "table"


def test_live_help_shows_once_command():
    _reset_output_format()

    result = runner.invoke(app, ["live", "--help"])

    assert result.exit_code == 0
    assert "once" in result.output.lower()
    assert "start" in result.output.lower()


def test_live_once_writes_notification_jsonl(tmp_path):
    account_path = tmp_path / "account.json"
    targets_path = tmp_path / "targets.json"
    snapshots_path = tmp_path / "snapshots.json"
    notifications_path = tmp_path / "alerts" / "live.jsonl"

    now = "2026-05-27T10:00:00"
    account_path.write_text(json.dumps({
        "as_of": now,
        "cash": 100000.0,
        "total_value": 100000.0,
        "positions": [],
    }), encoding="utf-8")
    targets_path.write_text(json.dumps([
        {
            "ts_code": "300750.SZ",
            "target_weight": 0.2,
            "target_shares": 200,
            "reason": "top ranked",
        }
    ]), encoding="utf-8")
    snapshots_path.write_text(json.dumps([
        {
            "ts_code": "300750.SZ",
            "trade_date": "20260527",
            "timestamp": now,
            "last_price": 100.5,
            "source": "test",
        }
    ]), encoding="utf-8")

    _reset_output_format()
    result = runner.invoke(app, [
        "live",
        "once",
        "--account",
        str(account_path),
        "--targets",
        str(targets_path),
        "--snapshots",
        str(snapshots_path),
        "--notifications",
        str(notifications_path),
        "--strategy-name",
        "chinext_lstm_mf8",
    ])

    assert result.exit_code == 0, result.output
    assert "notifications=1" in result.output

    rows = [
        json.loads(line)
        for line in notifications_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["title"] == "BUY 300750.SZ"
    assert rows[0]["action"] == "buy"
    assert rows[0]["symbols"] == ["300750.SZ"]
    assert rows[0]["decision_id"] == "20260527-300750.SZ-buy-200"
    assert datetime.fromisoformat(rows[0]["created_at"])


def test_live_start_runs_max_cycles_and_dedupes_notifications(tmp_path):
    account_path, targets_path, snapshots_path = _write_live_inputs(tmp_path)
    notifications_path = tmp_path / "alerts" / "live.jsonl"

    _reset_output_format()
    result = runner.invoke(app, [
        "live",
        "start",
        "--account",
        str(account_path),
        "--targets",
        str(targets_path),
        "--snapshots",
        str(snapshots_path),
        "--notifications",
        str(notifications_path),
        "--strategy-name",
        "chinext_lstm_mf8",
        "--active-interval",
        "1",
        "--idle-interval",
        "1",
        "--max-cycles",
        "2",
    ])

    assert result.exit_code == 0, result.output
    assert "cycles=2" in result.output
    assert "notifications=1" in result.output
    assert "deduped=1" in result.output

    rows = [
        json.loads(line)
        for line in notifications_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["decision_id"] == "20260527-300750.SZ-buy-200"


def _write_live_inputs(tmp_path):
    account_path = tmp_path / "account.json"
    targets_path = tmp_path / "targets.json"
    snapshots_path = tmp_path / "snapshots.json"

    now = "2026-05-27T10:00:00"
    account_path.write_text(json.dumps({
        "as_of": now,
        "cash": 100000.0,
        "total_value": 100000.0,
        "positions": [],
    }), encoding="utf-8")
    targets_path.write_text(json.dumps([
        {
            "ts_code": "300750.SZ",
            "target_weight": 0.2,
            "target_shares": 200,
            "reason": "top ranked",
        }
    ]), encoding="utf-8")
    snapshots_path.write_text(json.dumps([
        {
            "ts_code": "300750.SZ",
            "trade_date": "20260527",
            "timestamp": now,
            "last_price": 100.5,
            "source": "test",
        }
    ]), encoding="utf-8")
    return account_path, targets_path, snapshots_path
