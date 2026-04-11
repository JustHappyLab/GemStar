from src.tracking import wandb_run
import pandas as pd


class FakeRun:
    def __init__(self):
        self.logged = []
        self.summary = {}
        self.finished = False

    def log(self, payload, step=None):
        self.logged.append((payload, step))

    def finish(self):
        self.finished = True


class FakeWandb:
    class Table:
        def __init__(self, dataframe):
            self.dataframe = dataframe

    class plot:
        @staticmethod
        def line(table, x, y, stroke=None, title="", split_table=False):
            return {"kind": "line", "x": x, "y": y, "title": title}

        @staticmethod
        def line_series(xs, ys, keys=None, title="", xname="x", split_table=False):
            return {"kind": "line_series", "keys": keys, "title": title, "xname": xname}

    def __init__(self):
        self.login_calls = []
        self.init_calls = []
        self.run = FakeRun()

    def login(self, key):
        self.login_calls.append(key)

    def init(self, **kwargs):
        self.init_calls.append(kwargs)
        return self.run


def test_init_wandb_run_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    run = wandb_run.init_wandb_run({"start": "20210409"})
    assert run is None


def test_init_wandb_run_uses_env_configuration(monkeypatch):
    fake_wandb = FakeWandb()
    monkeypatch.setenv("WANDB_API_KEY", "test-key")
    monkeypatch.setenv("WANDB_PROJECT", "custom-project")
    monkeypatch.setenv("WANDB_RUN_NAME", "custom-run")
    monkeypatch.setattr(wandb_run, "import_module", lambda _: fake_wandb)

    run = wandb_run.init_wandb_run({"start": "20210409"}, job_type="backtest")

    assert run is fake_wandb.run
    assert fake_wandb.login_calls == ["test-key"]
    assert fake_wandb.init_calls[0]["project"] == "custom-project"
    assert fake_wandb.init_calls[0]["name"] == "custom-run"
    assert fake_wandb.init_calls[0]["job_type"] == "backtest"


def test_init_wandb_run_builds_semantic_name_by_default(monkeypatch):
    fake_wandb = FakeWandb()
    monkeypatch.setenv("WANDB_API_KEY", "test-key")
    monkeypatch.delenv("WANDB_RUN_NAME", raising=False)
    monkeypatch.setattr(wandb_run, "import_module", lambda _: fake_wandb)
    monkeypatch.setattr(wandb_run, "strftime", lambda _: "20260412-020000")

    run = wandb_run.init_wandb_run(
        {
            "start": "20210409",
            "end": "20260409",
            "train_start": "20190101",
            "capital": 100000,
            "retrain_months": 6,
        },
        job_type="backtest",
    )

    assert run is fake_wandb.run
    assert (
        fake_wandb.init_calls[0]["name"]
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

    wandb_run.log_timer_window_history(run, 1, window_dates, history, train_samples=160, val_samples=40)
    wandb_run.log_timer_window_skip(run, 2, window_dates, sample_count=180, required_samples=200)
    wandb_run.log_backtest_metrics(
        run,
        metrics={"CAGR": 0.12, "Sharpe": 1.5},
        signal_count=321,
        backtest_days=500,
        report_path="output/backtest_report.md",
        curve_data_path="output/backtest_curves.csv",
    )
    wandb_run.finish_wandb_run(run)

    assert len(run.logged) == 5
    assert run.summary["backtest/CAGR"] == 0.12
    assert run.summary["backtest/Sharpe"] == 1.5
    assert run.finished is True


def test_build_backtest_curve_frame_and_log_curves(monkeypatch):
    fake_wandb = FakeWandb()
    monkeypatch.setattr(wandb_run, "import_module", lambda _: fake_wandb)

    nav = pd.Series([100000.0, 101000.0, 99000.0], index=["20240102", "20240103", "20240104"])
    benchmark_nav = pd.Series([100000.0, 100500.0, 99500.0], index=["20240102", "20240103", "20240104"])
    signals = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103", "20240104"],
            "position": [0.0, 0.5, 1.0],
        }
    )
    daily_turnover = pd.Series([0.0, 1200.0, 900.0], index=["20240102", "20240103", "20240104"])

    curve_df = wandb_run.build_backtest_curve_frame(nav, benchmark_nav, signals, daily_turnover)
    run = FakeRun()
    wandb_run.log_backtest_curves(run, curve_df)

    assert "strategy_nav_norm" in curve_df.columns
    assert "drawdown" in curve_df.columns
    assert "turnover_ratio" in curve_df.columns
    assert len(run.logged) == 4
