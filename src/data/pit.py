"""Point-in-time (PIT) filter for financial data.

CALLING SPEC:
    pit_filter(df: pd.DataFrame, asof: str) -> pd.DataFrame
        Filter rows where disclosure_date <= asof.
        Raises ValueError if the DataFrame lacks a disclosure_date column.
"""

import pandas as pd


def pit_filter(df: pd.DataFrame, asof: str) -> pd.DataFrame:
    """Return rows whose ``disclosure_date`` is on or before *asof*.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain a ``disclosure_date`` column (YYYYMMDD strings).
    asof : str
        Cutoff date in YYYYMMDD format.

    Returns
    -------
    pd.DataFrame
        Filtered copy of *df*.

    Raises
    ------
    ValueError
        If ``disclosure_date`` column is missing.
    """
    if "disclosure_date" not in df.columns:
        raise ValueError(
            "DataFrame must contain a 'disclosure_date' column for PIT filtering."
        )

    if df.empty:
        return df.copy()

    return df[df["disclosure_date"] <= asof].copy()
