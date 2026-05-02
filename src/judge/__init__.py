"""Rule-based judge for strategy verdicts.

CALLING SPEC:
    Exports ``evaluate`` — the single public entry point that takes a
    ``BacktestResultV1`` and returns a ``VerdictV1`` with per-gate pass/fail
    and a recommended state transition.
"""
