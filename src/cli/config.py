"""GemStar configuration — YAML loader with env var expansion."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
benchmark: auto                     # 基准指数，auto 会按策略 universe 自动选择
data_cache_dir: data/raw            # 数据缓存目录（Parquet）

# ─── 数据拉取 ─────────────────────────────────────────────
data:
  scheduler_prefetch: true          # scheduler 在 run 前额外执行 gemstar fetch
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
log_path: logs/gemstar.log          # scheduler 日志路径

# ─── LLM 配置 ─────────────────────────────────────────────
# LLM 探索只由 gemstar research 显式触发；gemstar run/trade 不启用 LLM
llm:
  enabled: false                    # 保留为研究链路配置
  provider: claude_code             # 目前仅支持 claude_code

# ─── 策略生成 ──────────────────────────────────────────────
strategy_generation:
  target_count: 3                   # 目标候选策略数
  max_iterations: 5                 # 最大迭代次数（控制 LLM token 预算）
  cooldown_seconds: 300             # 每轮冷却（秒）

# ─── 工程自愈安全边界 ─────────────────────────────────────
# Engineer/Bugfix 只能在 allowed_paths 内改代码；forbidden_paths 永远优先
# 回测引擎、指标、规则等核心评估逻辑默认冻结
engineering:
  enabled: false                    # true = 允许创建/执行工程自愈任务
  provider: claude_code             # 目前仅支持 claude_code
  auto_execute: true                # true = pipeline 中自动执行 engineer/bugfix task
  auto_apply: false                 # false = 只产出 patch/task，需人工批准合入
  max_attempts: 1
  forbidden_paths:
    - src/engine/**
    - src/judge/**
    - src/portfolio/cost.py
    - src/schemas/metrics.py
    - src/schemas/verdict.py
  engineer:
    allowed_paths:
      - src/ranker/**
      - src/factors/**
      - src/orchestrator/signals.py
      - src/orchestrator/universe.py
      - src/strategies/**
      - src/schemas/strategy.py
      - factors/pool.json
      - strategies/drafts/**
      - tests/**
  bugfix:
    allowed_paths:
      - src/data/**
      - src/orchestrator/**
      - src/strategies/**
      - src/ranker/**
      - src/factors/**
      - tests/**

# ─── 角色 Provider 覆盖 ───────────────────────────────────
# 按角色覆盖仍由 LLM 执行的角色配置，无需改 roles/*.yaml
# model 可选值: sonnet / opus / haiku
# 未列出的角色使用 roles/*.yaml 中的默认配置
# 安装: npm i -g @anthropic-ai/claude-code → claude 登录
roles: {}
#  engineer:
#    provider: claude_code
#    model: opus                   # 工程任务可使用更强模型
#  macro_analyst:
#    provider: claude_code
#    model: sonnet                 # 未配置时默认 sonnet
#  strategy_architect:
#    provider: claude_code
#    model: sonnet

# ─── 策略 ─────────────────────────────────────────────────
# 日常 production/research 治理由 strategies/registry.yaml 管理。
# strategies 保留为没有 registry 时的兼容 fallback。
strategies:
  - strategies/chinext_lstm_mf8/config.yaml
"""

_ENV_RE = re.compile(r"\$\{(\w+)}")
ProviderName = Literal["claude_code"]

DEFAULT_ENGINEERING_FORBIDDEN_PATHS = [
    "src/engine/**",
    "src/judge/**",
    "src/portfolio/cost.py",
    "src/schemas/metrics.py",
    "src/schemas/verdict.py",
]
DEFAULT_ENGINEER_ALLOWED_PATHS = [
    "src/ranker/**",
    "src/factors/**",
    "src/orchestrator/signals.py",
    "src/orchestrator/universe.py",
    "src/strategies/**",
    "src/schemas/strategy.py",
    "factors/pool.json",
    "strategies/drafts/**",
    "tests/**",
]
DEFAULT_BUGFIX_ALLOWED_PATHS = [
    "src/data/**",
    "src/orchestrator/**",
    "src/strategies/**",
    "src/ranker/**",
    "src/factors/**",
    "tests/**",
]

# ── Schedule presets ──────────────────────────────────────────
_PRESETS: dict[str, dict[str, str]] = {
    "收盘后": {"fetch": "15:30", "run": "16:00"},
    "盘前":   {"fetch": "06:00", "run": "07:00"},
    "深夜":   {"fetch": "15:30", "run": "02:00"},
}


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: ProviderName = "claude_code"


class RoleOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderName | None = None
    model: str | None = None


class EngineeringRolePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_paths: list[str] = Field(default_factory=list)


class EngineeringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    provider: ProviderName = "claude_code"
    auto_execute: bool = True
    auto_apply: bool = False
    max_attempts: int = Field(default=1, ge=1, le=5)
    forbidden_paths: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ENGINEERING_FORBIDDEN_PATHS)
    )
    engineer: EngineeringRolePolicy = Field(
        default_factory=lambda: EngineeringRolePolicy(
            allowed_paths=list(DEFAULT_ENGINEER_ALLOWED_PATHS)
        )
    )
    bugfix: EngineeringRolePolicy = Field(
        default_factory=lambda: EngineeringRolePolicy(
            allowed_paths=list(DEFAULT_BUGFIX_ALLOWED_PATHS)
        )
    )


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduler_prefetch: bool = True
    lookback_years: int = 2


class StrategyGenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_count: int = 3
    max_iterations: int = 5
    cooldown_seconds: int = 300


class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

    tushare_token: str = ""
    benchmark: str = "auto"
    pool_path: str = "factors/pool.json"
    db_path: str = "state.db"
    artifacts_dir: str = "artifacts"
    data_cache_dir: str = "data/raw"
    log_path: str = "logs/gemstar.log"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    engineering: EngineeringConfig = Field(default_factory=EngineeringConfig)
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
    """Find the first existing config file in the current directory or parents."""
    for base in [Path.cwd(), *Path.cwd().parents]:
        for p in _CONFIG_SEARCH:
            candidate = base / p
            if candidate.exists():
                return candidate
    return None


def load_config(path: Path | None = None) -> GemStarConfig:
    """Load config from YAML, expanding ${VAR} references.

    If *path* is None, searches for gemstar.yaml / gemstar.yml / .gemstar.yaml
    in the current directory.  Returns defaults if no file is found.
    """
    load_dotenv()
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
