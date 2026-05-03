from tools.tracking import swanlab_run
import pandas as pd


class FakeRun:
    def __init__(self):
        self.logged = []
        self.finished = False

    def log(self, payload, step=None):
        self.logged.append((payload, step))

    def finish(self):
        self.finished = True


class FakeSwanlab:
    def __init__(self):
        self.init_calls = []
        self.run = FakeRun()

    def init(self, **kwargs):
        self.init_calls.append(kwargs)
        return self.run


def test_init_swanlab_run_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("SWANLAB_API_KEY", raising=False)
    run = swanlab_run.init_swanlab_run({"start": "20210409"})
    assert run is None


def test_init_swanlab_run_uses_env_configuration(monkeypatch):
    fake_swanlab = FakeSwanlab()
    monkeypatch.setenv("SWANLAB_API_KEY", "test-key")
    monkeypatch.setenv("SWANLAB_PROJ_NAME", "custom-project")
    monkeypatch.setenv("SWANLAB_EXP_NAME", "custom-run")
    monkeypatch.setattr(swanlab_run, "import_module", lambda _: fake_swanlab)

    run = swanlab_run.init_swanlab_run({"start": "20210409"}, job_type="backtest")

    assert run is fake_swanlab.run
    assert fake_swanlab.init_calls[0]["project"] == "custom-project"
    assert fake_swanlab.init_calls[0]["experiment_name"] == "custom-run"
    assert fake_swanlab.init_calls[0]["job_type"] == "backtest"


def test_init_swanlab_run_builds_semantic_name_by_default(monkeypatch):
    fake_swanlab = FakeSwanlab()
    monkeypatch.setenv("SWANLAB_API_KEY", "test-key")
    monkeypatch.delenv("SWANLAB_EXP_NAME", raising=False)
    monkeypatch.setattr(swanlab_run, "import_module", lambda _: fake_swanlab)
    monkeypatch.setattr(swanlab_run, "strftime", lambda _: "20260412-020000")

    run = swanlab_run.init_swanlab_run(
        {
            "start": "20210409",
            "end": "20260409",
            "train_start": "20190101",
            "capital": 100000,
            "retrain_months": 6,
        },
        job_type="backtest",
    )

    assert run is fake_swanlab.run
    assert (
        fake_swanlab.init_calls[0]["experiment_name"]
        == "backtest-20210409_20260409-train20190101-cap-100k-rt6m-20260412-020000"
    )


def test_logging_helpers_record_metrics():
    run = FakeRun()
    history = {
        "train_loss": [1.2, 0.9],
        "val_loss": [1.1, 0.8],
        "val_acc": [0.4, 0.6],
    }
    window_dates = {
        "train_start": "20190101",
        "train_end": "20210408",
        "predict_start": "20210409",
        "predict_end": "20211008",
    }

    swanlab_run.log_timer_window_history(run, 1, window_dates, history, train_samples=160, val_samples=40)
    swanlab_run.log_timer_window_skip(run, 2, window_dates, sample_count=180, required_samples=200)
    swanlab_run.log_backtest_metrics(
        run,
        metrics={"CAGR": 0.12, "Sharpe": 1.5},
        signal_count=321,
        backtest_days=500,
        report_path="output/backtest_report.md",
        curve_data_path="output/backtest_curves.csv",
    )
    swanlab_run.finish_swanlab_run(run)

    assert len(run.logged) == 5
    assert run.finished is True


def test_build_backtest_curve_frame_and_log_curves():
    nav = pd.Series([100000.0, 101000.0, 99000.0], index=["20240102", "20240103", "20240104"])
    benchmark_nav = pd.Series([100000.0, 100500.0, 99500.0], index=["20240102", "20240103", "20240104"])
    signals = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103", "20240104"],
            "position": [0.0, 0.5, 1.0],
        }
    )
    daily_turnover = pd.Series([0.0, 1200.0, 900.0], index=["20240102", "20240103", "20240104"])
    daily_exposure = pd.Series([0.0, 0.45, 0.8], index=["20240102", "20240103", "20240104"])

    curve_df = swanlab_run.build_backtest_curve_frame(
        nav,
        benchmark_nav,
        signals,
        daily_turnover,
        daily_exposure,
        initial_capital=100000.0,
    )
    run = FakeRun()
    swanlab_run.log_backtest_curves(run, curve_df)

    assert "strategy_nav_norm" in curve_df.columns
    assert "drawdown" in curve_df.columns
    assert "turnover_ratio" in curve_df.columns
    assert "target_position" in curve_df.columns
    assert curve_df.loc[0, "trade_date"] == "2024-01-02"
    assert curve_df.loc[1, "position"] == 0.45
    assert len(run.logged) == 3  # one log per day
    # Each log should contain the 5 curve metrics
    payload = run.logged[0][0]
    assert "backtest/strategy_nav_norm" in payload
    assert "backtest/drawdown" in payload
    assert "backtest/position" in payload
