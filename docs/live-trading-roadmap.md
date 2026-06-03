# GemStar Live Trading Radar Roadmap

CALLING SPEC:
    Read this roadmap before changing GemStar toward the live A-share
    investment assistant goal.

    Inputs:
        - Existing daily research pipeline, strategies, factor ranker, timer,
          portfolio allocation, scheduler, and data fetcher modules.
        - User objective: keep GemStar running continuously, compute strategy
          state, scan trading-session signals, and notify actionable buy/sell
          guidance.

    Outputs:
        - A sequence of small code changes with verification gates.
        - A commit boundary after each verified slice.

    Side effects:
        - Documentation only. No runtime behavior is changed by this file.

# Goal

GemStar should evolve from a daily research pipeline into a personal A-share
investment radar:

- Run continuously.
- Compute and refresh strategy state outside trading hours.
- Watch the market during A-share trading sessions.
- Emit explicit buy, sell, reduce, add, and hold guidance.
- Push actionable messages before any manual or future broker-side execution.
- Keep every signal explainable, reproducible, and bounded by risk controls.

The first production target is not automatic broker execution. The first target
is a reliable paper/live alert loop that tells the user what to do and why.

# Current State

GemStar already has reusable research infrastructure:

- `src/data/`: Tushare data fetch and local cache.
- `src/timer/`: daily index timing model and position signal generation.
- `src/ranker/`: cross-sectional factor scoring and Top-N ranking.
- `src/portfolio/`: allocation and A-share trading constraints.
- `src/engine/`: deterministic backtest engine.
- `src/orchestrator/`: daily FSM, artifacts, rankings, signals, scheduler.
- `src/cli/commands/daemon_cmd.py`: background process pattern.

But current runtime behavior is daily and batch-oriented:

- `gemstar scheduler start` waits for configured fetch/run times.
- `gemstar run` performs a daily research pipeline.
- Current `signals` are backtest inputs, not trading-session alerts.
- No notification channel exists.
- No live/paper position ledger exists.
- No intraday market clock or polling loop exists.

# Target Architecture

Add a parallel live path without weakening the research path:

```text
src/live/
    market_clock.py       # A-share sessions and polling cadence
    state.py              # paper/live account state and dedupe state
    snapshot.py           # normalized market snapshot input contract
    planner.py            # target portfolio from strategy outputs
    signal_engine.py      # actionable BUY/SELL/HOLD decisions
    loop.py               # long-running live radar loop

src/notify/
    message.py            # canonical notification payload
    local_file.py         # deterministic no-network notification sink
    feishu.py             # optional network sink

src/cli/commands/live_cmd.py
    gemstar live plan
    gemstar live once
    gemstar live start
```

The first implementation should use a local-file notification sink so tests do
not need network access. Feishu or enterprise IM can be added after the core
signal contract is stable.

# Milestones

## M0. Roadmap and Commit Discipline

Change:

- Add this roadmap.
- Use one commit per verified slice.
- Keep every new module below 800 LOC and give it a top-level calling spec.

Verification:

- `python -m compileall docs` is not meaningful for Markdown, so use file review
  and `wc -l docs/live-trading-roadmap.md`.
- Confirm `git status --short` only contains the roadmap before committing.

Expected effect:

- The implementation path is explicit and auditable.

Commit:

- `docs: add live trading radar roadmap`

## M1. Live Domain Schemas

Change:

- Add `src/schemas/live.py`.
- Define strongly validated Pydantic models:
  - `LivePositionV1`
  - `LiveAccountStateV1`
  - `MarketSnapshotV1`
  - `TargetHoldingV1`
  - `TradingIntentV1`
  - `LiveDecisionV1`
- Use `ConfigDict(extra="forbid")`.
- Add explicit numeric bounds for price, shares, confidence, target weight, and
  position percentage.

Verification:

- Add `tests/test_live_schemas.py`.
- Validate:
  - Unknown fields are rejected.
  - Negative prices/shares are rejected.
  - Decision actions are restricted to known values.
  - Minimal valid decision serializes to a stable dict.
- Run: `uv run python -m pytest tests/test_live_schemas.py`.

Expected effect:

- Future live modules have a zero-hallucination contract for market, account,
  and decision data.

Commit:

- `feat: add live trading schemas`

## M2. A-Share Market Clock

Change:

- Add `src/live/market_clock.py`.
- Implement pure functions:
  - `session_for_time(now) -> TradingSession`
  - `is_trading_time(now) -> bool`
  - `next_poll_seconds(now, active_interval, idle_interval) -> int`
- Cover A-share sessions:
  - pre-open: before 09:30
  - morning: 09:30-11:30
  - lunch: 11:30-13:00
  - afternoon: 13:00-15:00
  - after-close: after 15:00
- Keep holiday/trading-day knowledge injectable, not hard-coded, so it can use
  Tushare trade calendar later.

Verification:

- Add `tests/test_live_market_clock.py`.
- Validate boundary times: 09:29, 09:30, 11:30, 13:00, 15:00.
- Validate active sessions return trading time and lunch/closed sessions do not.
- Run: `uv run python -m pytest tests/test_live_market_clock.py`.

Expected effect:

- The live loop can run 24 hours while only scanning aggressively during trading
  sessions.

Commit:

- `feat: add a-share live market clock`

## M3. Local Notification Sink

Change:

- Add `src/notify/message.py`.
- Add `src/notify/local_file.py`.
- Define a deterministic message format:
  - timestamp
  - severity
  - title
  - body
  - decision id
  - action
  - symbol list
- Implement append-only JSONL sink.

Verification:

- Add `tests/test_notify_local_file.py`.
- Validate one emitted message writes one JSON line.
- Validate repeated messages preserve order.
- Validate sink creates parent directories.
- Run: `uv run python -m pytest tests/test_notify_local_file.py`.

Expected effect:

- GemStar can produce actionable alerts without depending on Feishu, WeChat,
  Feishu, or external network availability.

Commit:

- `feat: add local notification sink`

## M4. Live Signal Engine

Change:

- Add `src/live/signal_engine.py`.
- Pure function:
  - `build_live_decisions(account, targets, snapshots, risk_config) -> list[LiveDecisionV1]`
- Decision rules for the first slice:
  - Buy when target shares are above current shares and price is valid.
  - Sell when target shares are below current shares.
  - Hold when difference is below one lot.
  - Block buy on limit-up and block sell on limit-down when snapshot flags exist.
  - Deduplicate stable decision ids by date, code, action, target shares.

Verification:

- Add `tests/test_live_signal_engine.py`.
- Validate buy, sell, hold, limit-up blocked buy, limit-down blocked sell.
- Validate decisions include reason and confidence.
- Run: `uv run python -m pytest tests/test_live_signal_engine.py`.

Expected effect:

- GemStar can turn desired portfolio state into concrete A-share trading
  guidance.

Commit:

- `feat: add live signal engine`

## M5. Strategy-to-Target Planner

Change:

- Add `src/live/planner.py`.
- Reuse existing `compute_target_shares` from `src/portfolio/allocator.py`.
- Convert existing daily strategy outputs into target holdings:
  - timer position percentage
  - ranked Top-N symbols
  - latest available prices
  - account total value

Verification:

- Add `tests/test_live_planner.py`.
- Validate equal allocation across Top-N.
- Validate position percentage scales total exposure.
- Validate empty rankings returns empty targets.
- Run: `uv run python -m pytest tests/test_live_planner.py`.

Expected effect:

- Existing research strategy outputs become live target portfolio instructions.

Commit:

- `feat: plan live targets from strategy outputs`

## M6. Single-Cycle Live Command

Change:

- Add `src/cli/commands/live_cmd.py`.
- Register `gemstar live once`.
- Use deterministic local inputs first:
  - account JSON
  - targets JSON or generated targets
  - snapshots JSON
  - output notifications JSONL
- Do not fetch network data in this milestone.

Verification:

- Add `tests/test_cli_live.py`.
- Validate CLI help shows `live`.
- Validate `gemstar live once` emits expected JSONL notification for a fixture.
- Run: `uv run python -m pytest tests/test_cli_live.py`.

Expected effect:

- The user can run one local live decision cycle and inspect notifications.

Commit:

- `feat: add live once command`

## M7. Long-Running Live Loop

Change:

- Add `src/live/loop.py`.
- Register `gemstar live start`.
- Loop behavior:
  - Sleep at idle cadence outside trading sessions.
  - Poll at active cadence during trading sessions.
  - Emit notifications only for new decision ids.
  - Write heartbeat logs.
  - Stop cleanly on SIGINT/SIGTERM.

Verification:

- Add unit tests with fake clock and fake sleep.
- Validate no busy loop.
- Validate dedupe prevents repeated notifications.
- Validate stop event exits cleanly.
- Run focused tests, then run full CLI help tests.

Expected effect:

- GemStar can stay alive 24 hours and scan more frequently only when it matters.

Commit:

- `feat: add live radar loop`

## M8. Data Adapter for Near-Real-Time Snapshots

Change:

- Add `src/live/snapshot.py`.
- First adapter reads local cached daily data as a degraded/live-latency source.
- Later adapter can use Tushare realtime or another quote provider.
- Normalize all providers into `MarketSnapshotV1`.

Verification:

- Add fixture-driven tests.
- Validate missing price data causes a blocked decision, not a crash.
- Validate all snapshot providers return the same schema.

Expected effect:

- Signal engine remains provider-agnostic.

Commit:

- `feat: add live snapshot adapter`

## M9. External Notification Channel

Change:

- Add optional Feishu sink after local sink is stable.
- Config fields:
  - enabled
  - bot token env var
  - chat id env var
  - severity threshold
- Keep local file sink available as fallback.

Verification:

- Unit-test request payload construction without network.
- Optional manual smoke test only when credentials exist.

Expected effect:

- The user receives actionable messages on a phone or desktop IM channel.

Commit:

- `feat: add feishu notification sink`

## M10. Paper Ledger and Human Confirmation

Change:

- Add append-only paper ledger.
- Record intended action, notification time, user confirmation status, and
  resulting simulated position.
- Require explicit confirmation before marking a trade executed.

Verification:

- Test ledger append/read/replay.
- Test duplicate execution ids are rejected.
- Test T+1 sell restrictions are preserved in ledger logic.

Expected effect:

- The system can measure whether alerts would have made money and whether the
  user followed them.

Commit:

- `feat: add paper trading ledger`

# Cross-Validation Matrix

Every milestone must prove three things:

| Layer | Evidence | Why it matters |
| --- | --- | --- |
| Schema | Pydantic validation tests | Invalid live decisions fail early. |
| Pure logic | Focused unit tests | Trading rules are deterministic and inspectable. |
| CLI behavior | Typer runner tests | The user-facing command actually works. |
| Persistence | JSON/JSONL fixture tests | Alerts and state can be audited after the fact. |
| Integration | One-cycle live command | Existing strategy outputs can become live guidance. |

# Safety Boundaries

- Do not add automatic broker execution until alerting, paper ledger, and risk
  controls are proven.
- Do not let LLM output directly place trades or mutate account state.
- Keep deterministic trading math in pure, tested functions.
- Treat missing data as a blocked/hold decision, not as permission to trade.
- Prefer explicit user confirmation for anything that changes real money state.

# Definition of Done for the First Live MVP

The first live MVP is complete when:

- `gemstar live once` can turn account, targets, and snapshots into actionable
  notifications.
- `gemstar live start` can run continuously with fake/test data and clean stop.
- Alerts include action, symbol, shares, reason, confidence, and risk block if
  applicable.
- Duplicate alerts are suppressed.
- Focused live/notify tests pass.
- Existing scheduler/run tests still pass.
