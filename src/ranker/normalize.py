import pandas as pd
import numpy as np


def winsorize_mad(values: pd.Series, n_mad: float = 3.0) -> pd.Series:
    median = values.median()
    mad = (values - median).abs().median()
    if mad == 0:
        return values.copy()
    limit = n_mad * mad * 1.4826
    return values.clip(lower=median - limit, upper=median + limit)


def zscore_cross_section(values: pd.Series) -> pd.Series:
    std = values.std(ddof=0)
    if std == 0:
        return pd.Series(np.zeros(len(values)), index=values.index)
    return (values - values.mean()) / std
