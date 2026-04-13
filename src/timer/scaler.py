"""Sequence feature scaling helpers.

CALLING SPEC:
    scaler = fit_sequence_standardizer(X=np.ndarray[float32]) -> dict[str, np.ndarray]
        Fits per-feature mean/std across samples and timesteps.

    X_scaled = apply_sequence_standardizer(
        X=np.ndarray[float32],
        scaler=dict[str, np.ndarray],
    ) -> np.ndarray[float32]
        Applies the fitted standardization without mutating the input array.

SIDE EFFECTS:
    None.
"""

from __future__ import annotations

import numpy as np


def fit_sequence_standardizer(X: np.ndarray) -> dict[str, np.ndarray]:
    feature_mean = X.mean(axis=(0, 1), keepdims=True)
    feature_std = X.std(axis=(0, 1), keepdims=True)
    feature_std = np.where(feature_std == 0.0, 1.0, feature_std)
    return {"mean": feature_mean.astype(np.float32), "std": feature_std.astype(np.float32)}


def apply_sequence_standardizer(X: np.ndarray, scaler: dict[str, np.ndarray]) -> np.ndarray:
    mean = scaler["mean"]
    std = scaler["std"]
    return ((X - mean) / std).astype(np.float32)
