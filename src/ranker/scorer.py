import pandas as pd

DEFAULT_WEIGHTS = {
    'roe': 0.15, 'revenue_yoy': 0.15, 'netprofit_yoy': 0.10,
    'pe_inverse': 0.10, 'pb_inverse': 0.10, 'momentum_20d': 0.15,
    'turnover_20d': 0.10, 'rel_strength_20d': 0.15,
}


def compute_composite_score(df: pd.DataFrame, weights: dict = None) -> pd.DataFrame:
    w = weights or DEFAULT_WEIGHTS
    result = df.copy()
    score = pd.Series(0.0, index=result.index, dtype=float)
    for col, weight in w.items():
        score += pd.to_numeric(result[col], errors='coerce').fillna(0.0) * weight
    result['score'] = score
    return result


def rank_top_n(scored_df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return scored_df.nlargest(n, 'score')
