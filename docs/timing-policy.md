# GemStar Timing Policy

CALLING SPEC:
    Read this policy before changing timer generation, StrategyArchitect prompts,
    live target generation, or strategy promotion rules.

    Inputs:
        - Strategy YAML timer configuration.
        - StrategyArchitect draft output.
        - Backtest and live target generation flows.

    Outputs:
        - Guardrails for how timing exposure is selected, tested, and consumed.

    Side effects:
        - Documentation only. Runtime enforcement lives in StrategyArchitect
          normalization and live target generation.

# Policy

GemStar separates stock selection from market timing:

- Stock selection may be explored by AI through factor choice, factor weights,
  universe, `top_n`, and rebalance cadence.
- Market timing controls total exposure and must stay on a small, auditable set
  of templates.
- AI must not freely invent LSTM/GRU architectures, training horizons, sequence
  lengths, thresholds, or retraining schedules in ordinary strategy drafts.

# Current Runtime Rule

StrategyArchitect drafts are stock-selection drafts. They must use:

```yaml
timer:
  mode: full
```

The code also normalizes StrategyArchitect output back to `timer.mode: full` if
an LLM returns another timer mode. Hand-maintained strategy YAMLs may still use
`full`, `ma`, or the existing fixed `lstm` configuration, but those changes are
reviewed as strategy engineering work rather than prompt-level ideation.

# Controlled Timing Templates

Timing should enter automated comparison through named templates, not free-form
LLM-generated parameters. Candidate templates should be added deliberately and
backtested against the same selection sleeve:

| Template | Purpose | AI freedom |
|---|---|---|
| `full` | Baseline full exposure. | May be used in stock-selection drafts. |
| `ma20_guard` | Reduce exposure when benchmark is below a short moving average. | AI may recommend only after the template exists. |
| `ma60_guard` | Reduce exposure when benchmark is below an intermediate trend filter. | AI may recommend only after the template exists. |
| `drawdown_guard` | Reduce exposure after benchmark drawdown breaches a fixed threshold. | AI may recommend only after the template exists. |
| `lstm_baseline` | Existing reviewed LSTM timer with fixed parameters. | AI may recommend the template but not edit parameters. |

Each template must define:

- deterministic inputs and point-in-time alignment rules
- allowed exposure values or continuous exposure range
- fallback behavior when data is missing
- dedicated tests
- backtest evidence before it can affect live targets

# Promotion Rule

A timing template can be used by live trading only after:

- it is implemented as code or an explicit reviewed YAML preset
- it has been backtested with the target stock-selection sleeve
- it improves or stabilizes risk-adjusted results versus `full`
- it does not rely on look-ahead data
- it fails closed when required data or model artifacts are unavailable

# Live Handoff

Live target generation consumes the latest strategy-specific timer exposure and
scales target holdings by that percentage. If a non-`full` timer cannot produce
a valid signal, live target generation must use 0% exposure rather than silently
falling back to 100%.
