"""Timer model training and inference helpers.

CALLING SPEC:
    model, history = train_model(
        X_train=np.ndarray[float32] of shape (n_train, seq_len, n_features),
        y_train=np.ndarray[int64] of shape (n_train,),
        X_val=np.ndarray[float32] of shape (n_val, seq_len, n_features),
        y_val=np.ndarray[int64] of shape (n_val,),
        epochs=int,
        lr=float,
        patience=int,
        batch_size=int,
    )

    predict_probas(model, X=np.ndarray[float32]) -> np.ndarray[float32]:
        Returns class probabilities with shape (n_samples, 3).

SIDE EFFECTS:
    None outside returned PyTorch model state.
"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim.lr_scheduler import CosineAnnealingLR


def _build_class_weights(y_train: np.ndarray, class_count: int = 3) -> torch.Tensor:
    counts = np.bincount(y_train, minlength=class_count).astype(np.float32)
    non_zero = counts > 0
    weights = np.ones(class_count, dtype=np.float32)
    weights[non_zero] = counts.sum() / (class_count * counts[non_zero])
    return torch.tensor(weights, dtype=torch.float32)


class TimerModel(nn.Module):
    def __init__(self, n_features, dropout=0.3):
        super().__init__()
        self.lstm1 = nn.LSTM(n_features, 64, batch_first=True)
        self.dropout1 = nn.Dropout(dropout)
        self.lstm2 = nn.LSTM(64, 32, batch_first=True)
        self.dropout2 = nn.Dropout(dropout)
        self.fc1 = nn.Linear(32, 16)
        self.fc2 = nn.Linear(16, 3)

    def forward(self, x):
        out, _ = self.lstm1(x)
        out = self.dropout1(out)
        out, _ = self.lstm2(out)
        out = self.dropout2(out[:, -1, :])
        return self.fc2(F.relu(self.fc1(out)))


def predict_probas(model, X) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(X, dtype=torch.float32))
        return F.softmax(logits, dim=1).numpy()


def train_model(X_train, y_train, X_val, y_val, epochs=50, lr=1e-3, patience=5, batch_size=64):
    n_features = X_train.shape[2]
    model = TimerModel(n_features)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = nn.CrossEntropyLoss(weight=_build_class_weights(y_train))

    X_t = torch.tensor(X_train, dtype=torch.float32)
    y_t = torch.tensor(y_train, dtype=torch.long)
    X_v = torch.tensor(X_val, dtype=torch.float32)
    y_v = torch.tensor(y_val, dtype=torch.long)

    best_val_loss, wait, best_state = float('inf'), 0, None
    history = {"train_loss": [], "val_loss": [], "val_acc": []}

    for epoch in range(epochs):
        model.train()
        idx = torch.randperm(len(X_t))
        epoch_loss = 0.0
        n_batches = 0
        for start in range(0, len(X_t), batch_size):
            batch_idx = idx[start:start + batch_size]
            loss = criterion(model(X_t[batch_idx]), y_t[batch_idx])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            n_batches += 1
        scheduler.step()

        model.eval()
        with torch.no_grad():
            val_logits = model(X_v)
            val_loss = criterion(val_logits, y_v).item()
            val_acc = (val_logits.argmax(dim=1) == y_v).float().mean().item()

        history["train_loss"].append(epoch_loss / n_batches)
        history["val_loss"].append(val_loss)
        history["val_acc"].append(val_acc)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1
            if wait >= patience:
                break

    if best_state:
        model.load_state_dict(best_state)
    return model, history
