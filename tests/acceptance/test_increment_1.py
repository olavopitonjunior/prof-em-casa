"""Aceite do incremento 1 (domínio puro): um teste por AC, cada um jogando a jornada inteira.

Toda jornada parte de `new_session` e avança só por `apply_command` (via `helpers.run/apply`, que
montam o comando cru e passam por `parse_command`). Nenhum atalho de estado. O avaliador de
explicação é um stub (D2): não há leitura real de texto, voz nem foto.
"""

import json

import pytest
from app.domain.division.assistance import AssistanceLedger
from app.domain.division.commands import parse_command
from app.domain.division.errors import DomainError
from app.domain.division.session import SessionState, new_session, public_snapshot
from helpers import CONTENT, StubEvaluator, apply, attempt, cmd, run

pytestmark = pytest.mark.acceptance

DEMO_STEPS = [f"r{r}-g{g}" for r in (1, 2, 3) for g in (1, 2, 3, 4)]


def _types(result) -> list[str]:
    return [e.type for e in result.events]


def _snap(session: SessionState) -> dict:
    return public_snapshot(session, CONTENT)


def _demo(steps: int) -> SessionState:
    s = run(new_session("acc"), cmd("choose_reference_activity"))
    for step_id in DEMO_STEPS[:steps]:
        s = run(s, cmd("run_demo_step", actor="system", step_id=step_id))
    return s


def _practice() -> SessionState:
    return run(_demo(12), cmd("finish_demonstration", actor="system", reason="completed"))


def _practice_with(counts: list[int]) -> SessionState:
    s, nxt = _practice(), 1
    for g, n in enumerate(counts, start=1):
        for _ in range(n):
            s = run(
                s,
                cmd(
                    "move_piece",
                    piece_id=f"piece-{nxt:02d}",
                    from_location="available",
                    to_location=f"group-{g}",
                ),
            )
            nxt += 1
    return s


def _transfer() -> SessionState:
    """Prática -> resposta 6 -> explicação suficiente -> questão nova, tudo por comandos."""
    s = _practice_with([6, 6, 6, 6])
    s = run(s, cmd("submit_answer", answer=6))
    assert s.phase == "explanation"
    s = run(s, cmd("submit_explanation", text="4 grupos de 6 dão 24"))
    s = run(s, cmd("continue_after_explanation", reason="sufficient"))
    assert s.phase == "transfer"
    return s


@pytest.mark.ac("AC-03")
def test_ac03_complete_demonstration():
    s = _demo(12)
    scene = _snap(s)["scene"]
    assert s.phase == "demonstration"
    assert [len(g["piece_ids"]) for g in scene["groups"]] == [3, 3, 3, 3]
    assert scene["available_piece_ids"] == []
    assert scene["answer_display"] == 3  # 12 ÷ 4 = 3 permitido só no exemplo demonstrado
    s = run(s, cmd("finish_demonstration", actor="system", reason="completed"))
    snap = _snap(s)
    assert s.phase == "practice" and attempt(s, "demonstration").demo_partial is False
    assert snap["item"]["item_id"] == "guided-24-4"
    assert snap["scene"]["answer_display"] is None  # o item principal não nasce respondido
    assert len(snap["scene"]["available_piece_ids"]) == 24
    assert "6" not in json.dumps(snap["item"])


@pytest.mark.ac("AC-04")
def test_ac04_advance_request_before_and_after_the_first_round():
    before = _demo(3)
    with pytest.raises(DomainError) as e:
        apply(before, cmd("finish_demonstration", reason="learner_requested"))
    assert e.value.code == "INVALID_TRANSITION"
    assert before.phase == "demonstration" and attempt(before, "demonstration").status == "active"
    r = apply(_demo(6), cmd("finish_demonstration", reason="learner_requested"))
    demo = attempt(r.session, "demonstration")
    assert r.session.phase == "practice" and demo.demo_partial and demo.status == "closed"
    started = next(ev for ev in r.events if ev.type == "attempt_started")
    assert started.data["after_partial_demonstration"] is True
    assert started.data["demo_finish_reason"] == "learner_requested"  # pedido explícito registrado
    assert started.data["requested_by"] == "learner"
    assert started.data["completed_rounds"] == 1  # 6 passos = 1 rodada e meia
    # A cena guiada começa limpa: não herda as peças da demonstração parcial.
    scene = _snap(r.session)["scene"]
    assert len(scene["available_piece_ids"]) == 24
    assert all(g["piece_ids"] == [] for g in scene["groups"])


@pytest.mark.ac("AC-05")
def test_ac05_unequal_practice_detects_inequality_without_acting():
    s = _practice_with([7, 5, 6, 6])
    r = apply(s, cmd("check_distribution"))
    data = r.events[0].data
    assert r.events[0].type == "distribution_checked" and r.session.phase == "practice"
    assert data["group_counts"] == [7, 5, 6, 6] and data["valid_partition"] is False
    assert data["intervention"] == "compare_groups"
    assert data["intervention_targets"] == ["group-1", "group-2"]
    assert r.session.scene == s.scene and not r.scene_changed  # não move peça sozinho
    assert attempt(r.session, "guided").ledger == AssistanceLedger()
    assert not any(ev.type == "attempt_evaluated" for ev in r.events)  # nem marca domínio
    assert r.session.completion is None and attempt(r.session, "guided").answer is None


@pytest.mark.ac("AC-06")
def test_ac06_equal_groups_with_available_pieces_ask_about_the_total():
    s = _practice_with([5, 5, 5, 5])
    r = apply(s, cmd("check_distribution"))
    data = r.events[0].data
    assert data["group_counts"] == [5, 5, 5, 5] and data["valid_partition"] is False
    assert data["intervention"] == "check_total_use"
    assert data["intervention_targets"] == _snap(s)["scene"]["available_piece_ids"]
    assert len(data["intervention_targets"]) == 4
    public = json.dumps([_snap(r.session), [ev.model_dump(mode="json") for ev in r.events]])
    assert "resto" not in public.lower()  # disponíveis não são "resto" matemático
    assert r.session.scene == s.scene and r.session.phase == "practice"


@pytest.mark.ac("AC-21")
def test_ac21_new_question_starts_clean():
    s = _transfer()
    snap = _snap(s)
    assert snap["item"]["item_id"] == "transfer-20-5" and snap["attempt"]["kind"] == "transfer"
    assert snap["scene"] is None and s.scene is None  # sem cena resolvida nem peças prontas
    assert (
        snap["attempt"]["assistance_level"] == "none" and snap["attempt"]["support_resources"] == []
    )
    assert attempt(s, "transfer").ledger == AssistanceLedger()
    assert attempt(s, "transfer").answer is None and snap["attempt"]["answered"] is False
    dumped = json.dumps(snap)
    assert "quotient" not in dumped and "private" not in dumped
    assert '"answer_display": 4' not in dumped


@pytest.mark.ac("AC-22")
def test_ac22_correct_answer_with_sufficient_explanation_and_paper_is_without_item_help():
    s = run(_transfer(), cmd("enter_notebook", intent="try_on_paper"))
    s = run(s, cmd("return_to_activity"))
    assert s.phase == "transfer"
    s = run(s, cmd("submit_answer", answer=4))
    r = apply(s, cmd("submit_explanation", text="5 grupos de 4 dão 20"), evaluator=StubEvaluator())
    outcome = r.events[-1]
    assert outcome.type == "attempt_evaluated" and outcome.data["final"] is False
    assert outcome.data["outcome"] == "applied_without_item_help"
    ledger = attempt(r.session, "transfer").ledger
    assert ledger.resources == frozenset({"paper"}) and ledger.level == "none"  # papel não é ajuda
    done = apply(r.session, cmd("continue_after_explanation", reason="sufficient"))
    assert done.session.phase == "summary" and done.events[0].data["outcome"] == (
        "applied_without_item_help"
    )
    # O resumo não promete domínio geral nem retenção: só o resultado desta tentativa.
    text = json.dumps([_snap(done.session), [ev.data for ev in done.events]]).lower()
    assert "mastery" not in text and "domin" not in text and "retenç" not in text
    assert done.session.completion is None  # fechar a sessão é outro comando


@pytest.mark.ac("AC-23")
def test_ac23_bare_answer_is_partial_evidence_and_never_sufficient_alone():
    s = _transfer()
    a = apply(s, cmd("submit_answer", answer=4))
    assert a.session.phase == "explanation"
    assert a.events[-1].data["outcome"] == "answer_correct_evidence_partial"
    assert attempt(a.session, "transfer").explanation is None
    # "Sufficient" não é aceito sem explicação suficiente registrada.
    with pytest.raises(DomainError) as e:
        apply(a.session, cmd("continue_after_explanation", reason="sufficient"))
    assert e.value.code == "INVALID_TRANSITION"
    # Se a criança segue sem explicar, o registro final continua parcial.
    done = apply(a.session, cmd("continue_after_explanation", reason="learner_skipped"))
    assert done.events[0].data["outcome"] == "answer_correct_evidence_partial"
    assert done.events[0].data["final"] is True
    # Explicação insuficiente também não promove a evidência.
    weak = apply(
        a.session, cmd("submit_explanation", text="não sei"), evaluator=StubEvaluator("unclear")
    )
    assert weak.events[-1].data["outcome"] == "answer_correct_evidence_partial"


@pytest.mark.ac("AC-24")
def test_ac24_help_is_recorded_before_the_resource_and_marks_support():
    s = _transfer()
    r = apply(s, cmd("request_help", kind="virtual_objects", reason="quero as peças"))
    assert _types(r) == ["help_granted", "scene_changed"]  # apoio registrado antes da entrega
    assert "virtual_objects" in attempt(r.session, "transfer").ledger.resources
    assert len(_snap(r.session)["scene"]["available_piece_ids"]) == 20
    s2 = run(r.session, cmd("submit_answer", answer=4))
    s2 = run(s2, cmd("submit_explanation", text="5 grupos de 4 dão 20"))
    final = apply(s2, cmd("continue_after_explanation", reason="sufficient"))
    assert final.events[0].data["outcome"] == "applied_with_support"
    # (Instrução de upload é ajuda procedimental, só registrada pelo tutor via apply_help, que
    # ainda não tem handler: essa parte do AC-24 fica nos testes de assistance/classification.)
    # Pista conceitual: o resultado eventual é com suporte.
    hint = run(_transfer(), cmd("request_help", kind="prompt", reason="me dá uma pista"))
    assert attempt(hint, "transfer").ledger.level != "none"
    hint = run(hint, cmd("submit_answer", answer=4))
    hint = run(hint, cmd("submit_explanation", text="5 grupos de 4 dão 20"))
    hf = apply(hint, cmd("continue_after_explanation", reason="sufficient"))
    assert hf.events[0].data["outcome"] == "applied_with_support"


@pytest.mark.ac("AC-27")
@pytest.mark.parametrize(
    "mutation,code",
    [
        ({"expected_revision": 0}, "STALE_REVISION"),
        ({"attempt_id": "other-attempt"}, "ATTEMPT_CHANGED"),
        ({"expected_scene_revision": 0}, "STALE_SCENE"),
        (
            {
                "payload": {
                    "piece_id": "piece-01",
                    "from_location": "group-2",
                    "to_location": "group-1",
                }
            },
            "INVALID_SCENE",  # origem da peça incorreta
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
    ],
)
def test_ac27_rejected_commands_leave_no_partial_mutation(mutation, code):
    s = _practice_with([1, 0, 0, 0])
    before = s.model_dump(mode="json")
    with pytest.raises(DomainError) as e:
        apply(s, cmd("move_piece", **mutation))
    assert e.value.code == code
    assert s.model_dump(mode="json") == before  # a entrada continua intacta
    # A mesma sessão segue aceitando o comando correto, na revisão seguinte.
    ok = apply(s, cmd("move_piece", piece_id="piece-02", to_location="group-2"))
    assert ok.session.revision == s.revision + 1


@pytest.mark.ac("AC-39")
def test_ac39_invalid_json_extra_fields_and_unauthorized_actions_change_nothing():
    """A propriedade é a fronteira de parse: o que é rejeitado nunca chega ao apply_command (o HTTP repete isto no incremento 2)."""
    s = _practice_with([1, 0, 0, 0])
    base = {
        "schema_version": "1.0",
        "command_id": "c-x",
        "session_id": s.session_id,
        "attempt_id": s.active_attempt_id,
        "expected_revision": s.revision,
        "expected_scene_revision": s.scene_revision,
    }
    move = {"piece_id": "piece-02", "from_location": "available", "to_location": "group-2"}
    answer = {"answer": 6.0, "explanation": None}
    highlight = {**base, "type": "highlight_group", "payload": {"group_id": "group-1"}}
    tutor_move = {**base, "type": "move_piece", "payload": move, "turn_id": "t", "turn_epoch": 0}
    rejected = [  # (corpo cru, ator, código exato)
        ("{not json", "learner", "INVALID_PAYLOAD"),
        (
            json.dumps({**base, "type": "move_piece", "payload": move, "js": "x"}),
            "learner",
            "INVALID_PAYLOAD",
        ),
        (
            json.dumps({**base, "type": "move_piece", "payload": {**move, "extra": 1}}),
            "learner",
            "INVALID_PAYLOAD",
        ),
        (
            json.dumps({**base, "type": "move_piece", "payload": {"piece_id": "p"}}),
            "learner",
            "INVALID_PAYLOAD",
        ),
        (
            json.dumps({**base, "type": "set_phase", "payload": {"phase": "summary"}}),
            "learner",
            "INVALID_PAYLOAD",
        ),
        (
            json.dumps({**base, "type": "move_piece", "payload": move, "actor": "tutor"}),
            "learner",
            "INVALID_PAYLOAD",
        ),
        (
            json.dumps({**base, "type": "submit_answer", "payload": answer}),
            "learner",
            "INVALID_PAYLOAD",
        ),
        (
            json.dumps(highlight),
            "learner",
            "ACTION_NOT_ALLOWED",
        ),  # ação do tutor, enviada pela criança
        (json.dumps(tutor_move), "tutor", "ACTION_NOT_ALLOWED"),  # o tutor não move peça
    ]
    for raw, actor, code in rejected:
        with pytest.raises(DomainError) as e:
            parse_command(raw, actor)
        assert e.value.code == code, raw
    # Nada chegou ao domínio: um comando válido na mesma sessão avança exatamente uma revisão.
    ok = apply(s, cmd("move_piece", piece_id="piece-02", to_location="group-2"))
    assert ok.session.revision == s.revision + 1 and ok.session.phase == s.phase == "practice"
