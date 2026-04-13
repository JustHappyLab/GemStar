import numpy as np

from src.timer.scaler import apply_sequence_standardizer, fit_sequence_standardizer


def test_sequence_standardizer_normalizes_per_feature():
    X = np.array(
        [
            [[1.0, 10.0], [3.0, 14.0]],
            [[5.0, 18.0], [7.0, 22.0]],
        ],
        dtype=np.float32,
    )

    scaler = fit_sequence_standardizer(X)
    X_scaled = apply_sequence_standardizer(X, scaler)

    np.testing.assert_allclose(X_scaled.mean(axis=(0, 1)), np.zeros(2), atol=1e-6)
    np.testing.assert_allclose(X_scaled.std(axis=(0, 1)), np.ones(2), atol=1e-6)
