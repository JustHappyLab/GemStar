"""Tushare data fetch tools.

CALLING SPEC:
    pro = init_tushare(token: str | None = None) -> ts.pro_api client
        Reads `TUSHARE_TOKEN` from the explicit argument or environment.
        Raises ValueError when the token is missing.
    fetch_income, fetch_balancesheet, fetch_cashflow, fetch_disclosure_date,
    fetch_forecast, fetch_express — PIT-friendly financial data fetchers.
"""

import os
import time
from pathlib import Path

import pandas as pd
import tushare as ts
from requests.exceptions import RequestException


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


def _call_with_retry(fetch_fn, *args, op_name: str, retries: int = 4, backoff_sec: float = 1.0, **kwargs):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return fetch_fn(*args, **kwargs)
        except RequestException as exc:
            last_error = exc
            if attempt == retries:
                break
            wait_sec = backoff_sec * attempt
            print(
                f"[Data] {op_name} failed on attempt {attempt}/{retries}: {exc}. Retrying in {wait_sec:.1f}s...",
                flush=True,
            )
            time.sleep(wait_sec)
    raise last_error


def _normalize_fina_indicator(df: pd.DataFrame) -> pd.DataFrame:
    expected_cols = [
        "ts_code",
        "ann_date",
        "end_date",
        "roe",
        "revenue_yoy",
        "netprofit_yoy",
        "grossprofit_margin",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=expected_cols)

    normalized = df.rename(columns={"or_yoy": "revenue_yoy"}).copy()
    for col in expected_cols:
        if col not in normalized.columns:
            normalized[col] = None
    return normalized[expected_cols]


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
    candidate = token if token is not None else os.environ.get("TUSHARE_TOKEN", "")
    resolved_token = candidate.strip()
    if not resolved_token:
        raise ValueError(
            "TUSHARE_TOKEN is not set. Export it in your shell or create .env and run ./run.sh."
        )
    ts.set_token(resolved_token)
    return ts.pro_api()


def fetch_trade_calendar(pro, start_date: str, end_date: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    name = f"trade_cal_{start_date}_{end_date}"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        return cached
    df = _call_with_retry(
        pro.trade_cal,
        start_date=start_date,
        end_date=end_date,
        op_name=f"trade_cal {start_date}~{end_date}",
    )
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
    listed = _call_with_retry(
        pro.stock_basic,
        exchange="",
        list_status="L",
        fields=cols,
        op_name="stock_basic listed",
    )
    delisted = _call_with_retry(
        pro.stock_basic,
        exchange="",
        list_status="D",
        fields=cols,
        op_name="stock_basic delisted",
    )
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
    df = _call_with_retry(
        pro.index_daily,
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        op_name=f"index_daily {ts_code} {start_date}~{end_date}",
    )
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
        cal = _call_with_retry(
            pro.trade_cal,
            start_date=ms,
            end_date=me,
            op_name=f"trade_cal monthly {ms}~{me}",
        )
        dates = cal[cal["is_open"] == 1]["cal_date"].tolist()
        for d in dates:
            chunk = _call_with_retry(
                pro.daily,
                trade_date=d,
                op_name=f"daily {d}",
            )
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
        chunk = _call_with_retry(
            pro.daily_basic,
            start_date=ms,
            end_date=me,
            fields=",".join(cols),
            op_name=f"daily_basic {ms}~{me}",
        )
        if chunk is not None and not chunk.empty:
            frames.append(chunk[cols])
        _rate_limit()
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
    _write_cache(df, cache_dir, name)
    return df


def fetch_adj_factor(pro, start_date: str, end_date: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    name = f"adj_factor_{start_date}_{end_date}"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        return cached
    frames = []
    for ms, me in _split_monthly(start_date, end_date):
        chunk = _call_with_retry(
            pro.adj_factor,
            start_date=ms,
            end_date=me,
            op_name=f"adj_factor {ms}~{me}",
        )
        if chunk is not None and not chunk.empty:
            frames.append(chunk[["ts_code", "trade_date", "adj_factor"]])
        _rate_limit()
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
    _write_cache(df, cache_dir, name)
    return df


def fetch_fina_indicator(pro, ts_code: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    name = f"fina_{ts_code.replace('.', '_')}"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        normalized_cached = _normalize_fina_indicator(cached)
        if "revenue_yoy" in normalized_cached.columns and normalized_cached["revenue_yoy"].notna().any():
            return normalized_cached

    fetch_cols = ["ts_code", "ann_date", "end_date", "roe", "or_yoy", "netprofit_yoy", "grossprofit_margin"]
    df = _call_with_retry(
        pro.fina_indicator,
        ts_code=ts_code,
        fields=",".join(fetch_cols),
        op_name=f"fina_indicator {ts_code}",
    )
    df = _normalize_fina_indicator(df)
    _write_cache(df, cache_dir, name)
    _rate_limit()
    return df


def _fetch_by_ts_code(pro, ts_code: str, api_name: str, cache_dir: str) -> pd.DataFrame:
    """Shared helper for single-stock Tushare API fetches with caching."""
    name = f"{api_name}_{ts_code.replace('.', '_')}"
    cached = _read_cache(cache_dir, name)
    if cached is not None:
        return cached
    fetch_fn = getattr(pro, api_name)
    df = _call_with_retry(fetch_fn, ts_code=ts_code, op_name=f"{api_name} {ts_code}")
    if df is None:
        df = pd.DataFrame()
    _write_cache(df, cache_dir, name)
    _rate_limit()
    return df


def fetch_income(pro, ts_code: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    """Fetch income statement for a single stock."""
    return _fetch_by_ts_code(pro, ts_code, "income", cache_dir)


def fetch_balancesheet(pro, ts_code: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    """Fetch balance sheet for a single stock."""
    return _fetch_by_ts_code(pro, ts_code, "balancesheet", cache_dir)


def fetch_cashflow(pro, ts_code: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    """Fetch cash flow statement for a single stock."""
    return _fetch_by_ts_code(pro, ts_code, "cashflow", cache_dir)


def fetch_disclosure_date(pro, ts_code: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    """Fetch disclosure dates for a single stock."""
    return _fetch_by_ts_code(pro, ts_code, "disclosure_date", cache_dir)


def fetch_forecast(pro, ts_code: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    """Fetch earnings forecast for a single stock."""
    return _fetch_by_ts_code(pro, ts_code, "forecast", cache_dir)


def fetch_express(pro, ts_code: str, cache_dir: str = "data/raw") -> pd.DataFrame:
    """Fetch earnings express report for a single stock."""
    return _fetch_by_ts_code(pro, ts_code, "express", cache_dir)
