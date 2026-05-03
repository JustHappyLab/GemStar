# GemStar

ChiNext (GEM) 创业板自动化量化研究平台。FSM 驱动的多 Agent 日频 Pipeline，自动完成数据质检 → 因子监控 → 策略生成 → 回测 → 评审。

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

### 事件流

所有 Role 执行通过 `RoleEvent` 产生可观测事件（started/completed/failed），支持执行监控和调试。

---

## 项目结构

```
GemStar/
├── .env.example                # 环境变量模板
├── pyproject.toml              # 项目配置 + 依赖管理 (uv)
├── tools/                      # 附属工具
│   ├── backtest.py             # 独立回测 CLI（数据→训练→回测→报告）
│   └── tracking/               # SwanLab 实验追踪
├── roles/                      # Role YAML 配置（7 个角色）
│   ├── macro_analyst.yaml
│   ├── event_scanner.yaml
│   ├── research_analyst.yaml
│   ├── strategy_architect.yaml
│   ├── reviewer.yaml
│   ├── engineer.yaml
│   └── bugfix.yaml
├── skills/                     # Skill 目录（7 个 skill，各含 prompt.txt + sop.md + schema.json）
│   ├── analyze_market/
│   ├── scan_events/
│   ├── generate_tickets/
│   ├── draft_strategy/
│   ├── review_verdict/
│   ├── write_code/
│   └── fix_bug/
├── src/
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

### 安装

```bash
git clone https://github.com/JustHappyLab/GemStar.git
cd GemStar
uv sync
```

### 配置

```bash
cp .env.example .env
# 编辑 .env，填入 TUSHARE_TOKEN
```

可选配置 SwanLab 实验记录：

```bash
SWANLAB_API_KEY=your_key
SWANLAB_PROJ_NAME=gemstar
```

### 运行 Pipeline

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

首次运行会通过 Tushare API 拉取数据并缓存到 `data/raw/`（Parquet 格式），后续运行直接读取缓存。

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
