import pandas as pd
import numpy as np
from src.ranker.scorer import compute_composite_score, rank_top_n, DEFAULT_WEIGHTS


def _make_scored_df():
    cols = list(DEFAULT_WEIGHTS.keys())
    data = {c: np.random.randn(10) for c in cols}
    data['ts_code'] = [f'stock_{i}' for i in range(10)]
    data['trade_date'] = pd.date_range('2024-01-01', periods=10)
    return pd.DataFrame(data)


def test_default_weights_sum_to_one():
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-10


def test_composite_score_adds_column():
    df = _make_scored_df()
    result = compute_composite_score(df)
    assert 'score' in result.columns
    assert len(result) == 10


def test_rank_top_n():
    df = _make_scored_df()
    scored = compute_composite_score(df)
    top = rank_top_n(scored, n=5)
    assert len(top) == 5
    assert top['score'].is_monotonic_decreasing
