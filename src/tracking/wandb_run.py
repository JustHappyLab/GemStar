"""Weights & Biases tracking helpers.

CALLING SPEC:
    run = init_wandb_run(run_config=dict[str, object], job_type="backtest") -> object | None
        Returns an initialized W&B run when `WANDB_API_KEY` is present.
        Returns `None` when W&B is not configured.

    log_timer_window_history(
        run,
        window_index=int,
        window_dates=dict[str, str],
        history=dict[str, list[float]],
        train_samples=int,
        val_samples=int,
    ) -> None

    log_timer_window_skip(
        run,
        window_index=int,
        window_dates=dict[str, str],
        sample_count=int,
        required_samples=int,
    ) -> None

    log_backtest_metrics(
        run,
        metrics=dict[str, float],
        signal_count=int,
        backtest_days=int,
        report_path=str,
        curve_data_path=str | None,
    ) -> None

    curve_df = build_backtest_curve_frame(
        nav=pd.Series,
        benchmark_nav=pd.Series,
        signals=pd.DataFrame,
        daily_turnover=pd.Series,
    ) -> pd.DataFrame

    log_backtest_curves(run, curve_df) -> None

    finish_wandb_run(run) -> None

SIDE EFFECTS:
    Network calls to Weights & Biases when enabled.
"""

from __future__ import annotations

import os
from importlib import import_module
from time import strftime

import pandas as pd

from src.engine.metrics import calc_turnover_ratio_series


def _load_wandb(api_key_present: bool):
    try:
        return import_module("wandb")
    except ImportError as exc:
        if api_key_present:
            raise RuntimeError(
                "WANDB_API_KEY is set but the `wandb` package is not installed. Run `uv sync` first."
            ) from exc
        return None


def _format_capital(capital: object) -> str:
    try:
        value = float(capital)
    except (TypeError, ValueError):
        return "cap-unknown"

    if value >= 1_000_000:
        return f"cap-{value / 1_000_000:.1f}m".replace(".0", "")
    if value >= 1_000:
        return f"cap-{value / 1_000:.0f}k"
    return f"cap-{value:.0f}"


def _default_run_name(run_config: dict[str, object], job_type: str) -> str:
    start = str(run_config.get("start", "unknown"))
    end = str(run_config.get("end", "unknown"))
    train_start = str(run_config.get("train_start", "unknown"))
    capital = _format_capital(run_config.get("capital"))
    retrain_months = run_config.get("retrain_months")
    retrain_tag = f"rt{retrain_months}m" if retrain_months is not None else "rt-unknown"
    timestamp = strftime("%Y%m%d-%H%M%S")
    return f"{job_type}-{start}_{end}-train{train_start}-{capital}-{retrain_tag}-{timestamp}"


def init_wandb_run(run_config: dict[str, object], job_type: str = "backtest"):
    api_key = os.environ.get("WANDB_API_KEY", "").strip()
    if not api_key:
        return None

    wandb = _load_wandb(api_key_present=True)
    wandb.login(key=api_key)
    run_name = os.environ.get("WANDB_RUN_NAME") or _default_run_name(run_config, job_type)
    return wandb.init(
        project=os.environ.get("WANDB_PROJECT", "gemstar"),
        entity=os.environ.get("WANDB_ENTITY") or None,
        name=run_name,
        job_type=job_type,
        tags=["chinext", "timer", "backtest"],
        config=run_config,
    )


def build_backtest_curve_frame(
    nav: pd.Series,
    benchmark_nav: pd.Series,
    signals: pd.DataFrame,
    daily_turnover: pd.Series,
    daily_exposure: pd.Series,
    initial_capital: float,
) -> pd.DataFrame:
    nav_series = nav.sort_index().astype(float)
    trade_date_index = pd.to_datetime(pd.Index(nav_series.index).astype(str), format="%Y%m%d", errors="coerce")
    if trade_date_index.isna().any():
        trade_date_index = pd.to_datetime(pd.Index(nav_series.index), errors="coerce")
    benchmark_series = benchmark_nav.sort_index().reindex(nav_series.index).ffill().astype(float)
    if benchmark_series.isna().any():
        raise ValueError("benchmark_nav is missing leading values after alignment; refusing to backfill future data")
    target_position_series = (
        signals.set_index("trade_date")["position"]
        .reindex(nav_series.index)
        .ffill()
        .fillna(0.0)
        .astype(float)
    )
    realized_exposure_series = daily_exposure.reindex(nav_series.index).fillna(0.0).astype(float)
    turnover_series = daily_turnover.reindex(nav_series.index).fillna(0.0).astype(float)

    curve_df = pd.DataFrame(
        {
            "trade_date": trade_date_index.strftime("%Y-%m-%d"),
            "day_index": range(1, len(nav_series) + 1),
            "strategy_nav": nav_series.values,
            "benchmark_nav": benchmark_series.values,
            "position": realized_exposure_series.values,
            "target_position": target_position_series.values,
            "traded_notional": turnover_series.values,
        }
    )
    curve_df["strategy_nav_norm"] = curve_df["strategy_nav"] / curve_df["strategy_nav"].iloc[0]
    curve_df["benchmark_nav_norm"] = curve_df["benchmark_nav"] / curve_df["benchmark_nav"].iloc[0]
    curve_df["excess_nav"] = (
        curve_df["strategy_nav_norm"] / curve_df["benchmark_nav_norm"].replace(0.0, pd.NA)
    ).fillna(1.0) - 1.0
    curve_df["drawdown"] = curve_df["strategy_nav"] / curve_df["strategy_nav"].cummax() - 1.0
    curve_df["strategy_daily_return"] = curve_df["strategy_nav"].pct_change().fillna(0.0)
    curve_df["benchmark_daily_return"] = curve_df["benchmark_nav"].pct_change().fillna(0.0)
    curve_df["daily_excess_return"] = curve_df["strategy_daily_return"] - curve_df["benchmark_daily_return"]

    curve_df["turnover_ratio"] = calc_turnover_ratio_series(
        curve_df["strategy_nav"], curve_df["traded_notional"], initial_capital
    )
    return curve_df


def log_timer_window_history(
    run,
    window_index: int,
    window_dates: dict[str, str],
    history: dict[str, list[float]],
    train_samples: int,
    val_samples: int,
) -> None:
    if run is None:
        return

    epoch_count = len(history["train_loss"])
    step_base = window_index * 1000
    for epoch_index, (train_loss, val_loss, val_acc) in enumerate(
        zip(history["train_loss"], history["val_loss"], history["val_acc"]),
        start=1,
    ):
        run.log(
            {
                "timer/window_index": window_index,
                "timer/window_epoch": epoch_index,
                "timer/train_loss": train_loss,
                "timer/val_loss": val_loss,
                "timer/val_acc": val_acc,
                "timer/train_start": window_dates["train_start"],
                "timer/train_end": window_dates["train_end"],
                "timer/predict_start": window_dates["predict_start"],
                "timer/predict_end": window_dates["predict_end"],
            },
            step=step_base + epoch_index,
        )

    run.log(
        {
            "timer/window_index": window_index,
            "timer/window_epochs_ran": epoch_count,
            "timer/window_train_samples": train_samples,
            "timer/window_val_samples": val_samples,
            "timer/window_best_val_loss": min(history["val_loss"]),
            "timer/window_best_val_acc": max(history["val_acc"]),
        },
        step=step_base + epoch_count + 1,
    )


def log_timer_window_skip(
    run,
    window_index: int,
    window_dates: dict[str, str],
    sample_count: int,
    required_samples: int,
) -> None:
    if run is None:
        return

    run.log(
        {
            "timer/window_index": window_index,
            "timer/window_skipped": 1,
            "timer/window_sample_count": sample_count,
            "timer/window_required_samples": required_samples,
            "timer/train_start": window_dates["train_start"],
            "timer/train_end": window_dates["train_end"],
            "timer/predict_start": window_dates["predict_start"],
            "timer/predict_end": window_dates["predict_end"],
        },
        step=window_index * 1000,
    )


def log_backtest_metrics(
    run,
    metrics: dict[str, float],
    signal_count: int,
    backtest_days: int,
    report_path: str,
    curve_data_path: str | None = None,
) -> None:
    if run is None:
        return

    payload = {
        "backtest/signal_count": signal_count,
        "backtest/days": backtest_days,
        "backtest/report_path": report_path,
    }
    if curve_data_path is not None:
        payload["backtest/curve_data_path"] = curve_data_path
    for key, value in metrics.items():
        payload[f"backtest/{key}"] = value
        run.summary[f"backtest/{key}"] = value

    run.log(payload)


def log_backtest_curves(run, curve_df: pd.DataFrame) -> None:
    if run is None or curve_df.empty:
        return

    wandb = _load_wandb(api_key_present=False)
    equity_curve_df = pd.concat(
        [
            curve_df[["trade_date", "strategy_nav_norm"]]
            .rename(columns={"strategy_nav_norm": "nav"})
            .assign(series="Strategy"),
            curve_df[["trade_date", "benchmark_nav_norm"]]
            .rename(columns={"benchmark_nav_norm": "nav"})
            .assign(series="Benchmark"),
        ],
        ignore_index=True,
    )
    table_cols = [
        "trade_date",
        "day_index",
        "strategy_nav_norm",
        "benchmark_nav_norm",
        "excess_nav",
        "drawdown",
        "position",
        "target_position",
        "turnover_ratio",
        "traded_notional",
        "strategy_daily_return",
        "benchmark_daily_return",
        "daily_excess_return",
    ]
    table = wandb.Table(dataframe=curve_df[table_cols])
    equity_table = wandb.Table(dataframe=equity_curve_df)

    run.log(
        {
            "backtest/curve_table": table,
            "backtest/charts/equity_curve": wandb.plot.line(
                equity_table,
                "trade_date",
                "nav",
                stroke="series",
                title="Normalized NAV: Strategy vs ChiNext Benchmark",
            ),
            "backtest/charts/excess_curve": wandb.plot.line(
                table,
                "trade_date",
                "excess_nav",
                title="Relative Outperformance vs Benchmark",
            ),
            "backtest/charts/drawdown_curve": wandb.plot.line(
                table,
                "trade_date",
                "drawdown",
                title="Drawdown Curve",
            ),
            "backtest/charts/position_curve": wandb.plot.line(
                table,
                "trade_date",
                "position",
                title="Realized Exposure Over Time",
            ),
        }
    )


def finish_wandb_run(run) -> None:
    if run is not None:
        run.finish()
