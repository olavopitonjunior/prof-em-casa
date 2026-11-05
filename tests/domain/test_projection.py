"""Projeção pública de eventos (Task 3): o que a tela da criança vê versus o que o serviço guarda.

As jornadas rodam comandos reais (`helpers.apply`); nenhum evento é montado à mão. Os eventos
viram `EventRecord` sintéticos só para exercitar `project_event`.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import get_args

import pytest
from app.domain.division.analysis import apply_analysis_result
from app.domain.division.demonstration import demo_steps
from app.domain.division.session import new_session, public_snapshot
from app.domain.division.state import DomainEvent, EventType
from app.sessions.projection import (
    FORBIDDEN_LEARNER_KEYS,
    LEARNER_EVENT_FIELDS,
    LEARNER_EXCLUDED_FIELDS,
    EventRecord,
    project_event,
    session_view,
)
from helpers import (
    CONTENT,
    T12_4,
    StubEvaluator,
    apply,
    cmd,
    result_for,
    session_in_practice,
    session_in_transfer,
)

# --- jornadas reais ------------------------------------------------------------------------------


class _Journey:
    """Aplica comandos reais e acumula os eventos que eles emitem."""

    def __init__(self, session=None, *, evaluator=None):
        self.session = session or new_session("proj")
        self.events: list[DomainEvent] = []
        self.evaluator = evaluator

    def do(self, command):
        result = apply(self.session, command, evaluator=self.evaluator)
        self.session = result.session
        self.events += result.events
        return result

    def analysis(self, job_id, artifact_id, version=1):
        result = result_for(job_id, artifact_id, version, attempt_id=self.session.active_attempt_id)
        applied = apply_analysis_result(self.session, result, content=CONTENT).result
        self.session = applied.session
        self.events += applied.events

    def submit_artifact(self, artifact_id, job_id, version=1):
        from app.domain.division.analysis import submit_artifact

        result = submit_artifact(
            self.session,
            attempt_id=self.session.active_attempt_id,
            artifact_id=artifact_id,
            artifact_version=version,
            job_id=job_id,
        )
        self.session = result.session
        self.events += result.events


def _demo(j: _Journey, steps: int = 12) -> None:
    j.do(cmd("choose_reference_activity"))
    for step in demo_steps(T12_4, 3)[:steps]:
        j.do(cmd("run_demo_step", actor="system", step_id=step.step_id))


def journey_full_session():
    """Demonstração completa, prática com ajuda e caderno, resposta certa, transferência até o fim."""
    j = _Journey()
    _demo(j)
    j.do(cmd("finish_demonstration", actor="system", reason="completed"))
    for n in range(1, 5):
        j.do(
            cmd(
                "move_piece",
                piece_id=f"piece-{n:02d}",
                from_location="available",
                to_location="group-1",
            )
        )
    j.do(cmd("check_distribution"))
    j.do(cmd("request_help", kind="prompt", reason="preciso de uma pista"))
    j.do(cmd("request_help", kind="virtual_objects", reason="quero ver as peças"))
    j.do(cmd("enter_notebook", intent="try_on_paper"))
    j.do(cmd("return_to_activity"))
    j.do(cmd("submit_answer", answer=6, explanation="seis em cada grupo"))
    j.do(cmd("submit_explanation", text="4 grupos de 6 dão 24"))
    j.do(cmd("continue_after_explanation", reason="sufficient"))
    j.do(cmd("request_help", kind="virtual_objects", reason="preciso das peças"))
    j.do(cmd("submit_answer", answer=4, explanation=None))
    j.do(cmd("continue_after_explanation", reason="learner_skipped"))
    j.do(cmd("close_session", reason="completed"))
    return j.events


def journey_early_demo_exit_and_wrong_answers():
    j = _Journey(evaluator=StubEvaluator("unclear"))
    _demo(j, 4)
    j.do(cmd("finish_demonstration", reason="learner_requested"))
    j.do(cmd("submit_answer", answer=5, explanation="não sei"))
    j.do(cmd("submit_answer", answer=7, explanation=None))
    j.do(cmd("pause_session"))
    j.do(cmd("resume_session"))
    j.do(cmd("close_session", reason="learner_stopped"))
    return j.events


def journey_notebook_capture_and_revision():
    """Foto pendente reenviada, análise concluída, revisão do registro e saída pelo fluxo."""
    j = _Journey(session_in_practice())
    j.do(cmd("enter_notebook", intent="record_solution"))
    j.do(cmd("open_notebook_capture"))
    j.do(cmd("cancel_capture"))
    j.do(cmd("open_notebook_capture"))
    j.submit_artifact("art-1", "job-1")
    j.do(cmd("retake_notebook_photo"))  # pendente: analysis_superseded(retake)
    j.submit_artifact("art-2", "job-2")
    j.analysis("job-2", "art-2")  # analysis_completed
    j.do(cmd("enter_notebook", intent="revise_record"))
    j.do(cmd("open_notebook_capture"))
    j.submit_artifact("art-3", "job-3")
    j.do(cmd("pause_session"))
    j.do(cmd("close_session", reason="learner_stopped"))  # analysis_superseded(session_closed)
    return j.events


def journey_leaving_the_flow_with_a_pending_photo():
    j = _Journey(session_in_practice())
    j.do(cmd("enter_notebook", intent="record_solution"))
    j.do(cmd("open_notebook_capture"))
    j.submit_artifact("art-1", "job-1")
    j.do(cmd("enter_notebook", intent="revise_record"))  # revise_record
    j.do(cmd("return_to_activity"))
    j.do(cmd("submit_answer", answer=6, explanation=None))
    j.do(cmd("continue_after_explanation", reason="learner_skipped"))  # attempt_changed ou nada
    return j.events


def transfer_correct():
    j = _Journey(session_in_transfer())
    j.do(cmd("submit_answer", answer=4, explanation="4 em cada"))
    j.do(cmd("continue_after_explanation", reason="learner_skipped"))
    return j.events


def transfer_wrong():
    j = _Journey(session_in_transfer())
    j.do(cmd("submit_answer", answer=5, explanation="5 em cada"))
    j.do(cmd("request_help", kind="virtual_objects", reason="não achei"))
    return j.events


ALL_DOMAIN_JOURNEYS: list[Callable[[], list[DomainEvent]]] = [
    journey_full_session,
    journey_early_demo_exit_and_wrong_answers,
    journey_notebook_capture_and_revision,
    journey_leaving_the_flow_with_a_pending_photo,
]

# Nenhum handler emite estes dois (dispute/clarify ainda não têm handler); a lista de permitidos
# os cobre com `{}` até lá.
_NOT_EMITTED_YET = {"observation_disputed", "observation_clarified"}


def records(events: list[DomainEvent], *, session_id="proj") -> list[EventRecord]:
    return [
        EventRecord(
            event_id=f"ev-{i}",
            session_id=session_id,
            event_seq=i,
            revision=i,
            type=e.type,
            actor="learner",
            command_id=f"cmd-{i}",
            attempt_id=e.attempt_id,
            occurred_at=datetime(2026, 11, 5, tzinfo=UTC),
            data=e.data,
        )
        for i, e in enumerate(events, start=1)
    ]


def _all_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _all_keys(v)}
    if isinstance(value, list | tuple):
        return {k for v in value for k in _all_keys(v)}
    return set()


def _strip_ids(projected: dict) -> dict:
    return {k: v for k, v in projected.items() if k not in {"event_id", "event_seq", "revision"}}


ALL_JOURNEYS = [*ALL_DOMAIN_JOURNEYS, transfer_correct, transfer_wrong]


def _emitted() -> list[DomainEvent]:
    return [e for journey in ALL_JOURNEYS for e in journey()]


# --- a projeção da criança ----------------------------------------------------------------------


@pytest.mark.parametrize("journey", ALL_JOURNEYS, ids=lambda f: f.__name__)
def test_learner_projection_never_contains_forbidden_keys(journey):
    for record in records(journey()):
        assert not (_all_keys(project_event(record, "learner")) & FORBIDDEN_LEARNER_KEYS)


@pytest.mark.parametrize("journey", ALL_JOURNEYS, ids=lambda f: f.__name__)
def test_learner_projection_serialized_has_no_secret_values(journey):
    # O quociente e o texto livre da criança não aparecem nem como valor.
    text = json.dumps([project_event(r, "learner") for r in records(journey())])
    for secret in ("preciso de uma pista", "seis em cada grupo", "não sei", "não achei"):
        assert secret not in text


def test_correct_and_wrong_answers_project_identically():
    def submit(answer):
        j = _Journey(session_in_practice())
        j.do(cmd("submit_answer", answer=answer, explanation="porque sim"))
        return [_strip_ids(project_event(r, "learner")) for r in records(j.events)]

    right, wrong = submit(6), submit(5)
    assert [e["type"] for e in right] == [
        "answer_submitted",
        "explanation_evaluated",
        "attempt_evaluated",
    ]
    assert right == wrong


def test_the_rating_of_an_explanation_never_reaches_the_learner():
    for rating in ("sufficient", "partial", "unclear"):
        j = _Journey(session_in_practice(), evaluator=StubEvaluator(rating))
        j.do(cmd("submit_answer", answer=6, explanation="porque sim"))
        evaluated = [r for r in records(j.events) if r.type == "explanation_evaluated"]
        assert project_event(evaluated[0], "learner")["data"] == {"modality": "text"}


def test_analysis_completed_hides_verification_and_issues():
    completed = [r for r in records(_emitted()) if r.type == "analysis_completed"]
    assert completed
    for record in completed:
        assert {"verification_status", "issues"} <= set(record.data)  # estão no dado do serviço
        assert set(project_event(record, "learner")["data"]) == {
            "artifact_id",
            "artifact_version",
            "observation_id",
        }


def test_learner_envelope_has_no_actor_or_command_id():
    record = records(transfer_correct())[0]
    projected = project_event(record, "learner")
    assert set(projected) == {
        "event_id",
        "event_seq",
        "revision",
        "type",
        "attempt_id",
        "occurred_at",
        "data",
    }
    assert projected["event_id"] == record.event_id
    assert projected["occurred_at"] == record.occurred_at.isoformat()


def test_help_granted_keeps_levels_and_drops_the_free_text_reason():
    helps = [r for r in records(_emitted()) if r.type == "help_granted"]
    assert helps
    for record in helps:
        assert "reason" in record.data
        assert set(project_event(record, "learner")["data"]) == {
            "kind",
            "assistance_level",
            "support_resources",
        }


def test_distribution_checked_keeps_every_scene_fact():
    checked = [r for r in records(_emitted()) if r.type == "distribution_checked"]
    assert checked
    for record in checked:
        assert project_event(record, "learner")["data"] == record.data


def test_analysis_superseded_exposes_the_reason_code_but_not_the_job():
    superseded = [r for r in records(_emitted()) if r.type == "analysis_superseded"]
    assert {r.data["reason"] for r in superseded} >= {"retake", "session_closed", "revise_record"}
    for record in superseded:
        assert project_event(record, "learner")["data"] == {
            "artifact_id": record.data["artifact_id"],
            "reason": record.data["reason"],
        }


# --- a lista de permitidos ----------------------------------------------------------------------


def test_every_event_type_has_an_explicit_rule():
    assert set(get_args(EventType)) | {"control_claimed"} == set(LEARNER_EVENT_FIELDS)
    assert set(LEARNER_EXCLUDED_FIELDS) <= set(LEARNER_EVENT_FIELDS)


def test_allowed_and_excluded_fields_never_overlap_and_are_never_forbidden():
    for etype, allowed in LEARNER_EVENT_FIELDS.items():
        excluded = LEARNER_EXCLUDED_FIELDS.get(etype, frozenset())
        assert not (allowed & excluded), etype
        assert not (allowed & FORBIDDEN_LEARNER_KEYS), etype


def test_every_emitted_key_is_allowlisted_or_deliberately_excluded():
    """Uma chave nova num handler não vaza por omissão: este teste falha até alguém decidir."""
    emitted = _emitted()
    seen_types = {e.type for e in emitted}
    assert seen_types == set(get_args(EventType)) - _NOT_EMITTED_YET
    keys_by_type: dict[str, set[str]] = {}
    for event in emitted:
        keys_by_type.setdefault(event.type, set()).update(event.data)
    for etype, keys in keys_by_type.items():
        decided = LEARNER_EVENT_FIELDS[etype] | LEARNER_EXCLUDED_FIELDS.get(etype, frozenset())
        assert keys <= decided, f"{etype}: chave sem decisão {sorted(keys - decided)}"


def test_a_new_key_is_dropped_from_the_learner_projection():
    record = records(transfer_correct())[0]
    leaky = EventRecord(**{**record.__dict__, "data": {**record.data, "novo_campo": 1}})
    assert "novo_campo" not in project_event(leaky, "learner")["data"]
    assert project_event(leaky, "service")["data"]["novo_campo"] == 1


def test_unknown_event_type_projects_empty_data():
    record = records(transfer_correct())[0]
    unknown = EventRecord(**{**record.__dict__, "type": "tipo_futuro", "data": {"x": 1}})
    assert project_event(unknown, "learner")["data"] == {}


def test_control_claimed_exposes_only_the_control_counters():
    record = records(transfer_correct())[0]
    claimed = EventRecord(
        **{
            **record.__dict__,
            "type": "control_claimed",
            "data": {"connection_generation": 2, "turn_epoch": 3, "internal": "x"},
        }
    )
    assert project_event(claimed, "learner")["data"] == {
        "connection_generation": 2,
        "turn_epoch": 3,
    }


# --- audiência do serviço e visão de sessão -----------------------------------------------------


def test_service_audience_keeps_full_data_actor_and_command_id():
    for record in records(_emitted()):
        projected = project_event(record, "service")
        assert projected["data"] == record.data
        assert projected["actor"] == record.actor
        assert projected["command_id"] == record.command_id
        assert projected["type"] == record.type


def test_projection_does_not_alias_or_mutate_the_event_data():
    record = records(transfer_wrong())[-1]
    before = json.dumps(record.data, sort_keys=True)
    project_event(record, "service")["data"].clear()
    project_event(record, "learner")["data"].clear()
    assert json.dumps(record.data, sort_keys=True) == before


def test_session_view_is_the_public_snapshot_plus_the_connection_generation():
    s = session_in_transfer()
    view = session_view(s, CONTENT, connection_generation=7)
    assert view == public_snapshot(s, CONTENT) | {"connection_generation": 7}
    assert "connection_generation" not in public_snapshot(s, CONTENT)
