from src.portfolio.cost import calc_trade_cost, apply_slippage, COMMISSION_RATE, MIN_COMMISSION, SLIPPAGE_RATE, STAMP_TAX_FULL, STAMP_TAX_HALF


def test_buy_cost():
    cost = calc_trade_cost(10.0, 1000, "buy", "20230901")
    turnover = 10000.0
    expected = max(turnover * COMMISSION_RATE, MIN_COMMISSION)
    assert cost == expected


def test_sell_before_stamp_reduction():
    cost = calc_trade_cost(10.0, 1000, "sell", "20230801")
    turnover = 10000.0
    expected = max(turnover * COMMISSION_RATE, MIN_COMMISSION) + turnover * STAMP_TAX_FULL
    assert cost == expected


def test_sell_after_stamp_reduction():
    cost = calc_trade_cost(10.0, 1000, "sell", "20230901")
    turnover = 10000.0
    expected = max(turnover * COMMISSION_RATE, MIN_COMMISSION) + turnover * STAMP_TAX_HALF
    assert cost == expected


def test_small_trade_min_commission():
    cost = calc_trade_cost(1.0, 100, "buy", "20230901")
    assert cost == MIN_COMMISSION


def test_apply_slippage_buy():
    fill = apply_slippage(10.0, "buy")
    assert fill == 10.0 * (1 + SLIPPAGE_RATE)


def test_apply_slippage_sell():
    fill = apply_slippage(10.0, "sell")
    assert fill == 10.0 * (1 - SLIPPAGE_RATE)
