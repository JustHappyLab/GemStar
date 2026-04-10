import pandas as pd
from src.portfolio.allocator import compute_target_shares, check_limit_up_down, apply_t_plus_1


def test_full_position():
    result = compute_target_shares(["A", "B"], {"A": 10.0, "B": 20.0}, 100000, 1.0)
    assert result == {"A": 5000, "B": 2500}


def test_half_position():
    result = compute_target_shares(["A"], {"A": 10.0}, 100000, 0.5)
    assert result == {"A": 5000}


def test_zero_stocks():
    assert compute_target_shares([], {}, 100000, 1.0) == {}


def test_limit_up_detection():
    df = pd.DataFrame([{"ts_code": "300001.SZ", "trade_date": "20240101", "open": 12.0, "pre_close": 10.0}])
    result = check_limit_up_down(df, "20240101")
    assert result["300001.SZ"]["limit_up"] is True
    assert result["300001.SZ"]["limit_down"] is False


def test_t_plus_1_constraint():
    target = {"A": 0, "B": 500}
    current = {"A": 1000, "B": 1000}
    bought = {"A"}
    result = apply_t_plus_1(target, current, bought)
    assert result["A"] == 1000  # can't sell A bought today
    assert result["B"] == 500   # B not in bought_today, target applies
