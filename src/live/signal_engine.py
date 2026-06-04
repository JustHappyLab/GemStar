"""Convert live targets and snapshots into actionable trading decisions.

CALLING SPEC:
    decisions = build_live_decisions(
        account=LiveAccountStateV1,
        targets=list[TargetHoldingV1],
        snapshots=list[MarketSnapshotV1],
        strategy_name=str,
        created_at=datetime | None,
    ) -> list[LiveDecisionV1]

SIDE EFFECTS:
    None. This module contains deterministic decision logic only.
"""

from __future__ import annotations

from datetime import datetime

from src.schemas.live import (
    LiveAccountStateV1,
    LiveDecisionV1,
    MarketSnapshotV1,
    TargetHoldingV1,
    TradingIntentV1,
)


def build_live_decisions(
    account: LiveAccountStateV1,
    targets: list[TargetHoldingV1],
    snapshots: list[MarketSnapshotV1],
    strategy_name: str,
    created_at: datetime | None = None,
    min_trade_value: float = 0.0,
    required_trade_date: str | None = None,
) -> list[LiveDecisionV1]:
    """Build one decision per target/position symbol."""
    now = created_at or datetime.now()
    current_shares = {p.ts_code: p.shares for p in account.positions}
    target_shares = {t.ts_code: t.target_shares for t in targets}
    target_reasons = {t.ts_code: t.reason for t in targets}
    snapshot_map = {s.ts_code: s for s in snapshots}

    symbols = sorted(set(current_shares) | set(target_shares))
    return [
        _decision_for_symbol(
            ts_code=ts_code,
            current_shares=current_shares.get(ts_code, 0),
            target_shares=target_shares.get(ts_code, 0),
            target_reason=target_reasons.get(ts_code, ""),
            snapshot=snapshot_map.get(ts_code),
            strategy_name=strategy_name,
            created_at=now,
            min_trade_value=min_trade_value,
            required_trade_date=required_trade_date,
        )
        for ts_code in symbols
    ]


def _decision_for_symbol(
    ts_code: str,
    current_shares: int,
    target_shares: int,
    target_reason: str,
    snapshot: MarketSnapshotV1 | None,
    strategy_name: str,
    created_at: datetime,
    min_trade_value: float = 0.0,
    required_trade_date: str | None = None,
) -> LiveDecisionV1:
    action, shares, reason, risk_flags, notify_override = _intent_fields(
        current_shares=current_shares,
        target_shares=target_shares,
        target_reason=target_reason,
        snapshot=snapshot,
        min_trade_value=min_trade_value,
        required_trade_date=required_trade_date,
    )
    reference_price = snapshot.last_price if snapshot is not None else None
    trade_date = snapshot.trade_date if snapshot is not None else created_at.strftime("%Y%m%d")

    return LiveDecisionV1(
        decision_id=_decision_id(trade_date, ts_code, action, target_shares),
        created_at=created_at,
        strategy_name=strategy_name,
        ts_code=ts_code,
        severity="critical" if action == "blocked" else ("info" if action == "hold" else "warning"),
        intent=TradingIntentV1(
            action=action,
            shares=shares,
            reference_price=reference_price,
            confidence=0.5 if action == "blocked" else 0.8,
            reason=reason,
            risk_flags=risk_flags,
        ),
        notify=(action != "hold") if notify_override is None else notify_override,
    )


def _intent_fields(
    current_shares: int,
    target_shares: int,
    target_reason: str,
    snapshot: MarketSnapshotV1 | None,
    min_trade_value: float = 0.0,
    required_trade_date: str | None = None,
) -> tuple[str, int, str, list[str], bool | None]:
    if snapshot is None:
        return "blocked", 0, "missing market snapshot", ["missing_snapshot"], None

    if required_trade_date and snapshot.trade_date != required_trade_date:
        return (
            "blocked",
            0,
            f"stale market snapshot: {snapshot.trade_date} != {required_trade_date}",
            ["stale_snapshot"],
            False,
        )

    diff = target_shares - current_shares
    if abs(diff) < 100:
        return "hold", 0, "target is within one trading lot of current position", [], None

    if diff > 0:
        if snapshot.limit_up:
            return "blocked", 0, "buy blocked because the stock is limit-up", ["limit_up"], None
        action = "buy" if current_shares == 0 else "add"
        if _below_min_trade_value(diff, snapshot.last_price, min_trade_value):
            return "hold", 0, "trade value is below live minimum threshold", ["min_trade_value"], None
        return action, diff, _join_reason("target shares exceed current shares", target_reason), [], None

    sell_shares = abs(diff)
    if snapshot.limit_down:
        return "blocked", 0, "sell blocked because the stock is limit-down", ["limit_down"], None
    action = "sell" if target_shares == 0 else "reduce"
    if _below_min_trade_value(sell_shares, snapshot.last_price, min_trade_value):
        return "hold", 0, "trade value is below live minimum threshold", ["min_trade_value"], None
    return action, sell_shares, _join_reason("target shares are below current shares", target_reason), [], None


def _below_min_trade_value(shares: int, price: float | None, min_trade_value: float) -> bool:
    if min_trade_value <= 0 or price is None:
        return False
    return shares * price < min_trade_value


def _join_reason(base: str, detail: str) -> str:
    if not detail:
        return base
    return f"{base}: {detail}"


def _decision_id(trade_date: str, ts_code: str, action: str, target_shares: int) -> str:
    return f"{trade_date}-{ts_code}-{action}-{target_shares}"
