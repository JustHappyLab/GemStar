import pandas as pd

from src.orchestrator.rankings import build_rankings
from src.schemas.strategy import FactorWeightV1


def _daily_for_universe_test() -> pd.DataFrame:
    dates = ["20240101", "20240102"]
    rows = []
    for date in dates:
        rows.extend([
            {
                "ts_code": "300001.SZ",
                "trade_date": date,
                "close": 10.0,
                "pe_ttm": 10.0,
                "pb": 2.0,
                "turnover_rate": 1.0,
            },
            {
                "ts_code": "600001.SH",
                "trade_date": date,
                "close": 10.0,
                "pe_ttm": 1.0,
                "pb": 2.0,
                "turnover_rate": 1.0,
            },
        ])
    return pd.DataFrame(rows)


def test_chinext_universe_excludes_non_chinext_codes():
    daily = _daily_for_universe_test()
    index_daily = pd.DataFrame({
        "trade_date": ["20240101", "20240102"],
        "close": [100.0, 101.0],
    })
    stock_basic = pd.DataFrame({
        "ts_code": ["300001.SZ", "600001.SH"],
        "name": ["A", "B"],
        "list_date": ["20200101", "20200101"],
        "delist_date": [None, None],
    })

    rankings = build_rankings(
        daily,
        index_daily,
        pd.DataFrame(),
        [FactorWeightV1(factor_id="pe_inverse", weight=1.0)],
        top_n=1,
        trade_dates=["20240102"],
        universe="chinext",
        stock_basic=stock_basic,
    )

    assert rankings["20240102"] == ["300001.SZ"]


def test_all_universe_can_select_non_chinext_codes():
    daily = _daily_for_universe_test()
    index_daily = pd.DataFrame({
        "trade_date": ["20240101", "20240102"],
        "close": [100.0, 101.0],
    })
    stock_basic = pd.DataFrame({
        "ts_code": ["300001.SZ", "600001.SH"],
        "name": ["A", "B"],
        "list_date": ["20200101", "20200101"],
        "delist_date": [None, None],
    })

    rankings = build_rankings(
        daily,
        index_daily,
        pd.DataFrame(),
        [FactorWeightV1(factor_id="pe_inverse", weight=1.0)],
        top_n=1,
        trade_dates=["20240102"],
        universe="all",
        stock_basic=stock_basic,
    )

    assert rankings["20240102"] == ["600001.SH"]


def test_all_universe_does_not_use_chinext_only_stock_basic_as_full_filter():
    daily = _daily_for_universe_test()
    index_daily = pd.DataFrame({
        "trade_date": ["20240101", "20240102"],
        "close": [100.0, 101.0],
    })
    stock_basic = pd.DataFrame({
        "ts_code": ["300001.SZ"],
        "name": ["A"],
        "list_date": ["20200101"],
        "delist_date": [None],
    })

    rankings = build_rankings(
        daily,
        index_daily,
        pd.DataFrame(),
        [FactorWeightV1(factor_id="pe_inverse", weight=1.0)],
        top_n=1,
        trade_dates=["20240102"],
        universe="all",
        stock_basic=stock_basic,
    )

    assert rankings["20240102"] == ["600001.SH"]
