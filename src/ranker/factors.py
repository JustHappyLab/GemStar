"""Cross-sectional factor construction for daily stock ranking.

CALLING SPEC:
    factors = compute_all_factors(
        daily_merged=pd.DataFrame,
        index_daily=pd.DataFrame,
        fina_all=pd.DataFrame,
    ) -> pd.DataFrame
        Returns factor rows by `ts_code` and `trade_date`.
        All market-derived factors are lagged by one trading day so a
        ranking used on trade date `t` only depends on information
        available by the close of `t-1`.

SIDE EFFECTS:
    None.
"""

import numpy as np
import pandas as pd


def compute_all_factors(daily_merged: pd.DataFrame, index_daily: pd.DataFrame, fina_all: pd.DataFrame) -> pd.DataFrame:
    df = daily_merged.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    g = df.groupby('ts_code')

    df['momentum_20d'] = g['close'].pct_change(20)
    df['pe_inverse'] = np.where(df['pe_ttm'] > 0, 1.0 / df['pe_ttm'], np.nan)
    df['pb_inverse'] = np.where(df['pb'] > 0, 1.0 / df['pb'], np.nan)
    df['turnover_20d'] = g['turnover_rate'].transform(lambda x: x.rolling(20).mean())

    # Index 20d return
    idx = index_daily.sort_values('trade_date').copy()
    idx['trade_date'] = pd.to_datetime(idx['trade_date'])
    idx['index_ret_20d'] = idx['close'].pct_change(20)
    idx = idx[['trade_date', 'index_ret_20d']]

    df['stock_ret_20d'] = df['momentum_20d']
    df = df.merge(idx, on='trade_date', how='left')
    df['rel_strength_20d'] = df['stock_ret_20d'] - df['index_ret_20d']
    df.drop(columns=['stock_ret_20d', 'index_ret_20d'], inplace=True)

    # Financial factors via merge_asof per stock
    if not fina_all.empty:
        fina = fina_all[['ts_code', 'ann_date', 'end_date', 'roe', 'revenue_yoy', 'netprofit_yoy']].copy()
        if 'disclosure_date' in fina_all.columns:
            fina['available_date'] = fina_all['disclosure_date']
        else:
            fina['available_date'] = fina['ann_date']
        fina['available_date'] = pd.to_datetime(fina['available_date'])
        fina['ann_date'] = pd.to_datetime(fina['ann_date'])
        fina['end_date'] = pd.to_datetime(fina['end_date'], errors='coerce')
        fina = fina.dropna(subset=['available_date'])
        fina = fina.sort_values(['ts_code', 'available_date', 'end_date'])
        fina = fina.drop_duplicates(['ts_code', 'available_date'], keep='last')
        df = df.sort_values(['ts_code', 'trade_date'])

        parts = []
        for code, grp in df.groupby('ts_code'):
            f = fina[fina['ts_code'] == code]
            if f.empty:
                merged = grp.copy()
                for col in ['roe', 'revenue_yoy', 'netprofit_yoy']:
                    merged[col] = None
            else:
                merged = pd.merge_asof(
                    grp,
                    f.drop(columns='ts_code'),
                    left_on='trade_date',
                    right_on='available_date',
                    direction='backward',
                )
                merged.drop(columns=['ann_date', 'available_date', 'end_date'], inplace=True, errors='ignore')
            parts.append(merged)
        df = pd.concat(parts, ignore_index=True)
    else:
        for c in ['roe', 'revenue_yoy', 'netprofit_yoy']:
            df[c] = None

    market_factor_cols = [
        'momentum_20d',
        'pe_inverse',
        'pb_inverse',
        'turnover_20d',
        'rel_strength_20d',
    ]
    fundamental_factor_cols = ['roe', 'revenue_yoy', 'netprofit_yoy']
    factor_cols = market_factor_cols + fundamental_factor_cols
    df[market_factor_cols] = df.groupby('ts_code')[market_factor_cols].shift(1)

    df['trade_date'] = df['trade_date'].dt.strftime('%Y%m%d')
    cols = ['ts_code', 'trade_date', *factor_cols]
    return df[cols]
