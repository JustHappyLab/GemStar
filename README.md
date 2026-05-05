# GemStar

AI 驱动的自动化量化研究框架。FSM 驱动的多 Agent 日频 Pipeline，自动完成数据质检 → 因子监控 → 策略生成 → 回测 → 评审。

---

## Pipeline

14 状态有限状态机驱动，每个交易日自动执行完整研究流程：

```
COLLECTING → QUALITY_CHECKING → FACTOR_MONITORING → STRATEGY_IDEATION →
STRATEGY_VALIDATION → BACKTESTING → JUDGING → LEADERBOARD_BUILDING →
REPORTING → COMPLETED
```

### 核心模块

| 模块 | 职责 |
|------|------|
| DataQualityGate | 数据完整性检查，输出 pass/degraded/abort |
| FactorHealthMonitor | 基于 IC/IR 的因子健康度分析 |
| MacroAnalyst | LLM 评估市场宏观状态（regime + style bias） |
| EventScanner | LLM 扫描近期市场事件信号 |
| ResearchAnalyst | LLM 生成研究 ticket（假设 + 因子关联） |
| StrategyArchitect | LLM 从 ticket 草拟策略 YAML |
| RuleJudge | 规则引擎评估回测结果（gate 通过/拒绝） |
| Reviewer | LLM 生成评审意见（解释 + 风险 + 置信度） |
| IncidentFSM | 7 状态故障分类与自愈流程 |

### Role / Provider / Skill 三层架构

```
roles/*.yaml          skills/*/             src/llm/providers/
├── provider: api     ├── prompt.txt        ├── api_provider.py
├── skills:           ├── sop.md            ├── claude_code_provider.py
│   - analyze_market  └── schema.json       ├── gemini_cli_provider.py
└── approval: true                            └── codex_cli_provider.py
```

- **Role** — YAML 配置，定义使用哪个 provider、加载哪些 skill、是否需要人工批准
- **Skill** — 可复用的 SOP 单元（prompt + 流程文档 + 输出 schema），多个 role 可共享
- **Provider** — 统一的 agent 执行接口（API / Claude Code / Gemini CLI / Codex CLI）

用户可通过修改 `roles/*.yaml` 中的 `provider` 字段切换 LLM 后端，无需改代码。

#### 角色配置

| 角色 | Provider | Skills | 需要批准 |
|------|----------|--------|----------|
| macro_analyst | api | analyze_market | 否 |
| event_scanner | api | scan_events | 否 |
| research_analyst | api | generate_tickets | 否 |
| strategy_architect | api | draft_strategy | 否 |
| reviewer | api | review_verdict | 否 |
| engineer | claude_code | write_code, fix_bug | 是 |
| bugfix | claude_code | fix_bug | 是 |

#### Skill 目录

每个 skill 目录包含三个文件：

| 文件 | 用途 |
|------|------|
| `prompt.txt` | LLM 系统提示词 |
| `sop.md` | 标准操作流程文档（供人阅读） |
| `schema.json` | 输出 JSON schema（用于校验 LLM 输出） |

| Skill | 用途 |
|-------|------|
| analyze_market | 评估市场宏观状态（regime + style bias） |
| scan_events | 扫描近期市场事件信号 |
| generate_tickets | 从市场上下文生成研究 ticket |
| draft_strategy | 从 research ticket 草拟策略 YAML |
| review_verdict | 生成回测评审意见（解释 + 风险 + 置信度） |
| write_code | 代码编写（engineer 角色使用） |
| fix_bug | Bug 修复（engineer/bugfix 角色使用） |

#### Provider 实现

| Provider | 后端 | 说明 |
|----------|------|------|
| api | Anthropic API | 直接调用 Claude API，适合批量自动化 |
| claude_code | Claude Code CLI | 子进程调用，适合需要文件操作的任务 |
| gemini_cli | Gemini CLI | 子进程调用 Google Gemini |
| codex_cli | Codex CLI | 子进程调用 OpenAI Codex |

### 事件流

所有 Role 执行通过 `RoleEvent` 产生可观测事件（started/completed/failed），支持执行监控和调试。

---

## 项目结构

```
GemStar/
├── .env.example                # 环境变量模板
├── pyproject.toml              # 项目配置 + 依赖管理 (uv)
├── gemstar.yaml                # 项目配置（gemstar init 生成）
├── tools/                      # 附属工具
│   ├── backtest.py             # 独立回测 CLI（数据→训练→回测→报告）
│   └── tracking/               # SwanLab 实验追踪
├── roles/                      # Role YAML 配置（7 个角色）
├── skills/                     # Skill 目录（7 个 skill，各含 prompt.txt + sop.md + schema.json）
├── strategies/                 # 策略 YAML 配置
├── factors/                    # 因子池 (pool.json)
├── src/
│   ├── cli/                    # CLI 入口
│   │   ├── app.py              # typer app + 全局 --output 选项
│   │   ├── config.py           # GemStarConfig + YAML loader
│   │   ├── output.py           # table / json 统一输出
│   │   └── commands/           # 子命令（init/run/fetch/status/history/roles/strategies/factors）
│   ├── data/                   # Tushare 数据拉取 + 清洗
│   ├── timer/                  # LSTM 择时（特征 / 模型 / 信号）
│   ├── ranker/                 # 多因子选股（因子 / 标准化 / 打分）
│   ├── portfolio/              # 交易成本 + 仓位分配
│   ├── engine/                 # 回测引擎 + 绩效指标
│   ├── llm/                    # LLM 抽象层
│   │   ├── client.py           # Anthropic SDK wrapper
│   │   ├── adapter.py          # AgentProvider → LLMClient 桥接
│   │   └── providers/          # 4 个 provider 实现
│   ├── roles/                  # Role 配置加载 + 注册 + 事件流
│   ├── orchestrator/           # DailyFSM + IncidentFSM + pipeline
│   ├── strategies/             # 策略验证 + YAML 运行器
│   ├── judge/                  # 规则引擎
│   ├── reviewer/               # LLM 评审
│   ├── research/               # LLM 研究 ticket 生成
│   ├── scanner/                # 宏观分析 + 事件扫描
│   ├── reporter/               # 报告生成
│   ├── data_quality/           # 数据质量门
│   ├── factors/                # 因子池 + 健康监控
│   ├── ops/                    # 故障分类 + 自愈
│   └── schemas/                # Pydantic 数据模型
├── tests/                      # 单元测试
├── data/                       # Tushare 原始数据缓存 (Parquet)
├── output/                     # 回测结果 (报告/图表)
└── docs/
    ├── plans/                  # 实施计划
    └── specs/                  # 设计规格文档
```

---

## 快速开始

### 环境要求

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/) 包管理器
- [Tushare Pro](https://tushare.pro/) Token
- LLM Provider（按需，见下方配置）

### 安装

```bash
git clone https://github.com/JustHappyLab/GemStar.git
cd GemStar
uv sync
```

### 配置

```bash
cp .env.example .env
# 编辑 .env，填入必要 token

# 初始化项目（生成 gemstar.yaml + state.db）
gemstar init
```

#### 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `TUSHARE_TOKEN` | 是 | Tushare Pro API token，用于拉取 A 股数据 |
| `ANTHROPIC_API_KEY` | 否 | Anthropic API key，`api` provider 使用 |
| `ANTHROPIC_BASE_URL` | 否 | Anthropic API 代理地址（中国大陆用户） |
| `SWANLAB_API_KEY` | 否 | SwanLab 实验追踪（独立回测工具） |

#### LLM Provider 配置

不同角色使用不同的 LLM 后端，需安装对应 CLI 工具：

| Provider | 后端 | 安装方式 | 认证 | 文件系统 |
|----------|------|----------|------|----------|
| `api` | Anthropic API | `pip install anthropic` | `ANTHROPIC_API_KEY` 环境变量 | 否 |
| `claude_code` | Claude Code CLI | `npm i -g @anthropic-ai/claude-code` | `claude` 登录后自动认证 | 是 |
| `gemini_cli` | Gemini CLI | `npm i -g @google/gemini-cli` | `gemini` 登录后自动认证 | 是 |
| `codex_cli` | Codex CLI | `npm i -g @openai/codex` | `OPENAI_API_KEY` 环境变量 | 是 |

默认角色配置（`roles/*.yaml`）：

| 角色 | 默认 Provider | 可切换到 | 说明 |
|------|--------------|----------|------|
| macro_analyst | `api` | 任意 | 市场宏观分析（返回 JSON） |
| event_scanner | `api` | 任意 | 事件扫描（返回 JSON） |
| research_analyst | `api` | 任意 | 研究工单生成（返回 JSON） |
| strategy_architect | `api` | 任意 | 策略草稿（返回 YAML） |
| reviewer | `api` | 任意 | 回测评审（返回 JSON） |
| engineer | `claude_code` | `claude_code` / `gemini_cli` / `codex_cli` | 代码编写（需写文件） |
| bugfix | `claude_code` | `claude_code` / `gemini_cli` / `codex_cli` | Bug 修复（需写文件） |

**Provider 约束**：`engineer` 和 `bugfix` 角色需要写文件到磁盘，只能使用 CLI 类 provider（`claude_code` / `gemini_cli` / `codex_cli`）。配置为 `api` 会报错。分析类角色无此限制，4 个 provider 均可使用。

在 `gemstar.yaml` 中覆盖角色 provider：

```yaml
roles:
  engineer:
    provider: gemini_cli      # 工程师改用 Gemini
  macro_analyst:
    provider: claude_code     # 宏观分析改用 Claude Code
```

只需配置你实际使用的 provider。只跑不带 LLM 的 pipeline（`gemstar run`）只需 Tushare token；启用 LLM 策略生成（`gemstar run --llm`）则需额外配置对应 provider。

### CLI 命令

```bash
# 启动当日 pipeline（核心命令）
gemstar run --date 20260503

# 启用 LLM 策略生成
gemstar run --date 20260503 --llm

# 指定策略
gemstar run --date 20260503 --strategy strategies/chinext_lstm_mf8/config.yaml

# 拉取数据
gemstar fetch --start 20240101 --end 20260503

# 启动自动调度（后台运行）
gemstar scheduler start

# 前台运行（调试用，Ctrl+C 退出）
gemstar scheduler start --foreground

# 查看调度器状态
gemstar scheduler status

# 停止 / 重启
gemstar scheduler stop
gemstar scheduler restart

# 查看 pipeline 运行状态（JSON 输出，供 QClaw 解析）
gemstar -o json status

# 列出历史运行
gemstar history

# 查看可用角色 / 策略 / 因子
gemstar roles
gemstar strategies
gemstar factors
```

所有命令支持 `--output json`（或 `-o json`）输出 JSON 格式，用于自动化集成。

首次运行 `gemstar run` 会通过 Tushare API 拉取数据并缓存到 `data/raw/`（Parquet 格式），后续运行直接读取缓存。

### 自动调度

`gemstar scheduler start` 替代 cron，后台运行，内置交易日感知和失败重试：

```bash
# 后台启动
gemstar scheduler start

# 前台运行（调试用）
gemstar scheduler start --foreground

# 查看状态 / 停止 / 重启
gemstar scheduler status
gemstar scheduler stop
gemstar scheduler restart
```

在 `gemstar.yaml` 中配置调度时间和日志路径：

```yaml
# ─── 调度 ─────────────────────────────────────────────────
schedule: "收盘后"              # 预设：收盘后 / 盘前 / 深夜
# schedule: "16:00"            # 自定义时间
# schedule: null               # 手动模式，不自动调度
```

预设说明：

| 预设 | 数据拉取 | Pipeline | 适用场景 |
|------|---------|----------|---------|
| `收盘后` | 15:30 | 16:00 | 数据新鲜，最常用 |
| `盘前` | 06:00 | 07:00 | 用昨天数据，早上看结果 |
| `深夜` | 15:30 | 02:00 | 夜间 API 便宜 |

自动拉取数据（无需手动 `gemstar fetch`）：

```yaml
data:
  auto_fetch: true             # pipeline 前自动拉取缺失数据
  lookback_years: 2            # 训练数据回溯年数
```

Daemon 内置行为：
- 自动跳过非交易日（周末/节假日）
- 已完成的日期不重复执行
- 失败自动重试，最多 3 次
- 日志输出到 `logs/gemstar.log`（路径可在 `gemstar.yaml` 的 `log_path` 配置）
- `SIGINT` / `SIGTERM` 优雅退出

### Python API

也可以直接调用 pipeline：

```python
from src.orchestrator.pipeline import run_daily_pipeline

result = run_daily_pipeline(
    run_id="20260503-001",
    data=data_dict,           # Tushare DataFrame 映射
    strategies=[Path("...")], # 策略 YAML 路径
    pool_path=Path("factors/pool.json"),
    reference_date="20260503",
    benchmark_nav=benchmark_series,
    llm_available=True,       # 启用 LLM 策略生成
)
```

### 运行测试

```bash
uv run python -m pytest tests/ -v
```

---

## 回测引擎

内部组件，用于策略历史表现验证。模拟真实 A 股交易约束：

- **T+1**：当日买入不可当日卖出
- **涨跌停**：创业板 20% 涨跌停限制，涨停不追买，跌停不卖出
- **最小交易单位**：100 股（一手）
- **交易成本**：佣金万 2.5（最低 5 元）+ 印花税千 0.5（2023-08-28 后减半）+ 滑点万 5

### 绩效指标

| 指标 | 说明 |
|------|------|
| CAGR | 复合年化收益率 |
| Sharpe | 夏普比率（无风险利率 2.5%） |
| Max Drawdown | 最大回撤 |
| Calmar | 卡玛比率 (CAGR / MaxDD) |
| Win Rate | 胜率 |
| Profit Factor | 盈亏比 |
| Annual Turnover | 年化换手率 |
| Alpha | 相对创业板指超额收益 |

### 引擎验证

**内部自洽性检验** — 6 个手算可验证的 sanity check 场景：

| 场景 | 验证内容 |
|------|----------|
| 买入持有 | NAV 跟踪收盘价方向 |
| 零仓位 | NAV 恒等于初始资金 |
| 单次 round-trip | NAV 精确到小数点后 6 位 |
| 涨停不买 | 开盘涨停 20% 时拒绝买入 |
| 跌停不卖 | 开盘跌停 20% 时拒绝卖出 |
| 同价买卖 | 必亏（成本拖累） |

**跨平台验证（vs 聚宽 JoinQuant）** — 484 个交易日，NAV 差异 0.0000%（最大偏差 1.7e-14%，浮点精度误差）。

**数据完整性** — 无未来信息泄露（财务因子用 ann_date + merge_asof；市场因子 shift(1)）、无幸存者偏差（含已退市股票）、adj_factor 后复权、T+1 交割正确。

---

## 技术栈

| 依赖 | 用途 |
|------|------|
| Python 3.13 | 运行时 |
| PyTorch | LSTM 模型训练与推理 |
| pandas / numpy | 数据处理与数值计算 |
| tushare | A 股数据源 |
| scikit-learn | 数据预处理 |
| Pydantic v2 | Schema 校验 |
| Anthropic SDK | LLM API 调用 |

---

## License

Private repository. All rights reserved.
