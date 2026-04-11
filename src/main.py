"""Main orchestrator: data → train → backtest → report."""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.fetcher import (
    init_tushare, fetch_trade_calendar, fetch_stock_basic,
    fetch_index_daily, fetch_daily_all, fetch_daily_basic, fetch_fina_indicator,
)
from src.data.cleaner import filter_st, filter_new_stocks, fill_missing_cross_section
from src.timer.features import compute_index_features, build_sequences_and_labels
from src.timer.model import train_model
from src.timer.signal import generate_signals
from src.ranker.factors import compute_all_factors
from src.ranker.normalize import winsorize_mad, zscore_cross_section
from src.ranker.scorer import compute_composite_score, rank_top_n, DEFAULT_WEIGHTS
from src.engine.backtest import run_backtest
from src.engine.metrics import compute_all_metrics
from src.tracking.wandb_run import (
    build_backtest_curve_frame,
    finish_wandb_run,
    init_wandb_run,
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
    while cur < end:
        train_end = (cur - pd.Timedelta(days=1)).strftime("%Y%m%d")
        predict_start = cur.strftime("%Y%m%d")
        next_retrain = cur + pd.DateOffset(months=retrain_months)
        predict_end = min(next_retrain - pd.Timedelta(days=1), end).strftime("%Y%m%d")
        if train_end >= train_start:
            windows.append((train_start, train_end, predict_start, predict_end))
        cur = next_retrain
    return windows


def train_and_generate_signals(index_daily, trade_dates, train_start, retrain_months=6, tracker=None):
    print("[Timer] Computing index features...")
    features = compute_index_features(index_daily)
    feature_cols = [c for c in features.columns if c not in ("trade_date", "close")]
    print(f"  → {len(feature_cols)} features, {len(features)} samples")

    windows = _get_retrain_dates(trade_dates, train_start, retrain_months)
    all_signals = []

    for i, (ts, te, ps, pe) in enumerate(windows):
        print(f"[Timer] Window {i+1}/{len(windows)}: train {ts}~{te}, predict {ps}~{pe}")
        train_feat = features[(features["trade_date"] >= ts) & (features["trade_date"] <= te)]
        X_all, y_all, _ = build_sequences_and_labels(train_feat, feature_cols, seq_len=60, horizon=5)
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

        split = int(len(X_all) * 0.8)
        model, hist = train_model(
            X_all[:split], y_all[:split], X_all[split:], y_all[split:],
            epochs=100, batch_size=64, lr=1e-3, patience=10,
        )
        log_timer_window_history(
            tracker,
            window_index=i + 1,
            window_dates=window_dates,
            history=hist,
            train_samples=split,
            val_samples=len(X_all) - split,
        )
        print(f"  → {len(hist['train_loss'])} epochs, val_acc={hist['val_acc'][-1]:.3f}")

        pred_feat = features[(features["trade_date"] >= ps) & (features["trade_date"] <= pe)]
        pred_data = pred_feat[feature_cols].values
        pred_dates = pred_feat["trade_date"].values
        X_seq, d_seq = [], []
        for j in range(60, len(pred_data)):
            X_seq.append(pred_data[j - 60:j])
            d_seq.append(pred_dates[j])
        if not X_seq:
            continue
        sigs = generate_signals(model, np.array(X_seq, dtype=np.float32), d_seq)
        all_signals.append(sigs)

    if not all_signals:
        return pd.DataFrame(columns=["trade_date", "position"])
    result = pd.concat(all_signals, ignore_index=True)
    return result.drop_duplicates("trade_date", keep="last").sort_values("trade_date").reset_index(drop=True)


def compute_daily_rankings(all_factors_df, stock_basic, trade_dates):
    print("[Ranker] Computing daily rankings...")
    factor_cols = [c for c in all_factors_df.columns if c not in ("ts_code", "trade_date")]
    rankings = {}
    for i, date in enumerate(trade_dates):
        if (i + 1) % 200 == 0:
            print(f"  → {i+1}/{len(trade_dates)}")
        eligible = filter_st(stock_basic)
        eligible = filter_new_stocks(eligible, date, min_days=60)
        eligible_codes = set(eligible["ts_code"])
        day_factors = all_factors_df[
            (all_factors_df["trade_date"] == date) & (all_factors_df["ts_code"].isin(eligible_codes))
        ].copy()
        if len(day_factors) < 5:
            rankings[date] = day_factors["ts_code"].tolist()[:5] if len(day_factors) > 0 else []
            continue
        for col in factor_cols:
            day_factors[col] = winsorize_mad(day_factors[col].fillna(day_factors[col].median()))
            day_factors[col] = zscore_cross_section(day_factors[col])
        day_factors = fill_missing_cross_section(day_factors, factor_cols)
        scored = compute_composite_score(day_factors, DEFAULT_WEIGHTS)
        top = rank_top_n(scored, n=5)
        rankings[date] = top["ts_code"].tolist()
    return rankings


def generate_report(metrics, output_dir="output"):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    lines = ["# ChiNext Quant Strategy Backtest Report\n", "| Metric | Value |", "|--------|-------|"]
    for k, v in metrics.items():
        fmt = f"{v:.4f}" if isinstance(v, float) else str(v)
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
    args = p.parse_args()

    tracker = init_wandb_run(
        {
            "start": args.start,
            "end": args.end,
            "capital": args.capital,
            "train_start": args.train_start,
            "retrain_months": 6,
            "seq_len": 60,
            "horizon": 5,
            "min_train_samples": 200,
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

        signals = train_and_generate_signals(data["index_daily"], bt_dates, args.train_start, tracker=tracker)
        print(f"[Timer] {len(signals)} signals generated")

        print("[Ranker] Computing all factors (vectorized)...")
        daily_merged = data["daily_all"].merge(
            data["daily_basic"][["ts_code", "trade_date", "pe_ttm", "pb", "turnover_rate"]],
            on=["ts_code", "trade_date"], how="left",
        )
        all_factors = compute_all_factors(daily_merged, data["index_daily"], data["fina_all"])
        rankings = compute_daily_rankings(all_factors, data["stock_basic"], bt_dates)

        print("[Engine] Running backtest...")
        if "pre_close" not in data["daily_all"].columns:
            data["daily_all"]["pre_close"] = data["daily_all"].groupby("ts_code")["close"].shift(1)
        result = run_backtest(data["daily_all"], signals, rankings, args.capital)

        bench = data["index_daily"].set_index("trade_date")["close"].sort_index()
        bench_nav = bench.reindex(result["nav"].index).ffill().bfill()
        bench_nav = bench_nav / bench_nav.iloc[0] * args.capital
        curve_df = build_backtest_curve_frame(result["nav"], bench_nav, signals, result["daily_turnover"])
        curve_path = save_backtest_curves(curve_df)
        log_backtest_curves(tracker, curve_df)
        metrics = compute_all_metrics(
            result["nav"],
            result["trade_pnls"],
            result["daily_turnover"],
            bench_nav,
        )
        report_path = generate_report(metrics)
        log_backtest_metrics(
            tracker,
            metrics=metrics,
            signal_count=len(signals),
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
        finish_wandb_run(tracker)


if __name__ == "__main__":
    main()
