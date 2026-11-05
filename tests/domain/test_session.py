import json

import pytest
from app.domain.division.assistance import AssistanceLedger
from app.domain.division.demonstration import demo_steps
from app.domain.division.errors import DomainError
from app.domain.division.session import apply_command, new_session, public_snapshot
from helpers import (
    CONTENT,
    T12_4,
    StubEvaluator,
    apply,
    attempt,
    cmd,
    practice_with_counts,
    run,
    session_after_demo_steps,
    session_in_practice,
    session_in_transfer,
)
from pydantic import ValidationError


def _code(session, c, **kw) -> DomainError:
    with pytest.raises(DomainError) as e:
        apply(session, c, **kw)
    return e.value


def _types(result) -> list[str]:
    return [e.type for e in result.events]


def test_new_session_starts_clean():
    s = new_session("s1")
    assert s.phase == "source_capture" and s.session_status == "active"
    assert s.interaction_mode == "ready"
    assert (s.revision, s.scene_revision, s.turn_epoch, s.last_event_seq) == (0, 0, 0, 0)
    assert s.active_attempt_id is None and s.attempts == () and s.scene is None
    snap = public_snapshot(s, CONTENT)
    assert snap["scene"] is None and snap["item"] is None


def test_session_is_frozen():
    s = new_session("s1")
    with pytest.raises(ValidationError):
        s.phase = "summary"


# --- AC-03 / AC-04 ----------------------------------------------------------------------------


@pytest.mark.ac("AC-03")
def test_ac03_demo_flow_reaches_practice_without_answer():
    s = run(new_session("s1"), cmd("choose_reference_activity"))
    assert s.phase == "demonstration" and s.revision == 1
    for st in demo_steps(T12_4, 3):
        s = run(s, cmd("run_demo_step", actor="system", step_id=st.step_id))
    s = run(s, cmd("finish_demonstration", actor="system", reason="completed"))
    snap = public_snapshot(s, CONTENT)
    assert s.phase == "practice" and len(snap["scene"]["available_piece_ids"]) == 24
    assert snap["scene"]["answer_display"] is None and "6" not in json.dumps(snap["item"])
    assert snap["item"]["item_id"] == "guided-24-4"


def test_demo_scene_shows_the_demonstrated_answer_only_when_the_script_is_complete():
    s = session_after_demo_steps(11)
    assert public_snapshot(s, CONTENT)["scene"]["answer_display"] is None
    s = run(s, cmd("run_demo_step", actor="system", step_id="r3-g4"))
    assert public_snapshot(s, CONTENT)["scene"]["answer_display"] == 3  # Parte II §4, regra 4


@pytest.mark.ac("AC-04")
def test_ac04_finish_before_first_round_rejected_after_allowed():
    s = session_after_demo_steps(3)
    with pytest.raises(DomainError) as e:
        run(s, cmd("finish_demonstration", reason="learner_requested"))
    assert e.value.code == "INVALID_TRANSITION"
    r = apply(session_after_demo_steps(6), cmd("finish_demonstration", reason="learner_requested"))
    demo = attempt(r.session, "demonstration")
    assert demo.demo_partial and demo.status == "closed" and r.session.phase == "practice"
    started = [e for e in r.events if e.type == "attempt_started"]
    assert len(started) == 1 and started[0].data["kind"] == "guided"
    assert started[0].data["after_partial_demonstration"] is True
    assert r.scene_changed
    # Review Focus 3: a cena guiada não herda a cena [2,2,1,1] da demonstração.
    scene = public_snapshot(r.session, CONTENT)["scene"]
    assert len(scene["available_piece_ids"]) == 24
    assert all(g["piece_ids"] == [] for g in scene["groups"])
    assert scene["attempt_id"] == attempt(r.session, "guided").attempt_id


def test_complete_demo_is_not_partial():
    s = session_in_practice()
    assert attempt(s, "demonstration").demo_partial is False


def test_completed_reason_requires_the_whole_script():
    s = session_after_demo_steps(8)
    assert _code(s, cmd("finish_demonstration", actor="system", reason="completed")).code == (
        "INVALID_TRANSITION"
    )


def test_finish_by_tutor_not_allowed():
    s = session_after_demo_steps(6)
    # parse_command já recusa o ator tutor (catálogo L/S) ...
    with pytest.raises(DomainError) as e:
        apply(s, cmd("finish_demonstration", actor="tutor"))
    assert e.value.code == "ACTION_NOT_ALLOWED"
    # ... e apply_command confere de novo: comando válido para o aluno não vale como tutor.
    assert _code(s, cmd("finish_demonstration"), as_actor="tutor").code == "ACTION_NOT_ALLOWED"


def test_system_cannot_skip_the_demo_for_the_learner():
    s = session_after_demo_steps(6)
    e = _code(s, cmd("finish_demonstration", actor="system", reason="learner_requested"))
    assert e.code == "ACTION_NOT_ALLOWED"


def test_actor_gate_blocks_a_learner_command_applied_as_system():
    s = session_in_practice()
    assert _code(s, cmd("move_piece"), as_actor="system").code == "ACTION_NOT_ALLOWED"


def test_choose_reference_activity_rejects_a_package_that_is_not_the_loaded_one():
    other = CONTENT.model_copy(update={"version": "division-sharing-v0"})
    e = _code(new_session("s1"), cmd("choose_reference_activity"), content=other)
    assert e.code == "UNSUPPORTED_CONTENT"


def test_run_demo_step_follows_the_script_only():
    s = session_after_demo_steps(0)
    assert _code(s, cmd("run_demo_step", actor="system", step_id="r1-g2")).code == (
        "INVALID_TRANSITION"
    )  # fora de ordem
    assert _code(s, cmd("run_demo_step", actor="system", step_id="free-code")).code == (
        "INVALID_PAYLOAD"
    )
    done = session_after_demo_steps(12)
    assert _code(done, cmd("run_demo_step", actor="system", step_id="r3-g4")).code == (
        "INVALID_TRANSITION"
    )  # roteiro esgotado
    e = _code(s, cmd("run_demo_step", actor="system", step_id="r1-g1"), as_actor="learner")
    assert e.code == "ACTION_NOT_ALLOWED"


def test_run_demo_step_by_tutor_emits_events():
    s = session_after_demo_steps(3)
    r = apply(s, cmd("run_demo_step", actor="tutor", step_id="r1-g4"))
    assert _types(r) == ["demo_step_completed", "scene_changed"] and r.scene_changed
    assert r.events[0].data["round_completed"] is True


# --- R30: turno antigo do tutor não causa efeito -----------------------------------------------


def test_tutor_command_with_stale_turn_epoch_is_rejected():
    s = session_after_demo_steps(3).with_changes(turn_epoch=2)
    for old in (0, 1, 3):
        e = _code(s, cmd("run_demo_step", actor="tutor", step_id="r1-g4", turn_epoch=old))
        assert e.code == "STALE_TURN" and "2" in (e.detail or "")
    ok = apply(s, cmd("run_demo_step", actor="tutor", step_id="r1-g4", turn_epoch=2))
    assert ok.session.revision == s.revision + 1


def test_stale_turn_is_checked_before_any_other_rule():
    s = session_after_demo_steps(3).with_changes(turn_epoch=2)
    # revisão velha também: a recusa de turno vem antes e não revela nada do resto
    stale_both = cmd(
        "run_demo_step", actor="tutor", step_id="r1-g4", turn_epoch=1, expected_revision=0
    )
    assert _code(s, stale_both).code == "STALE_TURN"


def test_stale_turn_rule_does_not_touch_learner_or_system_commands():
    s = session_after_demo_steps(3).with_changes(turn_epoch=5)
    assert apply(s, cmd("run_demo_step", actor="system", step_id="r1-g4")).session.revision == (
        s.revision + 1
    )
    p = session_in_practice().with_changes(turn_epoch=5)
    assert apply(p, cmd("check_distribution")).session.revision == p.revision + 1


# --- AC-05 / AC-06 ----------------------------------------------------------------------------


@pytest.mark.ac("AC-05")
def test_ac05_ac06_check_distribution_keeps_phase():
    s = practice_with_counts([7, 5, 6, 6])
    r = apply(s, cmd("check_distribution"))
    assert r.session.phase == "practice" and not r.scene_changed
    assert r.session.scene == s.scene and r.session.scene_revision == s.scene_revision
    assert r.events[0].type == "distribution_checked"
    assert r.events[0].data["intervention"] == "compare_groups"
    assert r.events[0].data["intervention_targets"] == ["group-1", "group-2"]
    assert r.events[0].data["group_counts"] == [7, 5, 6, 6]


def test_check_distribution_valid_partition_has_no_intervention():
    r = apply(practice_with_counts([6, 6, 6, 6]), cmd("check_distribution"))
    assert r.events[0].data["valid_partition"] is True and r.events[0].data["intervention"] is None


def test_check_distribution_does_not_record_help():
    r = apply(practice_with_counts([7, 5, 6, 6]), cmd("check_distribution"))
    assert attempt(r.session, "guided").ledger == AssistanceLedger()


# --- movimento, revisões e erros (AC-27) ------------------------------------------------------


def test_revision_increments_once_per_command():
    s = session_in_practice()
    r = apply(s, cmd("move_piece"))
    assert r.session.revision == s.revision + 1 and r.session.scene_revision == s.scene_revision + 1
    assert r.scene_changed and _types(r) == ["scene_changed"]
    assert r.session.scene.scene_revision == r.session.scene_revision
    c = apply(r.session, cmd("check_distribution"))
    assert c.session.revision == r.session.revision + 1
    assert c.session.scene_revision == r.session.scene_revision and not c.scene_changed


def test_last_event_seq_counts_events():
    s = session_in_practice()
    r = apply(s, cmd("move_piece"))
    assert r.session.last_event_seq == s.last_event_seq + 1
    h = apply(r.session, cmd("request_help", kind="prompt"))
    assert h.session.last_event_seq == r.session.last_event_seq + len(h.events)


@pytest.mark.ac("AC-27")
@pytest.mark.parametrize(
    "mutation,code",
    [
        ({"expected_revision": 0}, "STALE_REVISION"),
        ({"attempt_id": "other"}, "ATTEMPT_CHANGED"),
        ({"expected_scene_revision": 0}, "STALE_SCENE"),
        (
            {
                "payload": {
                    "piece_id": "piece-01",
                    "from_location": "group-2",
                    "to_location": "group-1",
                }
            },
            "INVALID_SCENE",
        ),
        (
            {
                "payload": {
                    "piece_id": "piece-01",
                    "from_location": "group-1",
                    "to_location": "group-9",
                }
            },
            "INVALID_SCENE",
        ),
        (
            {
                "payload": {
                    "piece_id": "piece-99",
                    "from_location": "available",
                    "to_location": "group-1",
                }
            },
            "INVALID_SCENE",
        ),
        (
            {
                "payload": {
                    "piece_id": "piece-01",
                    "from_location": "group-1",
                    "to_location": "group-1",
                }
            },
            "NO_OP",
        ),
    ],
)
def test_ac27_errors_without_partial_mutation(mutation, code):
    s = practice_with_counts([1, 0, 0, 0])
    with pytest.raises(DomainError) as e:
        apply(s, cmd("move_piece", **mutation))
    assert e.value.code == code
    assert s == practice_with_counts([1, 0, 0, 0])  # entrada intacta


def test_guard_order_attempt_before_revision_before_scene_before_phase():
    s = practice_with_counts([1, 0, 0, 0])
    both = cmd("move_piece", attempt_id="other", expected_revision=0, expected_scene_revision=0)
    assert _code(s, both).code == "ATTEMPT_CHANGED"
    assert _code(s, cmd("move_piece", expected_revision=0, expected_scene_revision=0)).code == (
        "STALE_REVISION"
    )
    # Fase errada com cena velha: a cena é checada antes da fase.
    demo = session_after_demo_steps(0)
    assert _code(demo, cmd("move_piece", expected_scene_revision=99)).code == "STALE_SCENE"
    assert _code(demo, cmd("move_piece")).code == "INVALID_TRANSITION"


def test_command_before_any_attempt_must_carry_null_attempt():
    s = new_session("s1")
    assert _code(s, cmd("choose_reference_activity", attempt_id="a1")).code == "ATTEMPT_CHANGED"


# --- pausa, fechamento e exceção da Parte II §2 ----------------------------------------------


def test_pause_with_stale_revision_accepted():
    s = practice_with_counts([2, 0, 0, 0])
    r = apply(s, cmd("pause_session", expected_revision=0))
    assert r.session.session_status == "paused" and r.session.turn_epoch == s.turn_epoch + 1
    assert r.session.revision == s.revision + 1 and not r.scene_changed
    assert r.session.scene == s.scene and r.session.phase == "practice"
    assert _types(r) == ["session_paused"]


def test_pause_still_checks_the_attempt():
    s = session_in_practice()
    assert _code(s, cmd("pause_session", attempt_id="other")).code == "ATTEMPT_CHANGED"


def test_pausing_twice_is_a_no_op():
    p = run(session_in_practice(), cmd("pause_session"))
    assert _code(p, cmd("pause_session")).code == "NO_OP"


def test_resume_returns_to_active_and_keeps_phase_and_scene():
    p = run(session_after_demo_steps(3), cmd("pause_session"))
    r = apply(p, cmd("resume_session"))
    assert r.session.session_status == "active" and r.session.phase == p.phase
    assert r.session.scene == p.scene and r.session.turn_epoch == p.turn_epoch
    assert r.session.revision == p.revision + 1 and not r.scene_changed
    assert _types(r) == ["session_resumed"]


def test_pause_then_resume_then_demo_continues():
    p = run(session_after_demo_steps(3), cmd("pause_session"))
    assert _code(p, cmd("run_demo_step", actor="system", step_id="r1-g4")).detail == (
        "session_paused"
    )
    s = run(p, cmd("resume_session"))
    s = run(s, cmd("run_demo_step", actor="system", step_id="r1-g4"))
    assert s.session_status == "active" and s.scene_revision == p.scene_revision + 1


def test_resume_requires_a_paused_session():
    assert _code(session_in_practice(), cmd("resume_session")).code == "NO_OP"


def test_resume_is_not_revision_exempt():  # Parte II §2 isenta só pause/interrupt/learner_stopped
    p = run(session_in_practice(), cmd("pause_session"))
    assert _code(p, cmd("resume_session", expected_revision=0)).code == "STALE_REVISION"
    assert _code(p, cmd("resume_session", attempt_id="other")).code == "ATTEMPT_CHANGED"


@pytest.mark.parametrize("actor", ["tutor", "system"])
def test_only_the_learner_resumes(actor):
    p = run(session_in_practice(), cmd("pause_session"))
    c = cmd("resume_session", actor="learner")
    assert _code(p, c, as_actor=actor).code == "ACTION_NOT_ALLOWED"


def test_closed_session_cannot_resume():
    s = run(session_in_practice(), cmd("close_session", reason="learner_stopped"))
    assert _code(s, cmd("resume_session")).detail == "session_closed"


def test_learner_keeps_acting_while_paused():  # a pausa bloqueia só tutor/sistema
    p = run(practice_with_counts([1, 0, 0, 0]), cmd("pause_session"))
    r = apply(
        p,
        cmd(
            "move_piece",
            piece_id="piece-02",
            from_location="available",
            to_location="group-1",
        ),
    )
    assert r.session.session_status == "paused"


def test_paused_session_blocks_tutor_and_system_but_not_close():
    p = run(session_after_demo_steps(3), cmd("pause_session"))
    for actor in ("tutor", "system"):
        e = _code(p, cmd("run_demo_step", actor=actor, step_id="r1-g4"))
        assert e.code == "ACTION_NOT_ALLOWED" and e.detail == "session_paused"
    closed = run(p, cmd("close_session", reason="learner_stopped"))
    assert closed.session_status == "closed"


def test_close_learner_stopped_with_stale_revision_accepted():
    s = practice_with_counts([2, 0, 0, 0])
    r = apply(s, cmd("close_session", reason="learner_stopped", expected_revision=0))
    assert r.session.session_status == "closed" and r.session.phase == "summary"


def test_system_learner_stopped_close_does_not_skip_revision_check():
    s = session_in_practice()
    c = cmd("close_session", actor="system", reason="learner_stopped", expected_revision=0)
    assert _code(s, c).code == "STALE_REVISION"


@pytest.mark.parametrize("reason", ["limit_reached", "completed"])
def test_close_with_other_reasons_does_not_skip_revision_check(reason):
    s = session_in_practice()
    assert _code(s, cmd("close_session", reason=reason, expected_revision=0)).code == (
        "STALE_REVISION"
    )


def test_closed_session_rejects_everything():
    s = run(session_in_practice(), cmd("close_session", reason="learner_stopped"))
    assert s.phase == "summary" and s.session_status == "closed"
    for c in (cmd("move_piece"), cmd("pause_session"), cmd("close_session")):
        e = _code(s, c)
        assert e.code == "ACTION_NOT_ALLOWED" and e.detail == "session_closed"


def test_close_partial_records_partial_completion_and_not_attempted():
    r = apply(session_in_practice(), cmd("close_session", reason="learner_stopped"))
    assert _types(r) == ["attempt_evaluated", "session_closed"]
    assert r.events[0].data["outcome"] == "not_attempted" and r.events[0].data["final"] is True
    assert r.events[1].data == {"reason": "learner_stopped", "completion": "partial"}
    assert r.session.completion == "partial"
    assert attempt(r.session, "guided").status == "closed"


def test_close_completed_only_after_the_evidence_flow():
    assert _code(session_in_practice(), cmd("close_session", reason="completed")).code == (
        "INVALID_TRANSITION"
    )


# --- caderno ------------------------------------------------------------------------------------


def test_notebook_round_trip_in_practice_preserves_scene():
    s = practice_with_counts([2, 0, 0, 0])
    n = apply(s, cmd("enter_notebook", intent="try_on_paper"))
    assert n.session.phase == "notebook" and n.session.interaction_mode == "writing"
    assert n.session.return_phase == "practice" and n.session.notebook_intent == "try_on_paper"
    assert _types(n) == ["notebook_entered"] and not n.scene_changed
    assert n.session.scene == s.scene
    b = apply(n.session, cmd("return_to_activity"))
    assert b.session.phase == "practice" and b.session.interaction_mode == "ready"
    assert b.session.return_phase is None and b.session.scene == s.scene
    assert _types(b) == ["returned_to_activity"]


def test_notebook_in_transfer_keeps_scene_hidden_and_returns_to_transfer():
    s = session_in_transfer()
    n = run(s, cmd("enter_notebook", intent="record_solution"))
    assert n.phase == "notebook" and public_snapshot(n, CONTENT)["scene"] is None
    b = run(n, cmd("return_to_activity"))
    assert b.phase == "transfer" and public_snapshot(b, CONTENT)["scene"] is None
    assert attempt(b, "transfer").ledger == AssistanceLedger()  # voltar não libera nada


def test_notebook_blocks_scene_commands_until_return():
    n = run(practice_with_counts([1, 0, 0, 0]), cmd("enter_notebook"))
    assert _code(n, cmd("move_piece", piece_id="piece-02")).code == "INVALID_TRANSITION"


# --- ajuda (AC-24, D3, D4) ---------------------------------------------------------------------


@pytest.mark.ac("AC-21")
def test_ac21_transfer_starts_clean():
    s = session_in_transfer()
    snap = public_snapshot(s, CONTENT)
    assert s.phase == "transfer" and snap["scene"] is None and s.scene is None
    assert attempt(s, "transfer").ledger == AssistanceLedger()
    assert "quotient" not in json.dumps(snap) and '"4"' not in json.dumps(snap["item"])
    assert snap["item"]["item_id"] == "transfer-20-5"
    assert attempt(s, "guided").status == "closed" and attempt(s, "transfer").status == "active"


@pytest.mark.ac("AC-24")
def test_ac24_help_recorded_before_resource():
    s = session_in_transfer()
    r = apply(s, cmd("request_help", kind="virtual_objects", reason="quero peças"))
    assert [e.type for e in r.events] == ["help_granted", "scene_changed"]
    snap = public_snapshot(r.session, CONTENT)
    assert snap["scene"] is not None and len(snap["scene"]["available_piece_ids"]) == 20
    assert snap["scene"]["task"]["divisor"] == 5 and snap["scene"]["answer_display"] is None
    ledger = attempt(r.session, "transfer").ledger
    assert ledger.level == "none" and "virtual_objects" in ledger.resources
    assert r.scene_changed and r.session.scene_revision == s.scene_revision + 1


def test_reference_model_also_opens_the_scene_and_a_second_request_does_not_change_it():
    r = apply(session_in_transfer(), cmd("request_help", kind="reference_model", reason="modelo"))
    assert _types(r) == ["help_granted", "scene_changed"]
    r2 = apply(r.session, cmd("request_help", kind="virtual_objects", reason="peças"))
    assert _types(r2) == ["help_granted"] and not r2.scene_changed
    assert r2.session.scene == r.session.scene


def test_help_unlocks_moves_in_transfer_but_not_before():
    s = session_in_transfer()
    e = _code(s, cmd("move_piece"))
    assert e.code == "ACTION_NOT_ALLOWED" and e.detail == "scene_not_available"
    h = run(s, cmd("request_help", kind="virtual_objects", reason="peças"))
    moved = run(h, cmd("move_piece", to_location="group-2"))
    assert len(moved.scene.groups[1].piece_ids) == 1


def test_alternate_strategy_in_transfer_unsupported():
    s = session_in_transfer()
    assert _code(s, cmd("request_help", kind="alternate_strategy", reason="outro jeito")).code == (
        "UNSUPPORTED_CONTENT"
    )


def test_conceptual_help_raises_the_ledger_and_never_lowers_it():
    s = session_in_practice()
    s = run(s, cmd("request_help", kind="worked_step", reason="não sei"))
    s = run(s, cmd("request_help", kind="prompt", reason="outra"))
    ledger = attempt(s, "guided").ledger
    assert ledger.level == "demonstrated"
    assert public_snapshot(s, CONTENT)["attempt"]["assistance_level"] == "demonstrated"


def test_help_reason_text_is_not_kept_in_state_or_events():
    """R28 / AC-45: o texto livre da criança não fica no estado nem no evento; só `has_reason`."""
    secret = "Maria Silva 123"
    r = apply(session_in_practice(), cmd("request_help", kind="prompt", reason=secret))
    assert secret not in r.session.model_dump_json()
    granted = [e for e in r.events if e.type == "help_granted"]
    assert len(granted) == 1 and granted[0].data["has_reason"] is True
    assert secret not in repr([e.data for e in r.events])


def test_alternate_strategy_is_allowed_in_the_guided_item():
    r = apply(session_in_practice(), cmd("request_help", kind="alternate_strategy", reason="x"))
    assert attempt(r.session, "guided").ledger.level == "demonstrated"


def test_try_on_paper_adds_the_paper_resource_without_raising_the_level():
    n = run(session_in_practice(), cmd("enter_notebook", intent="try_on_paper"))
    ledger = attempt(n, "guided").ledger
    assert ledger.resources == frozenset({"paper"}) and ledger.level == "none"
    again = run(run(n, cmd("return_to_activity")), cmd("enter_notebook", intent="try_on_paper"))
    assert attempt(again, "guided").ledger == ledger  # idempotente


def test_record_solution_does_not_add_the_paper_resource():
    n = run(session_in_practice(), cmd("enter_notebook", intent="record_solution"))
    assert attempt(n, "guided").ledger.resources == frozenset()


def test_finish_demonstration_records_reason_and_requester():
    r = apply(session_after_demo_steps(6), cmd("finish_demonstration", reason="learner_requested"))
    started = next(e for e in r.events if e.type == "attempt_started")
    assert started.data["demo_finish_reason"] == "learner_requested"
    assert started.data["requested_by"] == "learner"
    full = apply(
        session_after_demo_steps(12),
        cmd("finish_demonstration", actor="system", reason="completed"),
    )
    started = next(e for e in full.events if e.type == "attempt_started")
    assert (started.data["demo_finish_reason"], started.data["requested_by"]) == (
        "completed",
        "system",
    )


def test_help_in_notebook_keeps_the_phase():
    n = run(session_in_practice(), cmd("enter_notebook"))
    h = run(n, cmd("request_help", kind="prompt", reason="dúvida"))
    assert h.phase == "notebook"


# --- resposta, explicação e classificação (AC-22, AC-23) --------------------------------------


@pytest.mark.ac("AC-22", "AC-23")
def test_ac22_ac23_via_commands():
    s = session_in_transfer()
    a = apply(s, cmd("submit_answer", answer=4))
    assert a.session.phase == "explanation" and "answer_submitted" in _types(a)
    assert a.events[-1].type == "attempt_evaluated"
    assert a.events[-1].data["outcome"] == "answer_correct_evidence_partial"  # AC-23
    e = apply(a.session, cmd("submit_explanation", text="5 grupos de 4"))
    assert _types(e) == ["explanation_evaluated", "attempt_evaluated"]
    assert e.events[-1].data["outcome"] == "applied_without_item_help"  # AC-22
    assert e.events[-1].data["final"] is False


def test_answer_with_inline_explanation_is_evaluated_through_the_port():
    ev = StubEvaluator("sufficient")
    r = apply(
        session_in_transfer(),
        cmd("submit_answer", answer=4, explanation="5 x 4 = 20"),
        evaluator=ev,
    )
    assert _types(r) == ["answer_submitted", "explanation_evaluated", "attempt_evaluated"]
    assert r.events[-1].data["outcome"] == "applied_without_item_help"
    assert ev.calls == [("transfer-20-5", "5 x 4 = 20")]


def test_partial_explanation_keeps_the_evidence_partial():
    ev = StubEvaluator("partial")
    r = apply(
        session_in_transfer(), cmd("submit_answer", answer=4, explanation="não sei"), evaluator=ev
    )
    assert r.events[-1].data["outcome"] == "answer_correct_evidence_partial"


def test_help_before_the_answer_makes_it_applied_with_support():
    s = run(session_in_transfer(), cmd("request_help", kind="virtual_objects", reason="peças"))
    r = apply(s, cmd("submit_answer", answer=4, explanation="5 x 4 = 20"))
    assert r.events[-1].data["outcome"] == "applied_with_support"


def test_wrong_answer_stays_in_the_phase_and_needs_review():
    s = session_in_transfer()
    r = apply(s, cmd("submit_answer", answer=5))
    assert r.session.phase == "transfer"
    assert r.events[0].data["correct"] is False
    assert r.events[-1].data["outcome"] == "needs_review"
    retry = apply(r.session, cmd("submit_answer", answer=4))
    assert retry.session.phase == "explanation"


def test_answer_and_events_never_leak_the_private_quotient():
    s = session_in_transfer()
    r = apply(s, cmd("submit_answer", answer=5))
    blob = json.dumps([e.model_dump(mode="json") for e in r.events])
    assert "quotient" not in blob and "explanation_criteria" not in blob
    snap = json.dumps(public_snapshot(r.session, CONTENT))
    assert "quotient" not in snap and "private" not in snap and "criteria" not in snap
    assert public_snapshot(r.session, CONTENT)["attempt"]["answered"] is True


def test_explanation_in_transfer_before_the_answer_does_not_classify():
    r = apply(session_in_transfer(), cmd("submit_explanation", text="juntei 5 grupos"))
    assert _types(r) == ["explanation_evaluated"] and r.session.phase == "transfer"


def test_artifact_explanation_waits_for_the_photo_flow():
    s = run(session_in_transfer(), cmd("submit_answer", answer=4))
    e = _code(s, cmd("submit_explanation", payload={"modality": "artifact", "artifact_id": "art1"}))
    assert e.code == "ACTION_NOT_ALLOWED" and e.detail == "not_in_increment_1"


def test_voice_transcript_modality_is_kept_in_the_result():
    s = run(session_in_transfer(), cmd("submit_answer", answer=4))
    r = apply(s, cmd("submit_explanation", payload={"modality": "voice_transcript", "text": "oi"}))
    assert r.events[0].data["modality"] == "voice_transcript"
    assert attempt(r.session, "transfer").explanation.modality == "voice_transcript"


def test_return_to_activity_from_explanation_goes_back_by_item_kind():
    guided = run(session_in_practice(), cmd("submit_answer", answer=6))
    assert guided.phase == "explanation"
    assert run(guided, cmd("return_to_activity")).phase == "practice"
    transfer = run(session_in_transfer(), cmd("submit_answer", answer=4))
    assert run(transfer, cmd("return_to_activity")).phase == "transfer"


def test_continue_sufficient_requires_a_sufficient_explanation():
    s = run(session_in_practice(), cmd("submit_answer", answer=6))
    assert _code(s, cmd("continue_after_explanation", reason="sufficient")).code == (
        "INVALID_TRANSITION"
    )
    skipped = apply(s, cmd("continue_after_explanation", reason="learner_skipped"))
    assert skipped.session.phase == "transfer"


def test_continue_from_guided_starts_a_clean_transfer():
    s = run(session_in_practice(), cmd("submit_answer", answer=6))
    r = apply(s, cmd("continue_after_explanation", reason="learner_skipped"))
    assert _types(r) == ["attempt_evaluated", "attempt_started", "scene_changed"]
    assert r.events[0].data["outcome"] == "answer_correct_evidence_partial"
    assert r.events[0].data["final"] is True
    assert r.scene_changed and r.session.scene is None
    assert r.session.active_attempt_id == attempt(r.session, "transfer").attempt_id


# --- jornada completa e resumo -------------------------------------------------------------


def test_full_journey_ends_in_summary_and_complete_close():
    s = session_in_transfer()
    s = run(s, cmd("submit_answer", answer=4, explanation="5 grupos de 4"))
    r = apply(s, cmd("continue_after_explanation", reason="sufficient"))
    assert r.session.phase == "summary" and r.session.session_status == "active"
    assert r.events[0].data["outcome"] == "applied_without_item_help"
    assert attempt(r.session, "transfer").status == "closed"
    # Resumo não aceita mais edição pedagógica.
    assert _code(r.session, cmd("submit_answer", answer=4)).code == "INVALID_TRANSITION"
    done = apply(r.session, cmd("close_session", reason="completed"))
    assert done.session.session_status == "closed" and done.session.completion == "complete"
    assert done.events[-1].data == {"reason": "completed", "completion": "complete"}


# --- D7: comandos sem handler no incremento 1 ------------------------------------------------


@pytest.mark.parametrize(
    "c",
    [
        cmd("undo_move"),
        cmd("highlight_group", actor="tutor"),
        cmd("set_projection"),
        cmd("apply_help", actor="system"),
        cmd("set_thinking"),
        cmd("interrupt_turn", actor="system"),
    ],
)
def test_commands_without_a_handler_are_not_in_increment_1(c):
    e = _code(session_in_practice(), c)
    assert e.code == "ACTION_NOT_ALLOWED" and e.detail == "not_in_increment_1"


def test_unhandled_command_in_the_wrong_phase_is_an_invalid_transition_first():
    e = _code(new_session("s1"), cmd("confirm_source"))
    assert e.code == "INVALID_TRANSITION"


def test_snapshot_exposes_checkpoint_fields():
    n = run(practice_with_counts([1, 0, 0, 0]), cmd("enter_notebook", intent="record_solution"))
    snap = public_snapshot(n, CONTENT)
    assert snap["phase"] == "notebook" and snap["return_phase"] == "practice"
    assert snap["notebook_intent"] == "record_solution" and snap["interaction_mode"] == "writing"
    assert snap["scene_revision"] == n.scene_revision and snap["revision"] == n.revision


def test_apply_command_is_exported_with_the_documented_signature():
    import inspect

    params = inspect.signature(apply_command).parameters
    assert list(params) == ["session", "command", "actor", "content", "explanation_evaluator"]
    assert params["content"].kind is inspect.Parameter.KEYWORD_ONLY


def test_snapshot_hides_the_transfer_scene_even_if_one_is_stored_without_a_resource():
    s = session_in_transfer()
    with_scene = s.with_changes(scene=session_in_practice().scene)
    assert public_snapshot(with_scene, CONTENT)["scene"] is None


def test_snapshot_never_shows_an_answer_outside_the_demonstration():
    s = session_in_practice()
    leaky = s.with_changes(
        scene=s.scene.__class__.model_validate({**dict(s.scene), "answer_display": 6})
    )
    assert public_snapshot(leaky, CONTENT)["scene"]["answer_display"] is None


# --- increment 2, Task 2: session_id (P12) e snapshot da análise ------------------------------


def test_session_id_mismatch_rejected():
    e = _code(session_in_practice(), cmd("check_distribution", session_id="other"))
    assert e.code == "INVALID_PAYLOAD" and e.detail == "session_id mismatch"


def test_session_id_mismatch_is_checked_before_session_state_guards():
    closed = run(session_in_practice(), cmd("close_session"))
    assert _code(closed, cmd("check_distribution", session_id="other")).code == "INVALID_PAYLOAD"
    # ... mas depois da autorização do ator.
    tutor_move = cmd("move_piece", actor="tutor", session_id="other")
    assert _code(session_in_practice(), tutor_move, as_actor="tutor").code == "ACTION_NOT_ALLOWED"


def test_snapshot_analysis_is_null_before_any_photo():
    assert public_snapshot(session_in_practice(), CONTENT)["analysis"] is None
