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

from src.data.fetcher import init_tushare, fetch_trade_calendar, fetch_daily_all, fetch_daily_basic
from src.data.cleaner import filter_suspended
from src.engine.backtest import run_backtest
from src.engine.metrics import calc_cagr, calc_sharpe, calc_max_drawdown
from src.portfolio.cost import calc_trade_cost


START = "20230101"
END = "20241231"
CAPITAL = 100_000.0


def _get_top5_by_mcap(daily_basic_df, date, eligible_codes):
    """Pick top-5 stocks by total market value on a given date."""
    day = daily_basic_df[
        (daily_basic_df["trade_date"] == date) &
        (daily_basic_df["ts_code"].isin(eligible_codes))
    ].copy()
    if day.empty:
        return []
    day = day.dropna(subset=["total_mv"])
    return day.nlargest(5, "total_mv")["ts_code"].tolist()


def _is_first_trading_day_of_month(date, prev_date):
    if prev_date is None:
        return True
    return date[:6] != prev_date[:6]


def build_rankings(trade_dates, daily_df, daily_basic_df, index_members):
    """Monthly rebalance: top-5 by market cap among index members."""
    rankings = {}
    prev_date = None
    current_top5 = []

    for date in trade_dates:
        if _is_first_trading_day_of_month(date, prev_date):
            tradable = filter_suspended(daily_df[daily_df["trade_date"] == date])
            eligible = set(index_members) & set(tradable["ts_code"])
            top5 = _get_top5_by_mcap(daily_basic_df, date, eligible)
            if top5:
                current_top5 = top5
        rankings[date] = current_top5
        prev_date = date

    return rankings


def run_gemstar(pro):
    print(f"[CrossVal] Fetching data {START}~{END}...")
    trade_cal = fetch_trade_calendar(pro, START, END)
    trade_dates = sorted(trade_cal["cal_date"].tolist())
    print(f"  → {len(trade_dates)} trading days")

    daily_all = fetch_daily_all(pro, START, END)
    daily_basic = fetch_daily_basic(pro, START, END)

    # Use 399006.SZ constituent approximation: all 300xxx/301xxx stocks
    chinext_codes = daily_all[daily_all["ts_code"].str.match(r"^30[01]")]["ts_code"].unique().tolist()
    print(f"  → {len(chinext_codes)} ChiNext stocks in data")

    if "pre_close" not in daily_all.columns:
        daily_all["pre_close"] = daily_all.groupby("ts_code")["close"].shift(1)
        daily_all["pre_close"] = daily_all["pre_close"].fillna(daily_all["open"])

    print("[CrossVal] Building monthly rankings (top-5 by market cap)...")
    rankings = build_rankings(trade_dates, daily_all, daily_basic, chinext_codes)

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


def compare(gemstar_nav, jq_csv_path):
    """Compare GemStar NAV against JoinQuant exported NAV."""
    jq = pd.read_csv(jq_csv_path)

    # JoinQuant CSV typically has columns: date, returns, benchmark_returns, or nav
    # Adapt column names as needed
    print(f"\n[Compare] JoinQuant CSV columns: {list(jq.columns)}")
    print(f"[Compare] JoinQuant rows: {len(jq)}")
    print(f"[Compare] GemStar days:   {len(gemstar_nav)}")

    # Try to find a date and nav/returns column
    date_col = None
    for c in jq.columns:
        if "date" in c.lower() or "日期" in c:
            date_col = c
            break

    if date_col is None:
        print("[Compare] Cannot find date column in JoinQuant CSV. Columns:", list(jq.columns))
        print("[Compare] Please manually align the data.")
        return

    jq[date_col] = jq[date_col].astype(str).str.replace("-", "")

    # Check if there's a NAV or returns column
    nav_col = None
    for c in jq.columns:
        if "nav" in c.lower() or "净值" in c.lower() or "value" in c.lower():
            nav_col = c
            break

    ret_col = None
    for c in jq.columns:
        if "return" in c.lower() or "收益" in c.lower():
            ret_col = c
            break

    if nav_col:
        jq_nav = jq.set_index(date_col)[nav_col].astype(float)
        # Normalize to same starting capital
        jq_nav = jq_nav / jq_nav.iloc[0] * CAPITAL
    elif ret_col:
        jq_returns = jq.set_index(date_col)[ret_col].astype(float)
        jq_nav = (1 + jq_returns).cumprod() * CAPITAL
    else:
        print("[Compare] Cannot find NAV or returns column. Columns:", list(jq.columns))
        return

    # Align dates
    common = gemstar_nav.index.intersection(jq_nav.index)
    print(f"[Compare] Common trading days: {len(common)}")

    if len(common) == 0:
        print("[Compare] No overlapping dates found. Check date format.")
        return

    gs = gemstar_nav.loc[common]
    jq_aligned = jq_nav.loc[common]

    diff = (gs - jq_aligned) / jq_aligned * 100  # percentage diff

    print(f"\n{'='*50}")
    print("NAV Difference (GemStar vs JoinQuant)")
    print(f"{'='*50}")
    print(f"  Mean diff:    {diff.mean():.4f}%")
    print(f"  Max diff:     {diff.abs().max():.4f}%")
    print(f"  Std diff:     {diff.std():.4f}%")
    print(f"  Final GS NAV: {gs.iloc[-1]:.2f}")
    print(f"  Final JQ NAV: {jq_aligned.iloc[-1]:.2f}")
    print(f"  Final diff:   {diff.iloc[-1]:.4f}%")

    if diff.abs().max() < 5.0:
        print("\n  ✅ Max diff < 5% — engine is reasonably consistent with JoinQuant")
    else:
        print("\n  ⚠️  Max diff >= 5% — investigate divergence points")

    # Save diff for analysis
    diff_df = pd.DataFrame({"gemstar": gs, "joinquant": jq_aligned, "diff_pct": diff})
    diff_path = Path("output/crossval_diff.csv")
    diff_df.to_csv(diff_path)
    print(f"  Saved diff to {diff_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--compare", help="Path to JoinQuant NAV CSV for comparison")
    args = p.parse_args()

    pro = init_tushare()
    nav = run_gemstar(pro)

    if args.compare:
        compare(nav, args.compare)


if __name__ == "__main__":
    main()
