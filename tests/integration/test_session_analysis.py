"""Task 6: artefato do caderno e análise com supersessão, adiamento e reconciliação (AC-33, AC-37).

As jornadas são montadas por comandos reais pelo serviço (nenhum atalho de estado). O ator
`vision_worker` entrega o resultado; o serviço decide a disposição. SQLite e Postgres.
"""

import json
import uuid

import pytest
from app.db.schema import analysis_jobs, artifacts, command_results, observations
from app.domain.division.observation import NotebookObservation
from app.sessions.context import ActorContext
from app.sessions.errors import SessionError
from helpers import cmd, load_raw
from sqlalchemy import func, select
from test_session_commands import (
    SYSTEM,
    body_of,
    dump_tables,
    event_rows,
    send,
    start_practice,
    state_of,
)

WORKER = ActorContext("vision_worker", "vision_worker-service", None, None)
TUTOR = ActorContext("tutor", "tutor-service", None, None)


# --- apoio ---------------------------------------------------------------------------------------


def to_capture(svc):
    """Prática -> caderno -> captura, por comandos reais."""
    ctx, sid = start_practice(svc)
    send(svc, ctx, sid, cmd("enter_notebook", intent="try_on_paper"))
    send(svc, ctx, sid, cmd("open_notebook_capture"))
    assert state_of(svc, sid).phase == "notebook_capture"
    return ctx, sid


def submit(svc, ctx, sid, rid):
    state = state_of(svc, sid)
    return svc.submit_notebook_artifact(
        ctx,
        sid,
        request_id=rid,
        expected_revision=state.revision,
        attempt_id=state.active_attempt_id,
    )


def obs_for(sid, sub, svc, **over) -> NotebookObservation:
    """Observação sintética coerente com o artefato enviado."""
    raw = load_raw("observacao-5-5-5-5")
    raw.update(
        artifact_id=sub["artifact_id"],
        artifact_version=sub["artifact_version"],
        attempt_id=state_of(svc, sid).active_attempt_id,
        observation_id=f"worker-{sub['job_id']}",
    )
    raw.update(over)
    return NotebookObservation.model_validate(raw)


def obs_of(svc, sid, sub) -> NotebookObservation:
    with svc.engine.connect() as conn:
        attempt_id = conn.execute(
            select(artifacts.c.attempt_id).where(artifacts.c.artifact_id == sub["artifact_id"])
        ).scalar_one()
    return obs_for(sid, sub, svc, attempt_id=attempt_id)


def job_row(svc, job_id) -> dict:
    with svc.engine.connect() as conn:
        return dict(
            conn.execute(select(analysis_jobs).where(analysis_jobs.c.job_id == job_id))
            .mappings()
            .one()
        )


def job_status(svc, job_id) -> str:
    return job_row(svc, job_id)["status"]


def count(svc, table, sid) -> int:
    with svc.engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(table).where(table.c.session_id == sid)
        ).scalar_one()


def last_event_types(svc, sid, n) -> list[str]:
    return [e["type"] for e in event_rows(svc.engine, sid)][-n:]


def snapshot_of(svc, ctx, sid):
    return svc.get_snapshot(ctx, sid)


# --- AC-33 ---------------------------------------------------------------------------------------


@pytest.mark.ac("AC-33")
def test_ac33_slow_v1_does_not_overwrite_v2(svc):
    ctx, sid = to_capture(svc)
    v1 = submit(svc, ctx, sid, "up-1")
    assert v1["artifact_version"] == 1
    send(svc, ctx, sid, cmd("retake_notebook_photo"))
    assert job_status(svc, v1["job_id"]) == "superseded"  # a mesma transação do retake
    v2 = submit(svc, ctx, sid, "up-2")
    assert v2["artifact_version"] == 2
    assert v2["artifact_id"] != v1["artifact_id"] and v2["job_id"] != v1["job_id"]

    assert svc.complete_analysis(WORKER, v1["job_id"], obs_of(svc, sid, v1)) == "superseded"
    snap = snapshot_of(svc, ctx, sid)
    assert snap["analysis"]["artifact_id"] == v2["artifact_id"]
    assert snap["analysis"]["status"] == "pending"
    assert job_status(svc, v1["job_id"]) == "superseded"
    assert job_status(svc, v2["job_id"]) == "queued"

    assert svc.complete_analysis(WORKER, v2["job_id"], obs_of(svc, sid, v2)) == "applied"
    assert snapshot_of(svc, ctx, sid)["analysis"]["status"] == "available"
    assert job_row(svc, v2["job_id"])["applied"] is True


@pytest.mark.ac("AC-33")
def test_ac33_result_after_attempt_changed_is_superseded(svc):
    ctx, sid = to_capture(svc)
    v1 = submit(svc, ctx, sid, "up-1")
    obs = obs_of(svc, sid, v1)
    send(svc, ctx, sid, cmd("retake_notebook_photo"))
    send(svc, ctx, sid, cmd("cancel_capture"))
    send(svc, ctx, sid, cmd("return_to_activity"))
    send(svc, ctx, sid, cmd("submit_answer", answer=6))
    send(svc, ctx, sid, cmd("continue_after_explanation", reason="learner_skipped"))
    state = state_of(svc, sid)
    assert state.phase == "transfer" and state.active_attempt_id != obs.attempt_id

    before = dump_tables(svc.engine, sid)
    assert svc.complete_analysis(WORKER, v1["job_id"], obs) == "superseded"
    assert dump_tables(svc.engine, sid) == before
    assert job_status(svc, v1["job_id"]) == "superseded"
    assert count(svc, observations, sid) == 0
    assert snapshot_of(svc, ctx, sid)["analysis"] is None


def test_leaving_capture_supersedes_the_queued_job(svc):
    ctx, sid = to_capture(svc)
    v1 = submit(svc, ctx, sid, "up-1")
    send(svc, ctx, sid, cmd("enter_notebook", intent="revise_record"))
    assert job_status(svc, v1["job_id"]) == "superseded"
    assert svc.complete_analysis(WORKER, v1["job_id"], obs_of(svc, sid, v1)) == "superseded"


# --- AC-37 ---------------------------------------------------------------------------------------


@pytest.mark.ac("AC-37")
def test_ac37_paused_keeps_result_until_resume(svc):
    ctx, sid = to_capture(svc)
    sub = submit(svc, ctx, sid, "up-1")
    send(svc, ctx, sid, cmd("pause_session"))
    paused = state_of(svc, sid)
    r_paused = paused.revision
    events_before = len(event_rows(svc.engine, sid))

    assert svc.complete_analysis(WORKER, sub["job_id"], obs_of(svc, sid, sub)) == "deferred"
    assert svc.get_snapshot(ctx, sid)["revision"] == r_paused  # sem mudança nem evento
    assert len(event_rows(svc.engine, sid)) == events_before
    assert state_of(svc, sid).observation is None
    assert snapshot_of(svc, ctx, sid)["analysis"]["status"] == "pending"
    job = job_row(svc, sub["job_id"])
    assert job["status"] == "ready" and job["applied"] is False
    assert count(svc, observations, sid) == 1

    out = send(svc, ctx, sid, cmd("resume_session"))
    assert out.body["revision"] == r_paused + 1  # uma revisão (P7)
    assert last_event_types(svc, sid, 2) == ["session_resumed", "analysis_completed"]
    assert state_of(svc, sid).revision == r_paused + 1
    assert out.body["event_seq"] == state_of(svc, sid).last_event_seq
    events = event_rows(svc.engine, sid)[-2:]
    assert [e["event_seq"] for e in events] == [events_before + 1, events_before + 2]
    assert {e["revision"] for e in events} == {r_paused + 1}
    assert snapshot_of(svc, ctx, sid)["analysis"]["status"] == "available"
    assert job_row(svc, sub["job_id"])["applied"] is True
    # a retomada não reaplica nada: um segundo resultado do mesmo job é a disposição anterior
    assert svc.complete_analysis(WORKER, sub["job_id"], obs_of(svc, sid, sub)) == "applied"


def test_resume_without_pending_result_changes_nothing_else(svc):
    ctx, sid = to_capture(svc)
    submit(svc, ctx, sid, "up-1")
    send(svc, ctx, sid, cmd("pause_session"))
    r = state_of(svc, sid).revision
    out = send(svc, ctx, sid, cmd("resume_session"))
    assert out.body["revision"] == r + 1
    assert last_event_types(svc, sid, 1) == ["session_resumed"]
    assert state_of(svc, sid).observation is None


@pytest.mark.ac("AC-37")
def test_ac37_closed_session_ignores_late_result(svc):
    ctx, sid = to_capture(svc)
    sub = submit(svc, ctx, sid, "up-1")
    send(svc, ctx, sid, cmd("close_session", reason="learner_stopped"))
    before = dump_tables(svc.engine, sid)
    revision = state_of(svc, sid).revision

    assert svc.complete_analysis(WORKER, sub["job_id"], obs_of(svc, sid, sub)) == "discarded"
    assert dump_tables(svc.engine, sid) == before  # revisão e eventos iguais
    assert state_of(svc, sid).revision == revision
    job = job_row(svc, sub["job_id"])
    assert job["status"] == "ready" and job["applied"] is False
    assert svc.complete_analysis(WORKER, sub["job_id"], obs_of(svc, sid, sub)) == "discarded"


@pytest.mark.ac("AC-37")
def test_ac37_tutor_command_rejected_while_paused_or_closed(svc):
    ctx, sid = start_practice(svc)

    def tutor_highlight():
        return svc.execute_command(
            TUTOR, sid, body_of(state_of(svc, sid), cmd("highlight_group", actor="tutor"))
        )

    send(svc, ctx, sid, cmd("pause_session"))
    before = dump_tables(svc.engine, sid)
    with pytest.raises(SessionError) as paused:  # época vigente: falha por pausa, não por época
        tutor_highlight()
    assert paused.value.code == "ACTION_NOT_ALLOWED"
    assert dump_tables(svc.engine, sid) == before

    send(svc, ctx, sid, cmd("resume_session"))
    send(svc, ctx, sid, cmd("close_session", reason="learner_stopped"))
    before = dump_tables(svc.engine, sid)
    with pytest.raises(SessionError) as closed:
        tutor_highlight()
    assert closed.value.code == "ACTION_NOT_ALLOWED"
    assert dump_tables(svc.engine, sid) == before


# --- envio do artefato ---------------------------------------------------------------------------


def test_submit_artifact_replay_same_job(svc):
    ctx, sid = to_capture(svc)
    first = submit(svc, ctx, sid, "up-1")
    assert set(first) == {"artifact_id", "artifact_version", "job_id", "revision"}
    assert first["revision"] == state_of(svc, sid).revision
    before = dump_tables(svc.engine, sid)
    stale = svc.submit_notebook_artifact(
        ctx,
        sid,
        request_id="up-1",
        expected_revision=first["revision"] - 1,
        attempt_id=state_of(svc, sid).active_attempt_id,
    )
    assert stale == first  # replay: o mesmo dicionário, mesmo com a revisão esperada antiga
    assert submit_replay(svc, ctx, sid, first) == first
    assert dump_tables(svc.engine, sid) == before
    assert count(svc, artifacts, sid) == 1 and count(svc, analysis_jobs, sid) == 1
    assert [e["type"] for e in event_rows(svc.engine, sid)].count("artifact_submitted") == 1
    assert job_status(svc, first["job_id"]) == "queued"
    with pytest.raises(SessionError) as e:  # mesma chave, outro corpo
        svc.submit_notebook_artifact(
            ctx, sid, request_id="up-1", expected_revision=0, attempt_id="other"
        )
    assert e.value.code == "IDEMPOTENCY_CONFLICT"


def submit_replay(svc, ctx, sid, first):
    return svc.submit_notebook_artifact(
        ctx,
        sid,
        request_id="up-1",
        expected_revision=first["revision"] - 1,
        attempt_id=state_of(svc, sid).active_attempt_id,
    )


def test_submit_artifact_keeps_object_key_empty_and_runs_one_transaction(svc):
    ctx, sid = to_capture(svc)
    sub = submit(svc, ctx, sid, "up-1")
    with svc.engine.connect() as conn:
        art = conn.execute(select(artifacts)).mappings().one()
    assert art["object_key"] is None and art["purpose"] == "notebook"
    assert art["artifact_id"] == sub["artifact_id"] and art["version"] == 1
    state = state_of(svc, sid)
    assert state.phase == "notebook_review"
    assert state.active_artifact.job_id == sub["job_id"]
    assert event_rows(svc.engine, sid, "artifact_submitted")[-1]["actor"] == "learner"


@pytest.mark.parametrize(
    ("who", "code"),
    [("worker", "ACTION_NOT_ALLOWED"), ("tutor", "ACTION_NOT_ALLOWED")],
)
def test_only_the_learner_submits(svc, who, code):
    _ctx, sid = to_capture(svc)
    state = state_of(svc, sid)
    before = dump_tables(svc.engine, sid)
    with pytest.raises(SessionError) as e:
        svc.submit_notebook_artifact(
            {"worker": WORKER, "tutor": TUTOR}[who],
            sid,
            request_id="up-1",
            expected_revision=state.revision,
            attempt_id=state.active_attempt_id,
        )
    assert e.value.code == code
    assert dump_tables(svc.engine, sid) == before


def test_submit_requires_the_current_controller(svc):
    _ctx, sid = to_capture(svc)
    state = state_of(svc, sid)
    other = ActorContext("learner", sid, sid, "another-tab-controller")
    with pytest.raises(SessionError) as e:
        svc.submit_notebook_artifact(
            other, sid, request_id="up-1", expected_revision=state.revision,
            attempt_id=state.active_attempt_id,
        )  # fmt: skip
    assert e.value.code == "CONTROL_LOST"
    assert count(svc, artifacts, sid) == 0


def test_submit_rejects_stale_revision_wrong_attempt_and_wrong_phase(svc):
    ctx, sid = to_capture(svc)
    state = state_of(svc, sid)
    cases = [
        (state.revision - 1, state.active_attempt_id, "STALE_REVISION"),
        (state.revision, "not-the-attempt", "ATTEMPT_CHANGED"),
    ]
    for revision, attempt_id, code in cases:
        with pytest.raises(SessionError) as e:
            svc.submit_notebook_artifact(
                ctx, sid, request_id="up-x", expected_revision=revision, attempt_id=attempt_id
            )
        assert e.value.code == code
    assert count(svc, artifacts, sid) == 0 and count(svc, analysis_jobs, sid) == 0
    assert count(svc, command_results, sid) == state.revision  # nada novo gravado

    ctx2, sid2 = start_practice(svc, 2)  # fora da captura
    st2 = state_of(svc, sid2)
    with pytest.raises(SessionError) as e:
        svc.submit_notebook_artifact(
            ctx2, sid2, request_id="up-1", expected_revision=st2.revision,
            attempt_id=st2.active_attempt_id,
        )  # fmt: skip
    assert e.value.code == "INVALID_TRANSITION"
    assert count(svc, artifacts, sid2) == 0


def test_foreign_session_token_cannot_submit(svc):
    _ctx, sid = to_capture(svc)
    other_ctx, _other_sid = start_practice(svc, 2)
    state = state_of(svc, sid)
    with pytest.raises(SessionError) as e:
        svc.submit_notebook_artifact(
            other_ctx, sid, request_id="up-1", expected_revision=state.revision,
            attempt_id=state.active_attempt_id,
        )  # fmt: skip
    assert e.value.code == "NOT_FOUND"


# --- resultado da análise ------------------------------------------------------------------------


def test_complete_analysis_twice_is_idempotent(svc):
    ctx, sid = to_capture(svc)
    sub = submit(svc, ctx, sid, "up-1")
    obs = obs_of(svc, sid, sub)
    assert svc.complete_analysis(WORKER, sub["job_id"], obs) == "applied"
    after_first = dump_tables(svc.engine, sid)
    assert svc.complete_analysis(WORKER, sub["job_id"], obs) == "applied"
    assert dump_tables(svc.engine, sid) == after_first
    assert count(svc, observations, sid) == 1
    assert [e["type"] for e in event_rows(svc.engine, sid)].count("analysis_completed") == 1


def test_only_vision_worker_completes(svc):
    ctx, sid = to_capture(svc)
    sub = submit(svc, ctx, sid, "up-1")
    obs = obs_of(svc, sid, sub)
    before = dump_tables(svc.engine, sid)
    for actor in (ctx, TUTOR, SYSTEM):
        with pytest.raises(SessionError) as e:
            svc.complete_analysis(actor, sub["job_id"], obs)
        assert e.value.code == "ACTION_NOT_ALLOWED"
    assert dump_tables(svc.engine, sid) == before
    assert job_status(svc, sub["job_id"]) == "queued"


def test_complete_analysis_unknown_job_is_not_found(svc):
    ctx, sid = to_capture(svc)
    sub = submit(svc, ctx, sid, "up-1")
    with pytest.raises(SessionError) as e:
        svc.complete_analysis(WORKER, "job_does_not_exist", obs_of(svc, sid, sub))
    assert e.value.code == "NOT_FOUND"


def test_needs_clarification_sets_the_job_status(svc):
    ctx, sid = to_capture(svc)
    sub = submit(svc, ctx, sid, "up-1")
    raw = load_raw("observacao-ambigua")
    state = state_of(svc, sid)
    raw.update(
        artifact_id=sub["artifact_id"],
        artifact_version=sub["artifact_version"],
        attempt_id=state.active_attempt_id,
    )
    obs = NotebookObservation.model_validate(raw)
    assert obs.status == "needs_clarification"
    assert svc.complete_analysis(WORKER, sub["job_id"], obs) == "applied"
    job = job_row(svc, sub["job_id"])
    assert job["status"] == "needs_clarification" and job["applied"] is True
    assert job["executions"] == 1


def test_incoherent_observation_is_rejected_without_effect(svc):
    ctx, sid = to_capture(svc)
    sub = submit(svc, ctx, sid, "up-1")
    bad = obs_for(sid, sub, svc, artifact_id="some-other-artifact")
    before = dump_tables(svc.engine, sid)
    with pytest.raises(SessionError) as e:
        svc.complete_analysis(WORKER, sub["job_id"], bad)
    assert e.value.code == "INVALID_PAYLOAD"
    assert dump_tables(svc.engine, sid) == before
    assert job_status(svc, sub["job_id"]) == "queued"
    assert count(svc, observations, sid) == 0


def test_observation_id_is_server_assigned_opaque_uuid(svc):
    ctx, sid = to_capture(svc)
    sub = submit(svc, ctx, sid, "up-1")
    obs = obs_for(sid, sub, svc, observation_id="free-text-from-the-worker")
    assert svc.complete_analysis(WORKER, sub["job_id"], obs) == "applied"
    event = event_rows(svc.engine, sid, "analysis_completed")[0]
    observation_id = event["data"]["observation_id"]
    assert str(uuid.UUID(observation_id)) == observation_id
    assert observation_id != "free-text-from-the-worker"
    with svc.engine.connect() as conn:
        stored = conn.execute(select(observations)).mappings().one()
    assert stored["observation_id"] == observation_id
    document = stored["document"]
    document = json.loads(document) if isinstance(document, str) else document
    assert document["observation_id"] == observation_id
    assert state_of(svc, sid).observation.observation_id == observation_id
