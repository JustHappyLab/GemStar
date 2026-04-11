from src.tracking import wandb_run


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
    )
    wandb_run.finish_wandb_run(run)

    assert len(run.logged) == 5
    assert run.summary["backtest/CAGR"] == 0.12
    assert run.summary["backtest/Sharpe"] == 1.5
    assert run.finished is True
