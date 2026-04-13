import numpy as np
import pandas as pd

from src.timer.signal import align_signals_to_calendar, discretize_position, probas_to_position


def test_probas_to_position():
    assert probas_to_position(np.array([1.0, 0.0, 0.0])) == 0.0
    assert probas_to_position(np.array([0.0, 1.0, 0.0])) == 0.5
    assert probas_to_position(np.array([0.0, 0.0, 1.0])) == 1.0
    assert abs(probas_to_position(np.array([0.5, 0.3, 0.2])) - 0.35) < 1e-9


def test_discretize_position():
    assert discretize_position(0.1) == 0.0
    assert discretize_position(0.5) == 0.5
    assert discretize_position(0.9) == 1.0
    assert discretize_position(0.3) == 0.5
    assert discretize_position(0.7) == 0.5


def test_align_signals_to_calendar_fills_missing_days():
    signals = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240104"],
            "position": [0.5, 1.0],
        }
    )

    aligned = align_signals_to_calendar(signals, ["20240102", "20240103", "20240104"])

    assert aligned.to_dict(orient="records") == [
        {"trade_date": "20240102", "position": 0.5},
        {"trade_date": "20240103", "position": 0.0},
        {"trade_date": "20240104", "position": 1.0},
    ]
