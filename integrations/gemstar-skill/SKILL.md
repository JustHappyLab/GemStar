---
name: gemstar-skill
description: 通过兼容 SKILL.md 协议的第三方智能体查询 GemStar 量化交易提醒、最新信号、目标持仓和运行状态；只允许查看或显式触发一次本地研究流程，禁止实盘下单。
---

# GemStar Integration Skill

Use this skill when the user asks from a compatible skill host about GemStar, current holdings, target holdings, trading alerts, live signals, paper ledger, leaderboard, bundled strategies, or whether GemStar has buy/sell guidance.

## Repository

GemStar lives at:

```bash
/Users/ken/workspace/GemStar
```

Run all GemStar commands from that directory.

## Primary Commands

Current holdings, target holdings, and rebalance actions:

```bash
cd /Users/ken/workspace/GemStar
test -f artifacts/current/trade_status.md && cat artifacts/current/trade_status.md
```

Use the bundled script when the current directory is unknown:

```bash
bash /Users/ken/workspace/GemStar/integrations/gemstar-skill/scripts/gemstar-status.sh
```

Machine-readable current trade status:

```bash
cd /Users/ken/workspace/GemStar
test -f artifacts/current/trade_status.json && cat artifacts/current/trade_status.json
```

Latest chat-friendly alerts:

```bash
cd /Users/ken/workspace/GemStar
uv run python -m src.cli.app alerts latest --limit 5
```

Use the bundled script when the current directory is unknown:

```bash
bash /Users/ken/workspace/GemStar/integrations/gemstar-skill/scripts/gemstar-alerts.sh 5
```

Machine-readable latest alerts:

```bash
cd /Users/ken/workspace/GemStar
uv run python -m src.cli.app --output json alerts latest --limit 5
```

Latest leaderboard:

```bash
cd /Users/ken/workspace/GemStar
uv run python -m src.cli.app leaderboard
```

Bundled leaderboard strategy:

```bash
cd /Users/ken/workspace/GemStar
test -f strategies/leaderboard_quality_lowvol_v1/config.yaml && cat strategies/leaderboard_quality_lowvol_v1/config.yaml
```

Pipeline status:

```bash
cd /Users/ken/workspace/GemStar
uv run python -m src.cli.app status
```

## Optional Manual Run

Only run this when the user explicitly asks to refresh or run GemStar now:

```bash
cd /Users/ken/workspace/GemStar
uv run python -m src.cli.app trade --once
```

This may take several minutes because it can run the deterministic production pipeline, target generation, and one live cycle. It does not invoke LLM research unless the user explicitly runs `gemstar research`.

## Response Style

- Return concise Chinese summaries suitable for chat.
- For "当前持仓", "目标仓位", "今天建议", and "为什么买/卖", read `artifacts/current/trade_status.json` first; fall back to `trade_status.md`, then alerts.
- For "最新信号", "最新建议", or "今天信号", always report the status `ref_date` and file `updated_at` first. If `ref_date` is older than today's date, explicitly say the current completed GemStar status is stale and do not present it as today's latest signal.
- For "最新 leaderboard", run `uv run python -m src.cli.app leaderboard` and summarize rank, strategy, status, Sharpe, CAGR, max drawdown, and alpha.
- For "内置榜单策略", read `strategies/leaderboard_quality_lowvol_v1/config.yaml` and summarize universe, timer, factor weights, `top_n`, rebalance frequency, and backtest window.
- Preserve stock code and Chinese name, e.g. `300750.SZ 宁德时代`.
- If no alerts exist, say there are no GemStar alerts yet and include the checked path.
- If no trade status exists, say GemStar has not generated `artifacts/current/trade_status.md` yet and suggest running `gemstar trade --once`.
- If a command fails, report the command and the short error. Do not invent trading signals.

## Safety Rules

- Never place real trades.
- Never call QMT, ptrade, broker APIs, or order entry tools.
- Never modify strategy YAML, factor pool, credentials, or configuration from WeChat or any chat host.
- Do not treat GemStar status messages as investment advice; present them as system-generated alerts.
- If the user asks to buy/sell through a chat host, refuse execution and suggest checking the GemStar alert details manually.
