# GemStar V2: 自主量化研究系统架构规划

> 版本: draft-1 | 日期: 2026-05-02 | 状态: 规划中

## 1. 愿景

将 GemStar 从单一策略回测系统，改造为一个**自主运行的量化研究"永动机"**：

- 自动采集结构化数据（Tushare）+ 非结构化数据（新闻、公告、政策）
- 自动挖掘因子、生成策略假设、回测验证
- 每日输出策略排行榜 + 科学解释 + 持仓信号
- 通过 IM（微信等）推送个性化报告

核心原则：**模拟真实量化团队分工，每个角色职责单一、输入输出明确、通过结构化数据协作。**

---

## 2. 系统总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Orchestrator (Python + Cron)                  │
│                  调度 · 状态管理 · 失败重试 · IM 推送                    │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────┬───────┘
       │          │          │          │          │          │
       ▼          ▼          ▼          ▼          ▼          ▼
 ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐
 │Collector ││  Factor  ││ Scanner  ││ Strategy ││Backtester││ Reporter │
 │          ││Researcher││          ││Architect ││          ││          │
 │ 纯代码   ││ CC Agent ││ LLM API  ││ LLM API  ││  纯代码  ││ LLM API  │
 └──────────┘└──────────┘└──────────┘└──────────┘└──────────┘└──────────┘
                   ▲                                    ▲
                   │          ┌──────────┐              │
                   └──────────│ Engineer │──────────────┘
                              │ CC Agent │
                              └─────┬────┘
                                    ▲
                              ┌─────┴────┐
                              │ Bugfix   │
                              │ Engineer │
                              │ CC Agent │
                              └──────────┘
```

CC Agent = Claude Code Agent (或 Gemini CLI Agent)，拥有文件读写、代码执行、终端操作的完整能力。

---

## 3. 角色定义

### 3.0 Orchestrator — 调度器

**实现**: Python + Cron (非 LLM)

**职责**:
- 定时触发每日流水线（22:00 启动）
- 管理角色间的依赖顺序和条件分支
- 失败重试（有限次）
- 触发 IM 推送

**为什么不用 LLM**: 调度逻辑是确定性的，用 LLM 反而引入不确定性。Python 代码更可靠、更快、更便宜。

**核心逻辑**:
```python
def daily_pipeline(date: str):
    # Phase 1: 数据采集
    collector_status = Collector.run(date)
    if collector_status.failed:
        BugfixEngineer.run(task="collector", log=collector_status.log)
        # 重试或跳过

    # Phase 2: 因子研究
    FactorResearcher.run(date)  # Agent: 更新因子池

    # Phase 3: 信号扫描
    signal = Scanner.run(date)  # LLM API

    # Phase 4: 策略生成 (条件触发)
    if signal.should_ideate:
        strategy_yaml = StrategyArchitect.run(signal)  # LLM API
        Backtester.run(strategy_yaml)  # 纯代码

    # Phase 5: 策略评估
    Judge.run(pending_results)  # LLM API

    # Phase 6: 报告生成
    report = Reporter.run(leaderboard, signals, news)  # LLM API
    push_to_im(report)
```

---

### 3.1 Collector — 数据采集员

**实现**: 纯 Python 代码

**职责**:
- 从 Tushare 采集结构化数据（日线、财务、资金流、公告、新闻）
- 增量更新 Parquet 缓存
- 数据质量校验（空值、异常值、时间连续性）
- 输出运行日志

**数据源**:

| 类别 | 数据 | Tushare 接口 | 用途 |
|------|------|-------------|------|
| **行情** | 交易日历 | `trade_cal` | 基础设施 |
| | 股票列表 | `stock_basic` | 标的池 |
| | 日线行情 | `daily` | 因子计算、回测 |
| | 基础指标 | `daily_basic` | PE/PB/换手率/市值 |
| | 复权因子 | `adj_factor` | 价格修正 |
| | 指数行情 | `index_daily` | 基准、择时特征 |
| **财务三表** | 利润表 | `income` | 营收/净利润/毛利率/费用率等原始项 |
| | 资产负债表 | `balancesheet` | 总资产/负债/应收/存货/商誉等 |
| | 现金流量表 | `cashflow` | 经营/投资/筹资现金流/自由现金流 |
| | 财务指标 | `fina_indicator` | ROE/ROA/净利率等汇总指标 (已有) |
| | 主营业务构成 | `fina_mainbz` | 收入来源分解，判断业务集中度 |
| | 财报披露日期 | `disclosure_date` | 控制财报数据的可用时点，防 look-ahead |
| **业绩预期** | 业绩预告 | `forecast` | 因子 + Scanner |
| | 业绩快报 | `express` | 因子 + Scanner |
| **研报/评级** | 研报详情 | `research_report` | 券商研报全文摘要、标题、行业 |
| | 机构评级 | `report_rc` | 买入/增持/中性/减持/卖出评级汇总 |
| | 机构盈利预测 | `report_fy` | 一致预期 EPS/营收/净利润预测 |
| | 机构目标价 | `report_rc` | 机构目标价中位数、预测变化趋势 |
| **新闻/公告** | 财经新闻 | `news` / `major_news` | Scanner 输入 |
| | 公告 | `anns_d` | Scanner 输入 |
| | 互动问答 | `irm_qa_sh` / `irm_qa_sz` | 交易所互动易，捕捉公司回应信号 |
| **资金流** | 北向资金 | `moneyflow_hsgt` | 资金流因子 |
| | 个股资金流 | `moneyflow` | 主力/散户/超大单资金流向 |
| | 行业资金流 | `moneyflow_ind_dc` | 板块因子 |
| | 龙虎榜 | `top_list` / `hsgt_top10` | 游资/机构席位动向 |
| **板块** | 申万指数 | `sw_daily` | 行业轮动因子 |
| | 同花顺概念 | `ths_index` / `ths_member` | 概念板块动量 |
| **情绪** | 涨跌停统计 | `limit_list_d` / `limit_step` | 市场情绪因子 |

**输出**:
```
data/raw/               # Parquet 缓存 (已有)
logs/collector_YYYYMMDD.log  # 运行日志
```

**已有代码**: `src/data/fetcher.py` + `src/data/cleaner.py`，需扩展接口。

**关键数据源与因子族的对应关系**:

| 因子族 | 来源接口 | 典型因子 | 价值 |
|--------|---------|---------|------|
| 盈利质量 | `income` + `cashflow` | 经营现金流/净利润、应收账款周转天数变化、毛利率稳定性 | 识别"纸面利润" vs 真金白银 |
| 资产健康 | `balancesheet` | 商誉/总资产、资产负债率边际变化、存货周转 | 排雷：高商誉减值风险、高杠杆 |
| 自由现金流 | `cashflow` | FCF yield = (经营现金流-资本开支)/市值 | 真实盈利能力，比 PE 更可靠 |
| 业务结构 | `fina_mainbz` | 主营收入集中度、毛利率分业务对比 | 识别业务转型、多元化风险 |
| 分析师预期 | `report_fy` + `report_rc` | 一致预期 EPS 变动率、评级上调/下调比例、目标价隐含空间 | 最有效的 alpha 信号之一，预期差驱动股价 |
| 资金行为 | `moneyflow` + `top_list` | 主力净流入占比、龙虎榜机构席位净买入 | 跟踪聪明钱 |
| 市场情绪 | `limit_list_d` | 涨停/跌停比、连板高度、炸板率 | 短期情绪拐点 |
| 互动信号 | `irm_qa_sh` / `irm_qa_sz` | 互动易回复频率异常、关键词命中 | 公司主动信息披露信号 |

**三表数据的特殊处理**:
- 三表数据量大（每只股票每季度一次），需要按报告期分批拉取
- 必须用 `disclosure_date`（实际披露日）而非 `end_date`（报告期）做时序对齐，否则构成 look-ahead bias
- 同比/环比计算需要跨报告期比较，建议预计算后缓存

**研报数据的特殊处理**:
- `research_report` 返回的是摘要而非全文，适合 Scanner 做主题提取
- `report_fy` 的一致预期数据需要跟踪"预期修正"（本次预测 vs 上次预测），而非绝对值
- 评级变化（上调/下调）比绝对评级更有预测力

---

### 3.2 Factor Researcher — 因子研究员

**实现**: Claude Code Agent

**为什么是 Agent**: 挖掘因子是一个研究过程——写代码、跑计算、看结果、迭代。不是一次 LLM 调用能完成的。

**职责**:

| 任务 | 频率 | 说明 |
|------|------|------|
| IC 监控 | 每日 | 跑现有因子的滚动 IC/IR，检测漂移 |
| 因子淘汰 | 每周 | IC_IR < 0.3 且连续 20 天 IC < 0 → 标记待观察 |
| 因子相关性 | 每周 | 因子间相关性 > 0.7 → 标记冗余 |
| 新因子研究 | 事件/周度 | 从新数据源、新闻信号中挖掘候选因子 |
| 因子池维护 | 持续 | 更新 factors/pool.json |

**输入**:
- `data/raw/` 中的 Tushare 数据
- `factors/pool.json` 当前因子池状态
- Scanner 的信号（如有新数据源可用）

**输出**: `factors/pool.json` (因子注册表)

**因子注册表结构** (`factors/pool.json`):
```json
{
  "version": 2,
  "last_updated": "2026-05-02",
  "active": [
    {
      "name": "momentum_20d",
      "source": "daily.close",
      "computation": "close.pct_change(20).shift(1)",
      "ic_mean": 0.028,
      "ic_ir": 0.45,
      "ic_positive_rate": 0.58,
      "last_updated": "2026-05-01",
      "status": "healthy"
    }
  ],
  "watchlist": [
    {
      "name": "turnover_20d",
      "source": "daily_basic.turnover_rate",
      "reason": "IC_IR 降至 0.15，连续 15 天 IC 为负",
      "since": "2026-04-15",
      "status": "under_review"
    }
  ],
  "retired": [
    {
      "name": "pb_inverse",
      "reason": "与 pe_inverse 相关性 0.85，信息冗余",
      "retired_at": "2026-04-20"
    }
  ],
  "candidates": [
    {
      "name": "northbound_net_inflow",
      "source": "moneyflow_hsgt",
      "computation": "待实现",
      "ic_mean": null,
      "status": "pending_implementation"
    }
  ]
}
```

**与 Engineer 的交互**:
- 如果候选因子需要新的 Tushare 接口 → 向 Orchestrator 发起 Engineer 任务请求
- 如果候选因子的计算逻辑复杂 → 自行实现 Python 脚本，放入 `factors/custom/`

---

### 3.3 Scanner — 信号扫描员

**实现**: LLM API

**职责**: 每天看完数据后，回答一个问题——"今天有没有值得关注的变化？"

**输入** (~2000 tokens):
```
- 今日市场概况: 创业板指涨跌幅、成交量变化
- 因子池变更: Factor Researcher 的 watchlist/retired 变动
- 今日新闻摘要: Tushare news/major_news 标题 (最近 20 条)
- 今日公告摘要: Tushare anns_d (创业板相关)
- 业绩预告/快报: forecast/express 中的异常值
- 涨停/跌停统计: limit_list_d
```

**输出** (`signals/YYYYMMDD.json`):
```json
{
  "date": "2026-05-01",
  "market_overview": "创业板指涨 1.2%，成交量较前日放大 15%",
  "notable": true,
  "signals": [
    {
      "type": "policy_event",
      "detail": "国务院常务会议通过半导体产业新一轮扶持政策",
      "severity": "high",
      "affected_sectors": ["半导体", "芯片"]
    },
    {
      "type": "earnings_surprise",
      "detail": "300750.SZ 业绩快报净利润同比增长 45%，超市场预期",
      "severity": "medium"
    },
    {
      "type": "factor_drift",
      "detail": "Factor Researcher 标记 turnover_20d 为 under_review",
      "severity": "low"
    }
  ],
  "should_ideate": true,
  "ideate_direction": "半导体板块事件驱动 + 业绩超预期"
}
```

**关键约束**: Scanner 不生成策略，只判断信号。策略生成交给 Strategy Architect。

---

### 3.4 Strategy Architect — 策略架构师

**实现**: LLM API

**职责**: 根据信号 + 因子池，设计策略配置。

**择时治理**:
- StrategyArchitect 默认只生成选股 sleeve：因子、权重、股票池、`top_n`、调仓频率。
- 自动生成的策略必须使用 `timer.mode: full`，不得自由生成 LSTM/GRU 参数、窗口、阈值或再训练计划。
- 择时进入自动化比较时，必须走受控模板：例如 `full`、`ma20_guard`、`ma60_guard`、`drawdown_guard`、`lstm_baseline`。
- AI 未来只能推荐已实现、已回测的择时模板，不能直接发明新 timer 配置。
- 详细规范见 `docs/timing-policy.md`。

**输入** (~3000 tokens):
```
- Scanner 的信号摘要
- factors/pool.json 中 status="healthy" 或 "pending_test" 的因子列表
- 现有策略列表 + 各自的 Sharpe/Alpha
- 标的池约束
```

**输出**: `strategies/<name>/config.yaml`

```yaml
name: semi_earnings_momentum_001
hypothesis: "半导体政策利好 + 业绩超预期双催化，短中期动量捕捉"
source_idea: "Scanner: 国务院半导体政策 + 300750.SZ 业绩超预期"
created: "2026-05-01"
universe: chinext
timer:
  mode: full          # 事件驱动不做择时
factors:
  - name: momentum_5d
    weight: 0.20
  - name: earnings_surprise
    weight: 0.20
  - name: roe
    weight: 0.15
  - name: revenue_yoy
    weight: 0.15
  - name: rel_strength_5d
    weight: 0.10
  - name: northbound_net_inflow
    weight: 0.10
  - name: pe_inverse
    weight: 0.05
  - name: turnover_5d
    weight: 0.05
top_n: 8
rebalance: daily
backtest:
  start: "20220101"
  end: "20260501"
  capital: 200000
```

**关键约束**:
- 只能使用 `factors/pool.json` 中已注册的因子
- 如果引用了 `status: "pending_implementation"` 的因子，Orchestrator 需先触发 Engineer 实现

---

### 3.5 Backtester — 回测引擎

**实现**: 纯 Python 代码

**职责**:
- 读取策略配置 YAML
- 执行回测（复用现有 `engine/backtest.py`）
- 计算指标（复用现有 `engine/metrics.py`）
- 计算因子 IC
- 输出结构化结果

**输入**: `strategies/<name>/config.yaml`

**输出**:
```
strategies/<name>/results/<timestamp>/
  ├── metrics.json        # 回测指标
  ├── ic_summary.json     # 因子 IC 分析
  ├── segment_metrics.json # 分段表现
  ├── curves.csv          # 净值曲线
  └── trades.csv          # 交易记录
```

**metrics.json 结构**:
```json
{
  "strategy": "semi_earnings_momentum_001",
  "backtest_period": "20220101~20260501",
  "capital": 200000,
  "metrics": {
    "cagr": 0.28,
    "sharpe": 1.20,
    "max_drawdown": -0.18,
    "calmar": 1.56,
    "win_rate": 0.55,
    "profit_factor": 1.35,
    "alpha": 0.15,
    "annual_turnover": 8.5,
    "longest_drawdown_days": 45,
    "completed_trades": 420
  },
  "segments": [
    {"period": "2022", "cagr": 0.15, "sharpe": 0.85, "max_dd": -0.22},
    {"period": "2023", "cagr": 0.32, "sharpe": 1.40, "max_dd": -0.12},
    {"period": "2024", "cagr": 0.25, "sharpe": 1.10, "max_dd": -0.18},
    {"period": "2025", "cagr": 0.38, "sharpe": 1.45, "max_dd": -0.15}
  ]
}
```

**已有代码**: `src/engine/backtest.py` + `src/engine/metrics.py`，需适配配置化调用。

---

### 3.6 Judge — 策略评审员

**实现**: LLM API

**职责**: 评估回测结果，判断策略是否值得上线/保留/淘汰。

**输入** (~1500 tokens):
```
- 策略配置摘要 (YAML 中的 hypothesis + factors)
- 回测指标 (metrics.json)
- 分段表现 (segment_metrics.json)
- 因子 IC 分析 (ic_summary.json)
- 与现有最优策略的对比
```

**输出** (`strategies/<name>/results/<timestamp>/verdict.json`):
```json
{
  "strategy": "semi_earnings_momentum_001",
  "verdict": "promote",
  "confidence": 0.75,
  "reasoning": "Sharpe 1.2 显著高于 baseline (0.85)，MaxDD -18% 可接受。分段表现稳定，2023-2025 年均正 Alpha。",
  "risks": [
    "回测区间 4 年，样本量偏小",
    "动量因子与 chinext_lstm_mf8 可能存在相关性",
    "半导体政策催化属一次性事件，策略可能快速衰减"
  ],
  "action": {
    "type": "observe",
    "duration_days": 30,
    "monitor_metrics": ["sharpe_rolling_60d", "ic_momentum_5d"]
  }
}
```

**verdict 枚举值**:
- `promote` — 加入排行榜，开始跟踪
- `observe` — 加入排行榜但标记为观察期
- `reject` — 不上线，记录原因
- `demote` — 从活跃策略降级
- `retire` — 淘汰

---

### 3.7 Engineer — 工程师

**实现**: Claude Code Agent

**为什么是 Agent**: 需要改代码、加依赖、跑测试。是 LLM API 做不到的。

**触发条件** (按需，非日常):

| 触发来源 | 场景 |
|---------|------|
| Factor Researcher | 需要新 Tushare 接口 (如 `moneyflow_hsgt`) |
| Factor Researcher | 候选因子需要复杂计算逻辑 |
| Strategy Architect | 策略需要配置文件不支持的模式 (如月度调仓) |
| Bugfix Engineer | 发现需代码修复的 bug |
| Orchestrator | 性能优化需求 |

**工作方式**:
```
可用工具:
  - 读写 src/ 下所有 Python 文件
  - 执行 pytest 验证改动
  - 读写 pyproject.toml (加依赖)
  - git 操作

任务流:
  1. 接收需求描述 (来自 Orchestrator)
  2. 阅读相关代码
  3. 实现改动
  4. 跑测试验证
  5. 输出: 改动摘要 + 测试结果
```

**约束**:
- 每次改动必须跑测试，测试不通过不能提交
- 不主动改代码，只响应明确需求
- 改动范围尽量小，不做无关重构

---

### 3.8 Bugfix Engineer — 运维工程师

**实现**: Claude Code Agent

**职责**: 系统健康监控 + 自动修复。

**每日任务**:

| 任务 | 说明 |
|------|------|
| 日志扫描 | 检查 Collector / Backtester 运行日志 |
| 错误分类 | 区分"可自动修复"和"需人工介入" |
| 自动修复 | 重试失败任务、修复配置错误、处理数据异常 |
| 健康报告 | 输出 `logs/health_YYYYMMDD.json` |

**错误分类策略**:

| 错误类型 | 处理方式 |
|---------|---------|
| 网络超时 / 429 | 自动重试 (已有逻辑) |
| Tushare 权限不足 | 标记为"需人工检查积分" |
| 数据字段缺失 | 尝试修改 fetcher 参数 |
| 策略配置引用未注册因子 | 通知 Factor Researcher |
| 回测引擎 KeyError | 提交 Engineer 修复 |
| LLM API 调用失败 | 自动重试，超过阈值告警 |

**输出** (`logs/health_YYYYMMDD.json`):
```json
{
  "date": "2026-05-01",
  "overall_status": "healthy",
  "components": [
    {"name": "collector", "status": "ok", "message": "15 interfaces fetched"},
    {"name": "factor_researcher", "status": "ok", "message": "IC scan complete, 1 on watchlist"},
    {"name": "backtester", "status": "ok", "message": "2 strategies backtested"},
    {"name": "reporter", "status": "ok", "message": "Report generated and pushed"}
  ],
  "auto_fixes": [],
  "manual_attention": []
}
```

---

### 3.9 Reporter — 报告员

**实现**: LLM API

**职责**: 组装每日报告，推送到 IM。

**输入** (~3000 tokens):
```
- Leaderboard (所有策略最新指标 + 排名变动)
- 今日各策略持仓信号
- Scanner 信号摘要
- Judge 对新策略的评估
- 今日新闻/公告摘要
- Factor Researcher 的因子池变更
- Bugfix Engineer 的健康报告 (如有异常)
```

**输出**: `output/reports/YYYYMMDD.md` + IM 推送

```markdown
# GemStar 每日量化报告 2026-05-01

## 市场概况
创业板指涨 1.2%，成交量放大 15%。半导体板块受政策催化领涨。

## 策略排行榜
| # | 策略 | Sharpe | CAGR | MaxDD | Alpha | 周变动 |
|---|------|--------|------|-------|-------|-------|
| 1 | chinext_lstm_mf8 | 1.35 | 28% | -15% | 18% | → |
| 2 | semi_earnings_001 | 1.20 | 32% | -18% | 15% | ↑ 新 |
| 3 | sector_rotation_001 | 0.85 | 18% | -22% | 8% | ↓ |

## 今日信号
- LSTM 择时: 偏多 (position=0.72)
- 推荐持仓: 300750.SZ, 300059.SZ, 300124.SZ, 300033.SZ, 300760.SZ

## 因子动态
- ⚠️ turnover_20d IC 持续走弱，已进入观察期
- ✅ 新候选因子 northbound_net_inflow 待测试

## 新策略评估
- semi_earnings_001: Judge 评估为 observe (信心 0.75)
  - 优势: 政策 + 业绩双催化，分段表现稳定
  - 风险: 样本量偏小，催化可能一次性

## 系统健康
- 状态: 正常
- 今日无异常

## 重要新闻
- 国务院常务会议通过半导体产业新一轮扶持政策
- 300750.SZ 业绩快报净利润同比增 45%
```

---

## 4. 数据流全景

```
外部数据源                    内部存储                      角色间传递
───────────                  ──────────                    ──────────

Tushare API ──┐
              ├→ Collector ──→ data/raw/*.parquet
              │                    │
              │                    ├──→ Factor Researcher ──→ factors/pool.json
              │                    │                              │
              │                    ├──→ Scanner ──→ signals/YYYYMMDD.json
              │                    │                    │
              │                    │                    └──→ Strategy Architect
              │                    │                              │
              │                    │                              └──→ strategies/<name>/config.yaml
              │                    │                                        │
              │                    └──→ Backtester ←────────────────────────┘
              │                              │
              │                              └──→ strategies/<name>/results/<ts>/
              │                                        │
              │                                        ├──→ Judge ──→ verdict.json
              │                                        │
              │                                        └──→ Reporter ──→ output/reports/YYYYMMDD.md
              │                                                              │
              │                                                              └──→ IM 推送
              │
              └→ logs/collector_YYYYMMDD.log
                          │
                          └──→ Bugfix Engineer ──→ logs/health_YYYYMMDD.json
                                                        │
                                                        └──→ Engineer (如需代码修复)
```

---

## 5. 文件结构 (目标)

```
GemStar/
├── src/
│   ├── collector/              # 数据采集 (原 data/)
│   │   ├── fetcher.py          # Tushare 接口 (已有，需扩展)
│   │   ├── cleaner.py          # 数据清洗 (已有)
│   │   └── quality.py          # 数据质量校验 (新增)
│   │
│   ├── factors/                # 因子管理
│   │   ├── compute.py          # 因子计算 (原 ranker/factors.py)
│   │   ├── normalize.py        # 标准化 (已有)
│   │   ├── ic.py               # IC 分析 (已有)
│   │   └── custom/             # Agent 生成的自定义因子脚本
│   │       └── northbound_net_inflow.py
│   │
│   ├── strategies/             # 策略注册表
│   │   ├── registry.py         # 策略加载/执行
│   │   └── <name>/
│   │       ├── config.yaml     # 声明式配置
│   │       └── results/        # 回测结果
│   │
│   ├── engine/                 # 回测引擎 (已有，不变)
│   │   ├── backtest.py
│   │   └── metrics.py
│   │
│   ├── timer/                  # 择时模块 (已有，不变)
│   │   ├── features.py
│   │   ├── model.py
│   │   ├── scaler.py
│   │   └── signal.py
│   │
│   ├── portfolio/              # 组合管理 (已有，不变)
│   │   ├── cost.py
│   │   └── allocator.py
│   │
│   ├── scanner/                # 信号扫描 (新增)
│   │   └── prompt.py           # Scanner 的 prompt 模板
│   │
│   ├── reporter/               # 报告生成 (新增)
│   │   ├── prompt.py           # Reporter 的 prompt 模板
│   │   └── format.py           # 输出格式化
│   │
│   ├── judge/                  # 策略评审 (新增)
│   │   └── prompt.py           # Judge 的 prompt 模板
│   │
│   ├── llm/                    # LLM 调用封装 (新增)
│   │   ├── client.py           # 统一的 API 调用
│   │   └── prompts/            # 各角色的 prompt 文件
│   │
│   ├── orchestrator.py         # 调度器 (新增，替代 main.py)
│   └── tracking/               # 实验追踪 (已有)
│       └── swanlab_run.py
│
├── factors/
│   └── pool.json               # 因子注册表 (新增)
│
├── signals/                    # Scanner 输出 (新增)
│   └── YYYYMMDD.json
│
├── logs/                       # 运行日志 (新增)
│   ├── collector_YYYYMMDD.log
│   └── health_YYYYMMDD.json
│
├── output/
│   └── reports/                # 每日报告 (新增)
│       └── YYYYMMDD.md
│
├── data/
│   └── raw/                    # Parquet 缓存 (已有)
│
├── tests/                      # 测试 (已有，需扩展)
│
├── docs/
│   ├── gemstar-v2-plan.md      # 本文件
│   └── superpowers/
│
├── pyproject.toml
└── run.sh
```

---

## 6. 实施路线图

### Phase 1: 策略声明化 + 结果存储 (1 周)

**目标**: 现有策略不改逻辑，只改管理方式。

- [ ] 定义策略配置 YAML schema
- [ ] 将现有 GemStar 策略迁移为 `strategies/chinext_lstm_mf8/config.yaml`
- [ ] 实现 `strategies/registry.py` — 加载 YAML、调用现有流水线
- [ ] 实现结果存储 — 每次回测结果写入 `strategies/<name>/results/<ts>/`
- [ ] 重构 `main.py` → `orchestrator.py`，支持按配置文件执行
- [ ] 验证: 用 YAML 配置跑出的结果与原 main.py 一致

**交付物**: 可以通过 YAML 管理多个策略，回测结果自动归档。

### Phase 2: 因子注册表 + Factor Researcher (1 周)

**目标**: 因子从"写死在代码里"变为"可管理的资产"。

- [ ] 创建 `factors/pool.json` 初始版本（从现有 8 个因子导入）
- [ ] 实现因子 IC 监控脚本（复用现有 `ic.py`，加滚动窗口）
- [ ] 编写 Factor Researcher 的 Agent prompt
- [ ] 实现因子淘汰/晋升逻辑
- [ ] 验证: Factor Researcher 能自动完成 IC 监控并更新 pool.json

**交付物**: 因子池有注册表，有质量监控，可自动维护。

### Phase 3: 数据层扩展 (1-2 周)

**目标**: Collector 支持财务三表、研报评级、新闻公告、资金流等全量数据源。

**Step 3a: 财务三表 + 研报 (高优先级)**
- [ ] 扩展 `fetcher.py`，添加: `income`, `balancesheet`, `cashflow`, `fina_mainbz`, `disclosure_date`
- [ ] 实现三表数据的 `disclosure_date` 时序对齐逻辑
- [ ] 添加: `research_report`, `report_rc`, `report_fy`
- [ ] 实现一致预期修正（本次预测 vs 上次预测）的预计算
- [ ] 验证: 三表数据可正确按披露日对齐，研报数据可正常获取

**Step 3b: 新闻/公告/资金流/情绪**
- [ ] 添加: `news`, `major_news`, `anns_d`
- [ ] 添加: `moneyflow_hsgt`, `moneyflow`, `top_list`, `hsgt_top10`
- [ ] 添加: `limit_list_d`, `limit_step`
- [ ] 添加: `irm_qa_sh`, `irm_qa_sz` (互动易)
- [ ] 实现增量更新机制（只拉新数据，不全量重拉）
- [ ] 实现数据质量校验 (`quality.py`)
- [ ] 验证: 全量数据源可正常获取并缓存

**交付物**: Collector 覆盖行情/三表/研报/新闻/资金流/情绪全量数据。

### Phase 4: Scanner + Strategy Architect (1 周)

**目标**: 系统能自动发现信号并生成策略假设。

- [ ] 编写 Scanner prompt，实现 `scanner/prompt.py`
- [ ] 编写 Strategy Architect prompt，实现策略 YAML 生成
- [ ] 实现策略与因子池的校验（只能用已注册因子）
- [ ] 验证: 给定模拟信号，能生成合理的策略 YAML

**交付物**: 系统具备自动构思策略的能力。

### Phase 5: Backtester 配置化 + Judge (1 周)

**目标**: 回测引擎能接受 YAML 配置，Judge 能评估结果。

- [ ] 重构 Backtester，从 YAML 读取因子权重、标的池、择时模式
- [ ] 实现批量回测调度（并行跑多个策略）
- [ ] 编写 Judge prompt，实现 `judge/prompt.py`
- [ ] 实现 verdict.json 输出
- [ ] 验证: 新策略 YAML → 自动回测 → Judge 评估 → verdict

**交付物**: 从策略配置到评估的全自动化。

### Phase 6: Reporter + IM 推送 (1 周)

**目标**: 每日自动生成报告并推送到 IM。

- [ ] 编写 Reporter prompt，实现 `reporter/prompt.py`
- [ ] 实现 Leaderboard 计算（所有策略的指标汇总 + 排名）
- [ ] 实现 IM 推送（先支持一种渠道，如飞书 / 企业微信）
- [ ] 验证: 完整流水线端到端运行

**交付物**: 每日自动报告推送到 IM。

### Phase 7: Engineer + Bugfix Engineer (1 周)

**目标**: 系统具备自我修复和扩展能力。

- [ ] 编写 Engineer Agent prompt
- [ ] 编写 Bugfix Engineer Agent prompt
- [ ] 实现日志扫描 + 错误分类逻辑
- [ ] 实现健康报告生成
- [ ] 验证: 模拟错误场景，Bugfix 能检测并修复

**交付物**: 系统具备运维自动化能力。

### Phase 8: 调度 + 稳定化 (持续)

**目标**: 系统稳定每日自动运行。

- [ ] 配置 Cron 定时任务
- [ ] 实现失败重试和告警
- [ ] 长期运行稳定性测试
- [ ] 根据实际运行情况调优各角色 prompt

---

## 7. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 包管理 | uv | 已在使用 |
| 数据存储 | Parquet + JSON | 已有 Parquet 缓存，JSON 存元数据 |
| 策略配置 | YAML | 可读性好，LLM 易生成 |
| LLM API | Claude API (Sonnet) | 性价比好，中文能力强 |
| Agent 框架 | Claude Code CLI | 已有文件读写、代码执行能力 |
| 实验追踪 | SwanLab | 已集成 |
| IM 推送 | 待定 (飞书 / 企业微信) | Phase 6 决定 |
| 调度 | Cron + Python | 简单可靠 |

---

## 8. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| LLM 生成的策略配置有误 | 回测失败或结果不可信 | YAML schema 校验 + Backtester 前置检查 |
| Agent 改代码引入 bug | 系统崩溃 | 改动必须跑测试 + Bugfix 日常扫描 |
| 因子过拟合 | 策略实盘失效 | Judge 严格评估 + 观察期机制 |
| Tushare 接口限流 | 数据采集失败 | 已有重试机制 + Bugfix 监控 |
| LLM API 成本 | 日常运行费用 | 控制各角色 prompt 大小 + 用 Sonnet 而非 Opus |
| 新闻/公告质量参差 | Scanner 产生噪声信号 | Scanner 输出 severity 分级，低级信号不触发策略生成 |
| 三表数据 look-ahead bias | 回测结果虚高 | 严格用 `disclosure_date` 而非 `end_date` 做时序对齐，Backtester 内置检查 |
| 三表数据量大 | 采集耗时、存储膨胀 | 按报告期增量拉取，预计算衍生指标后只缓存结果 |
| 研报数据积分需求 | 2000 积分可能不足以覆盖全部研报接口 | 先用 `report_rc`（评级，积分要求较低），`research_report` 视积分情况扩展 |
| 一致预期数据滞后 | 机构预测更新频率不一 | 用最新一条预测，记录预测日期，计算修正方向和幅度 |
| 研报/评级噪声 | 机构评级普遍偏乐观（买入 > 80%） | 使用"评级变动"（上调/下调/首次覆盖）而非绝对评级，关注预期修正而非绝对值 |

---

## 9. 成功指标

系统上线后，用以下指标衡量是否成功:

| 指标 | 目标 | 说明 |
|------|------|------|
| 每日流水线成功率 | > 95% | 不因错误中断 |
| 策略排行榜 Sharpe Top1 | > 1.0 | 最优策略的风险调整收益 |
| 新策略生成频率 | 2-4 个/月 | 不要太多（过拟合风险），不要太少（缺乏探索） |
| 因子池健康率 | > 70% 因子 IC_IR > 0.3 | 因子质量持续达标 |
| 人工干预频率 | < 2 次/周 | 系统自主运行 |
| 报告推送及时性 | 每日 23:00 前 | 不延迟 |
