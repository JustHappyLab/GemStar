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
    assert cfg.benchmark == "auto"
    assert cfg.pool_path == "factors/pool.json"
    assert cfg.db_path == "state.db"
    assert cfg.artifacts_dir == "artifacts"
    assert cfg.data_cache_dir == "data/raw"
    assert cfg.llm.enabled is False
    assert cfg.llm.provider == "claude_code"
    assert cfg.engineering.enabled is False
    assert cfg.engineering.provider == "claude_code"
    assert cfg.engineering.auto_execute is True
    assert "src/engine/**" in cfg.engineering.forbidden_paths
    assert "src/ranker/**" in cfg.engineering.engineer.allowed_paths
    assert "src/data/**" in cfg.engineering.bugfix.allowed_paths
    assert cfg.strategy_generation.max_iterations == 5
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
  enabled: true
  provider: claude_code
engineering:
  enabled: true
  provider: claude_code
  auto_execute: false
  auto_apply: false
  max_attempts: 2
  forbidden_paths:
    - src/engine/**
  engineer:
    allowed_paths:
      - src/factors/**
  bugfix:
    allowed_paths:
      - src/data/**
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
    assert cfg.llm.enabled is True
    assert cfg.llm.provider == "claude_code"
    assert cfg.engineering.enabled is True
    assert cfg.engineering.provider == "claude_code"
    assert cfg.engineering.auto_execute is False
    assert cfg.engineering.max_attempts == 2
    assert cfg.engineering.forbidden_paths == ["src/engine/**"]
    assert cfg.engineering.engineer.allowed_paths == ["src/factors/**"]
    assert cfg.engineering.bugfix.allowed_paths == ["src/data/**"]
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
# 4. ${VAR} expansion in nested dict (llm.enabled, llm.provider)
# ---------------------------------------------------------------------------

def test_env_var_expansion_nested(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude_code")
    yaml_content = """\
llm:
  provider: ${LLM_PROVIDER}
"""
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text(yaml_content)

    cfg = load_config(cfg_path)
    assert cfg.llm.provider == "claude_code"


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
    assert "benchmark: auto" in text
    assert "llm:" in text
    assert "engineering:" in text
    assert "src/engine/**" in text


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


def test_find_config_searches_parent_directories(tmp_path, monkeypatch):
    (tmp_path / "gemstar.yaml").write_text("benchmark: parent\n")
    child = tmp_path / "nested" / "child"
    child.mkdir(parents=True)
    monkeypatch.chdir(child)

    found = find_config()

    assert found == tmp_path / "gemstar.yaml"


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
    assert cfg.benchmark == "auto"
    assert cfg.llm.enabled is False
    assert cfg.strategies == []


# ---------------------------------------------------------------------------
# 9. Empty YAML file returns defaults
# ---------------------------------------------------------------------------

def test_empty_yaml_returns_defaults(tmp_path):
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text("")

    cfg = load_config(cfg_path)
    assert cfg.tushare_token == ""
    assert cfg.benchmark == "auto"
    assert cfg.llm.enabled is False
    assert cfg.llm.provider == "claude_code"


def test_llm_available_is_rejected(tmp_path):
    """Old llm.available config is rejected instead of silently supported."""
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text("llm:\n  available: true\n")

    with pytest.raises(Exception, match="available"):
        load_config(cfg_path)


def test_invalid_llm_provider_is_rejected(tmp_path):
    """Unknown LLM providers fail during config loading."""
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text("llm:\n  provider: openai\n")

    with pytest.raises(Exception, match="provider"):
        load_config(cfg_path)


def test_engineering_provider_rejects_api(tmp_path):
    """Engineering automation must use a CLI provider because it can edit files."""
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text("engineering:\n  enabled: true\n  provider: api\n")

    with pytest.raises(Exception, match="provider"):
        load_config(cfg_path)


def test_data_auto_fetch_is_rejected(tmp_path):
    """Old data.auto_fetch is rejected; scheduler_prefetch is the supported field."""
    cfg_path = tmp_path / "gemstar.yaml"
    cfg_path.write_text("data:\n  auto_fetch: true\n")

    with pytest.raises(Exception, match="auto_fetch"):
        load_config(cfg_path)
