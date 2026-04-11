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
    ) -> None

    finish_wandb_run(run) -> None

SIDE EFFECTS:
    Network calls to Weights & Biases when enabled.
"""

from __future__ import annotations

import os
from importlib import import_module


def _load_wandb(api_key_present: bool):
    try:
        return import_module("wandb")
    except ImportError as exc:
        if api_key_present:
            raise RuntimeError(
                "WANDB_API_KEY is set but the `wandb` package is not installed. Run `uv sync` first."
            ) from exc
        return None


def init_wandb_run(run_config: dict[str, object], job_type: str = "backtest"):
    api_key = os.environ.get("WANDB_API_KEY", "").strip()
    if not api_key:
        return None

    wandb = _load_wandb(api_key_present=True)
    wandb.login(key=api_key)
    return wandb.init(
        project=os.environ.get("WANDB_PROJECT", "gemstar"),
        entity=os.environ.get("WANDB_ENTITY") or None,
        name=os.environ.get("WANDB_RUN_NAME") or None,
        job_type=job_type,
        tags=["chinext", "timer", "backtest"],
        config=run_config,
    )


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
) -> None:
    if run is None:
        return

    payload = {
        "backtest/signal_count": signal_count,
        "backtest/days": backtest_days,
        "backtest/report_path": report_path,
    }
    for key, value in metrics.items():
        payload[f"backtest/{key}"] = value
        run.summary[f"backtest/{key}"] = value

    run.log(payload)


def finish_wandb_run(run) -> None:
    if run is not None:
        run.finish()
