import numpy as np
from src.timer.signal import probas_to_position, discretize_position


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
