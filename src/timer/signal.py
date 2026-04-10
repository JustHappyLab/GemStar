import numpy as np
import pandas as pd
from src.timer.model import predict_probas


def probas_to_position(probas) -> float:
    return probas[0] * 0.0 + probas[1] * 0.5 + probas[2] * 1.0


def discretize_position(signal, low=0.3, high=0.7):
    if signal < low:
        return 0.0
    elif signal > high:
        return 1.0
    return 0.5


def generate_signals(model, X_sequences, dates) -> pd.DataFrame:
    probas = predict_probas(model, X_sequences)
    positions = [discretize_position(probas_to_position(p)) for p in probas]
    return pd.DataFrame({'trade_date': dates, 'position': positions})
