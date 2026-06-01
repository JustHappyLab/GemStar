---
name: gemstar-qclaw
description: 通过 QClaw/微信查询 GemStar 量化交易提醒、最新信号、目标持仓和运行状态；只允许查看或显式触发一次本地研究流程，禁止实盘下单。
---

# GemStar QClaw Skill

Use this skill when the user asks in WeChat/QClaw about GemStar, trading alerts, live signals, paper ledger, target holdings, leaderboard, or whether GemStar has buy/sell guidance.

## Repository

GemStar lives at:

```bash
/Users/ken/workspace/GemStar
```

Run all GemStar commands from that directory.

## Primary Commands

Latest WeChat-friendly alerts:

```bash
cd /Users/ken/workspace/GemStar
uv run python -m src.cli.app alerts latest --limit 5
```

Use the bundled script when the current directory is unknown:

```bash
bash /Users/ken/workspace/GemStar/skills/gemstar-qclaw/scripts/gemstar-alerts.sh 5
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

Pipeline status:

```bash
cd /Users/ken/workspace/GemStar
uv run python -m src.cli.app status
```

## Optional Manual Run

Only run this when the user explicitly asks to refresh or run GemStar now:

```bash
cd /Users/ken/workspace/GemStar
uv run python -m src.cli.app trade --once --max-cycles 1
```

This may take several minutes because it can run research, LLM roles, target generation, and one live cycle.

## Response Style

- Return concise Chinese summaries suitable for WeChat.
- Preserve stock code and Chinese name, e.g. `300750.SZ 宁德时代`.
- If no alerts exist, say there are no GemStar alerts yet and include the checked path.
- If a command fails, report the command and the short error. Do not invent trading signals.

## Safety Rules

- Never place real trades.
- Never call QMT, ptrade, broker APIs, or order entry tools.
- Never modify strategy YAML, factor pool, credentials, or configuration from WeChat.
- Do not treat GemStar status messages as investment advice; present them as system-generated alerts.
- If the user asks to buy/sell through WeChat, refuse execution and suggest checking the GemStar alert details manually.
