import pandas as pd
import numpy as np
from src.ranker.factors import compute_all_factors

FACTOR_COLS = ['momentum_20d', 'pe_inverse', 'pb_inverse', 'roe',
               'revenue_yoy', 'netprofit_yoy', 'turnover_20d', 'rel_strength_20d']


def _make_data():
    dates = pd.date_range('2024-01-01', periods=25, freq='B')
    rows = []
    for code in ['000001.SZ', '000002.SZ']:
        for d in dates:
            rows.append({'ts_code': code, 'trade_date': d,
                         'close': 10 + np.random.randn() * 0.5,
                         'pe_ttm': 15.0, 'pb': 2.0, 'turnover_rate': 3.0})
    daily = pd.DataFrame(rows)

    idx_rows = [{'trade_date': d, 'close': 3000 + np.random.randn() * 10} for d in dates]
    index_daily = pd.DataFrame(idx_rows)

    fina = pd.DataFrame([
        {'ts_code': '000001.SZ', 'ann_date': dates[0], 'roe': 12.0, 'revenue_yoy': 10.0, 'netprofit_yoy': 8.0},
        {'ts_code': '000002.SZ', 'ann_date': dates[0], 'roe': 15.0, 'revenue_yoy': 20.0, 'netprofit_yoy': 12.0},
    ])
    return daily, index_daily, fina


def test_compute_all_factors_columns_and_length():
    daily, index_daily, fina = _make_data()
    result = compute_all_factors(daily, index_daily, fina)
    assert len(result) == 50  # 2 stocks * 25 days
    for col in FACTOR_COLS:
        assert col in result.columns


def test_compute_all_factors_has_ts_code_and_date():
    daily, index_daily, fina = _make_data()
    result = compute_all_factors(daily, index_daily, fina)
    assert 'ts_code' in result.columns
    assert 'trade_date' in result.columns
