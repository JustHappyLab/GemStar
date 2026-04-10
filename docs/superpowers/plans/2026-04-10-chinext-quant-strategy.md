# ChiNext Quant Strategy Implementation Plan

**Goal:** Build a daily-frequency quantitative trading strategy for ChiNext stocks combining LSTM/GRU index-level market timing with StockRank multi-factor stock selection, backtested over 5 years with 100k RMB capital.

**Architecture:** Serial two-layer design — Layer 1 uses an LSTM/GRU model on ChiNext Index (399006.SZ) features to produce position signals (0%/50%/100%). Layer 2 uses a multi-factor scoring model (StockRank) across all ChiNext stocks to select Top-5 holdings. A vectorized backtest engine simulates daily trading with A-share constraints (T+1, price limits, stamp tax).

**Tech Stack:** Python 3.13, uv for dependency management. All dependencies in `pyproject.toml`, managed via `uv sync`.

**Spec:** `docs/superpowers/specs/2026-04-09-chinext-quant-strategy-design.md`

---

## Review 修正记录

原始 plan 存在以下问题，已在本版本中修正：

1. **环境管理**：废弃 `.vendor/` + `PYTHONPATH` hack，改用 `uv` + `pyproject.toml`，标准 venv
2. **Softmax 重复**：`model.py` 的 forward 不加 softmax（PyTorch CrossEntropyLoss 内含），推理时再 softmax
3. **features.py close 列**：`compute_index_features` 直接保留 close 列在输出中
4. **数据拉取性能**：个股日线改用 `pro.daily()` 按日期批量拉取，而非逐股拉取
5. **因子计算性能**：向量化计算所有日期的因子，而非逐日循环
6. **T+1 跟踪 bug**：`bought_today` 在循环顶部无条件清空
7. **LSTM 结构**：与 spec 对齐，两层分别 64/32 hidden units（用两个独立 LSTM 层）
8. **训练窗口验证**：`_get_retrain_dates` 检查训练数据是否充足

---

## File Structure

```
tushare/
├── pyproject.toml                # uv 项目配置 + 所有依赖
├── run.sh                        # One-command launcher
├── src/
│   ├── __init__.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py            # Tushare API wrapper with caching + rate limiting
│   │   └── cleaner.py            # Data cleaning: ST filter, IPO filter, missing values
│   ├── timer/
│   │   ├── __init__.py
│   │   ├── features.py           # ChiNext index feature engineering (20 features)
│   │   ├── model.py              # LSTM/GRU model definition + training loop
│   │   └── signal.py             # Position signal generation from model output
│   ├── ranker/
│   │   ├── __init__.py
│   │   ├── factors.py            # Individual factor computation (vectorized)
│   │   ├── normalize.py          # MAD winsorize + Z-score
│   │   └── scorer.py             # Weighted scoring + Top-N ranking
│   ├── portfolio/
│   │   ├── __init__.py
│   │   ├── cost.py               # Transaction cost model
│   │   └── allocator.py          # Position allocation with A-share constraints
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── backtest.py           # Daily backtest simulation
│   │   └── metrics.py            # Performance metrics
│   └── main.py                   # Orchestrator
├── tests/
│   └── (one test file per module)
├── data/
│   ├── raw/                      # Cached tushare parquet files
│   └── features/                 # Processed feature data
└── output/                       # Backtest results
```

---

### Task 1: Project Setup & Dependencies

- [ ] **Step 1: Initialize uv project**

```bash
uv init --no-readme
```

- [ ] **Step 2: Configure pyproject.toml**

```toml
[project]
name = "chinext-quant"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "tushare>=1.4.29",
    "pandas>=3.0",
    "numpy>=2.4",
    "torch>=2.0",
    "matplotlib>=3.7",
    "scikit-learn>=1.3",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[dependency-groups]
dev = ["pytest>=7.0"]
```

- [ ] **Step 3: Install dependencies**

```bash
uv sync
```

- [ ] **Step 4: Create run.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$DIR/.env" ]; then set -a; source "$DIR/.env"; set +a; fi
uv run python src/main.py "$@"
```

- [ ] **Step 5: Create directory structure**

```bash
mkdir -p src/data src/timer src/ranker src/portfolio src/engine tests data/raw data/features output
touch src/__init__.py src/data/__init__.py src/timer/__init__.py src/ranker/__init__.py src/portfolio/__init__.py src/engine/__init__.py tests/__init__.py
```

- [ ] **Step 6: Update .gitignore**

```
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/raw/
data/features/
output/
```

- [ ] **Step 7: Verify environment**

```bash
uv run python -c "import tushare, pandas, numpy, torch, matplotlib, sklearn; print('All OK')"
```

---

### Task 2: Data Fetcher (`src/data/fetcher.py`)

关键修正：个股日线改用 `pro.daily()` 按日期批量拉取。

- [ ] **Step 1: Write tests** (`tests/test_fetcher.py`)

测试 `fetch_trade_calendar`, `fetch_stock_basic`, `fetch_index_daily`, `fetch_daily_all`, `fetch_daily_basic`, `fetch_fina_indicator`。使用 mock pro API + tmp_path 缓存目录。

- [ ] **Step 2: Write implementation**

核心接口：
```python
init_tushare(token) -> pro
fetch_trade_calendar(pro, start, end, cache_dir) -> DataFrame  # 仅交易日
fetch_stock_basic(pro, cache_dir) -> DataFrame  # 仅创业板
fetch_index_daily(pro, ts_code, start, end, cache_dir) -> DataFrame
fetch_daily_all(pro, start, end, cache_dir) -> DataFrame  # 按日期批量拉取所有股票日线
fetch_daily_basic(pro, start, end, cache_dir) -> DataFrame
fetch_fina_indicator(pro, ts_code, cache_dir) -> DataFrame
```

`fetch_daily_all` 改为按月分段调用 `pro.daily(trade_date=date)`，一次拉一天所有股票，比逐股拉取快 ~100x。

- [ ] **Step 3: Run tests, commit**

---

### Task 3: Data Cleaner (`src/data/cleaner.py`)

无修正，与原 plan 一致。

- [ ] **Step 1: Write tests** — filter_st, filter_new_stocks, filter_suspended, fill_missing_cross_section
- [ ] **Step 2: Write implementation**
- [ ] **Step 3: Run tests, commit**

---

### Task 4: Timer Feature Engineering (`src/timer/features.py`)

关键修正：`compute_index_features` 保留 close 列在输出中。

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Write implementation**

`compute_index_features(df)` 返回 DataFrame 包含 trade_date + close + ~20 feature columns。
`build_sequences_and_labels(features_df, feature_cols, seq_len, horizon, thresholds)` 直接从 features_df["close"] 计算标签。

- [ ] **Step 3: Run tests, commit**

---

### Task 5: LSTM/GRU Model (`src/timer/model.py`)

关键修正：
- forward 输出 raw logits（不加 softmax），训练用 CrossEntropyLoss
- 两层 LSTM 分别 64/32 hidden units（与 spec 对齐）
- 提供 `predict_probas(model, X)` 方法，推理时加 softmax

- [ ] **Step 1: Write tests**

```python
def test_forward_output_logits():
    # 输出 shape (batch, 3)，不是概率（不 sum to 1）
    ...

def test_predict_probas():
    # 输出 shape (batch, 3)，sum to 1
    ...
```

- [ ] **Step 2: Write implementation**

```python
class TimerModel(nn.Module):
    def __init__(self, n_features, hidden1=64, hidden2=32, dropout=0.3):
        self.lstm1 = nn.LSTM(n_features, hidden1, batch_first=True)
        self.dropout1 = nn.Dropout(dropout)
        self.lstm2 = nn.LSTM(hidden1, hidden2, batch_first=True)
        self.dropout2 = nn.Dropout(dropout)
        self.fc1 = nn.Linear(hidden2, 16)
        self.fc2 = nn.Linear(16, 3)

    def forward(self, x):
        out, _ = self.lstm1(x)
        out = self.dropout1(out)
        out, _ = self.lstm2(out)
        last = out[:, -1, :]
        out = F.relu(self.fc1(self.dropout2(last)))
        return self.fc2(out)  # raw logits, NO softmax

def predict_probas(model, X: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(X, dtype=torch.float32))
        return F.softmax(logits, dim=1).numpy()
```

- [ ] **Step 3: Run tests, commit**

---

### Task 6: Position Signal Generator (`src/timer/signal.py`)

修正：调用 `predict_probas` 而非直接 `model(x)`。

- [ ] **Step 1: Write tests** — probas_to_position, discretize_position
- [ ] **Step 2: Write implementation**
- [ ] **Step 3: Run tests, commit**

---

### Task 7: Factor Computation (`src/ranker/factors.py`)

关键修正：向量化计算，不逐日循环。

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Write implementation**

所有因子函数改为向量化：
```python
def compute_all_factors(daily_merged, index_daily, fina_all) -> DataFrame:
    """一次性计算所有日期所有股票的全部因子。
    返回 DataFrame[ts_code, trade_date, momentum_20d, pe_inverse, ...]"""
    # momentum: groupby('ts_code').close.pct_change(20)
    # pe_inverse: 1 / pe_ttm
    # turnover_20d: groupby('ts_code').turnover_rate.rolling(20).mean()
    # rel_strength: stock_ret_20d - index_ret_20d
    # 财务因子: merge_asof by ann_date
```

- [ ] **Step 3: Run tests, commit**

---

### Task 8: Factor Normalization (`src/ranker/normalize.py`)

无修正，与原 plan 一致。

- [ ] **Step 1: Write tests** — winsorize_mad, zscore_cross_section
- [ ] **Step 2: Write implementation**
- [ ] **Step 3: Run tests, commit**

---

### Task 9: StockRank Scorer (`src/ranker/scorer.py`)

无修正。

- [ ] **Step 1: Write tests** — compute_composite_score, rank_top_n, DEFAULT_WEIGHTS
- [ ] **Step 2: Write implementation**
- [ ] **Step 3: Run tests, commit**

---

### Task 10: Transaction Cost Model (`src/portfolio/cost.py`)

无修正。

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Write implementation**
- [ ] **Step 3: Run tests, commit**

---

### Task 11: Portfolio Allocator (`src/portfolio/allocator.py`)

无修正。

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Write implementation**
- [ ] **Step 3: Run tests, commit**

---

### Task 12: Performance Metrics (`src/engine/metrics.py`)

无修正。

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Write implementation**
- [ ] **Step 3: Run tests, commit**

---

### Task 13: Backtest Engine (`src/engine/backtest.py`)

关键修正：`bought_today` 在循环顶部无条件清空。

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Write implementation**

```python
for date in dates:
    prev_bought = bought_today  # 保存昨天买入的
    bought_today = set()        # 无条件清空

    # ... apply_t_plus_1 用 prev_bought
```

- [ ] **Step 3: Run tests, commit**

---

### Task 14: Main Orchestrator (`src/main.py`)

关键修正：
- `_get_retrain_dates` 验证训练数据充足性
- 因子计算调用向量化的 `compute_all_factors`
- 数据拉取用 `fetch_daily_all`

- [ ] **Step 1: Write implementation**
- [ ] **Step 2: Run all tests, commit**

---

### Task 15: Integration Test & End-to-End Verification

- [ ] **Step 1: `uv run pytest tests/ -v`**
- [ ] **Step 2: Smoke test** `./run.sh --start 20240101 --end 20240301 --capital 100000`
- [ ] **Step 3: Review output/backtest_report.md**

---

## Dependency Graph

```
Task 1 (Setup)
  ├── Task 2 (Fetcher) → Task 3 (Cleaner)
  ├── Task 4 (Features) → Task 5 (Model) → Task 6 (Signal)
  ├── Task 7 (Factors) → Task 8 (Normalize) → Task 9 (Scorer)
  ├── Task 10 (Cost) → Task 11 (Allocator)
  └── Task 12 (Metrics)
        └── Task 13 (Backtest) ← depends on 10, 11
              └── Task 14 (Main) ← depends on all
                    └── Task 15 (Integration)
```

**可并行组**（Task 1 完成后）：
- Group A: Tasks 2-3
- Group B: Tasks 4-6
- Group C: Tasks 7-9
- Group D: Tasks 10-11
- Group E: Task 12
