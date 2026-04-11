import pandas as pd
import numpy as np
from src.ranker.factors import compute_all_factors
from pandas.api.types import is_string_dtype

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


def test_compute_all_factors_normalizes_string_dates_for_asof_merge():
    daily, index_daily, fina = _make_data()
    daily["trade_date"] = daily["trade_date"].dt.strftime("%Y%m%d")
    index_daily["trade_date"] = index_daily["trade_date"].dt.strftime("%Y%m%d")
    fina["ann_date"] = fina["ann_date"].dt.strftime("%Y%m%d")

    result = compute_all_factors(daily, index_daily, fina)

    assert is_string_dtype(result["trade_date"])
    assert result["revenue_yoy"].notna().any()


def test_compute_all_factors_handles_missing_announcement_dates():
    daily, index_daily, fina = _make_data()
    fina.loc[0, "ann_date"] = pd.NaT

    result = compute_all_factors(daily, index_daily, fina)

    assert len(result) == 50
    assert "revenue_yoy" in result.columns
