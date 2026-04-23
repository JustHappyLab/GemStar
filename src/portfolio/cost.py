"""A-share transaction cost model."""

COMMISSION_RATE = 0.00025
MIN_COMMISSION = 5.0
SLIPPAGE_RATE = 0.0005
STAMP_TAX_FULL = 0.001
STAMP_TAX_HALF = 0.0005
STAMP_TAX_CUTOFF = "20230828"


def apply_slippage(price: float, direction: str, slippage_rate: float = SLIPPAGE_RATE) -> float:
    """Return the fill price after slippage."""
    if direction == "buy":
        return price * (1 + slippage_rate)
    return price * (1 - slippage_rate)


def calc_trade_cost(price: float, shares: int, direction: str, trade_date: str, cost_multiplier: float = 1.0) -> float:
    """Commission + stamp tax (slippage is now handled via fill price)."""
    turnover = price * shares
    commission = max(turnover * COMMISSION_RATE, MIN_COMMISSION)
    stamp_tax = 0.0
    if direction == "sell":
        rate = STAMP_TAX_HALF if trade_date >= STAMP_TAX_CUTOFF else STAMP_TAX_FULL
        stamp_tax = turnover * rate
    return (commission + stamp_tax) * cost_multiplier
