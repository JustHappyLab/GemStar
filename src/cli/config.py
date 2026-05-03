"""GemStar configuration — YAML loader with env var expansion."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

_CONFIG_SEARCH = [
    Path("gemstar.yaml"),
    Path("gemstar.yml"),
    Path(".gemstar.yaml"),
]

_DEFAULT_TEMPLATE = """\
# GemStar 配置文件
# 运行 gemstar init 自动生成，按需修改

# ─── 数据源 ───────────────────────────────────────────────
tushare_token: ${TUSHARE_TOKEN}     # Tushare Pro API token（必需）
benchmark: 399006.SZ                # 基准指数（创业板指）
data_cache_dir: data/raw            # 数据缓存目录（Parquet）

# ─── 数据拉取 ─────────────────────────────────────────────
data:
  auto_fetch: true                  # pipeline 前自动拉取缺失数据
  lookback_years: 2                 # 训练数据回溯年数

# ─── 调度 ─────────────────────────────────────────────────
# 预设: 收盘后 / 盘前 / 深夜
# 自定义: {fetch: "15:30", run: "17:00"}
# 手动模式: null（只用 gemstar run 手动执行）
schedule: "收盘后"

# ─── 路径 ─────────────────────────────────────────────────
pool_path: factors/pool.json        # 因子池
db_path: state.db                   # 状态数据库
artifacts_dir: artifacts            # 产物目录

# ─── LLM 配置 ─────────────────────────────────────────────
# 控制 pipeline 是否启用 LLM 策略生成阶段
# gemstar run --llm 可临时覆盖
llm:
  available: false                  # true = 默认启用 LLM
  provider: api                     # 默认 provider（api / claude_code / gemini_cli / codex_cli）
  base_url: null                    # Anthropic API 代理地址（中国大陆用户设置，如 https://your-proxy.com/v1）

# ─── 策略生成 ──────────────────────────────────────────────
strategy_generation:
  target_count: 3                   # 目标候选策略数
  max_iterations: 10                # 最大迭代次数
  cooldown_seconds: 300             # 每轮冷却（秒）

# ─── 角色 Provider 覆盖 ───────────────────────────────────
# 按角色切换 LLM 后端，无需改 roles/*.yaml
# 可选值: api, claude_code, gemini_cli, codex_cli
# 未列出的角色使用 roles/*.yaml 中的默认配置
#
# 安装与认证:
#   api          → pip install anthropic         → ANTHROPIC_API_KEY
#   claude_code  → npm i -g @anthropic-ai/claude-code → claude 登录
#   gemini_cli   → npm i -g @google/gemini-cli   → gemini 登录
#   codex_cli    → npm i -g @openai/codex        → OPENAI_API_KEY
roles: {}
#  engineer:
#    provider: gemini_cli          # 工程师角色改用 Gemini
#  bugfix:
#    provider: codex_cli           # Bug 修复改用 Codex
#  macro_analyst:
#    provider: claude_code         # 宏观分析改用 Claude Code

# ─── 策略 ─────────────────────────────────────────────────
strategies:
  - strategies/chinext_lstm_mf8/config.yaml
"""

_ENV_RE = re.compile(r"\$\{(\w+)}")

# ── Schedule presets ──────────────────────────────────────────
_PRESETS: dict[str, dict[str, str]] = {
    "收盘后": {"fetch": "15:30", "run": "16:00"},
    "盘前":   {"fetch": "06:00", "run": "07:00"},
    "深夜":   {"fetch": "15:30", "run": "02:00"},
}


class LLMConfig(BaseModel):
    available: bool = False
    provider: str = "api"
    base_url: str | None = None


class RoleOverride(BaseModel):
    provider: str | None = None


class DataConfig(BaseModel):
    auto_fetch: bool = True
    lookback_years: int = 2


class StrategyGenConfig(BaseModel):
    target_count: int = 3
    max_iterations: int = 10
    cooldown_seconds: int = 300


class ScheduleConfig(BaseModel):
    fetch: str = "15:30"
    run: str = "16:00"


def parse_schedule(value: str | dict | None) -> ScheduleConfig | None:
    """Parse schedule config: preset name, time string, dict, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        if value in _PRESETS:
            return ScheduleConfig(**_PRESETS[value])
        # Validate HH:MM format
        parts = value.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return ScheduleConfig(fetch=value, run=value)
        raise ValueError(f"Invalid schedule value: {value!r} (expected preset name or HH:MM)")
    if isinstance(value, dict):
        return ScheduleConfig(**value)
    raise ValueError(f"Invalid schedule value: {value!r}")


class GemStarConfig(BaseModel):
    tushare_token: str = ""
    benchmark: str = "399006.SZ"
    pool_path: str = "factors/pool.json"
    db_path: str = "state.db"
    artifacts_dir: str = "artifacts"
    data_cache_dir: str = "data/raw"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    strategy_generation: StrategyGenConfig = Field(default_factory=StrategyGenConfig)
    schedule: ScheduleConfig | None = None
    roles: dict[str, RoleOverride] = Field(default_factory=dict)
    strategies: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _parse_schedule(cls, values: dict) -> dict:
        if "schedule" in values:
            values["schedule"] = parse_schedule(values["schedule"])
        return values


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

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        return GemStarConfig()
    expanded = _expand_dict(raw)
    return GemStarConfig.model_validate(expanded)


def write_template(dest: Path = Path("gemstar.yaml")) -> Path:
    """Write the default config template to *dest*."""
    dest.write_text(_DEFAULT_TEMPLATE)
    return dest
