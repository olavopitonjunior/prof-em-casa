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
    apply,
    cmd,
    in_notebook_capture,
    in_review,
    load_obs,
    obs_with,
    result_for,
    run,
    session_in_practice,
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


def test_retake_supersedes_and_clears_observation():
    s = apply_analysis_result(in_review(), result_for("job-1", "art-1", 1), content=CONTENT)
    reviewed = s.result.session
    assert reviewed.observation is not None and reviewed.verification is not None
    r = apply(reviewed, cmd("retake_notebook_photo"))
    assert r.session.phase == "notebook_capture"
    assert [e.type for e in r.events] == ["analysis_superseded"]
    assert r.events[0].data == {"artifact_id": "art-1", "job_id": "job-1", "reason": "retake"}
    assert r.session.active_artifact is None
    assert r.session.observation is None and r.session.verification is None
    assert r.session.revision == reviewed.revision + 1
    assert r.session.last_event_seq == reviewed.last_event_seq + 1


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


# --- restrição global ---------------------------------------------------------------------------


def test_domain_has_no_io_imports():
    src = "\n".join(p.read_text() for p in DOMAIN_DIR.rglob("*.py"))
    assert not re.search(
        r"^\s*(from|import) (sqlalchemy|fastapi|httpx|psycopg|app\.sessions|app\.api|app\.db)",
        src,
        re.MULTILINE,
    )
