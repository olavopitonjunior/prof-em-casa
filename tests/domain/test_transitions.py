from typing import get_args

import pytest
from app.domain.division.commands import CommandType
from app.domain.division.errors import DomainError
from app.domain.division.transitions import (
    _NEXT_PHASE_RULES,
    TRANSITIONS,
    NextPhaseFacts,
    Phase,
    is_allowed_in,
    next_phase,
)

PHASES = set(get_args(Phase))
ALL = frozenset(PHASES)


def _facts(phase, kind="guided", return_phase=None, correct=None):
    return NextPhaseFacts(
        phase=phase, attempt_kind=kind, return_phase=return_phase, answer_correct=correct
    )


def test_table_covers_the_whole_catalog_and_nothing_else():
    assert set(TRANSITIONS) == set(get_args(CommandType)) and len(TRANSITIONS) == 30
    assert "set_phase" not in TRANSITIONS


def test_table_uses_only_known_phases():
    for allowed, nxt in TRANSITIONS.values():
        assert allowed and allowed <= PHASES
        assert nxt is None or nxt in PHASES


def test_result_dependent_commands_have_rules():
    assert set(_NEXT_PHASE_RULES) == {
        "enter_notebook",
        "return_to_activity",
        "submit_answer",
        "continue_after_explanation",
    }


@pytest.mark.parametrize(
    "command,phase,target",
    [
        # Spec Parte I §4, uma linha por comando que muda de fase.
        ("choose_reference_activity", "source_capture", "demonstration"),
        ("choose_reference_activity", "source_review", "demonstration"),
        ("confirm_source", "source_review", "demonstration"),
        ("retake_source_photo", "source_review", "source_capture"),
        ("finish_demonstration", "demonstration", "practice"),
        ("enter_notebook", "practice", "notebook"),
        ("enter_notebook", "transfer", "notebook"),
        ("enter_notebook", "correction", "notebook"),
        ("open_notebook_capture", "notebook", "notebook_capture"),
        ("cancel_capture", "notebook_capture", "notebook"),
        ("retake_notebook_photo", "notebook_review", "notebook_capture"),
        # D7: arestas que a Spec Parte I §4 não escreve.
        ("request_reconstruction", "notebook_review", "correction"),
        ("enter_notebook", "notebook_review", "notebook"),
        ("close_session", "practice", "summary"),
        ("close_session", "source_capture", "summary"),
        # Fases que mantêm a fase.
        ("run_demo_step", "demonstration", "demonstration"),
        ("move_piece", "practice", "practice"),
        ("check_distribution", "practice", "practice"),
        ("request_help", "transfer", "transfer"),
        ("submit_explanation", "explanation", "explanation"),
    ],
)
def test_each_command_reaches_its_target_phase(command, phase, target):
    assert is_allowed_in(command, phase)
    assert next_phase(command, _facts(phase, kind="transfer", return_phase="practice")) == target


@pytest.mark.parametrize(
    "command,phase",
    [
        ("finish_demonstration", "practice"),
        ("run_demo_step", "practice"),
        ("move_piece", "demonstration"),
        ("move_piece", "notebook"),  # no caderno a cena não é manipulada
        ("move_piece", "summary"),
        ("submit_answer", "demonstration"),
        ("submit_answer", "explanation"),
        ("continue_after_explanation", "transfer"),
        ("enter_notebook", "explanation"),
        ("enter_notebook", "summary"),
        ("open_notebook_capture", "practice"),
        ("choose_reference_activity", "practice"),
    ],
)
def test_commands_outside_their_phases_are_not_allowed(command, phase):
    assert not is_allowed_in(command, phase)


def test_summary_accepts_only_session_control():
    allowed = {c for c in TRANSITIONS if is_allowed_in(c, "summary")}
    assert allowed == {"pause_session", "resume_session", "interrupt_turn", "close_session"}


def test_close_and_pause_are_allowed_in_every_phase():
    for phase in PHASES:
        assert is_allowed_in("close_session", phase) and is_allowed_in("pause_session", phase)


@pytest.mark.parametrize(
    "correct,phase,expected",
    [
        (True, "practice", "explanation"),
        (False, "practice", "practice"),
        (True, "transfer", "explanation"),
        (False, "transfer", "transfer"),
    ],
)
def test_submit_answer_depends_on_the_result(correct, phase, expected):
    assert next_phase("submit_answer", _facts(phase, correct=correct)) == expected


def test_return_to_activity_uses_checkpoint_or_attempt_kind():
    assert (
        next_phase("return_to_activity", _facts("notebook", return_phase="transfer")) == "transfer"
    )
    assert (
        next_phase("return_to_activity", _facts("notebook", return_phase="correction"))
        == "correction"
    )
    # D7: explanation -> prática se guiada, transfer se item novo.
    assert next_phase("return_to_activity", _facts("explanation", kind="guided")) == "practice"
    assert next_phase("return_to_activity", _facts("explanation", kind="transfer")) == "transfer"


def test_return_to_activity_without_checkpoint_is_invalid():
    with pytest.raises(DomainError) as e:
        next_phase("return_to_activity", _facts("notebook", return_phase=None))
    assert e.value.code == "INVALID_TRANSITION"


def test_continue_after_explanation_creates_transfer_or_summary():
    assert (
        next_phase("continue_after_explanation", _facts("explanation", kind="guided")) == "transfer"
    )
    assert (
        next_phase("continue_after_explanation", _facts("explanation", kind="transfer"))
        == "summary"
    )
