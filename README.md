# GemStar ⭐

ChiNext (GEM) 创业板量化交易策略 — LSTM 择时 + 多因子选股，日频回测框架。

## 策略概述

GemStar 是一个针对 A 股创业板（300xxx/301xxx）的日频量化交易策略，采用**串行两层架构**：

```
Layer 1: 择时 (Timer)
  创业板指(399006.SZ) → LSTM(64→32) → 仓位信号 (0% / 50% / 100%)

Layer 2: 选股 (StockRank)
  创业板全股票池 → 8因子打分 → Top-5 等权持仓

组合: 仓位信号 × Top-5 等权 → 每日目标持仓 → 回测引擎执行
```

### 择时模块

基于创业板指数日线数据，构建 60 日滑窗的 17 维技术特征，输入两层 LSTM 网络进行三分类预测（看空/中性/看多），输出离散仓位信号。

| 特征类别 | 特征 |
|----------|------|
| 价格动量 | 5/10/20/60 日收益率 |
| 均线偏离 | 5/10/20/60 日均线偏离度 |
| 波动率 | 5/10/20 日对数收益率滚动标准差 |
| 量价 | 5/20 日成交量比 |
| 技术指标 | RSI(14), MACD(12,26,9), ADX(14) |

模型每 6 个月滚动重训，使用 expanding window，Adam + CosineAnnealing + 早停。

### 选股模块

8 因子 StockRank 打分模型，每日截面计算：

| 因子 | 权重 | 来源 |
|------|------|------|
| ROE(TTM) | 15% | 财务指标 |
| 营收同比增速 | 15% | 财务指标 |
| 净利润同比增速 | 10% | 财务指标 |
| PE(TTM) 倒数 | 10% | 日度估值 |
| PB 倒数 | 10% | 日度估值 |
| 20日动量 | 15% | 日线行情 |
| 20日平均换手率 | 10% | 日度指标 |
| 相对创业板指超额收益 | 15% | 计算 |

因子处理流程：MAD 3σ 去极值 → 截面 Z-Score 标准化 → 中位数填充 → 加权合成 → Top-5。

### 回测引擎

模拟真实 A 股交易约束：

- **T+1**：当日买入不可当日卖出
- **涨跌停**：创业板 20% 涨跌停限制，涨停不追买，跌停不卖出
- **最小交易单位**：100 股（一手）
- **交易成本**：佣金万 2.5（最低 5 元）+ 印花税千 0.5（2023-08-28 后减半）+ 滑点万 5

## 项目结构

```
GemStar/
├── pyproject.toml              # 项目配置 + 依赖管理 (uv)
├── run.sh                      # 一键启动
├── src/
│   ├── data/
│   │   ├── fetcher.py          # Tushare 数据拉取 + Parquet 缓存
│   │   └── cleaner.py          # ST过滤 / 次新股过滤 / 停牌过滤 / 缺失填充
│   ├── timer/
│   │   ├── features.py         # 创业板指 17 维特征工程
│   │   ├── model.py            # LSTM(64→32) 三分类模型 + 训练
│   │   └── signal.py           # 概率 → 离散仓位信号
│   ├── ranker/
│   │   ├── factors.py          # 8 因子向量化计算
│   │   ├── normalize.py        # MAD 去极值 + Z-Score 标准化
│   │   └── scorer.py           # 加权打分 + Top-N 排序
│   ├── portfolio/
│   │   ├── cost.py             # A股交易成本模型
│   │   └── allocator.py        # 仓位分配 + T+1 / 涨跌停约束
│   ├── engine/
│   │   ├── backtest.py         # 逐日回测引擎
│   │   └── metrics.py          # 绩效指标 (CAGR/Sharpe/MaxDD/Calmar...)
│   └── main.py                 # 编排器：数据→训练→回测→报告
├── tests/                      # 43 个单元测试
├── data/
│   ├── raw/                    # Tushare 原始数据缓存 (Parquet)
│   └── features/               # 处理后的特征数据
├── output/                     # 回测结果 (报告/图表)
└── docs/superpowers/
    ├── plans/                  # 实施计划
    └── specs/                  # 设计规格文档
```

## 快速开始

### 环境要求

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) 包管理器
- [Tushare Pro](https://tushare.pro/) Token

### 安装

```bash
git clone https://github.com/JustHappyLab/GemStar.git
cd GemStar
uv sync
```

### 配置

创建 `.env` 文件：

```bash
echo "TUSHARE_TOKEN=your_token_here" > .env
```

### 运行回测

```bash
# 默认参数：2021-04-09 ~ 2026-04-09，本金 10 万
./run.sh

# 自定义参数
./run.sh --start 20220101 --end 20241231 --capital 200000

# 指定训练数据起始日期
./run.sh --train-start 20180101
```

### 运行测试

```bash
uv run pytest tests/ -v
```

## 回测参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--start` | 20210409 | 回测起始日期 |
| `--end` | 20260409 | 回测结束日期 |
| `--capital` | 100000 | 初始资金（元） |
| `--train-start` | 20190101 | LSTM 训练数据起始日期 |

## 绩效指标

回测完成后在 `output/backtest_report.md` 生成报告，包含：

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

## 技术栈

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.13 | 运行时 |
| PyTorch | 2.11 | LSTM 模型训练与推理 |
| pandas | 3.0 | 数据处理 |
| numpy | 2.4 | 数值计算 |
| tushare | 1.4.29 | A 股数据源 |
| scikit-learn | 1.8 | 数据预处理 |
| matplotlib | 3.x | 图表绘制 |

## 数据说明

所有数据通过 Tushare Pro API 获取，首次运行会自动拉取并缓存到 `data/raw/`（Parquet 格式），后续运行直接读取缓存。

| 数据 | 接口 | 说明 |
|------|------|------|
| 交易日历 | `trade_cal` | SSE 交易日 |
| 股票列表 | `stock_basic` | 创业板股票（含已退市） |
| 指数日线 | `index_daily` | 创业板指 399006.SZ |
| 个股日线 | `daily` | 按日期批量拉取 |
| 估值指标 | `daily_basic` | PE/PB/换手率/市值 |
| 财务指标 | `fina_indicator` | ROE/营收增速/净利润增速 |

> ⚠️ 首次拉取数据可能需要较长时间（取决于 Tushare 积分和接口限速）。

## 已知局限

1. **过拟合风险** — 5 年日线约 1200 条，LSTM 小样本容易过拟合，通过 Dropout + 早停 + 滚动重训缓解
2. **因子权重静态** — 8 因子权重为人工设定，未做 IC/IR 动态调权
3. **财务数据回溯修正** — 严格按披露日期使用，但 Tushare 部分字段可能存在事后修正
4. **流动性** — 10 万本金对市场无冲击，但部分小盘股涨跌停频繁
5. **印花税分段** — 2023-08-28 前后印花税费率不同，已在成本模型中处理

## License

Private repository. All rights reserved.
