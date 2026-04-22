"""Main orchestrator: data -> train -> backtest -> report.

CALLING SPEC:
    uv run python -m src.main --start=YYYYMMDD --end=YYYYMMDD --train-start=YYYYMMDD --capital=float
        Fetches data, trains the timer model on rolling windows, runs the daily backtest,
        writes `output/backtest_report.md` and `output/backtest_curves.csv`,
        and logs a compact SwanLab backtest dashboard when configured.

SIDE EFFECTS:
    Network I/O to Tushare and SwanLab.
    Writes report artifacts under `output/`.
"""
import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.fetcher import (
    init_tushare, fetch_trade_calendar, fetch_stock_basic,
    fetch_index_daily, fetch_daily_all, fetch_daily_basic, fetch_fina_indicator,
)
from src.data.cleaner import filter_active_stocks, filter_new_stocks, filter_st, filter_suspended
from src.timer.features import (
    build_prediction_sequences,
    build_sequences_and_labels,
    compute_index_features,
)
from src.timer.model import train_model
from src.timer.scaler import apply_sequence_standardizer, fit_sequence_standardizer
from src.timer.signal import align_signals_to_calendar, generate_signals
from src.ranker.factors import compute_all_factors
from src.ranker.normalize import winsorize_mad, zscore_cross_section
from src.ranker.scorer import compute_composite_score, rank_top_n, DEFAULT_WEIGHTS
from src.engine.backtest import run_backtest
from src.engine.metrics import compute_all_metrics
from src.tracking.swanlab_run import (
    build_backtest_curve_frame,
    finish_swanlab_run,
    init_swanlab_run,
    log_backtest_curves,
    log_backtest_metrics,
    log_timer_window_history,
    log_timer_window_skip,
)


def fetch_all_data(pro, start, end, train_start):
    print(f"[Data] Fetching calendar {train_start}~{end}...")
    trade_cal = fetch_trade_calendar(pro, train_start, end)
    print("[Data] Fetching ChiNext stock list...")
    stock_basic = fetch_stock_basic(pro)
    print(f"  → {len(stock_basic)} stocks")
    print("[Data] Fetching index daily...")
    index_daily = fetch_index_daily(pro, "399006.SZ", train_start, end)
    print("[Data] Fetching daily bars (batch)...")
    daily_all = fetch_daily_all(pro, train_start, end)
    print("[Data] Fetching daily basic...")
    daily_basic = fetch_daily_basic(pro, train_start, end)
    print("[Data] Fetching financial indicators...")
    codes = stock_basic["ts_code"].tolist()
    fina_frames = []
    for i, code in enumerate(codes):
        if (i + 1) % 200 == 0:
            print(f"  → {i + 1}/{len(codes)}")
        df = fetch_fina_indicator(pro, code)
        if len(df) > 0:
            fina_frames.append(df)
    fina_all = pd.concat(fina_frames, ignore_index=True) if fina_frames else pd.DataFrame()
    return dict(trade_cal=trade_cal, stock_basic=stock_basic, index_daily=index_daily,
                daily_all=daily_all, daily_basic=daily_basic, fina_all=fina_all)


def _get_retrain_dates(trade_dates, train_start, retrain_months):
    dates_sorted = sorted(trade_dates)
    cur = pd.Timestamp(dates_sorted[0])
    end = pd.Timestamp(dates_sorted[-1])
    windows = []
    while cur <= end:
        train_end = (cur - pd.Timedelta(days=1)).strftime("%Y%m%d")
        predict_start = cur.strftime("%Y%m%d")
        next_retrain = cur + pd.DateOffset(months=retrain_months)
        predict_end = min(next_retrain - pd.Timedelta(days=1), end).strftime("%Y%m%d")
        if train_end >= train_start:
            windows.append((train_start, train_end, predict_start, predict_end))
        cur = next_retrain
    return windows


def _split_train_validation_indices(sample_count, embargo, min_train_samples=160, min_val_samples=40):
    train_end = int(sample_count * 0.8)
    val_start = train_end + embargo
    if sample_count - val_start < min_val_samples:
        train_end = sample_count - embargo - min_val_samples
        val_start = train_end + embargo
    if train_end < min_train_samples or sample_count - val_start < min_val_samples:
        return None
    return train_end, val_start


def train_and_generate_signals(index_daily, trade_dates, train_start, retrain_months=6, tracker=None):
    print("[Timer] Computing index features...")
    features = compute_index_features(index_daily)
    feature_cols = [c for c in features.columns if c not in ("trade_date", "close")]
    seq_len = 60
    horizon = 5
    print(f"  → {len(feature_cols)} features, {len(features)} samples")

    windows = _get_retrain_dates(trade_dates, train_start, retrain_months)
    all_signals = []
    raw_signal_count = 0

    for i, (ts, te, ps, pe) in enumerate(windows):
        print(f"[Timer] Window {i+1}/{len(windows)}: train {ts}~{te}, predict {ps}~{pe}")
        train_feat = features[(features["trade_date"] >= ts) & (features["trade_date"] <= te)]
        X_all, y_all, _ = build_sequences_and_labels(train_feat, feature_cols, seq_len=seq_len, horizon=horizon)
        window_dates = {
            "train_start": ts,
            "train_end": te,
            "predict_start": ps,
            "predict_end": pe,
        }
        if len(X_all) < 200:
            print("  → Insufficient training data, skipping")
            log_timer_window_skip(
                tracker,
                window_index=i + 1,
                window_dates=window_dates,
                sample_count=len(X_all),
                required_samples=200,
            )
            continue

        split_indices = _split_train_validation_indices(len(X_all), embargo=seq_len + horizon)
        if split_indices is None:
            print("  → Insufficient purged validation data, skipping")
            log_timer_window_skip(
                tracker,
                window_index=i + 1,
                window_dates=window_dates,
                sample_count=len(X_all),
                required_samples=200 + seq_len + horizon,
            )
            continue

        split, val_start = split_indices
        X_train, y_train = X_all[:split], y_all[:split]
        X_val, y_val = X_all[val_start:], y_all[val_start:]
        scaler = fit_sequence_standardizer(X_train)
        model, hist = train_model(
            apply_sequence_standardizer(X_train, scaler),
            y_train,
            apply_sequence_standardizer(X_val, scaler),
            y_val,
            epochs=100, batch_size=64, lr=1e-3, patience=10,
        )
        log_timer_window_history(
            tracker,
            window_index=i + 1,
            window_dates=window_dates,
            history=hist,
            train_samples=split,
            val_samples=len(X_val),
        )
        print(f"  → {len(hist['train_loss'])} epochs, val_acc={hist['val_acc'][-1]:.3f}")

        X_pred, pred_dates = build_prediction_sequences(
            features,
            feature_cols,
            predict_start=ps,
            predict_end=pe,
            seq_len=seq_len,
        )
        if len(X_pred) == 0:
            continue
        sigs = generate_signals(model, apply_sequence_standardizer(X_pred, scaler), pred_dates)
        all_signals.append(sigs)
        raw_signal_count += len(sigs)

    if not all_signals:
        empty = pd.DataFrame(columns=["trade_date", "position"])
        return align_signals_to_calendar(empty, trade_dates), 0

    result = pd.concat(all_signals, ignore_index=True)
    raw_signal_days = result["trade_date"].astype(str).nunique()
    aligned = align_signals_to_calendar(result, trade_dates)
    missing_days = len(trade_dates) - raw_signal_days
    if missing_days > 0:
        print(f"[Timer] Warning: filled {missing_days} missing signal days with neutral position")
    return aligned, raw_signal_count



def _random_daily_rankings(stock_basic, daily_df, trade_dates, n=5, seed=42):
    """Ablation baseline: random Top-N from eligible stocks each day."""
    rng = np.random.default_rng(seed)
    rankings: dict[str, list[str]] = {}
    for date in trade_dates:
        eligible = filter_st(stock_basic)
        eligible = filter_active_stocks(eligible, date)
        eligible = filter_new_stocks(eligible, date, min_days=60)
        tradable = filter_suspended(daily_df[daily_df["trade_date"] == date])
        codes = list(set(eligible["ts_code"]) & set(tradable["ts_code"]))
        pick = min(n, len(codes))
        rankings[date] = list(rng.choice(codes, size=pick, replace=False)) if pick > 0 else []
    return rankings

def compute_daily_rankings(all_factors_df, stock_basic, daily_df, trade_dates):
    print("[Ranker] Computing daily rankings...")
    factor_cols = [c for c in all_factors_df.columns if c not in ("ts_code", "trade_date")]
    rankings = {}
    for i, date in enumerate(trade_dates):
        if (i + 1) % 200 == 0:
            print(f"  → {i+1}/{len(trade_dates)}")
        eligible = filter_st(stock_basic)
        eligible = filter_active_stocks(eligible, date)
        eligible = filter_new_stocks(eligible, date, min_days=60)
        tradable_rows = filter_suspended(daily_df[daily_df["trade_date"] == date])
        eligible_codes = set(eligible["ts_code"]) & set(tradable_rows["ts_code"])
        day_factors = all_factors_df[
            (all_factors_df["trade_date"] == date) & (all_factors_df["ts_code"].isin(eligible_codes))
        ].copy()
        if day_factors.empty:
            rankings[date] = []
            continue
        min_factor_count = max(4, len(factor_cols) // 2)
        day_factors = day_factors[day_factors[factor_cols].notna().sum(axis=1) >= min_factor_count].copy()
        if day_factors.empty:
            rankings[date] = []
            continue
        for col in factor_cols:
            series = pd.to_numeric(day_factors[col], errors="coerce")
            if series.notna().sum() < 3:
                day_factors[col] = 0.0
                continue
            filled = series.fillna(series.median())
            day_factors[col] = zscore_cross_section(winsorize_mad(filled))
        scored = compute_composite_score(day_factors, DEFAULT_WEIGHTS)
        top = rank_top_n(scored, n=5)
        rankings[date] = top["ts_code"].tolist()
    return rankings


def generate_report(metrics, output_dir="output"):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    lines = ["# ChiNext Quant Strategy Backtest Report\n", "| Metric | Value |", "|--------|-------|"]
    for k, v in metrics.items():
        if isinstance(v, float):
            fmt = f"{v:.4f}" if math.isfinite(v) else "N/A"
        else:
            fmt = str(v)
        lines.append(f"| {k} | {fmt} |")
    path = Path(output_dir) / "backtest_report.md"
    path.write_text("\n".join(lines))
    print(f"[Report] Saved to {path}")
    return path


def save_backtest_curves(curve_df: pd.DataFrame, output_dir="output"):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = Path(output_dir) / "backtest_curves.csv"
    curve_df.to_csv(path, index=False)
    print(f"[Report] Saved curve data to {path}")
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="20210409")
    p.add_argument("--end", default="20260409")
    p.add_argument("--capital", type=float, default=100000)
    p.add_argument("--train-start", default="20190101")
    p.add_argument("--no-timer", action="store_true", help="Ablation: fix position to 100%%, skip LSTM training")
    p.add_argument("--no-ranker", action="store_true", help="Ablation: random Top-5 selection each day")
    args = p.parse_args()

    tracker = init_swanlab_run(
        {
            "start": args.start,
            "end": args.end,
            "capital": args.capital,
            "train_start": args.train_start,
            "retrain_months": 6,
            "seq_len": 60,
            "horizon": 5,
            "min_train_samples": 200,
            "no_timer": args.no_timer,
            "no_ranker": args.no_ranker,
        }
    )

    try:
        pro = init_tushare()
        data = fetch_all_data(pro, args.start, args.end, args.train_start)

        bt_cal = data["trade_cal"]
        bt_dates = sorted(
            bt_cal[(bt_cal["cal_date"] >= args.start) & (bt_cal["cal_date"] <= args.end)]["cal_date"].tolist()
        )
        print(f"[Main] Backtest: {bt_dates[0]}~{bt_dates[-1]}, {len(bt_dates)} days")

        # --- Timer ---
        if args.no_timer:
            print("[Timer] Ablation: fixed 100% position")
            signals = pd.DataFrame({"trade_date": bt_dates, "position": 1.0})
            raw_signal_count = 0
        else:
            signals, raw_signal_count = train_and_generate_signals(
                data["index_daily"],
                bt_dates,
                args.train_start,
                tracker=tracker,
            )
            print(f"[Timer] {raw_signal_count} raw signals generated, {len(signals)} days aligned")

        # --- Ranker ---
        if args.no_ranker:
            print("[Ranker] Ablation: random Top-5 per day")
            rankings = _random_daily_rankings(data["stock_basic"], data["daily_all"], bt_dates)
        else:
            print("[Ranker] Computing all factors (vectorized)...")
            daily_merged = data["daily_all"].merge(
                data["daily_basic"][["ts_code", "trade_date", "pe_ttm", "pb", "turnover_rate"]],
                on=["ts_code", "trade_date"], how="left",
            )
            all_factors = compute_all_factors(daily_merged, data["index_daily"], data["fina_all"])
            rankings = compute_daily_rankings(all_factors, data["stock_basic"], data["daily_all"], bt_dates)

        print("[Engine] Running backtest...")
        if "pre_close" not in data["daily_all"].columns:
            data["daily_all"]["pre_close"] = data["daily_all"].groupby("ts_code")["close"].shift(1)
        result = run_backtest(data["daily_all"], signals, rankings, args.capital, trade_dates=bt_dates)

        bench = data["index_daily"].set_index("trade_date")["close"].sort_index()
        bench_nav = bench.reindex(result["nav"].index).ffill()
        if bench_nav.isna().any():
            raise ValueError("benchmark series is missing leading values in the backtest window")
        bench_nav = bench_nav / bench_nav.iloc[0] * args.capital
        curve_df = build_backtest_curve_frame(
            result["nav"],
            bench_nav,
            signals,
            result["daily_turnover"],
            result["daily_exposure"],
            args.capital,
        )
        curve_path = save_backtest_curves(curve_df)
        log_backtest_curves(tracker, curve_df)
        metrics = compute_all_metrics(
            result["nav"],
            result["trade_pnls"],
            result["daily_turnover"],
            bench_nav,
            args.capital,
        )
        report_path = generate_report(metrics)
        log_backtest_metrics(
            tracker,
            metrics=metrics,
            signal_count=raw_signal_count,
            backtest_days=len(bt_dates),
            report_path=str(report_path),
            curve_data_path=str(curve_path),
        )

        print("\n" + "=" * 50)
        print("BACKTEST COMPLETE")
        print("=" * 50)
        for k, v in metrics.items():
            print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    finally:
        finish_swanlab_run(tracker)


if __name__ == "__main__":
    main()
