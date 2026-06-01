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
        {
            'ts_code': '000001.SZ',
            'ann_date': dates[0],
            'disclosure_date': dates[0],
            'end_date': dates[0] - pd.Timedelta(days=90),
            'roe': 12.0,
            'revenue_yoy': 10.0,
            'netprofit_yoy': 8.0,
        },
        {
            'ts_code': '000002.SZ',
            'ann_date': dates[0],
            'disclosure_date': dates[0],
            'end_date': dates[0] - pd.Timedelta(days=90),
            'roe': 15.0,
            'revenue_yoy': 20.0,
            'netprofit_yoy': 12.0,
        },
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


def test_compute_all_factors_lags_market_factors_by_one_day():
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    daily = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * len(dates),
            "trade_date": dates,
            "close": np.arange(1.0, len(dates) + 1.0),
            "pe_ttm": np.arange(11.0, len(dates) + 11.0),
            "pb": np.full(len(dates), 2.0),
            "turnover_rate": np.arange(1.0, len(dates) + 1.0),
        }
    )
    index_daily = pd.DataFrame({"trade_date": dates, "close": np.arange(100.0, 100.0 + len(dates))})

    result = compute_all_factors(daily, index_daily, pd.DataFrame())
    target_date = dates[21].strftime("%Y%m%d")
    row = result[result["trade_date"] == target_date].iloc[0]

    expected_momentum = daily["close"].pct_change(20).iloc[20]
    expected_pe_inverse = 1.0 / daily["pe_ttm"].iloc[20]

    assert np.isclose(row["momentum_20d"], expected_momentum, equal_nan=False)
    assert np.isclose(row["pe_inverse"], expected_pe_inverse, equal_nan=False)


def test_compute_all_factors_keeps_same_day_fundamentals_available():
    daily, index_daily, fina = _make_data()
    result = compute_all_factors(daily, index_daily, fina)
    first_row = result[result["trade_date"] == daily["trade_date"].min().strftime("%Y%m%d")].iloc[0]

    assert pd.notna(first_row["roe"])


def test_compute_all_factors_does_not_fallback_to_ann_date_without_disclosure_date():
    daily, index_daily, fina = _make_data()
    fina = fina.drop(columns=["disclosure_date"])

    result = compute_all_factors(daily, index_daily, fina)

    assert result["roe"].isna().all()


def test_compute_all_factors_uses_disclosure_date_for_fundamentals():
    daily, index_daily, fina = _make_data()
    first_date = daily["trade_date"].min()
    fina["ann_date"] = first_date
    fina["disclosure_date"] = first_date + pd.Timedelta(days=5)

    result = compute_all_factors(daily, index_daily, fina)
    before_disclosure = result[result["trade_date"] == first_date.strftime("%Y%m%d")]
    after_disclosure = result[result["trade_date"] == (first_date + pd.offsets.BDay(5)).strftime("%Y%m%d")]

    assert before_disclosure["roe"].isna().all()
    assert after_disclosure["roe"].notna().any()


def test_compute_all_factors_supports_daily_pre_close_and_vol_expression_fields():
    daily, index_daily, fina = _make_data()
    daily = daily.sort_values(["ts_code", "trade_date"]).copy()
    daily["pre_close"] = daily.groupby("ts_code")["close"].shift(1).fillna(daily["close"])
    daily["open"] = daily["pre_close"] * 1.01
    daily["high"] = daily[["open", "close"]].max(axis=1) * 1.01
    daily["low"] = daily[["open", "close"]].min(axis=1) * 0.99
    daily["vol"] = np.arange(1.0, len(daily) + 1.0) * 1000.0
    daily["amount"] = daily["vol"] * daily["close"]

    result = compute_all_factors(
        daily,
        index_daily,
        fina,
        expression_factors=[
            ("gap_reversal_v1", "(open - pre_close) / (pre_close + 0.001)"),
            ("vol_price_corr_v1", "ts_corr(close, vol, 10)"),
        ],
    )

    assert "gap_reversal_v1" in result.columns
    assert "vol_price_corr_v1" in result.columns
    assert result["gap_reversal_v1"].notna().any()
    assert result["vol_price_corr_v1"].notna().any()
