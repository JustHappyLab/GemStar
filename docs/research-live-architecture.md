# Research-to-Live Architecture

CALLING SPEC:
    Read this document when wiring strategy generation to the live radar.

    Inputs:
        - Daily research pipeline artifacts.
        - Validated strategy YAML files and verdicts.
        - Live account, market snapshot, target, notification, and paper ledger
          modules.

    Outputs:
        - A two-loop operating model for GemStar:
          research loop generates and validates strategies;
          live loop watches approved targets and alerts the user.

    Side effects:
        - Documentation only.

# Summary

GemStar should run two connected loops, not one overloaded loop:

1. Research Loop: slow, data-heavy, LLM-assisted, evidence-producing.
2. Live Loop: fast, deterministic, stateful, alert-producing.

The research loop is allowed to explore ideas. The live loop is only allowed to
act on approved strategy outputs and explicit account/market state.

# Research Loop

Purpose:

- Discover context: market regime, events, factor health.
- Generate research tickets.
- Draft candidate strategy YAMLs.
- Validate schemas and factor references.
- Build strategy-specific signals and rankings.
- Backtest and judge strategies.
- Publish artifacts and candidate verdicts.

Recommended order:

```text
Data quality
  -> Factor health
  -> Optional factor mining when candidate generation is requested
  -> Macro/event context
  -> Research tickets
  -> Strategy drafts
  -> Validation
  -> Strategy-specific inputs
  -> Backtest
  -> Rule judge
  -> Reviewer
  -> Leaderboard / candidate artifacts
```

Important boundary:

- FactorMiner is not a prerequisite for every LLM run.
- Research tickets generated during context gathering must be consumed before
  asking ResearchAnalyst for more tickets.
- StrategyArchitect may draft YAML, but RuleJudge/Reviewer decide whether the
  result can move toward live use.

# Live Loop

Purpose:

- Run continuously.
- Poll aggressively only during trading sessions.
- Convert approved target holdings into buy/sell/blocked decisions.
- Deduplicate repeated decisions.
- Notify the user with action, symbol, shares, confidence, risk flags, and
  reason.
- Record confirmed paper executions in an append-only ledger.

Current commands:

```bash
gemstar live once \
  --account account.json \
  --targets targets.json \
  --snapshots snapshots.json \
  --notifications alerts/live.jsonl \
  --strategy-name chinext_lstm_mf8

gemstar live start \
  --account account.json \
  --targets targets.json \
  --snapshots snapshots.json \
  --notifications alerts/live.jsonl \
  --strategy-name chinext_lstm_mf8
```

# Handoff Contract

Research should not directly trigger real trades. It should publish approved
live inputs:

```text
approved strategy YAML
  -> latest strategy-specific ranking
  -> latest timer exposure
  -> target holdings JSON
  -> live radar consumes targets + account + snapshots
```

The handoff artifact should eventually be:

```text
artifacts/<run_id>/live_targets/<strategy_name>.json
```

Each target should include:

- strategy name
- trade date
- symbol
- target shares
- target weight
- reason
- source run id
- source verdict id

# Safety Rules

- LLMs can propose strategy drafts, not execute trades.
- Live decisions are deterministic and schema-validated.
- Missing market data produces blocked decisions.
- Limit-up buys and limit-down sells are blocked.
- Paper executions require explicit confirmation.
- Duplicate paper execution ids are rejected.
- T+1 sell restrictions are enforced in the paper ledger.

# Next Implementation Step

Add a research-to-live exporter:

```text
src/live/exporter.py
```

It should take:

- strategy YAML
- latest rankings
- latest position signal
- latest prices
- account total value
- source run id / verdict id

And write:

- `TargetHoldingV1` JSON for `gemstar live once/start`.

This exporter is the clean bridge between strategy generation and live radar.
