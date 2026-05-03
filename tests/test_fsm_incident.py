"""Tests for the incident FSM — state transitions and terminal states."""

import pytest

from src.orchestrator.fsm_incident import IncidentFSM, incident_states, is_terminal


def test_incident_states_contains_all():
    """All 7 incident states are listed."""
    states = incident_states()
    assert len(states) == 7
    assert "detected" in states
    assert "classified" in states
    assert "resolved" in states


def test_fsm_starts_in_detected():
    """FSM starts in 'detected' state."""
    fsm = IncidentFSM()
    assert fsm.current() == "detected"


def test_fsm_valid_transitions():
    """Valid transitions succeed."""
    fsm = IncidentFSM()
    fsm.transition("classified")
    assert fsm.current() == "classified"

    fsm.transition("retrying")
    assert fsm.current() == "retrying"

    fsm.transition("resolved")
    assert fsm.current() == "resolved"
    assert fsm.is_terminal()


def test_fsm_classified_to_multiple_targets():
    """classified can go to retrying, degraded, manual_attention, engineering_task_created, or resolved."""
    for target in ("retrying", "degraded", "manual_attention", "engineering_task_created", "resolved"):
        fsm = IncidentFSM()
        fsm.transition("classified")
        fsm.transition(target)
        assert fsm.current() == target


def test_fsm_invalid_transition():
    """Invalid transitions raise ValueError."""
    fsm = IncidentFSM()
    with pytest.raises(ValueError, match="Invalid incident transition"):
        fsm.transition("resolved")  # detected → resolved is invalid


def test_fsm_terminal_states():
    """resolved is the only terminal state."""
    assert is_terminal("resolved") is True
    assert is_terminal("detected") is False
    assert is_terminal("classified") is False
    assert is_terminal("retrying") is False


def test_fsm_manual_attention_to_engineering():
    """manual_attention → engineering_task_created is valid."""
    fsm = IncidentFSM()
    fsm.transition("classified")
    fsm.transition("manual_attention")
    fsm.transition("engineering_task_created")
    assert fsm.current() == "engineering_task_created"


def test_fsm_engineering_to_resolved():
    """engineering_task_created → resolved is valid."""
    fsm = IncidentFSM()
    fsm.transition("classified")
    fsm.transition("engineering_task_created")
    fsm.transition("resolved")
    assert fsm.is_terminal()
