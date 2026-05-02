"""Tests for factor pool loading and validation.

CALLING SPEC:
    pytest tests/test_factor_pool.py

SIDE EFFECTS:
    None.
"""

from src.factors.pool import load_pool, pool_path
from src.schemas.factor import FactorPoolV1

EXPECTED_FACTORS = {
    "roe",
    "revenue_yoy",
    "netprofit_yoy",
    "pe_inverse",
    "pb_inverse",
    "momentum_20d",
    "turnover_20d",
    "rel_strength_20d",
}


def test_pool_json_exists():
    assert pool_path().is_file()


def test_pool_loads_as_factor_pool_v1():
    pool = load_pool()
    assert isinstance(pool, FactorPoolV1)


def test_eight_factors_present():
    pool = load_pool()
    names = {e.name for e in pool.all_entries()}
    assert names == EXPECTED_FACTORS


def test_all_active_factors_have_status_active():
    pool = load_pool()
    assert len(pool.active) == 8
    for entry in pool.active:
        assert entry.status == "active"


def test_is_registered_for_known_factors():
    pool = load_pool()
    for name in EXPECTED_FACTORS:
        assert pool.is_registered(name), f"{name} should be registered"


def test_is_registered_returns_false_for_unknown():
    pool = load_pool()
    assert not pool.is_registered("nonexistent_factor")


def test_is_active_or_candidate_for_active_factors():
    pool = load_pool()
    for name in EXPECTED_FACTORS:
        assert pool.is_active_or_candidate(name), f"{name} should be active or candidate"


def test_is_active_or_candidate_returns_false_for_unknown():
    pool = load_pool()
    assert not pool.is_active_or_candidate("nonexistent_factor")


def test_pool_version_is_2():
    pool = load_pool()
    assert pool.version == 2


def test_empty_watchlist_retired_candidates():
    pool = load_pool()
    assert pool.watchlist == []
    assert pool.retired == []
    assert pool.candidates == []
