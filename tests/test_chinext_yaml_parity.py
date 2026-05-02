"""Parity test: YAML config matches hardcoded values in main.py / scorer.py.

CALLING SPEC:
    Validates that strategies/chinext_lstm_mf8/config.yaml, when loaded via
    StrategyConfigV1.from_yaml(), produces identical parameter values to the
    hardcoded defaults in src/main.py and src/ranker/scorer.py.

SIDE EFFECTS:
    None.
"""

from pathlib import Path

from src.schemas.strategy import StrategyConfigV1

CONFIG_PATH = Path(__file__).resolve().parent.parent / "strategies" / "chinext_lstm_mf8" / "config.yaml"

# --- Hardcoded values from src/main.py (lines 118-310) and src/ranker/scorer.py ---

EXPECTED_TIMER = {
    "mode": "lstm",
    "seq_len": 60,
    "horizon": 5,
    "retrain_months": 6,
    "epochs": 100,
    "batch_size": 64,
    "lr": 1e-3,
    "patience": 10,
}

EXPECTED_WEIGHTS = {
    "roe": 0.15,
    "revenue_yoy": 0.15,
    "netprofit_yoy": 0.10,
    "pe_inverse": 0.10,
    "pb_inverse": 0.10,
    "momentum_20d": 0.15,
    "turnover_20d": 0.10,
    "rel_strength_20d": 0.15,
}

EXPECTED_BACKTEST = {
    "start": "20210409",
    "end": "20260409",
    "capital": 100000.0,
    "rf_annual": 0.025,
    "volume_limit_pct": 0.25,
    "cost_multiplier": 1.0,
}


def test_yaml_loads_successfully() -> None:
    cfg = StrategyConfigV1.from_yaml(CONFIG_PATH)
    assert cfg.version == "StrategyConfigV1"
    assert cfg.name == "chinext_lstm_mf8"


def test_timer_params_parity() -> None:
    cfg = StrategyConfigV1.from_yaml(CONFIG_PATH)
    timer = cfg.timer.model_dump()
    for key, expected in EXPECTED_TIMER.items():
        actual = timer[key]
        assert actual == expected, f"timer.{key}: expected {expected}, got {actual}"


def test_ranker_weights_parity() -> None:
    cfg = StrategyConfigV1.from_yaml(CONFIG_PATH)
    weights = {fw.factor_id: fw.weight for fw in cfg.factors}
    assert weights == EXPECTED_WEIGHTS, f"weights mismatch: {weights}"


def test_ranker_top_n_parity() -> None:
    cfg = StrategyConfigV1.from_yaml(CONFIG_PATH)
    assert cfg.top_n == 5


def test_backtest_params_parity() -> None:
    cfg = StrategyConfigV1.from_yaml(CONFIG_PATH)
    bt = cfg.backtest.model_dump()
    for key, expected in EXPECTED_BACKTEST.items():
        actual = bt[key]
        assert actual == expected, f"backtest.{key}: expected {expected}, got {actual}"


def test_universe_parity() -> None:
    cfg = StrategyConfigV1.from_yaml(CONFIG_PATH)
    assert cfg.universe == "chinext"


def test_factor_count() -> None:
    cfg = StrategyConfigV1.from_yaml(CONFIG_PATH)
    assert len(cfg.factors) == 8
