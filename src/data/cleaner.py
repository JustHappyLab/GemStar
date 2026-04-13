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
