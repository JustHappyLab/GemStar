"""Portfolio allocation utilities."""

import pandas as pd


def compute_target_shares(
    top_stocks: list[str], prices: dict[str, float], total_capital: float, position_pct: float
) -> dict[str, int]:
    if not top_stocks:
        return {}
    capital_per_stock = total_capital * position_pct / len(top_stocks)
    return {
        code: int(capital_per_stock / prices[code] // 100) * 100
        for code in top_stocks
        if prices.get(code)
    }


def check_limit_up_down(daily_df: pd.DataFrame, date: str) -> dict[str, dict]:
    df = daily_df[daily_df["trade_date"] == date].copy()
    result = {}
    for _, row in df.iterrows():
        pct = (row["open"] - row["pre_close"]) / row["pre_close"]
        limit = 0.20
        tolerance = 0.005
        hit = abs(abs(pct) - limit) < tolerance
        result[row["ts_code"]] = {"pct": pct, "limit_up": pct > 0 and hit, "limit_down": pct < 0 and hit}
    return result


def apply_t_plus_1(
    target: dict[str, int], current_holdings: dict[str, int], bought_today: set[str]
) -> dict[str, int]:
    result = dict(target)
    for code in bought_today:
        if code in result and code in current_holdings and result[code] < current_holdings[code]:
            result[code] = current_holdings[code]
    return result
