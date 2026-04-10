import numpy as np
import pandas as pd
from src.timer.features import compute_index_features, build_sequences_and_labels


def make_synthetic(n=200):
    dates = pd.date_range('2020-01-01', periods=n, freq='B').strftime('%Y%m%d')
    close = 3000 + np.cumsum(np.random.randn(n) * 10)
    high = close + np.abs(np.random.randn(n)) * 5
    low = close - np.abs(np.random.randn(n)) * 5
    return pd.DataFrame({
        'trade_date': dates,
        'open': close + np.random.randn(n),
        'high': high,
        'low': low,
        'close': close,
        'vol': np.random.rand(n) * 1e6 + 1e5,
    })


def test_compute_index_features_shape():
    df = make_synthetic()
    feat = compute_index_features(df)
    # trade_date + close + ~20 features
    assert 'trade_date' in feat.columns
    assert 'close' in feat.columns
    assert len(feat.columns) >= 19


def test_compute_index_features_no_nan():
    df = make_synthetic()
    feat = compute_index_features(df)
    assert feat.isna().sum().sum() == 0


def test_build_sequences_shapes():
    df = make_synthetic()
    feat = compute_index_features(df)
    feature_cols = [c for c in feat.columns if c not in ('trade_date', 'close')]
    X, y, dates = build_sequences_and_labels(feat, feature_cols, seq_len=20, horizon=3)
    assert X.shape[0] == y.shape[0] == len(dates)
    assert X.shape[1] == 20
    assert X.shape[2] == len(feature_cols)
    assert set(np.unique(y)).issubset({0, 1, 2})
