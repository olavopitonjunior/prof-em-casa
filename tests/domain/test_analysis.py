"""Fluxo de captura do caderno: submit_artifact, apply_analysis_result e os 3 comandos (AC-33)."""

import json
import re
from pathlib import Path

import pytest
from app.domain.division.analysis import AnalysisResult, apply_analysis_result, submit_artifact
from app.domain.division.errors import DomainError
from app.domain.division.session import SessionState, public_snapshot
from helpers import (
    CONTENT,
    GUIDED_ID,
    apply,
    cmd,
    in_notebook_capture,
    in_review,
    load_obs,
    obs_with,
    result_for,
    run,
    session_in_practice,
    session_in_transfer,
    submitted,
)

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "services/backend/app/domain"


def _submit(s, **over):
    args = {
        "attempt_id": s.active_attempt_id,
        "artifact_id": "art-1",
        "artifact_version": 1,
        "job_id": "job-1",
    }
    return submit_artifact(s, **{**args, **over})


def _code(fn, *a, **kw) -> str:
    with pytest.raises(DomainError) as e:
        fn(*a, **kw)
    return e.value.code


def _paused(s):
    return run(s, cmd("pause_session"))


def _closed(s):
    return run(s, cmd("close_session"))


# --- comandos de captura ------------------------------------------------------------------------


def test_open_and_cancel_capture_move_phase_without_events():
    n = run(session_in_practice(), cmd("enter_notebook", intent="record_solution"))
    opened = apply(n, cmd("open_notebook_capture"))
    assert opened.session.phase == "notebook_capture" and opened.events == ()
    assert opened.session.revision == n.revision + 1
    back = apply(opened.session, cmd("cancel_capture"))
    assert back.session.phase == "notebook" and back.events == ()
    assert back.session.return_phase == "practice"  # o checkpoint sobrevive ao cancelamento
    assert run(back.session, cmd("return_to_activity")).phase == "practice"


def test_open_capture_is_only_allowed_in_notebook():
    assert _code(apply, session_in_practice(), cmd("open_notebook_capture")) == "INVALID_TRANSITION"


def test_capture_flow_reaches_review():
    s = in_notebook_capture()
    r = submit_artifact(
        s, attempt_id=s.active_attempt_id, artifact_id="art-1", artifact_version=1, job_id="job-1"
    )
    assert r.session.phase == "notebook_review" and r.session.revision == s.revision + 1
    assert [e.type for e in r.events] == ["artifact_submitted"]
    assert r.events[0].data == {"artifact_id": "art-1", "artifact_version": 1, "job_id": "job-1"}
    assert r.events[0].attempt_id == s.active_attempt_id
    assert r.session.last_event_seq == s.last_event_seq + 1
    assert (r.session.active_artifact.artifact_id, r.session.active_artifact.job_id) == (
        "art-1",
        "job-1",
    )
    assert r.scene_changed is False
    assert s.phase == "notebook_capture" and s.active_artifact is None  # entrada intacta


def test_submit_artifact_guards():
    s = in_notebook_capture()
    assert _code(_submit, s, attempt_id="outra") == "ATTEMPT_CHANGED"
    assert _code(_submit, session_in_practice()) == "INVALID_TRANSITION"
    assert _code(_submit, in_review()) == "INVALID_TRANSITION"
    assert _code(_submit, _closed(s)) == "ACTION_NOT_ALLOWED"
    with pytest.raises(ValueError):  # versão do artefato começa em 1
        _submit(s, artifact_version=0)


def test_submit_while_paused_is_accepted_and_keeps_the_pause():
    r = _submit(_paused(in_notebook_capture()))
    assert r.session.session_status == "paused" and r.session.phase == "notebook_review"


def test_retake_of_a_pending_analysis_emits_one_superseded_and_clears():
    review = in_review()
    r = apply(review, cmd("retake_notebook_photo"))
    assert r.session.phase == "notebook_capture"
    assert [e.type for e in r.events] == ["analysis_superseded"]
    assert r.events[0].data == {"artifact_id": "art-1", "job_id": "job-1", "reason": "retake"}
    assert r.session.active_artifact is None
    assert r.session.observation is None and r.session.verification is None
    assert r.session.revision == review.revision + 1
    assert r.session.last_event_seq == review.last_event_seq + 1


def test_retake_after_the_analysis_completed_clears_without_an_event():  # R26
    reviewed = _reviewed()
    assert reviewed.observation is not None and reviewed.verification is not None
    r = apply(reviewed, cmd("retake_notebook_photo"))
    assert r.session.phase == "notebook_capture" and r.events == ()
    assert r.session.active_artifact is None
    assert r.session.observation is None and r.session.verification is None
    assert r.session.revision == reviewed.revision + 1
    assert r.session.last_event_seq == reviewed.last_event_seq


def _reviewed():
    app = apply_analysis_result(in_review(), result_for("job-1", "art-1", 1), content=CONTENT)
    return app.result.session


def test_retake_without_active_artifact_emits_nothing():
    s = in_review().with_changes(active_artifact=None)
    r = apply(s, cmd("retake_notebook_photo"))
    assert r.events == () and r.session.phase == "notebook_capture"


def test_retake_is_only_allowed_in_review():
    assert _code(apply, in_notebook_capture(), cmd("retake_notebook_photo")) == "INVALID_TRANSITION"


# --- AC-33: só a última foto vale ---------------------------------------------------------------


def with_v2_submitted():
    """v1 enviado -> retake_notebook_photo -> v2 enviado."""
    retaken = run(in_review(), cmd("retake_notebook_photo"))
    return submitted(retaken, "art-2", 2, "job-2")


@pytest.mark.ac("AC-33")
def test_ac33_v1_result_after_v2_submitted_is_superseded():
    v2 = with_v2_submitted()
    app = apply_analysis_result(v2, result_for("job-1", "art-1", 1), content=CONTENT)
    assert app.disposition == "superseded" and app.result is None
    assert v2.observation is None and v2.verification is None
    assert public_snapshot(v2, CONTENT)["analysis"] == {
        "artifact_id": "art-2",
        "artifact_version": 2,
        "status": "pending",
    }


@pytest.mark.ac("AC-33")
def test_ac33_v2_result_is_applied_after_v1_was_superseded():
    v2 = with_v2_submitted()
    app = apply_analysis_result(v2, result_for("job-2", "art-2", 2), content=CONTENT)
    assert app.disposition == "applied"
    assert app.result.session.active_artifact.artifact_id == "art-2"


@pytest.mark.parametrize(
    "over",
    [
        {"artifact_id": "art-9"},
        {"job_id": "job-9"},
        {"artifact_version": 2},
    ],
)
def test_result_with_any_other_identity_is_superseded(over):
    args = {"job_id": "job-1", "artifact_id": "art-1", "version": 1}
    args.update({("version" if k == "artifact_version" else k): v for k, v in over.items()})
    app = apply_analysis_result(in_review(), result_for(**args), content=CONTENT)
    assert app.disposition == "superseded" and app.result is None


def _in_transfer_after_a_guided_photo():
    """Foto da tentativa guiada enviada; a criança revisa, volta, acerta e chega à questão nova."""
    s = apply_analysis_result(in_review(), result_for("job-1", "art-1", 1), content=CONTENT)
    s = run(s.result.session, cmd("enter_notebook", intent="revise_record"))
    s = run(s, cmd("return_to_activity"))
    assert s.phase == "practice"
    s = run(s, cmd("submit_answer", answer=6))
    return run(s, cmd("continue_after_explanation", reason="learner_skipped"))


@pytest.mark.ac("AC-33")
def test_ac33_result_for_changed_attempt_is_superseded():
    s = _in_transfer_after_a_guided_photo()
    assert s.phase == "transfer"
    guided_id = s.attempts[1].attempt_id
    app = apply_analysis_result(
        s, result_for("job-1", "art-1", 1, attempt_id=guided_id), content=CONTENT
    )
    assert app.disposition == "superseded" and app.result is None


def test_new_attempt_does_not_inherit_the_guided_photo():
    s = _in_transfer_after_a_guided_photo()
    assert s.active_artifact is None and s.observation is None and s.verification is None
    assert public_snapshot(s, CONTENT)["analysis"] is None


# --- pausa, fechamento e aplicação --------------------------------------------------------------


def test_paused_result_is_deferred():
    s = _paused(in_review())
    app = apply_analysis_result(s, result_for("job-1", "art-1", 1), content=CONTENT)
    assert app.disposition == "deferred" and app.result is None
    assert s.observation is None  # estado igual: a sessão aplica na retomada


def test_closed_result_is_discarded():
    app = apply_analysis_result(
        _closed(in_review()), result_for("job-1", "art-1", 1), content=CONTENT
    )
    assert app.disposition == "discarded" and app.result is None


def test_closed_takes_precedence_over_superseded():
    app = apply_analysis_result(
        _closed(in_review()), result_for("job-9", "art-9", 1), content=CONTENT
    )
    assert app.disposition == "discarded"


def test_superseded_takes_precedence_over_deferred():
    app = apply_analysis_result(
        _paused(in_review()), result_for("job-9", "art-9", 1), content=CONTENT
    )
    assert app.disposition == "superseded"


def test_applied_result_records_verification_without_quotient():
    review = in_review()
    app = apply_analysis_result(
        review,
        result_for("job-1", "art-1", 1, obs=load_obs("observacao-5-5-5-5")),
        content=CONTENT,
    )
    assert app.disposition == "applied"
    out = app.result.session
    assert out.verification.status == "inconsistent"
    assert out.observation.observation_id == "obs-001"
    assert out.phase == "notebook_review"
    assert out.revision == review.revision + 1
    assert out.last_event_seq == review.last_event_seq + 1
    (event,) = app.result.events
    assert event.type == "analysis_completed"
    assert event.data == {
        "job_id": "job-1",
        "artifact_id": "art-1",
        "artifact_version": 1,
        "observation_id": "obs-001",
        "verification_status": "inconsistent",
        "issues": list(out.verification.issues),
        "reconstruction_allowed": out.verification.reconstruction_allowed,
    }
    assert "quotient" not in json.dumps(event.model_dump(mode="json"))
    snap = public_snapshot(out, CONTENT)
    assert "quotient" not in json.dumps(snap)
    assert snap["analysis"] == {
        "artifact_id": "art-1",
        "artifact_version": 1,
        "status": "available",
    }
    assert "issues" not in json.dumps(snap) and "facts" not in json.dumps(snap)
    assert "obs-001" not in json.dumps(snap)  # a observação inteira também não sai
    assert review.observation is None  # entrada intacta


def test_ambiguous_observation_is_recorded_as_inconclusive():
    app = apply_analysis_result(
        in_review(),
        result_for("job-1", "art-1", 1, obs=load_obs("observacao-ambigua")),
        content=CONTENT,
    )
    assert app.disposition == "applied"
    assert app.result.session.verification.status == "inconclusive"  # R8
    assert app.result.session.verification.reconstruction_allowed is False  # R12


def test_consistent_observation_is_applied():
    obs = obs_with(counts=[6, 6, 6, 6], dividend=24, divisor=4, answer=6)
    app = apply_analysis_result(
        in_review(), result_for("job-1", "art-1", 1, obs=obs), content=CONTENT
    )
    assert app.result.session.verification.status == "consistent"


def test_bump_revision_false_keeps_revision():
    review = in_review()
    app = apply_analysis_result(
        review, result_for("job-1", "art-1", 1), content=CONTENT, bump_revision=False
    )
    assert app.disposition == "applied"
    assert app.result.session.revision == review.revision
    assert app.result.session.last_event_seq == review.last_event_seq + 1  # o evento existe


def test_state_with_observation_survives_a_json_round_trip():
    out = apply_analysis_result(
        in_review(), result_for("job-1", "art-1", 1), content=CONTENT
    ).result.session
    again = SessionState.model_validate(json.loads(json.dumps(out.model_dump(mode="json"))))
    assert again == out


def test_analysis_result_rejects_unknown_fields_and_bad_version():
    base = result_for("job-1", "art-1", 1).model_dump(mode="json")
    with pytest.raises(ValueError):
        AnalysisResult.model_validate({**base, "extra": 1})
    with pytest.raises(ValueError):
        AnalysisResult.model_validate({**base, "artifact_version": 0})


# --- R23/R26: abandonar um artefato pendente emite exatamente um analysis_superseded -----------


def _revising_pending():
    """Foto enviada, análise pendente; a criança volta ao caderno (revise_record) e a abandona."""
    return run(in_review(), cmd("enter_notebook", intent="revise_record"))


def _pending_artifact(s, **over):
    """Estado montado à mão com um artefato ainda pendente (nenhuma análise aplicada)."""
    artifact = {"artifact_id": "art-1", "artifact_version": 1, "job_id": "job-1"}
    return s.with_changes(active_artifact={**artifact, **over})


def test_revise_record_drops_a_pending_artifact_with_one_event():  # R27
    review = in_review()
    r = apply(review, cmd("enter_notebook", intent="revise_record"))
    assert r.session.phase == "notebook"
    assert [e.type for e in r.events] == ["notebook_entered", "analysis_superseded"]
    assert r.events[1].data == {
        "artifact_id": "art-1",
        "job_id": "job-1",
        "reason": "revise_record",
    }
    assert r.session.active_artifact is None
    assert r.session.last_event_seq == review.last_event_seq + 2


def test_r23_recapture_supersedes_a_leftover_pending_artifact():
    leftover = _pending_artifact(in_review().with_changes(phase="notebook"))
    r = apply(leftover, cmd("open_notebook_capture"))
    assert r.session.phase == "notebook_capture"
    assert [e.type for e in r.events] == ["analysis_superseded"]
    assert r.events[0].data == {"artifact_id": "art-1", "job_id": "job-1", "reason": "recapture"}
    assert r.session.active_artifact is None
    assert r.session.observation is None and r.session.verification is None
    assert r.session.last_event_seq == leftover.last_event_seq + 1


@pytest.mark.ac("AC-33")
def test_r23_late_result_for_the_recaptured_artifact_is_superseded():
    recaptured = run(_revising_pending(), cmd("open_notebook_capture"))
    late = result_for("job-1", "art-1", 1)
    assert apply_analysis_result(recaptured, late, content=CONTENT).disposition == "superseded"
    v2 = submitted(recaptured, "art-2", 2, "job-2")
    app = apply_analysis_result(v2, late, content=CONTENT)
    assert app.disposition == "superseded" and app.result is None


def test_r23_recapture_after_the_analysis_completed_clears_without_an_event():
    reviewed = run(_reviewed(), cmd("enter_notebook", intent="revise_record"))
    assert reviewed.observation is not None
    r = apply(reviewed, cmd("open_notebook_capture"))
    assert r.events == ()
    assert r.session.active_artifact is None and r.session.observation is None
    assert r.session.verification is None


def test_cancel_capture_after_recapture_has_no_artifact_to_lose():
    capture = run(_revising_pending(), cmd("open_notebook_capture"))
    back = apply(capture, cmd("cancel_capture"))
    assert back.events == () and back.session.active_artifact is None


def test_submit_over_a_leftover_artifact_supersedes_it():
    leftover = in_notebook_capture().with_changes(
        active_artifact={"artifact_id": "old", "artifact_version": 1, "job_id": "job-old"}
    )
    r = _submit(leftover)
    assert [e.type for e in r.events] == ["analysis_superseded", "artifact_submitted"]
    assert r.events[0].data == {"artifact_id": "old", "job_id": "job-old", "reason": "replaced"}
    assert r.session.last_event_seq == leftover.last_event_seq + 2


def _transfer_with_photo(*, analyzed: bool):
    """Tentativa nova (transfer) com foto enviada; a criança revisa, volta e responde."""
    s = run(session_in_transfer(), cmd("enter_notebook", intent="record_solution"))
    s = run(s, cmd("open_notebook_capture"))
    s = submitted(s, "art-t", 1, "job-t")
    if analyzed:
        s = apply_analysis_result(
            s, result_for("job-t", "art-t", 1, attempt_id=s.active_attempt_id), content=CONTENT
        ).result.session
    s = run(s, cmd("enter_notebook", intent="revise_record"))
    s = run(s, cmd("return_to_activity"))
    assert s.phase == "transfer"
    return run(s, cmd("submit_answer", answer=4))


def test_guided_to_transfer_supersedes_a_pending_artifact_once():
    explanation = _pending_artifact(run(session_in_practice(), cmd("submit_answer", answer=6)))
    r = apply(explanation, cmd("continue_after_explanation", reason="learner_skipped"))
    types = [e.type for e in r.events]
    assert types == ["attempt_evaluated", "analysis_superseded", "attempt_started", "scene_changed"]
    assert r.events[1].data == {
        "artifact_id": "art-1",
        "job_id": "job-1",
        "reason": "attempt_changed",
    }
    assert r.events[1].attempt_id == GUIDED_ID
    assert r.session.active_artifact is None


def test_transfer_to_summary_supersedes_a_pending_artifact():
    explanation = run(session_in_transfer(), cmd("submit_answer", answer=4))
    s = _pending_artifact(explanation, artifact_id="art-t", job_id="job-t")
    r = apply(s, cmd("continue_after_explanation", reason="learner_skipped"))
    assert r.session.phase == "summary"
    assert [e.type for e in r.events] == ["attempt_evaluated", "analysis_superseded"]
    assert r.events[1].data["reason"] == "attempt_closed"
    assert r.session.active_artifact is None
    late = result_for("job-t", "art-t", 1, attempt_id=s.active_attempt_id)
    assert apply_analysis_result(r.session, late, content=CONTENT).disposition == "superseded"


def test_transfer_to_summary_keeps_a_completed_analysis_without_an_event():
    s = _transfer_with_photo(analyzed=True)
    r = apply(s, cmd("continue_after_explanation", reason="learner_skipped"))
    assert [e.type for e in r.events] == ["attempt_evaluated"]
    assert r.session.observation is not None and r.session.active_artifact is not None


# --- R27: análise pendente só existe em notebook_capture/notebook_review ----------------------

_PENDING_PHASES = {"notebook_capture", "notebook_review"}


def _pending_start_states():
    """Real: foto enviada (notebook_review). Montados à mão: estados em que um artefato pendente
    sobraria fora da revisão, para provar que nenhuma transição o deixa para trás."""
    practice = session_in_practice()
    return {
        "review": in_review(),
        "capture": _pending_artifact(in_notebook_capture()),
        "notebook": _pending_artifact(in_review().with_changes(phase="notebook")),
        "explanation": _pending_artifact(run(practice, cmd("submit_answer", answer=6))),
        "practice": _pending_artifact(practice),
    }


_PAYLOAD_VARIANTS = {
    "enter_notebook": [{"intent": "revise_record"}, {"intent": "record_solution"}],
}


def _is_pending(s) -> bool:
    return s.active_artifact is not None and s.observation is None


def test_no_reachable_state_shows_pending_analysis_outside_capture_and_review():
    from app.domain.division.commands import ALLOWED_ACTORS

    succeeded: set[tuple[str, str]] = set()
    for name, start in _pending_start_states().items():
        assert _is_pending(start)
        for ctype in sorted(ALLOWED_ACTORS):
            actor = min(ALLOWED_ACTORS[ctype])
            for over in _PAYLOAD_VARIANTS.get(ctype, [{}]):
                try:
                    r = apply(start, cmd(ctype, actor=actor, **over))
                except (DomainError, ValueError):
                    continue  # recusado (fase, payload ou sem handler): o estado não muda
                succeeded.add((name, ctype))
                out = r.session
                assert out.phase in _PENDING_PHASES or not _is_pending(out), (name, ctype)
                if not _is_pending(out):
                    dropped = [e for e in r.events if e.type == "analysis_superseded"]
                    assert len(dropped) == 1, (name, ctype)  # R26: exatamente um
    # a varredura precisa ter alcançado as saídas que importam
    for pair in [
        ("review", "enter_notebook"),
        ("review", "retake_notebook_photo"),
        ("review", "close_session"),
        ("capture", "cancel_capture"),
        ("capture", "close_session"),
        ("notebook", "return_to_activity"),
        ("notebook", "open_notebook_capture"),
        ("explanation", "return_to_activity"),
        ("explanation", "continue_after_explanation"),
        ("practice", "enter_notebook"),
    ]:
        assert pair in succeeded, pair


@pytest.mark.parametrize(
    ("start", "command", "reason"),
    [
        ("review", cmd("enter_notebook", intent="revise_record"), "revise_record"),
        ("review", cmd("retake_notebook_photo"), "retake"),
        ("review", cmd("close_session"), "session_closed"),
        ("capture", cmd("cancel_capture"), "left_capture"),
        ("notebook", cmd("return_to_activity"), "left_notebook"),
        ("explanation", cmd("return_to_activity"), "left_notebook"),
    ],
)
def test_leaving_the_flow_drops_the_pending_artifact_with_a_clear_reason(start, command, reason):
    r = apply(_pending_start_states()[start], command)
    dropped = [e for e in r.events if e.type == "analysis_superseded"]
    assert [e.data["reason"] for e in dropped] == [reason]
    assert r.session.active_artifact is None


def test_pause_keeps_the_pending_artifact_in_review():
    r = apply(in_review(), cmd("pause_session"))
    assert r.session.phase == "notebook_review" and _is_pending(r.session)
    assert [e.type for e in r.events] == ["session_paused"]


def test_closing_a_session_with_a_pending_artifact_supersedes_before_the_close_event():
    r = apply(in_review(), cmd("close_session"))
    assert [e.type for e in r.events] == [
        "attempt_evaluated",
        "analysis_superseded",
        "session_closed",
    ]
    app = apply_analysis_result(r.session, result_for("job-1", "art-1", 1), content=CONTENT)
    assert app.disposition == "discarded"


# --- result só vale na tentativa ativa e numa fase que espera análise -------------------------


@pytest.mark.ac("AC-33")
def test_result_with_matching_artifact_but_another_attempt_is_superseded():
    review = in_review()
    app = apply_analysis_result(
        review, result_for("job-1", "art-1", 1, attempt_id="attempt-9-guided"), content=CONTENT
    )
    assert app.disposition == "superseded" and app.result is None


def test_result_for_a_closed_attempt_is_superseded():
    review = in_review()
    closed = review.attempts[1].with_changes(status="closed")
    s = review.with_changes(attempts=(review.attempts[0], closed, *review.attempts[2:]))
    assert s.active_attempt_id == GUIDED_ID and s.session_status == "active"
    app = apply_analysis_result(s, result_for("job-1", "art-1", 1), content=CONTENT)
    assert app.disposition == "superseded" and app.result is None


@pytest.mark.parametrize(
    "phase",
    [
        "notebook",
        "correction",
        "summary",
        "practice",
        "transfer",
        "notebook_capture",
        "explanation",
    ],
)
def test_result_outside_the_awaiting_phases_is_superseded(phase):
    s = in_review().with_changes(phase=phase)
    app = apply_analysis_result(s, result_for("job-1", "art-1", 1), content=CONTENT)
    assert app.disposition == "superseded" and app.result is None


def test_result_after_revise_record_is_superseded():  # R27: o artefato pendente foi abandonado
    app = apply_analysis_result(
        _revising_pending(), result_for("job-1", "art-1", 1), content=CONTENT
    )
    assert app.disposition == "superseded" and app.result is None


def test_late_result_after_the_transfer_attempt_ended_in_summary_is_superseded():
    s = _transfer_with_photo(analyzed=False)
    ended = apply(s, cmd("continue_after_explanation", reason="learner_skipped")).session
    assert ended.phase == "summary" and ended.active_attempt.status == "closed"
    late = result_for("job-t", "art-t", 1, attempt_id=s.active_attempt_id)
    assert apply_analysis_result(ended, late, content=CONTENT).disposition == "superseded"


# --- duplicata -----------------------------------------------------------------------------


def test_second_delivery_of_the_same_result_is_a_no_op():
    first = apply_analysis_result(in_review(), result_for("job-1", "art-1", 1), content=CONTENT)
    done = first.result.session
    again = apply_analysis_result(done, result_for("job-1", "art-1", 1), content=CONTENT)
    assert again.disposition == "already_applied" and again.result is None
    assert done.revision == first.result.session.revision  # nada mudou


def test_a_different_observation_for_an_analyzed_artifact_does_not_overwrite_it():
    done = _reviewed()
    other = result_for("job-1", "art-1", 1, obs=load_obs("observacao-ambigua"))
    again = apply_analysis_result(done, other, content=CONTENT)
    assert again.disposition == "already_applied" and again.result is None


def test_already_applied_still_loses_to_closed_and_superseded():
    done = _reviewed()
    stale = result_for("job-9", "art-9", 1)
    assert apply_analysis_result(done, stale, content=CONTENT).disposition == "superseded"
    closed = _closed(done)
    assert (
        apply_analysis_result(closed, result_for("job-1", "art-1", 1), content=CONTENT).disposition
        == "discarded"
    )


# --- R24: a observação tem de ser do resultado -------------------------------------------------


def _result_with_observation(**obs_over):
    r = result_for("job-1", "art-1", 1)
    obs = type(r.observation).model_validate({**r.observation.model_dump(mode="json"), **obs_over})
    return AnalysisResult(**{**dict(r), "observation": obs})


@pytest.mark.parametrize(
    "over",
    [{"artifact_id": "art-2"}, {"attempt_id": "attempt-9-guided"}, {"artifact_version": 2}],
)
def test_r24_observation_must_match_the_result(over):
    result = _result_with_observation(**over)
    assert _code(apply_analysis_result, in_review(), result, content=CONTENT) == "INVALID_PAYLOAD"


def test_r24_mismatch_is_invalid_even_when_the_result_is_stale():
    result = _result_with_observation(artifact_id="art-2")
    stale = _paused(in_review().with_changes(active_artifact=None))
    assert _code(apply_analysis_result, stale, result, content=CONTENT) == "INVALID_PAYLOAD"


def test_state_rejects_an_observation_without_artifact():
    done = _reviewed()
    with pytest.raises(ValueError):
        done.with_changes(active_artifact=None)
    with pytest.raises(ValueError):
        done.with_changes(verification=None)


def test_application_disposition_and_result_must_agree():
    from app.domain.division.analysis import AnalysisApplication

    with pytest.raises(ValueError):
        AnalysisApplication(disposition="applied")
    with pytest.raises(ValueError):
        AnalysisApplication(disposition="superseded", result=_reviewed_result())


def _reviewed_result():
    app = apply_analysis_result(in_review(), result_for("job-1", "art-1", 1), content=CONTENT)
    return app.result


# --- restrição global ---------------------------------------------------------------------------


def test_domain_has_no_io_imports():
    src = "\n".join(p.read_text() for p in DOMAIN_DIR.rglob("*.py"))
    assert not re.search(
        r"^\s*(from|import) (sqlalchemy|fastapi|httpx|psycopg|app\.sessions|app\.api|app\.db)",
        src,
        re.MULTILINE,
    )
