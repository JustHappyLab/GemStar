import pandas as pd

from src.orchestrator.universe import (
    eligible_codes_from_stock_basic,
    filter_group_for_universe,
    resolve_strategy_universe,
    resolve_universe_value,
)
from src.schemas.strategy import FactorWeightV1, StrategyConfigV1


def test_auto_defaults_to_a_share_core_for_general_strategy():
    strategy = StrategyConfigV1(
        name="quality_value",
        hypothesis="稳健全市场质量价值选股",
        factors=[FactorWeightV1(factor_id="roe", weight=1.0)],
    )

    resolution = resolve_strategy_universe(strategy)

    assert resolution.requested == "auto"
    assert resolution.resolved == "a_share_core"
    assert any("listed at least" in f for f in resolution.filters)


def test_auto_selects_chinext_core_when_context_mentions_chinext():
    strategy = StrategyConfigV1(
        name="chinext_growth",
        hypothesis="创业板成长动量策略",
        factors=[FactorWeightV1(factor_id="momentum_20d", weight=1.0)],
    )

    resolution = resolve_strategy_universe(strategy)

    assert resolution.resolved == "chinext_core"


def test_all_is_compatibility_alias_for_a_share():
    resolution = resolve_universe_value("all")

    assert resolution.requested == "all"
    assert resolution.resolved == "a_share"


def test_core_universe_filters_st_new_and_wrong_board_names():
    stock_basic = pd.DataFrame({
        "ts_code": ["300001.SZ", "300002.SZ", "600001.SH", "300003.SZ"],
        "name": ["A", "B", "C", "ST D"],
        "list_date": ["20200101", "20240315", "20200101", "20200101"],
        "delist_date": [None, None, None, None],
    })
    resolution = resolve_universe_value("chinext_core")

    eligible = eligible_codes_from_stock_basic(stock_basic, "20240501", resolution)

    assert eligible == {"300001.SZ"}


def test_liquid_universe_filters_lowest_amount_bucket():
    group = pd.DataFrame({
        "ts_code": ["300001.SZ", "300002.SZ", "300003.SZ", "300004.SZ", "300005.SZ"],
        "amount": [1.0, 2.0, 3.0, 4.0, 5.0],
    })
    resolution = resolve_universe_value("a_share_liquid")

    filtered = filter_group_for_universe(
        group,
        stock_basic=None,
        trade_date="20240501",
        resolution=resolution,
    )

    assert "300001.SZ" not in set(filtered["ts_code"])
    assert "300005.SZ" in set(filtered["ts_code"])
