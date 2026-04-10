import numpy as np
import torch
from src.timer.model import TimerModel, predict_probas, train_model


def test_forward_outputs_logits():
    model = TimerModel(n_features=10)
    X = torch.randn(4, 20, 10)
    out = model(X)
    assert out.shape == (4, 3)
    # logits should NOT sum to 1
    sums = out.sum(dim=1).detach().numpy()
    assert not np.allclose(sums, 1.0, atol=0.05)


def test_predict_probas_sum_to_one():
    model = TimerModel(n_features=10)
    X = np.random.randn(4, 20, 10).astype(np.float32)
    probas = predict_probas(model, X)
    assert probas.shape == (4, 3)
    np.testing.assert_allclose(probas.sum(axis=1), 1.0, atol=1e-5)


def test_train_model_runs():
    n, seq, feat = 80, 10, 5
    X = np.random.randn(n, seq, feat).astype(np.float32)
    y = np.random.randint(0, 3, n).astype(np.int64)
    model, history = train_model(X[:60], y[:60], X[60:], y[60:], epochs=3, patience=5)
    assert isinstance(model, TimerModel)
    assert len(history['train_loss']) <= 3
