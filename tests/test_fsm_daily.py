"""Tests for the daily run FSM."""

import tempfile
from pathlib import Path

from src.orchestrator.fsm_daily import DailyFSM, DailyState, daily_states, is_terminal
from src.orchestrator.run_manifest import start_run


def test_daily_states_contains_all():
    states = daily_states()
    assert "initialized" in states
    assert "completed" in states
    assert "failed" in states
    assert "degraded" in states
    assert "manual_attention" in states
    assert len(states) >= 13


def test_fsm_starts_in_initialized():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        fsm = DailyFSM("run_001", db_path=db)
        assert fsm.current() == "initialized"


def test_fsm_valid_transitions():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        start_run("run_001", db_path=db, artifacts_dir=str(Path(tmpdir) / "artifacts"))
        fsm = DailyFSM("run_001", db_path=db)
        fsm.transition("collecting")
        assert fsm.current() == "collecting"
        fsm.transition("quality_checking")
        assert fsm.current() == "quality_checking"
        fsm.transition("factor_monitoring")
        assert fsm.current() == "factor_monitoring"
        fsm.transition("strategy_ideation")
        assert fsm.current() == "strategy_ideation"
        fsm.transition("strategy_validation")
        assert fsm.current() == "strategy_validation"
        fsm.transition("backtesting")
        assert fsm.current() == "backtesting"
        fsm.transition("judging")
        assert fsm.current() == "judging"
        fsm.transition("leaderboard_building")
        assert fsm.current() == "leaderboard_building"
        fsm.transition("reporting")
        assert fsm.current() == "reporting"
        fsm.transition("completed")
        assert fsm.current() == "completed"
        assert fsm.is_terminal()


def test_fsm_invalid_transition():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        start_run("run_001", db_path=db, artifacts_dir=str(Path(tmpdir) / "artifacts"))
        fsm = DailyFSM("run_001", db_path=db)
        try:
            fsm.transition("backtesting")  # can't jump from initialized
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid transition" in str(e)


def test_fsm_terminal_states():
    assert is_terminal("completed")
    assert is_terminal("failed")
    assert is_terminal("manual_attention")
    assert not is_terminal("collecting")


def test_fsm_degraded_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        start_run("run_001", db_path=db, artifacts_dir=str(Path(tmpdir) / "artifacts"))
        fsm = DailyFSM("run_001", db_path=db)
        fsm.transition("collecting")
        fsm.transition("quality_checking")
        fsm.transition("degraded")
        assert fsm.is_degraded()
        # degraded can still report
        fsm.transition("reporting")
        assert fsm.current() == "reporting"


def test_fsm_degraded_can_continue_pipeline():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = str(Path(tmpdir) / "test.db")
        start_run("run_001", db_path=db, artifacts_dir=str(Path(tmpdir) / "artifacts"))
        fsm = DailyFSM("run_001", db_path=db)
        fsm.transition("collecting")
        fsm.transition("quality_checking")
        fsm.transition("degraded")
        fsm.transition("factor_monitoring")
        assert fsm.current() == "factor_monitoring"
