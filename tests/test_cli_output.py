"""Tests for src.cli.output — emit() formatting logic."""

from __future__ import annotations

import json

from src.cli.output import emit


def test_emit_dict_json_outputs_valid_json(capsys):
    data = {"symbol": "600519", "score": 0.95}
    emit(data, format="json")
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["symbol"] == "600519"
    assert parsed["score"] == 0.95


def test_emit_list_of_dicts_json_outputs_valid_json_array(capsys):
    data = [{"name": "alpha", "weight": 0.3}, {"name": "beta", "weight": 0.7}]
    emit(data, format="json")
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[1]["name"] == "beta"


def test_emit_str_json_outputs_json_string(capsys):
    emit("hello world", format="json")
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed == "hello world"


def test_emit_dict_table_prints_table(capsys):
    data = {"key1": "val1", "key2": "val2"}
    emit(data, format="table")
    out = capsys.readouterr().out
    assert "key1" in out
    assert "val1" in out
    assert "key2" in out
    assert "val2" in out


def test_emit_list_of_dicts_table_prints_multi_row(capsys):
    data = [
        {"col_a": 1, "col_b": 2},
        {"col_a": 3, "col_b": 4},
    ]
    emit(data, format="table")
    out = capsys.readouterr().out
    assert "col_a" in out
    assert "col_b" in out
    assert "1" in out
    assert "4" in out


def test_emit_str_table_prints_plain_text(capsys):
    emit("simple message", format="table")
    out = capsys.readouterr().out
    assert "simple message" in out
