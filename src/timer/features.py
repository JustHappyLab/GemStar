import numpy as np
import pandas as pd


def compute_index_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df[['trade_date', 'close', 'high', 'low', 'vol']].copy()
    c = d['close']
    log_ret = np.log(c / c.shift(1))

    for w in [5, 10, 20, 60]:
        d[f'ret_{w}'] = c.pct_change(w)
        ma = c.rolling(w).mean()
        d[f'ma_dev_{w}'] = (c - ma) / ma

    for w in [5, 10, 20]:
        d[f'vol_{w}'] = log_ret.rolling(w).std()

    d['vol_ratio_5_20'] = d['vol_5'] / d['vol_20']

    # RSI 14
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    d['rsi_14'] = 100 - 100 / (1 + rs)

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd_diff = ema12 - ema26
    macd_dea = macd_diff.ewm(span=9, adjust=False).mean()
    d['macd_diff'] = macd_diff / c
    d['macd_dea'] = macd_dea / c
    d['macd_hist'] = (macd_diff - macd_dea) / c

    # ADX 14
    h, lo, cl = d['high'], d['low'], c
    plus_dm = (h - h.shift(1)).clip(lower=0)
    minus_dm = (lo.shift(1) - lo).clip(lower=0)
    plus_dm[plus_dm <= minus_dm] = 0
    minus_dm[minus_dm <= plus_dm] = 0
    tr = pd.concat([h - lo, (h - cl.shift(1)).abs(), (lo - cl.shift(1)).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    plus_di = 100 * plus_dm.rolling(14).mean() / atr14
    minus_di = 100 * minus_dm.rolling(14).mean() / atr14
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    d['adx_14'] = dx.rolling(14).mean()

    d.drop(columns=['high', 'low', 'vol'], inplace=True)
    d.dropna(inplace=True)
    d.reset_index(drop=True, inplace=True)
    return d


def build_sequences_and_labels(features_df, feature_cols, seq_len=60, horizon=5, thresholds=(-0.01, 0.01)):
    close = features_df['close'].values
    feat = features_df[feature_cols].values
    dates = features_df['trade_date'].values

    X, y, d_out = [], [], []
    for i in range(seq_len, len(features_df) - horizon):
        X.append(feat[i - seq_len:i])
        future_ret = (close[i + horizon] - close[i]) / close[i]
        if future_ret < thresholds[0]:
            y.append(0)
        elif future_ret > thresholds[1]:
            y.append(2)
        else:
            y.append(1)
        d_out.append(dates[i])

    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int64), np.array(d_out)
