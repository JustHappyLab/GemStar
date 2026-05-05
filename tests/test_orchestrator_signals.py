import numpy as np
import pandas as pd

from src.orchestrator import signals as signals_mod
from src.schemas.strategy import TimerConfigV1


def test_training_mask_excludes_labels_on_or_after_cutoff():
    features = pd.DataFrame({
        "trade_date": [
            "20240101",
            "20240102",
            "20240103",
            "20240104",
            "20240105",
            "20240106",
            "20240107",
        ],
    })

    mask = signals_mod._training_mask_for_cutoff(
        features,
        seq_len=2,
        horizon=2,
        cutoff_date="20240106",
    )

    assert mask.tolist() == [True, False, False]


def test_lstm_signals_train_only_on_visible_labels(monkeypatch):
    features = _synthetic_features(260)
    trade_dates = features["trade_date"].iloc[150:190].tolist()
    full_sample_count = len(features) - 3 - 2
    seen_sample_counts: list[int] = []

    def fake_train_model(X_train, y_train, X_val, y_val, **kwargs):
        seen_sample_counts.append(len(X_train) + len(X_val))
        return object(), {}

    def fake_generate_signals(model, X_sequences, dates):
        return pd.DataFrame({
            "trade_date": dates,
            "position": np.full(len(dates), 0.5),
        })

    monkeypatch.setattr(signals_mod, "compute_index_features", lambda _df: features)
    monkeypatch.setattr(signals_mod, "train_model", fake_train_model)
    monkeypatch.setattr(signals_mod, "generate_signals", fake_generate_signals)

    result = signals_mod.build_signals(
        features[["trade_date", "close"]],
        trade_dates,
        TimerConfigV1(
            mode="lstm",
            seq_len=3,
            horizon=2,
            retrain_months=1,
            epochs=1,
            batch_size=16,
            patience=1,
        ),
    )

    assert seen_sample_counts
    assert max(seen_sample_counts) < full_sample_count
    assert len(result) == len(trade_dates)


def _synthetic_features(n: int) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=n, freq="B").strftime("%Y%m%d")
    data = {
        "trade_date": dates,
        "close": np.linspace(100.0, 130.0, n),
    }
    for idx, col in enumerate(signals_mod._FEATURE_COLS):
        data[col] = np.sin(np.arange(n) / (idx + 2))
    return pd.DataFrame(data)
