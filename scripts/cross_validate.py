"""Cross-validate GemStar backtest engine against JoinQuant.

Strategy: equal-weight top-5 ChiNext index constituents by market cap,
monthly rebalance on the 1st trading day, fully invested.

This is a deterministic strategy with no model dependency, making it
easy to replicate exactly on JoinQuant for comparison.

Usage:
    # 1. Run this script to produce GemStar NAV
    uv run python scripts/cross_validate.py

    # 2. Run the equivalent strategy on JoinQuant (see README)
    # 3. Download JoinQuant NAV CSV
    # 4. Compare:
    uv run python scripts/cross_validate.py --compare output/jq_nav.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.fetcher import init_tushare, fetch_trade_calendar, fetch_daily_all
from src.data.cleaner import filter_suspended
from src.engine.backtest import run_backtest
from src.engine.metrics import calc_cagr, calc_sharpe, calc_max_drawdown
from src.portfolio.cost import calc_trade_cost


START = "20230101"
END = "20241231"
CAPITAL = 100_000.0


def _get_top5_by_mcap(daily_df, date, eligible_codes):
    """Pick top-5 stocks by trading amount (proxy for market cap) on a given date."""
    day = daily_df[
        (daily_df["trade_date"] == date) &
        (daily_df["ts_code"].isin(eligible_codes))
    ].copy()
    if day.empty or "amount" not in day.columns:
        return []
    day = day.dropna(subset=["amount"])
    return day.nlargest(5, "amount")["ts_code"].tolist()


def _is_first_trading_day_of_month(date, prev_date):
    if prev_date is None:
        return True
    return date[:6] != prev_date[:6]


def build_rankings(trade_dates, daily_df, index_members):
    """Monthly rebalance: top-5 by trading amount among index members."""
    rankings = {}
    prev_date = None
    current_top5 = []

    for date in trade_dates:
        if _is_first_trading_day_of_month(date, prev_date):
            tradable = filter_suspended(daily_df[daily_df["trade_date"] == date])
            eligible = set(index_members) & set(tradable["ts_code"])
            top5 = _get_top5_by_mcap(daily_df, date, eligible)
            if top5:
                current_top5 = top5
        rankings[date] = current_top5
        prev_date = date

    return rankings


def run_gemstar(pro, jq_holdings=None):
    print(f"[CrossVal] Fetching data {START}~{END}...")
    trade_cal = fetch_trade_calendar(pro, START, END)
    trade_dates = sorted(trade_cal["cal_date"].tolist())
    print(f"  → {len(trade_dates)} trading days")

    daily_all = fetch_daily_all(pro, START, END)

    if "pre_close" not in daily_all.columns:
        daily_all["pre_close"] = daily_all.groupby("ts_code")["close"].shift(1)
        daily_all["pre_close"] = daily_all["pre_close"].fillna(daily_all["open"])

    if jq_holdings:
        print("[CrossVal] Using JoinQuant holdings as rankings (exact replication)")
        rankings = {d: jq_holdings.get(d, []) for d in trade_dates}
    else:
        chinext_codes = daily_all[daily_all["ts_code"].str.match(r"^30[01]")]["ts_code"].unique().tolist()
        print(f"  → {len(chinext_codes)} ChiNext stocks in data")
        print("[CrossVal] Building monthly rankings (top-5 by amount)...")
        rankings = build_rankings(trade_dates, daily_all, chinext_codes)

    # Full position, no timing
    signals = pd.DataFrame({"trade_date": trade_dates, "position": 1.0})

    print("[CrossVal] Running backtest...")
    result = run_backtest(daily_all, signals, rankings, CAPITAL, trade_dates=trade_dates)

    nav = result["nav"]
    daily_ret = nav.pct_change().dropna()
    cagr = calc_cagr(nav)
    sharpe = calc_sharpe(daily_ret)
    mdd, _, _ = calc_max_drawdown(nav)

    print(f"\n{'='*50}")
    print("GemStar Cross-Validation Backtest")
    print(f"{'='*50}")
    print(f"  Period:       {trade_dates[0]} ~ {trade_dates[-1]}")
    print(f"  CAGR:         {cagr:.4f}")
    print(f"  Sharpe:       {sharpe:.4f}")
    print(f"  Max Drawdown: {mdd:.4f}")
    print(f"  Final NAV:    {nav.iloc[-1]:.2f}")

    out_path = Path("output/crossval_gemstar_nav.csv")
    out_path.parent.mkdir(exist_ok=True)
    nav.to_csv(out_path, header=["nav"])
    print(f"\n[CrossVal] Saved to {out_path}")
    return nav


def _parse_jq_holdings(path):
    """Extract daily stock holdings from JoinQuant position CSV."""
    raw = pd.read_csv(path, encoding="gbk", header=None, skiprows=1)
    stocks = raw[(raw[2] != "Cash") & raw[2].notna()].copy()
    stocks["code"] = stocks[2].str.extract(r"\(([^)]+)\)")
    stocks["code"] = stocks["code"].str.replace(".XSHE", ".SZ")
    stocks["date"] = stocks[0].astype(str).str.replace("-", "")
    return stocks.groupby("date")["code"].apply(list).to_dict()


def _parse_jq_position_csv(path):
    """Parse JoinQuant '持仓&收益' CSV (GBK encoded).

    Format: 17 columns (header has 16), col 0=date, col 2=标的, col 15=total_asset.
    Stock rows have total asset; Cash rows don't. Take first stock row per date.
    """
    raw = pd.read_csv(path, encoding="gbk", header=None, skiprows=1)
    stock_rows = raw[raw[2] != "Cash"]
    daily = stock_rows.groupby(0)[15].first().sort_index()
    daily.index = daily.index.astype(str).str.replace("-", "")
    daily.index.name = "trade_date"
    daily.name = "nav"
    return daily.astype(float)


def compare(gemstar_nav, jq_csv_path):
    """Compare GemStar NAV against JoinQuant exported NAV."""
    jq_nav = _parse_jq_position_csv(jq_csv_path)
    print(f"\n[Compare] JoinQuant: {len(jq_nav)} days, {jq_nav.index[0]}~{jq_nav.index[-1]}")
    print(f"[Compare] GemStar:   {len(gemstar_nav)} days, {gemstar_nav.index[0]}~{gemstar_nav.index[-1]}")

    common = gemstar_nav.index.intersection(jq_nav.index)
    print(f"[Compare] Common trading days: {len(common)}")

    if len(common) == 0:
        print("[Compare] No overlapping dates. Check date format.")
        return

    gs = gemstar_nav.loc[common]
    jq = jq_nav.loc[common]

    diff = (gs - jq) / jq * 100  # percentage diff

    print(f"\n{'='*50}")
    print("NAV Difference (GemStar vs JoinQuant)")
    print(f"{'='*50}")
    print(f"  Mean diff:    {diff.mean():.4f}%")
    print(f"  Max diff:     {diff.abs().max():.4f}%")
    print(f"  Std diff:     {diff.std():.4f}%")
    print(f"  Final GS NAV: {gs.iloc[-1]:.2f}")
    print(f"  Final JQ NAV: {jq.iloc[-1]:.2f}")
    print(f"  Final diff:   {diff.iloc[-1]:.4f}%")

    if diff.abs().max() < 5.0:
        print("\n  ✅ Max diff < 5% — engine is reasonably consistent with JoinQuant")
    else:
        print("\n  ⚠️  Max diff >= 5% — investigate divergence points")
        # Show top 5 divergence dates
        worst = diff.abs().nlargest(5)
        print("\n  Top 5 divergence dates:")
        for d, v in worst.items():
            print(f"    {d}: GS={gs.loc[d]:.2f}  JQ={jq.loc[d]:.2f}  diff={diff.loc[d]:.2f}%")

    # Save diff for analysis
    diff_df = pd.DataFrame({"gemstar": gs, "joinquant": jq, "diff_pct": diff})
    diff_path = Path("output/crossval_diff.csv")
    diff_df.to_csv(diff_path)
    print(f"  Saved diff to {diff_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--compare", help="Path to JoinQuant NAV CSV for comparison")
    args = p.parse_args()

    pro = init_tushare()

    jq_holdings = None
    if args.compare:
        jq_holdings = _parse_jq_holdings(args.compare)

    nav = run_gemstar(pro, jq_holdings=jq_holdings)

    if args.compare:
        compare(nav, args.compare)


if __name__ == "__main__":
    main()
