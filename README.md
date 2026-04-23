# GemStar ⭐

ChiNext (GEM) 创业板量化交易策略 — LSTM 择时 + 多因子选股，日频回测框架。

## 策略概述

GemStar 是一个针对 A 股创业板（300xxx/301xxx）的日频量化交易策略，采用**串行两层架构**：

```
Layer 1: 择时 (Timer)
  创业板指(399006.SZ) → LSTM(64→32) → 连续仓位信号 (0% ~ 100%)

Layer 2: 选股 (StockRank)
  创业板全股票池 → 8因子打分 → Top-5 等权持仓

组合: 仓位信号 × Top-5 等权 → 每日目标持仓 → 回测引擎执行
```

### 择时模块

基于创业板指数日线数据，构建 60 日滑窗的 17 维技术特征，输入两层 LSTM 网络进行三分类预测（看空/中性/看多），再把类别概率映射为连续仓位信号。

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
├── .env.example                # 环境变量模板（复制为 .env 后填入 Token）
├── pyproject.toml              # 项目配置 + 依赖管理 (uv)
├── run.sh                      # 一键启动
├── src/
│   ├── data/
│   │   ├── fetcher.py          # Tushare 数据拉取 + Parquet 缓存
│   │   └── cleaner.py          # ST过滤 / 次新股过滤 / 停牌过滤 / 缺失填充
│   ├── timer/
│   │   ├── features.py         # 创业板指 17 维特征工程
│   │   ├── model.py            # LSTM(64→32) 三分类模型 + 训练
│   │   └── signal.py           # 概率 → 连续仓位信号
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
- [SwanLab](https://swanlab.cn/) 账号（可选，用于实验记录）

### 安装

```bash
git clone https://github.com/JustHappyLab/GemStar.git
cd GemStar
uv sync
```

### 配置

项目提供了 `.env.example` 模板，复制后填入你的 Tushare Token；如果你希望自动把训练和回测指标同步到 SwanLab，也可以一起填入 `SWANLAB_API_KEY`：

```bash
cp .env.example .env
# 编辑 .env，将占位符替换为你的真实 Token / API Key
```

Token 申请地址：https://tushare.pro/register?inv=XXXXXX

`./run.sh` 启动时会自动加载项目根目录的 `.env`。如果你选择直接运行模块入口，需要先手动导出环境变量：

```bash
export TUSHARE_TOKEN=your_token_here
uv run python -m src.main
```

如果环境里存在 `SWANLAB_API_KEY`，项目会自动记录以下信息到 SwanLab：

- 每个滚动训练窗口的 train/val loss
- 每个滚动训练窗口的 val accuracy
- 跳过训练窗口的样本数不足告警
- 回测汇总指标与报告路径

推荐把下面几个环境变量一起配上，便于在 SwanLab 里区分不同实验：

```bash
SWANLAB_API_KEY=your_swanlab_api_key_here
SWANLAB_PROJ_NAME=gemstar
# SWANLAB_WORKSPACE=your_team_or_username
# SWANLAB_EXP_NAME=gemstar-backtest-20260412
```

如果不显式设置 `SWANLAB_EXP_NAME`，项目会自动生成语义化名称，例如：

```bash
backtest-20210409_20260409-train20190101-cap-100k-rt6m-20260412-020000
```

这样在 SwanLab 里看实验列表时，能直接看出回测区间、训练起点、资金规模和重训周期。

### SwanLab 记录内容

启用后，GemStar 会为每次完整回测创建一个 SwanLab 实验，并自动上传：

- `timer/train_loss`、`timer/val_loss`、`timer/val_acc`
- 每个滚动训练窗口的起止日期与训练/验证样本数
- 因样本不足而被跳过的训练窗口
- 最终回测指标：`cagr`、`sharpe`、`max_drawdown`、`calmar`、`alpha` 等
- 量化时序曲线（按 day_index 步进记录）：
  - 策略归一化 NAV vs 基准归一化 NAV
  - 相对基准超额表现
  - 回撤曲线
  - 资金暴露/择时仓位曲线
- 本地产物路径：`output/backtest_report.md` 和 `output/backtest_curves.csv`

SwanLab 会自动为每个 metric key 生成折线图，策略和基准净值曲线使用归一化净值（起点都为 `1.0`），超额曲线使用相对基准的累计跑赢比例。

查看方式：

- 终端里会显示 SwanLab 实验的同步信息
- 运行结束后可在 SwanLab 项目页按 `SWANLAB_PROJ_NAME` 找到对应实验
- 本地仍然会保留 Markdown 报告，不依赖 SwanLab 才能查看结果

### 运行回测

```bash
# 默认参数：2021-04-09 ~ 2026-04-09，本金 10 万
./run.sh

# 自定义参数
./run.sh --start 20220101 --end 20241231 --capital 200000

# 指定训练数据起始日期
./run.sh --train-start 20180101
```

首次运行会通过 Tushare API 拉取全部原始数据并缓存到 `data/raw/`（Parquet 格式），耗时取决于你的 Tushare 积分等级和接口限速。后续运行直接读取缓存，速度很快。

回测完成后，绩效报告会输出到 `output/backtest_report.md`。

### 运行测试

```bash
uv run python -m pytest tests/ -v
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

## 回测引擎验证

### 内部自洽性检验

6 个手算可验证的 sanity check 场景，覆盖：

| 场景 | 验证内容 |
|------|----------|
| 买入持有 | NAV 跟踪收盘价方向 |
| 零仓位 | NAV 恒等于初始资金 |
| 单次 round-trip | NAV 精确到小数点后 6 位 |
| 涨停不买 | 开盘涨停 20% 时拒绝买入 |
| 跌停不卖 | 开盘跌停 20% 时拒绝卖出 |
| 同价买卖 | 必亏（成本拖累） |

### 跨平台验证（vs 聚宽 JoinQuant）

使用聚宽导出的真实持仓数据，在 GemStar 中用 Tushare 收盘价重新计算 NAV，与聚宽报告的 NAV 逐日对比：

- **484 个交易日，NAV 差异 0.0000%**（最大偏差 1.7e-14%，浮点精度误差）
- 验证了 Tushare 与聚宽使用完全相同的行情数据
- 验证了 GemStar 的 mark-to-market 计算与生产级平台一致

> 注：两个引擎的下单撮合逻辑存在设计差异（GemStar 用开盘价全额撮合，聚宽有内部资金预留机制），导致相同策略的持仓量不同。这属于模型假设差异，不影响定价引擎的正确性。

### 数据完整性

| 检查项 | 状态 |
|--------|------|
| 未来信息泄露 (Look-ahead) | ✅ 财务因子用 ann_date + merge_asof；市场因子 shift(1) |
| 幸存者偏差 | ✅ 股票池包含已退市股票 |
| 复权处理 | ✅ adj_factor 后复权 |
| T+1 交割 | ✅ 先卖后买执行顺序隐式保证 |

## 已知局限

1. **过拟合风险** — 5 年日线约 1200 条，LSTM 小样本容易过拟合，通过 Dropout + 早停 + 滚动重训缓解
2. **因子权重静态** — 8 因子权重为人工设定，未做 IC/IR 动态调权
3. **财务数据回溯修正** — 严格按披露日期使用，但 Tushare 部分字段可能存在事后修正
4. **流动性** — 10 万本金对市场无冲击，但部分小盘股涨跌停频繁
5. **印花税分段** — 2023-08-28 前后印花税费率不同，已在成本模型中处理

## License

Private repository. All rights reserved.
