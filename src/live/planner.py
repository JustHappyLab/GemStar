"""Plan live target holdings from strategy outputs.

CALLING SPEC:
    targets = plan_live_targets(
        top_stocks=list[str],
        prices=dict[str, float],
        total_capital=float,
        position_pct=float,
        reason=str,
    ) -> list[TargetHoldingV1]

SIDE EFFECTS:
    None. This module reuses deterministic portfolio allocation logic.
"""

from __future__ import annotations

from src.portfolio.allocator import compute_target_shares
from src.schemas.live import TargetHoldingV1


def plan_live_targets(
    top_stocks: list[str],
    prices: dict[str, float],
    total_capital: float,
    position_pct: float,
    reason: str = "",
) -> list[TargetHoldingV1]:
    """Convert ranked symbols and timing exposure into target holdings."""
    if total_capital < 0:
        raise ValueError("total_capital must be non-negative")
    if not 0.0 <= position_pct <= 1.0:
        raise ValueError("position_pct must be between 0 and 1")
    if not top_stocks or total_capital == 0 or position_pct == 0:
        return []

    shares_by_code = compute_target_shares(
        top_stocks=top_stocks,
        prices=prices,
        total_capital=total_capital,
        position_pct=position_pct,
    )
    targets: list[TargetHoldingV1] = []
    for code in top_stocks:
        shares = shares_by_code.get(code, 0)
        price = prices.get(code)
        if shares <= 0 or not price:
            continue
        targets.append(
            TargetHoldingV1(
                ts_code=code,
                target_weight=(shares * price) / total_capital,
                target_shares=shares,
                reason=reason,
            )
        )
    return targets
