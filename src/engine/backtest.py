"""Daily backtest engine."""

import pandas as pd

from src.portfolio.allocator import apply_t_plus_1, check_limit_up_down, compute_target_shares
from src.portfolio.cost import calc_trade_cost


def run_backtest(daily_df, signals, rankings, initial_capital=100000) -> dict:
    """Day-by-day backtest.

    daily_df: ts_code, trade_date, open, close, high, low, pre_close, vol
    signals: DataFrame[trade_date, position] (0.0/0.5/1.0)
    rankings: dict[trade_date, list[ts_code]] top-N stocks per day
    Returns: {nav: Series, trades: list[dict], daily_log: list[dict],
              trade_pnls: Series, daily_turnover: Series}
    """
    dates = sorted(signals["trade_date"].unique())
    sig_map = signals.set_index("trade_date")["position"].to_dict()

    cash = float(initial_capital)
    holdings: dict[str, int] = {}
    bought_today: set[str] = set()
    nav_list, trades, daily_log, turnover_list = [], [], [], []

    for date in dates:
        prev_bought = bought_today
        bought_today = set()

        day_data = daily_df[daily_df["trade_date"] == date]
        open_prices = dict(zip(day_data["ts_code"], day_data["open"]))
        close_prices = dict(zip(day_data["ts_code"], day_data["close"]))

        # holdings value at open
        holdings_value = sum(open_prices.get(c, 0) * s for c, s in holdings.items())
        total_value = cash + holdings_value

        position_pct = sig_map.get(date, 0.0)
        top_stocks = rankings.get(date, [])

        limits = check_limit_up_down(daily_df, date)
        target = compute_target_shares(top_stocks, open_prices, total_value, position_pct)
        target = apply_t_plus_1(target, holdings, prev_bought)

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
                price = open_prices.get(code, 0)
                cost = calc_trade_cost(price, sell_shares, "sell", date)
                cash += price * sell_shares - cost
                day_turnover += price * sell_shares
                holdings[code] = target_shares
                if target_shares == 0:
                    del holdings[code]
                trades.append({"date": date, "code": code, "dir": "sell",
                               "shares": sell_shares, "price": price, "cost": cost})

        # buy
        for code, tgt in target.items():
            held = holdings.get(code, 0)
            if tgt > held:
                info = limits.get(code, {})
                if info.get("limit_up"):
                    continue
                buy_shares = tgt - held
                price = open_prices.get(code, 0)
                cost = calc_trade_cost(price, buy_shares, "buy", date)
                needed = price * buy_shares + cost
                if needed > cash:
                    continue
                cash -= needed
                day_turnover += price * buy_shares
                holdings[code] = held + buy_shares
                bought_today.add(code)
                trades.append({"date": date, "code": code, "dir": "buy",
                               "shares": buy_shares, "price": price, "cost": cost})

        # mark to close
        holdings_value_close = sum(close_prices.get(c, 0) * s for c, s in holdings.items())
        nav = cash + holdings_value_close
        nav_list.append({"date": date, "nav": nav})
        turnover_list.append({"date": date, "turnover": day_turnover})
        daily_log.append({"date": date, "cash": cash, "holdings": dict(holdings), "nav": nav})

    nav_series = pd.Series({r["date"]: r["nav"] for r in nav_list})
    turnover_series = pd.Series({r["date"]: r["turnover"] for r in turnover_list})
    # trade pnl per trade code (simplified: close - open for buy trades)
    pnl_data = {}
    for t in trades:
        code = t["code"]
        pnl_data.setdefault(code, 0.0)
        sign = 1 if t["dir"] == "sell" else -1
        pnl_data[code] += sign * t["price"] * t["shares"] - t["cost"]
    trade_pnls = pd.Series(pnl_data)

    return {
        "nav": nav_series,
        "trades": trades,
        "daily_log": daily_log,
        "trade_pnls": trade_pnls,
        "daily_turnover": turnover_series,
    }
