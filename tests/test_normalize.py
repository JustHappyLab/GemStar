import pandas as pd
import numpy as np
from src.ranker.normalize import winsorize_mad, zscore_cross_section


def test_winsorize_mad_clips_outlier():
    s = pd.Series([1, 2, 3, 4, 5, 100])
    result = winsorize_mad(s)
    assert result.max() < 100


def test_winsorize_mad_constant_unchanged():
    s = pd.Series([5.0, 5.0, 5.0, 5.0])
    result = winsorize_mad(s)
    assert (result == 5.0).all()


def test_zscore_mean_and_std():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = zscore_cross_section(s)
    assert abs(result.mean()) < 1e-10
    assert abs(result.std(ddof=0) - 1.0) < 1e-10


def test_zscore_constant_returns_zeros():
    s = pd.Series([7.0, 7.0, 7.0])
    result = zscore_cross_section(s)
    assert (result == 0).all()
