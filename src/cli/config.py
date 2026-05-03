"""GemStar configuration — YAML loader with env var expansion."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_CONFIG_SEARCH = [
    Path("gemstar.yaml"),
    Path("gemstar.yml"),
    Path(".gemstar.yaml"),
]

_DEFAULT_TEMPLATE = """\
# GemStar configuration
tushare_token: ${TUSHARE_TOKEN}
benchmark: 399006.SZ
pool_path: factors/pool.json
db_path: state.db
artifacts_dir: artifacts
data_cache_dir: data/raw

llm:
  available: false
  provider: api

strategies:
  - strategies/chinext_lstm_mf8/config.yaml
"""

_ENV_RE = re.compile(r"\$\{(\w+)}")


class LLMConfig(BaseModel):
    available: bool = False
    provider: str = "api"


class GemStarConfig(BaseModel):
    tushare_token: str = ""
    benchmark: str = "399006.SZ"
    pool_path: str = "factors/pool.json"
    db_path: str = "state.db"
    artifacts_dir: str = "artifacts"
    data_cache_dir: str = "data/raw"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    strategies: list[str] = Field(default_factory=list)


def _expand_env(value: str) -> str:
    """Expand ${VAR} references in a string."""
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _expand_dict(obj):
    """Recursively expand env vars in a dict."""
    if isinstance(obj, str):
        return _expand_env(obj)
    if isinstance(obj, dict):
        return {k: _expand_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_dict(v) for v in obj]
    return obj


def find_config() -> Path | None:
    """Find the first existing config file in the search order."""
    for p in _CONFIG_SEARCH:
        if p.exists():
            return p
    return None


def load_config(path: Path | None = None) -> GemStarConfig:
    """Load config from YAML, expanding ${VAR} references.

    If *path* is None, searches for gemstar.yaml / gemstar.yml / .gemstar.yaml
    in the current directory.  Returns defaults if no file is found.
    """
    if path is None:
        path = find_config()
    if path is None or not path.exists():
        return GemStarConfig()

    raw = yaml.safe_load(path.read_text()) or {}
    expanded = _expand_dict(raw)
    return GemStarConfig.model_validate(expanded)


def write_template(dest: Path = Path("gemstar.yaml")) -> Path:
    """Write the default config template to *dest*."""
    dest.write_text(_DEFAULT_TEMPLATE)
    return dest
