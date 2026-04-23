"""Factor Information Coefficient (IC) analysis.

CALLING SPEC:
    ic_df = compute_daily_rank_ic(
        factors_df=pd.DataFrame,
        daily_df=pd.DataFrame,
        factor_cols=list[str],
    ) -> pd.DataFrame
        Returns one row per trade_date with Rank IC for each factor.

    summary = summarize_ic(ic_df=pd.DataFrame) -> pd.DataFrame
        Returns IC_mean, IC_std, IC_IR, IC_positive_rate per factor.

SIDE EFFECTS:
    None.
"""

import pandas as pd


def compute_daily_rank_ic(
    factors_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    factor_cols: list[str],
) -> pd.DataFrame:
    """Rank IC = Spearman correlation between factor value and next-day return."""
    ret = daily_df[["ts_code", "trade_date", "close"]].copy()
    ret["trade_date"] = ret["trade_date"].astype(str)
    ret = ret.sort_values(["ts_code", "trade_date"])
    ret["fwd_ret"] = ret.groupby("ts_code")["close"].pct_change().shift(-1)

    merged = factors_df.merge(ret[["ts_code", "trade_date", "fwd_ret"]], on=["ts_code", "trade_date"], how="inner")

    records = []
    for date, grp in merged.groupby("trade_date"):
        if len(grp) < 5:
            continue
        row = {"trade_date": date}
        for col in factor_cols:
            valid = grp[[col, "fwd_ret"]].dropna()
            if len(valid) < 5:
                row[col] = None
            else:
                row[col] = valid[col].rank().corr(valid["fwd_ret"].rank())
        records.append(row)

    return pd.DataFrame(records)


def summarize_ic(ic_df: pd.DataFrame) -> pd.DataFrame:
    factor_cols = [c for c in ic_df.columns if c != "trade_date"]
    rows = []
    for col in factor_cols:
        s = ic_df[col].dropna()
        rows.append({
            "factor": col,
            "IC_mean": s.mean() if len(s) else None,
            "IC_std": s.std() if len(s) else None,
            "IC_IR": s.mean() / s.std() if len(s) and s.std() != 0 else None,
            "IC_positive_rate": (s > 0).mean() if len(s) else None,
        })
    return pd.DataFrame(rows)
