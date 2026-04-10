import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts


def _cache_path(cache_dir: str, name: str) -> Path:
    return Path(cache_dir) / f"{name}.parquet"


def _read_cache(cache_dir: str, name: str) -> pd.DataFrame | None:
    p = _cache_path(cache_dir, name)
    if p.exists():
        return pd.read_parquet(p)
    return None


def _write_cache(df: pd.DataFrame, cache_dir: str, name: str) -> None:
    p = _cache_path(cache_dir, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)


def _rate_limit():
    time.sleep(0.35)


def _split_monthly(start_date: str, end_date: str) -> list[tuple[str, str]]:
    starts = pd.date_range(start_date, end_date, freq="MS")
    ends = (starts + pd.offsets.MonthEnd(0)).strftime("%Y%m%d")
    starts = starts.strftime("%Y%m%d")
    pairs = list(zip(starts, ends))
    # clamp to original range
    if pairs:
        pairs[0] = (start_date, pairs[0][1])
        pairs[-1] = (pairs[-1][0], end_date)
    return pairs


def init_tushare(token: str | None = None):
    t = token or os.environ.get("TUSHARE_TOKEN", "")
    ts.set_token(t)
    return ts.pro_api()


def fetch_trade_calendar(pro, start_date: str, end_date: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    name = f"trade_cal_{start_date}_{end_date}"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        return cached
    df = pro.trade_cal(start_date=start_date, end_date=end_date)
    df = df[df["is_open"] == 1][["cal_date"]].reset_index(drop=True)
    _write_cache(df, cache_dir, name)
    _rate_limit()
    return df


def fetch_stock_basic(pro, cache_dir: str = "data/raw") -> pd.DataFrame:
    name = "stock_basic_chinext"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        return cached
    cols = "ts_code,name,list_date,delist_date,market"
    listed = pro.stock_basic(exchange="", list_status="L", fields=cols)
    delisted = pro.stock_basic(exchange="", list_status="D", fields=cols)
    df = pd.concat([listed, delisted], ignore_index=True)
    df = df[df["ts_code"].str.match(r"^30[01]")].reset_index(drop=True)
    _write_cache(df, cache_dir, name)
    _rate_limit()
    return df


def fetch_index_daily(pro, ts_code: str, start_date: str, end_date: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    name = f"index_daily_{ts_code}_{start_date}_{end_date}"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        return cached
    df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    df = df.sort_values("trade_date").reset_index(drop=True)
    _write_cache(df, cache_dir, name)
    _rate_limit()
    return df


def fetch_daily_all(pro, start_date: str, end_date: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    name = f"daily_all_{start_date}_{end_date}"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        return cached
    cols = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"]
    frames = []
    for ms, me in _split_monthly(start_date, end_date):
        cal = pro.trade_cal(start_date=ms, end_date=me)
        dates = cal[cal["is_open"] == 1]["cal_date"].tolist()
        for d in dates:
            chunk = pro.daily(trade_date=d)
            if chunk is not None and not chunk.empty:
                frames.append(chunk[cols])
            _rate_limit()
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
    _write_cache(df, cache_dir, name)
    return df


def fetch_daily_basic(pro, start_date: str, end_date: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    name = f"daily_basic_{start_date}_{end_date}"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        return cached
    cols = ["ts_code", "trade_date", "pe_ttm", "pb", "turnover_rate", "total_mv", "circ_mv"]
    frames = []
    for ms, me in _split_monthly(start_date, end_date):
        chunk = pro.daily_basic(start_date=ms, end_date=me, fields=",".join(cols))
        if chunk is not None and not chunk.empty:
            frames.append(chunk[cols])
        _rate_limit()
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
    _write_cache(df, cache_dir, name)
    return df


def fetch_fina_indicator(pro, ts_code: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    name = f"fina_{ts_code.replace('.', '_')}"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        return cached
    cols = ["ts_code", "ann_date", "end_date", "roe", "revenue_yoy", "netprofit_yoy", "grossprofit_margin"]
    df = pro.fina_indicator(ts_code=ts_code, fields=",".join(cols))
    if df is None or df.empty:
        df = pd.DataFrame(columns=cols)
    _write_cache(df, cache_dir, name)
    _rate_limit()
    return df
