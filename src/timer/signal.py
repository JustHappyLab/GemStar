"""Signal conversion and calendar alignment helpers.

CALLING SPEC:
    position = probas_to_position(probas=np.ndarray) -> float
        Converts class probabilities into a continuous position score.

    position = discretize_position(signal=float, low=float, high=float) -> float
        Maps the continuous score into {0.0, 0.5, 1.0}.

    signals = generate_signals(model, X_sequences=np.ndarray, dates=np.ndarray) -> pd.DataFrame
        Returns columns: trade_date, position

    aligned = align_signals_to_calendar(
        signals=pd.DataFrame,
        trade_dates=list[str],
        default_position=float,
    ) -> pd.DataFrame
        Ensures there is one position per trade date.

SIDE EFFECTS:
    None.
"""

import numpy as np
import pandas as pd
from src.timer.model import predict_probas


def probas_to_position(probas) -> float:
    bear_prob = float(probas[0])
    bull_prob = float(probas[2])
    return float(np.clip(0.5 + 0.5 * (bull_prob - bear_prob), 0.0, 1.0))


def discretize_position(signal, low=0.3, high=0.7):
    if signal < low:
        return 0.0
    elif signal > high:
        return 1.0
    return 0.5


def generate_signals(model, X_sequences, dates, discrete: bool = False) -> pd.DataFrame:
    probas = predict_probas(model, X_sequences)
    positions = [probas_to_position(p) for p in probas]
    if discrete:
        positions = [discretize_position(position) for position in positions]
    return pd.DataFrame({'trade_date': dates, 'position': positions})


def align_signals_to_calendar(signals, trade_dates, default_position=0.0) -> pd.DataFrame:
    if not trade_dates:
        return pd.DataFrame(columns=["trade_date", "position"])

    if signals.empty:
        return pd.DataFrame({"trade_date": list(trade_dates), "position": default_position})

    signal_series = (
        signals.assign(trade_date=signals["trade_date"].astype(str))
        .drop_duplicates("trade_date", keep="last")
        .set_index("trade_date")["position"]
    )
    aligned = signal_series.reindex(list(trade_dates)).fillna(default_position).astype(float)
    return aligned.rename_axis("trade_date").reset_index(name="position")
