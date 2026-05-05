import pandas as pd


def filter_st(stocks_df: pd.DataFrame) -> pd.DataFrame:
    return stocks_df[~stocks_df["name"].str.contains("ST", case=False, na=False)].reset_index(drop=True)


def filter_active_stocks(stocks_df: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    td = pd.Timestamp(trade_date)
    listed = pd.to_datetime(stocks_df["list_date"], format="%Y%m%d", errors="coerce")
    delisted = pd.to_datetime(
        stocks_df["delist_date"].replace("", pd.NA),
        format="%Y%m%d",
        errors="coerce",
    )
    is_listed = listed.notna() & (listed <= td)
    not_delisted = delisted.isna() | (delisted >= td)
    return stocks_df[is_listed & not_delisted].reset_index(drop=True)


def filter_new_stocks(stocks_df: pd.DataFrame, trade_date: str, min_days: int = 60) -> pd.DataFrame:
    td = pd.Timestamp(trade_date)
    listed = pd.to_datetime(stocks_df["list_date"], format="%Y%m%d", errors="coerce")
    return stocks_df[listed.notna() & ((td - listed).dt.days >= min_days)].reset_index(drop=True)


def filter_suspended(daily_df: pd.DataFrame) -> pd.DataFrame:
    return daily_df[daily_df["vol"] != 0].reset_index(drop=True)


def fill_missing_cross_section(df: pd.DataFrame, factor_cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in factor_cols:
        df[col] = df[col].fillna(df[col].median())
    return df


def apply_adjusted_prices(daily_df: pd.DataFrame, adj_factor_df: pd.DataFrame | None) -> pd.DataFrame:
    """Return daily bars with OHLC/pre_close adjusted by Tushare adj_factor.

    Uses the common qfq-style normalization: adjusted_price = raw_price *
    adj_factor / latest_adj_factor_for_stock.  Non-price columns, including
    volume and amount, are preserved.
    """
    if adj_factor_df is None or adj_factor_df.empty or daily_df.empty:
        return daily_df.copy()
    required = {"ts_code", "trade_date", "adj_factor"}
    if not required.issubset(adj_factor_df.columns):
        return daily_df.copy()

    merged = daily_df.copy()
    merged["trade_date"] = merged["trade_date"].astype(str)
    adj = adj_factor_df[["ts_code", "trade_date", "adj_factor"]].copy()
    adj["trade_date"] = adj["trade_date"].astype(str)
    adj["adj_factor"] = pd.to_numeric(adj["adj_factor"], errors="coerce")
    merged = merged.merge(adj, on=["ts_code", "trade_date"], how="left")
    if merged["adj_factor"].isna().all():
        return daily_df.copy()

    latest = (
        adj.dropna(subset=["adj_factor"])
        .sort_values(["ts_code", "trade_date"])
        .groupby("ts_code")["adj_factor"]
        .last()
    )
    base = merged["ts_code"].map(latest)
    ratio = merged["adj_factor"] / base
    price_cols = [c for c in ["open", "high", "low", "close", "pre_close"] if c in merged.columns]
    for col in price_cols:
        merged[col] = pd.to_numeric(merged[col], errors="coerce") * ratio.fillna(1.0)
    return merged.drop(columns=["adj_factor"])
