"""Tests for src.cli.config — YAML loader with env var expansion."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.cli.config import (
    GemStarConfig,
    find_config,
    load_config,
    write_template,
)


# ---------------------------------------------------------------------------
# 1. Default values when no YAML file exists
# ---------------------------------------------------------------------------

def test_defaults_when_no_file(tmp_path, monkeypatch):
    """load_config() returns sensible defaults when no config file exists."""
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.tushare_token == ""
    assert cfg.benchmark == "399006.SZ"
    assert cfg.pool_path == "factors/pool.json"
    assert cfg.db_path == "state.db"
    assert cfg.artifacts_dir == "artifacts"
    assert cfg.data_cache_dir == "data/raw"
    assert cfg.llm.available is False
    assert cfg.llm.provider == "api"
    assert cfg.strategies == []


# ---------------------------------------------------------------------------
# 2. Valid YAML — all fields parsed correctly
# ---------------------------------------------------------------------------

def test_load_valid_yaml_all_fields(tmp_path):
    yaml_content = """\
tushare_token: mytoken123
benchmark: 000300.SH
pool_path: custom/pool.json
db_path: custom.db
artifacts_dir: out
data_cache_dir: cache/raw
llm:
  available: true
  provider: openai
strategies:
  - strategies/s1/config.yaml
  - strategies/s2/config.yaml
"""
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text(yaml_content)

    cfg = load_config(cfg_path)
    assert cfg.tushare_token == "mytoken123"
    assert cfg.benchmark == "000300.SH"
    assert cfg.pool_path == "custom/pool.json"
    assert cfg.db_path == "custom.db"
    assert cfg.artifacts_dir == "out"
    assert cfg.data_cache_dir == "cache/raw"
    assert cfg.llm.available is True
    assert cfg.llm.provider == "openai"
    assert cfg.strategies == [
        "strategies/s1/config.yaml",
        "strategies/s2/config.yaml",
    ]


# ---------------------------------------------------------------------------
# 3. ${VAR} expansion in string values
# ---------------------------------------------------------------------------

def test_env_var_expansion_string(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_TUSHARE_TOKEN", "secret_abc")
    yaml_content = "tushare_token: ${MY_TUSHARE_TOKEN}\nbenchmark: 000300.SH\n"
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text(yaml_content)

    cfg = load_config(cfg_path)
    assert cfg.tushare_token == "secret_abc"


# ---------------------------------------------------------------------------
# 4. ${VAR} expansion in nested dict (llm.available, llm.provider)
# ---------------------------------------------------------------------------

def test_env_var_expansion_nested(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    yaml_content = """\
llm:
  provider: ${LLM_PROVIDER}
"""
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text(yaml_content)

    cfg = load_config(cfg_path)
    assert cfg.llm.provider == "anthropic"


# ---------------------------------------------------------------------------
# 5. write_template() creates a file with expected content
# ---------------------------------------------------------------------------

def test_write_template_creates_file(tmp_path):
    dest = tmp_path / "gemstar.yaml"
    result = write_template(dest)

    assert result == dest
    assert dest.exists()
    text = dest.read_text()
    assert "tushare_token: ${TUSHARE_TOKEN}" in text
    assert "benchmark: 399006.SZ" in text
    assert "llm:" in text


# ---------------------------------------------------------------------------
# 6. find_config() finds files in order: gemstar.yaml, gemstar.yml, .gemstar.yaml
# ---------------------------------------------------------------------------

def test_find_config_prefers_gemstar_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gemstar.yaml").write_text("benchmark: A\n")
    (tmp_path / "gemstar.yml").write_text("benchmark: B\n")
    (tmp_path / ".gemstar.yaml").write_text("benchmark: C\n")

    found = find_config()
    assert found is not None
    assert found.name == "gemstar.yaml"


def test_find_config_falls_back_to_yml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gemstar.yml").write_text("benchmark: B\n")
    (tmp_path / ".gemstar.yaml").write_text("benchmark: C\n")

    found = find_config()
    assert found is not None
    assert found.name == "gemstar.yml"


def test_find_config_falls_back_to_dotfile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gemstar.yaml").write_text("benchmark: C\n")

    found = find_config()
    assert found is not None
    assert found.name == ".gemstar.yaml"


# ---------------------------------------------------------------------------
# 7. find_config() returns None when no config exists
# ---------------------------------------------------------------------------

def test_find_config_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert find_config() is None


# ---------------------------------------------------------------------------
# 8. Invalid YAML returns defaults (not crash)
# ---------------------------------------------------------------------------

def test_invalid_yaml_returns_defaults(tmp_path):
    """Non-mapping YAML (bare string) should return defaults, not crash."""
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text("just a bare string, not a mapping")

    cfg = load_config(cfg_path)
    assert cfg.tushare_token == ""
    assert cfg.benchmark == "399006.SZ"
    assert cfg.llm.available is False
    assert cfg.strategies == []


# ---------------------------------------------------------------------------
# 9. Empty YAML file returns defaults
# ---------------------------------------------------------------------------

def test_empty_yaml_returns_defaults(tmp_path):
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text("")

    cfg = load_config(cfg_path)
    assert cfg.tushare_token == ""
    assert cfg.benchmark == "399006.SZ"
    assert cfg.llm.available is False
    assert cfg.llm.provider == "api"
    assert cfg.strategies == []
