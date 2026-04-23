"""Daily backtest engine.

CALLING SPEC:
    result = run_backtest(
        daily_df=pd.DataFrame,
        signals=pd.DataFrame,
        rankings=dict[str, list[str]],
        initial_capital=float,
        trade_dates=list[str] | None,
        volume_limit_pct=float,
    ) -> dict
        daily_df columns: ts_code, trade_date, open, close, high, low, pre_close, vol
        signals columns: trade_date, position
        rankings maps trade_date -> ranked stock codes
        volume_limit_pct: max fraction of daily volume per trade (default 0.25)

        Returns:
            nav: pd.Series indexed by trade_date
            trades: list[dict]
            daily_log: list[dict]
            trade_pnls: pd.Series of completed round-trip position-cycle PnL
            daily_turnover: pd.Series indexed by trade_date
            daily_exposure: pd.Series indexed by trade_date

SIDE EFFECTS:
    None.
"""

import pandas as pd

from src.portfolio.allocator import check_limit_up_down, compute_target_shares
from src.portfolio.cost import apply_slippage, calc_trade_cost


def _record_buy_lot(open_lots: dict[str, list[dict[str, float]]], code: str, shares: int, price: float, cost: float) -> None:
    if shares <= 0:
        return
    cost_per_share = (price * shares + cost) / shares
    open_lots.setdefault(code, []).append({"shares": shares, "cost_per_share": cost_per_share})


def _realize_sell_pnl(
    open_lots: dict[str, list[dict[str, float]]],
    code: str,
    shares: int,
    price: float,
    cost: float,
) -> float:
    if shares <= 0:
        return 0.0

    remaining = shares
    basis_cost = 0.0
    lots = open_lots.get(code, [])
    while remaining > 0 and lots:
        lot = lots[0]
        take = min(remaining, int(lot["shares"]))
        basis_cost += take * float(lot["cost_per_share"])
        lot["shares"] -= take
        remaining -= take
        if lot["shares"] == 0:
            lots.pop(0)

    if not lots and code in open_lots:
        del open_lots[code]
    if remaining > 0:
        basis_cost += remaining * price

    net_sell_proceeds = price * shares - cost
    return net_sell_proceeds - basis_cost


def _cap_shares_by_volume(shares: int, vol: float, volume_limit_pct: float) -> int:
    """Round down to 100-lot aligned volume cap."""
    if vol <= 0 or volume_limit_pct <= 0:
        return shares
    max_shares = int(vol * volume_limit_pct // 100) * 100
    return min(shares, max_shares)


def _fit_buy_shares_to_cash(price: float, desired_shares: int, cash: float, trade_date: str, cost_multiplier: float = 1.0) -> tuple[int, float]:
    shares = desired_shares
    while shares > 0:
        cost = calc_trade_cost(price, shares, "buy", trade_date, cost_multiplier)
        needed = price * shares + cost
        if needed <= cash:
            return shares, cost
        shares -= 100
    return 0, 0.0


def run_backtest(daily_df, signals, rankings, initial_capital=100000, trade_dates=None, volume_limit_pct=0.25, cost_multiplier=1.0) -> dict:
    """Day-by-day backtest."""
    dates = sorted(signals["trade_date"].astype(str).unique()) if trade_dates is None else list(trade_dates)
    sig_map = signals.assign(trade_date=signals["trade_date"].astype(str)).set_index("trade_date")["position"].to_dict()

    cash = float(initial_capital)
    holdings: dict[str, int] = {}
    open_lots: dict[str, list[dict[str, float]]] = {}
    cycle_realized_pnl: dict[str, float] = {}
    nav_list, trades, daily_log, turnover_list = [], [], [], []
    exposure_list = []
    realized_pnls: list[float] = []

    daily_grouped = dict(tuple(daily_df.groupby("trade_date")))

    for date in dates:
        day_data = daily_grouped.get(date, pd.DataFrame())
        open_prices = dict(zip(day_data["ts_code"], day_data["open"]))
        close_prices = dict(zip(day_data["ts_code"], day_data["close"]))
        volumes = dict(zip(day_data["ts_code"], day_data["vol"]))

        # holdings value at open
        holdings_value = sum(open_prices.get(c, 0) * s for c, s in holdings.items())
        total_value = cash + holdings_value

        position_pct = sig_map.get(date, 0.0)
        top_stocks = rankings.get(date, [])

        limits = check_limit_up_down(daily_df, date)
        target = compute_target_shares(top_stocks, open_prices, total_value, position_pct)

        day_turnover = 0.0

        # sell first
        for code in list(holdings):
            target_shares = target.get(code, 0)
            held = holdings[code]
            if target_shares < held:
                info = limits.get(code, {})
                if info.get("limit_down"):
                    continue
                sell_shares = held - target_shares
                sell_shares = _cap_shares_by_volume(sell_shares, volumes.get(code, 0), volume_limit_pct)
                if sell_shares == 0:
                    continue
                fill_price = apply_slippage(open_prices.get(code, 0), "sell")
                cost = calc_trade_cost(fill_price, sell_shares, "sell", date, cost_multiplier)
                cash += fill_price * sell_shares - cost
                day_turnover += fill_price * sell_shares
                cycle_realized_pnl[code] = cycle_realized_pnl.get(code, 0.0) + _realize_sell_pnl(
                    open_lots, code, sell_shares, fill_price, cost,
                )
                holdings[code] = held - sell_shares
                if holdings[code] == 0:
                    del holdings[code]
                    realized_pnls.append(cycle_realized_pnl.pop(code, 0.0))
                trades.append({"date": date, "code": code, "dir": "sell",
                               "shares": sell_shares, "price": fill_price, "cost": cost})

        # buy
        for code, tgt in target.items():
            held = holdings.get(code, 0)
            if tgt > held:
                info = limits.get(code, {})
                if info.get("limit_up"):
                    continue
                buy_shares = tgt - held
                buy_shares = _cap_shares_by_volume(buy_shares, volumes.get(code, 0), volume_limit_pct)
                if buy_shares == 0:
                    continue
                fill_price = apply_slippage(open_prices.get(code, 0), "buy")
                buy_shares, cost = _fit_buy_shares_to_cash(fill_price, buy_shares, cash, date, cost_multiplier)
                if buy_shares == 0:
                    continue
                needed = fill_price * buy_shares + cost
                cash -= needed
                day_turnover += fill_price * buy_shares
                if held == 0 and code not in cycle_realized_pnl:
                    cycle_realized_pnl[code] = 0.0
                holdings[code] = held + buy_shares
                _record_buy_lot(open_lots, code, buy_shares, fill_price, cost)
                trades.append({"date": date, "code": code, "dir": "buy",
                               "shares": buy_shares, "price": fill_price, "cost": cost})

        # mark to close
        holdings_value_close = sum(close_prices.get(c, 0) * s for c, s in holdings.items())
        nav = cash + holdings_value_close
        exposure = holdings_value_close / nav if nav != 0 else 0.0
        nav_list.append({"date": date, "nav": nav})
        turnover_list.append({"date": date, "turnover": day_turnover})
        exposure_list.append({"date": date, "exposure": exposure})
        daily_log.append({"date": date, "cash": cash, "holdings": dict(holdings), "nav": nav, "exposure": exposure})

    # Mark remaining positions to last close and flush as realized PnL
    if dates:
        last_data = daily_grouped.get(dates[-1], pd.DataFrame())
        last_close = dict(zip(last_data["ts_code"], last_data["close"]))
        for code, shares in holdings.items():
            price = last_close.get(code, 0)
            unrealized = _realize_sell_pnl(open_lots, code, shares, price, 0.0)
            realized_pnls.append(cycle_realized_pnl.pop(code, 0.0) + unrealized)

    nav_series = pd.Series({r["date"]: r["nav"] for r in nav_list})
    turnover_series = pd.Series({r["date"]: r["turnover"] for r in turnover_list})
    exposure_series = pd.Series({r["date"]: r["exposure"] for r in exposure_list})
    trade_pnls = pd.Series(realized_pnls, dtype=float)

    return {
        "nav": nav_series,
        "trades": trades,
        "daily_log": daily_log,
        "trade_pnls": trade_pnls,
        "daily_turnover": turnover_series,
        "daily_exposure": exposure_series,
    }
