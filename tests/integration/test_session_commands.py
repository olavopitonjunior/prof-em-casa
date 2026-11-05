"""SessionService (Task 4): criação, comando transacional e idempotência, em SQLite e Postgres.

Nenhum teste monta estado à mão: a sessão chega à prática por comandos reais pelo serviço. Os
testes de thread usam o SQLite em arquivo sob `tmp_path` (a fixture `db_url`), nunca `:memory:`.
"""

import json
import re
import threading
from datetime import timedelta

import pytest
from app.db.engine import make_engine
from app.db.schema import attempts, command_results, session_credentials, session_events, sessions
from app.domain.division.classification import ExplanationResult
from app.sessions import repository
from app.sessions import service as service_module
from app.sessions.context import ActorContext, default_ids
from app.sessions.credentials import derive_session_token, hash_token
from app.sessions.errors import SessionError
from app.sessions.evaluator import UnavailableEvaluator
from app.sessions.repository import SessionRow
from app.sessions.service import SessionService
from conftest import (
    SYSTEM,
    TOKEN_SECRET,
    VERSION,
    body_of,
    dump_tables,
    event_rows,
    learner_ctx,
    move_body,
    request_id,
    revisions,
    run_parallel,
    send,
    start_practice,
    state_of,
)
from helpers import CONTENT, cmd, submitted
from helpers import _raw as raw_command
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

# --- apoio ---------------------------------------------------------------------------------------


@pytest.fixture
def learner_in_practice(svc):
    return start_practice(svc)


def count_events(svc, sid, type_, *, after) -> int:
    return len(event_rows(svc.engine, sid, type_, after=after))


def pieces_in(snapshot, group_id) -> list[str]:
    return next(g["piece_ids"] for g in snapshot["scene"]["groups"] if g["id"] == group_id)


# --- criação -------------------------------------------------------------------------------------


def test_create_session_returns_snapshot_and_credentials(svc):
    created = svc.create_session(request_id(1), VERSION)
    assert not created.replay
    assert created.controller_id != request_id(1) and created.connection_generation == 1
    assert created.session_token == derive_session_token(TOKEN_SECRET, request_id(1))
    assert created.snapshot["session_id"] == created.session_id
    assert created.snapshot["revision"] == 0 and created.snapshot["connection_generation"] == 1
    assert created.snapshot["phase"] == "source_capture"
    with svc.engine.connect() as conn:
        creds = conn.execute(select(session_credentials)).mappings().all()
    # No banco fica só o hash do token (P2).
    assert [c["token_hash"] for c in creds] == [hash_token(created.session_token)]
    assert created.session_token not in json.dumps(
        [{k: str(v) for k, v in c.items()} for c in creds]
    )


def test_create_session_replay_returns_same_token(svc):
    first = svc.create_session(request_id(1), VERSION)
    again = svc.create_session(request_id(1), VERSION)
    assert again.replay and not first.replay
    assert (again.session_id, again.session_token, again.controller_id) == (
        first.session_id,
        first.session_token,
        first.controller_id,
    )
    other = svc.create_session(request_id(2), VERSION)
    assert other.session_id != first.session_id and other.session_token != first.session_token
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(sessions)).scalar_one() == 2


def test_create_session_replay_does_not_hand_over_a_taken_control(svc):
    """O replay devolve o controle original, nunca o controlador vigente."""
    created = svc.create_session(request_id(1), VERSION)
    with svc.engine.begin() as conn:
        conn.execute(
            sessions.update()
            .where(sessions.c.session_id == created.session_id)
            .values(controller_id="someone-else-entirely", connection_generation=2)
        )
    again = svc.create_session(request_id(1), VERSION)
    # Quem repete o POST depois de uma troca de controle recebe um id que não controla nada.
    assert again.snapshot["connection_generation"] == 2
    assert again.controller_id not in {
        request_id(1),
        "someone-else-entirely",
        created.controller_id,
    }


@pytest.mark.parametrize(
    "req,version,code",
    [
        (request_id(1), "division-sharing-v0", "UNSUPPORTED_CONTENT"),
        ("curto", VERSION, "INVALID_PAYLOAD"),
        ("x" * 129, VERSION, "INVALID_PAYLOAD"),
        ("a" * 21 + "!", VERSION, "INVALID_PAYLOAD"),
        ("a" * 22 + "\n", VERSION, "INVALID_PAYLOAD"),
    ],
)
def test_create_session_rejects_bad_input(svc, req, version, code):
    with pytest.raises(SessionError) as e:
        svc.create_session(req, version)
    assert e.value.code == code
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(sessions)).scalar_one() == 0


def test_create_session_concurrent_same_request_makes_one_session(svc):
    results = run_parallel(8, lambda i: svc.create_session(request_id(1), VERSION))
    assert all(not isinstance(r, Exception) for r in results), results
    assert len({r.session_id for r in results}) == 1
    assert sum(not r.replay for r in results) == 1
    with svc.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(sessions)).scalar_one() == 1


def test_default_ids_are_opaque(engine, clock):
    svc = SessionService(
        engine, CONTENT, UnavailableEvaluator(), token_secret=TOKEN_SECRET, clock=clock
    )
    created = svc.create_session(request_id(1), VERSION)
    assert re.fullmatch(r"ses_[A-Za-z0-9_-]{16}", created.session_id)
    assert default_ids("evt") != default_ids("evt")
    assert re.fullmatch(r"evt_[A-Za-z0-9_-]{16}", default_ids("evt"))


# --- AC-26: idempotência ---------------------------------------------------------------------


@pytest.mark.ac("AC-26")
def test_ac26_same_command_twice_one_effect(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    body = move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-move-1")
    first = svc.execute_command(ctx, sid, body)
    again = svc.execute_command(ctx, sid, body)
    assert again.replay and not first.replay
    assert again.body == first.body and first.body["revision"] == R + 1
    assert first.body["scene_effect"] == {
        "effect_id": f"effect-{S + 1}",
        "requires_ack": "render_applied",
    }
    snap = svc.get_snapshot(ctx, sid)
    assert snap["revision"] == R + 1 and count_events(svc, sid, "scene_changed", after=R) == 1
    assert pieces_in(snap, "group-1") == ["piece-01"]


@pytest.mark.ac("AC-36")
def test_replay_after_revision_advanced_returns_original(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    first_body = move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-move-1")
    first = svc.execute_command(ctx, sid, first_body)
    svc.execute_command(
        ctx,
        sid,
        move_body(svc, sid, rev=R + 1, scene_rev=S + 1, cmd_id="c-move-2", piece="piece-02"),
    )
    assert revisions(svc, sid)[0] == R + 2
    again = svc.execute_command(ctx, sid, first_body)
    assert again.replay and again.body == first.body and again.body["revision"] == R + 1
    assert revisions(svc, sid)[0] == R + 2  # o replay não move nada


def test_key_order_and_whitespace_do_not_change_hash(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    raw = json.loads(move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-move-1"))
    first = svc.execute_command(ctx, sid, json.dumps(raw, separators=(",", ":")).encode())
    reordered = dict(reversed(list(raw.items())))
    reordered["payload"] = dict(reversed(list(raw["payload"].items())))
    again = svc.execute_command(ctx, sid, json.dumps(reordered, indent=4).encode())
    assert again.replay and again.body == first.body
    assert count_events(svc, sid, "scene_changed", after=R) == 1


def test_non_ascii_body_replays(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    state = state_of(svc, sid)
    c = cmd("request_help", kind="prompt", reason="não entendi a pergunta")
    body = json.dumps(raw_command(state, c), ensure_ascii=False).encode("utf-8")
    first = svc.execute_command(ctx, sid, body)
    escaped = json.dumps(raw_command(state, c), ensure_ascii=True).encode()
    assert svc.execute_command(ctx, sid, escaped).body == first.body


# --- AC-27: erros não deixam rastro ----------------------------------------------------------


@pytest.mark.ac("AC-27")
@pytest.mark.parametrize(
    "variant,code",
    [
        ("same_id_other_body", "IDEMPOTENCY_CONFLICT"),
        ("stale_revision", "STALE_REVISION"),
        ("other_attempt", "ATTEMPT_CHANGED"),
        ("wrong_origin", "INVALID_SCENE"),
    ],
)
def test_ac27_errors_leave_no_partial_mutation(svc, learner_in_practice, variant, code):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    if variant == "same_id_other_body":
        svc.execute_command(ctx, sid, move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-move-1"))
        R, S = revisions(svc, sid)
    bodies = {
        "same_id_other_body": move_body(
            svc, sid, rev=R, scene_rev=S, cmd_id="c-move-1", piece="piece-02"
        ),
        "stale_revision": move_body(svc, sid, rev=R - 1, scene_rev=S, cmd_id="c-stale"),
        "other_attempt": move_body(
            svc, sid, rev=R, scene_rev=S, cmd_id="c-other", attempt_id="attempt-1-demonstration"
        ),
        "wrong_origin": move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-origin", frm="group-2"),
    }
    before = dump_tables(svc.engine, sid)
    with pytest.raises(SessionError) as e:
        svc.execute_command(ctx, sid, bodies[variant])
    assert e.value.code == code and dump_tables(svc.engine, sid) == before
    if code == "STALE_REVISION":
        assert e.value.current_revision == R and e.value.current_scene_revision == S
        assert e.value.command_id == "c-stale"


def test_rejected_command_id_is_not_reserved(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    with pytest.raises(SessionError) as e:
        svc.execute_command(ctx, sid, move_body(svc, sid, rev=R - 1, scene_rev=S, cmd_id="c-9"))
    assert e.value.code == "STALE_REVISION"
    ok = svc.execute_command(ctx, sid, move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-9"))
    assert ok.body["status"] == "accepted" and ok.body["revision"] == R + 1 and not ok.replay


def test_same_body_from_other_actor_conflicts(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    body = body_of(state_of(svc, sid), cmd("close_session", reason="learner_stopped"))
    svc.execute_command(ctx, sid, body)
    before = dump_tables(svc.engine, sid)
    with pytest.raises(SessionError) as e:
        svc.execute_command(SYSTEM, sid, body)
    assert e.value.code == "IDEMPOTENCY_CONFLICT" and dump_tables(svc.engine, sid) == before
    assert svc.execute_command(ctx, sid, body).replay  # o dono do corpo continua com o replay


def test_url_body_session_mismatch_invalid_payload(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    before = dump_tables(svc.engine, sid)
    body = move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-1", session_id="ses_other")
    with pytest.raises(SessionError) as e:
        svc.execute_command(ctx, sid, body)
    assert e.value.code == "INVALID_PAYLOAD" and dump_tables(svc.engine, sid) == before


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b'{"a":1,"a":2}',
        b'{"command_id": NaN}',
        b"[]",
        b'{"session_id": "x"}',  # sem command_id
        b'{"command_id": 7}',
        b"\xff\xfe",
    ],
)
def test_malformed_body_is_invalid_payload_without_mutation(svc, learner_in_practice, raw):
    ctx, sid = learner_in_practice
    before = dump_tables(svc.engine, sid)
    with pytest.raises(SessionError) as e:
        svc.execute_command(ctx, sid, raw)
    assert e.value.code == "INVALID_PAYLOAD" and dump_tables(svc.engine, sid) == before


@pytest.mark.parametrize("text", ["a\u0000b", "\ud800"])
def test_text_the_database_cannot_store_is_rejected(svc, learner_in_practice, text):
    """NUL e substituto solto derrubariam o JSONB do Postgres com 500: viram 400 antes de gravar."""
    ctx, sid = learner_in_practice
    state = state_of(svc, sid)
    before = dump_tables(svc.engine, sid)
    body = json.dumps(raw_command(state, cmd("request_help", kind="prompt", reason=text)))
    with pytest.raises(SessionError) as e:
        svc.execute_command(ctx, sid, body.encode())
    assert e.value.code == "INVALID_PAYLOAD" and dump_tables(svc.engine, sid) == before


def test_actor_in_body_and_wrong_actor_are_rejected(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    state = state_of(svc, sid)
    before = dump_tables(svc.engine, sid)
    with pytest.raises(SessionError) as e:
        svc.execute_command(ctx, sid, body_of(state, cmd("check_distribution"), actor="system"))
    assert e.value.code == "INVALID_PAYLOAD"
    # o aluno tentando um comando do sistema
    with pytest.raises(SessionError) as e:
        svc.execute_command(ctx, sid, body_of(state, cmd("run_demo_step", actor="system")))
    assert e.value.code == "ACTION_NOT_ALLOWED" and dump_tables(svc.engine, sid) == before


def test_unavailable_evaluator_maps_to_provider_unavailable(engine, make_service):
    svc = make_service(engine, evaluator=UnavailableEvaluator())
    ctx, sid = start_practice(svc)
    send(svc, ctx, sid, cmd("submit_answer", answer=6))
    before = dump_tables(engine, sid)
    with pytest.raises(SessionError) as e:
        send(svc, ctx, sid, cmd("submit_explanation", text="4 grupos de 6 dão 24"))
    assert e.value.code == "PROVIDER_UNAVAILABLE"
    assert e.value.current_revision == state_of(svc, sid).revision
    assert dump_tables(engine, sid) == before


def test_r27_free_text_evidence_from_the_evaluator_is_never_stored(engine, make_service):
    """R27: o texto livre que o avaliador devolve como `evidence` pode citar a fala da criança;
    nem o estado, nem o evento, nem o ledger o guardam."""
    leak = "LEAK-citacao-da-crianca-quatro-grupos"

    class LeakyEvaluator:
        def evaluate(self, item_id, text):
            return ExplanationResult(rating="sufficient", modality="text", evidence=leak)

    svc = make_service(engine, evaluator=LeakyEvaluator())
    ctx, sid = start_practice(svc)
    send(svc, ctx, sid, cmd("submit_answer", answer=6))
    send(svc, ctx, sid, cmd("submit_explanation", text="4 grupos de 6 dão 24"))

    dumped = json.dumps(dump_tables(engine, sid), default=str)
    assert leak not in dumped
    (evaluated,) = event_rows(engine, sid, "explanation_evaluated")
    assert evaluated["data"] == {"rating": "sufficient", "modality": "text"}  # só estruturado
    stored = state_of(svc, sid).active_attempt.explanation
    assert (stored.rating, stored.modality, stored.evidence) == ("sufficient", "text", None)
    # a classificação segue usando a nota
    assert event_rows(engine, sid, "attempt_evaluated")[-1]["data"]["outcome"]


# --- autorização -----------------------------------------------------------------------------


def test_missing_expired_and_foreign_sessions_look_the_same(svc, clock, learner_in_practice):
    ctx, sid = learner_in_practice
    other = svc.create_session(request_id(2), VERSION)
    foreign = learner_ctx(other)  # credencial da sessão B usada na URL da sessão A
    body = body_of(state_of(svc, sid), cmd("check_distribution"))
    before = dump_tables(svc.engine, sid)

    def seen(call) -> tuple:
        with pytest.raises(SessionError) as e:
            call()
        return (str(e.value), vars(e.value))

    probes = {
        "ghost": (
            lambda: svc.get_snapshot(SYSTEM, "ses_doesnotexist"),
            lambda: svc.execute_command(SYSTEM, "ses_doesnotexist", body),
        ),
        "foreign": (
            lambda: svc.get_snapshot(foreign, sid),
            lambda: svc.execute_command(foreign, sid, body),
        ),
    }
    results = {name: (seen(read), seen(write)) for name, (read, write) in probes.items()}
    assert results["ghost"] == results["foreign"]
    assert results["foreign"][0][1]["code"] == "NOT_FOUND"
    assert sid not in json.dumps(results["foreign"], default=str)
    assert dump_tables(svc.engine, sid) == before

    clock.advance(timedelta(hours=24, seconds=1))  # decisão P11
    assert seen(lambda: svc.get_snapshot(ctx, sid)) == results["ghost"][0]
    assert seen(lambda: svc.execute_command(ctx, sid, body)) == results["ghost"][1]


def test_session_is_valid_until_its_expiry_instant(svc, clock):
    created = svc.create_session(request_id(1), VERSION)
    ctx = learner_ctx(created)
    clock.advance(timedelta(hours=24) - timedelta(microseconds=1))
    assert svc.get_snapshot(ctx, created.session_id)["session_id"] == created.session_id
    clock.advance(timedelta(microseconds=1))
    with pytest.raises(SessionError) as e:
        svc.get_snapshot(ctx, created.session_id)
    assert e.value.code == "NOT_FOUND"


def test_learner_without_the_current_controller_gets_control_lost(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    stale = ActorContext("learner", sid, sid, "some-former-controller")
    before = dump_tables(svc.engine, sid)
    body = move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-1")
    for bad in (stale, ActorContext("learner", sid, sid, None)):
        with pytest.raises(SessionError) as e:
            svc.execute_command(bad, sid, body)
        assert e.value.code == "CONTROL_LOST"
    assert dump_tables(svc.engine, sid) == before
    assert svc.get_snapshot(stale, sid)["revision"] == R  # leitura não exige o controle
    # Mesmo o replay de um comando já aceito exige o controle (autorizar vem antes de procurar).
    svc.execute_command(ctx, sid, body)
    with pytest.raises(SessionError) as e:
        svc.execute_command(stale, sid, body)
    assert e.value.code == "CONTROL_LOST"


def test_control_taken_during_the_request_is_caught_inside_the_transaction(
    svc, learner_in_practice, monkeypatch
):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    real = service_module.parse_command

    def take_control_after_authorization(body, actor):
        command = real(body, actor)  # passos 1 a 5 já passaram; outra aba toma o controle agora
        with svc.engine.begin() as other:
            other.execute(
                sessions.update()
                .where(sessions.c.session_id == sid)
                .values(controller_id="newer-controller", connection_generation=2)
            )
        return command

    monkeypatch.setattr(service_module, "parse_command", take_control_after_authorization)
    with pytest.raises(SessionError) as e:
        svc.execute_command(ctx, sid, move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-1"))
    assert e.value.code == "CONTROL_LOST" and revisions(svc, sid) == (R, S)


# --- persistência ----------------------------------------------------------------------------


def test_events_are_persisted_with_contiguous_sequence(svc, learner_in_practice):
    _, sid = learner_in_practice
    state = state_of(svc, sid)
    rows = event_rows(svc.engine, sid)
    assert [r["event_seq"] for r in rows] == list(range(1, len(rows) + 1))
    assert state.last_event_seq == len(rows) > 0
    assert len({r["event_id"] for r in rows}) == len(rows)
    assert all(r["session_id"] == sid for r in rows)
    assert {r["actor"] for r in rows} == {"learner", "system"}
    # cada evento aponta o comando que o gerou, e a revisão é a da transação que o gravou
    assert all(r["command_id"] and r["revision"] >= 1 for r in rows)
    assert [r["revision"] for r in rows] == sorted(r["revision"] for r in rows)


def test_attempts_read_model_follows_the_state(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    with svc.engine.connect() as conn:
        rows = {
            r["attempt_id"]: dict(r)
            for r in conn.execute(select(attempts).where(attempts.c.session_id == sid)).mappings()
        }
    assert set(rows) == {"attempt-1-demonstration", "attempt-2-guided"}
    assert rows["attempt-1-demonstration"]["status"] == "closed"
    guided = rows["attempt-2-guided"]
    assert guided["status"] == "active" and guided["kind"] == "guided"
    assert guided["outcome"] is None and guided["support_resources"] == []
    revision_before = guided["updated_revision"]

    send(svc, ctx, sid, cmd("request_help", kind="virtual_objects", reason="quero ver as peças"))
    send(svc, ctx, sid, cmd("submit_answer", answer=6))
    with svc.engine.connect() as conn:
        after = {
            r["attempt_id"]: dict(r)
            for r in conn.execute(select(attempts).where(attempts.c.session_id == sid)).mappings()
        }
    guided = after["attempt-2-guided"]
    assert guided["support_resources"] == ["virtual_objects"] and guided["outcome"] is not None
    assert guided["updated_revision"] > revision_before
    # a tentativa que não mudou não ganha revisão nova
    assert after["attempt-1-demonstration"] == rows["attempt-1-demonstration"]


def test_domain_events_are_persisted_as_returned(svc, learner_in_practice, clock):
    """R27: o descarte de uma análise pendente chega ao log como o domínio o emitiu."""
    ctx, sid = learner_in_practice
    send(svc, ctx, sid, cmd("enter_notebook", intent="record_solution"))
    send(svc, ctx, sid, cmd("open_notebook_capture"))
    with svc.engine.begin() as conn:  # o upload e o worker (Task 6) ainda não existem
        row = repository.load_session(conn, sid, for_update=True)
        pending = submitted(row.state, "art-1", 1, "job-1")
        repository.save_session(
            conn,
            expected_revision=row.state.revision,
            row=SessionRow(pending, row.connection_generation, row.controller_id, row.expires_at),
            now=clock(),
        )
    send(svc, ctx, sid, cmd("retake_notebook_photo"))
    (event,) = event_rows(svc.engine, sid, "analysis_superseded")
    assert event["data"] == {"artifact_id": "art-1", "job_id": "job-1", "reason": "retake"}
    assert event["actor"] == "learner" and event["command_id"]
    assert state_of(svc, sid).active_artifact is None


def test_save_session_refuses_a_stale_revision(svc, learner_in_practice, clock):
    _, sid = learner_in_practice
    with svc.engine.begin() as conn:
        row = repository.load_session(conn, sid, for_update=True)
        with pytest.raises(SessionError) as e:
            repository.save_session(
                conn, expected_revision=row.state.revision - 1, row=row, now=clock()
            )
    assert e.value.code == "STALE_REVISION"


def test_restart_reloads_identical_state(db_url, svc, make_service, learner_in_practice):
    ctx, sid = learner_in_practice
    send(svc, ctx, sid, cmd("request_help", kind="virtual_objects", reason="quero ver as peças"))
    R, S = revisions(svc, sid)
    body = move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-move-1")
    first = svc.execute_command(ctx, sid, body)
    old_state, old_snapshot = state_of(svc, sid), svc.get_snapshot(ctx, sid)
    assert old_state.active_attempt.ledger.resources  # há um frozenset de verdade para recarregar

    engine2 = make_engine(db_url)  # "reinício": engine e serviço novos sobre o mesmo banco
    try:
        svc2 = make_service(engine2)
        new_state = state_of(svc2, sid)
        assert new_state == old_state
        assert (
            new_state.active_attempt.ledger.resources == old_state.active_attempt.ledger.resources
        )
        assert isinstance(new_state.active_attempt.ledger.resources, frozenset)
        assert (
            new_state.scene == old_state.scene and new_state.return_phase == old_state.return_phase
        )
        assert svc2.get_snapshot(ctx, sid) == old_snapshot
        again = svc2.execute_command(ctx, sid, body)
        assert again.replay and again.body == first.body
        nxt = svc2.execute_command(
            ctx,
            sid,
            move_body(svc2, sid, rev=R + 1, scene_rev=S + 1, cmd_id="c-2", piece="piece-02"),
        )
        assert nxt.body["revision"] == R + 2 and not nxt.replay
    finally:
        engine2.dispose()


# --- concorrência (Review Focus 1) ---------------------------------------------------------


def test_concurrent_duplicates_single_effect(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    body = move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-move-1")
    results = run_parallel(8, lambda i: svc.execute_command(ctx, sid, body))
    assert all(not isinstance(r, Exception) for r in results), results  # nenhum 500
    assert len({json.dumps(r.body, sort_keys=True) for r in results}) == 1
    assert sum(not r.replay for r in results) == 1
    assert revisions(svc, sid) == (R + 1, S + 1)
    assert count_events(svc, sid, "scene_changed", after=R) == 1
    with svc.engine.connect() as conn:
        rows = conn.execute(
            select(func.count())
            .select_from(command_results)
            .where(command_results.c.command_id == "c-move-1")
        ).scalar_one()
    assert rows == 1


def test_duplicates_that_all_passed_the_lookup_before_any_commit(
    svc, learner_in_practice, monkeypatch
):
    """Força o pior intercalamento: todas as threads passam pelo passo 4 (sem achar nada) antes
    de qualquer transação começar. A trava da linha deve transformar as perdedoras em replay."""
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    body = move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-move-1")
    barrier = threading.Barrier(4)
    real = service_module.parse_command

    def parse_after_everyone_looked_up(raw, actor):
        barrier.wait(timeout=30)
        return real(raw, actor)

    monkeypatch.setattr(service_module, "parse_command", parse_after_everyone_looked_up)
    results = run_parallel(4, lambda i: svc.execute_command(ctx, sid, body))
    assert all(not isinstance(r, Exception) for r in results), results
    assert sum(not r.replay for r in results) == 1
    assert len({json.dumps(r.body, sort_keys=True) for r in results}) == 1
    assert revisions(svc, sid) == (R + 1, S + 1)
    assert count_events(svc, sid, "scene_changed", after=R) == 1


def test_concurrent_same_command_id_other_body_one_accepted(svc, learner_in_practice):
    """Mesmo command_id com corpos diferentes ao mesmo tempo: um só vence, o resto é conflito."""
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)

    def move(i):
        body = move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-same", piece=f"piece-{i + 1:02d}")
        return svc.execute_command(ctx, sid, body)

    results = run_parallel(6, move)
    accepted = [r for r in results if not isinstance(r, Exception)]
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(accepted) == 1 and not accepted[0].replay
    assert len(errors) == 5 and all(isinstance(e, SessionError) for e in errors), errors
    assert {e.code for e in errors} == {"IDEMPOTENCY_CONFLICT"}
    assert revisions(svc, sid) == (R + 1, S + 1)
    assert count_events(svc, sid, "scene_changed", after=R) == 1
    with svc.engine.connect() as conn:
        rows = conn.execute(
            select(func.count())
            .select_from(command_results)
            .where(command_results.c.command_id == "c-same")
        ).scalar_one()
    assert rows == 1


# --- R28 / AC-45: o texto livre da criança não é gravado em lugar nenhum ---------------------

SENTINEL = "Maria Silva 123"


def _raw_text_of_every_row(engine, sid) -> list[str]:
    """Todo texto gravado para a sessão: JSON cru de cada linha de cada tabela."""
    texts = []
    with engine.connect() as conn:
        for table in (sessions, session_events, command_results, attempts, session_credentials):
            query = select(table).where(table.c.session_id == sid)
            texts.extend(
                json.dumps(dict(r), default=str, ensure_ascii=False)
                for r in conn.execute(query).mappings()
            )
    return texts


@pytest.mark.ac("AC-45")
@pytest.mark.parametrize("kind", ["prompt", "worked_step", "virtual_objects"])
def test_request_help_reason_is_never_persisted(svc, learner_in_practice, kind):
    ctx, sid = learner_in_practice
    result = send(svc, ctx, sid, cmd("request_help", kind=kind, reason=SENTINEL))
    assert SENTINEL not in json.dumps(result.body, ensure_ascii=False)
    granted = event_rows(svc.engine, sid, "help_granted")
    assert granted and all(e["data"].get("has_reason") is True for e in granted)
    assert all("reason" not in e["data"] for e in granted)
    texts = _raw_text_of_every_row(svc.engine, sid)
    assert texts, "o teste precisa ler linhas de verdade"
    for text in texts:
        assert SENTINEL not in text
        assert "Maria" not in text
    state = state_of(svc, sid)
    assert SENTINEL not in state.model_dump_json()


def test_concurrent_distinct_commands_same_revision_one_wins(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)

    def move(i):
        body = move_body(
            svc, sid, rev=R, scene_rev=S, cmd_id=f"c-move-{i}", piece=f"piece-{i + 1:02d}"
        )
        return svc.execute_command(ctx, sid, body)

    results = run_parallel(8, move)
    accepted = [r for r in results if not isinstance(r, Exception)]
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(accepted) == 1 and accepted[0].body["revision"] == R + 1
    assert len(errors) == 7
    assert {e.code for e in errors} == {"STALE_REVISION"}
    assert all(e.current_revision == R + 1 for e in errors)
    assert revisions(svc, sid) == (R + 1, S + 1)
    assert len(event_rows(svc.engine, sid, after=R)) == len(
        event_rows(svc.engine, sid, "scene_changed", after=R)
    )


def test_result_race_is_retried_once(svc, learner_in_practice, monkeypatch):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    real = repository.insert_result
    calls = []

    def lose_the_race_once(conn, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            real(conn, **kwargs)  # grava na transação que vai ser desfeita
            raise IntegrityError(
                "insert", {}, Exception("UNIQUE constraint failed: command_results.command_id")
            )
        return real(conn, **kwargs)

    monkeypatch.setattr(repository, "insert_result", lose_the_race_once)
    out = svc.execute_command(ctx, sid, move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-1"))
    assert len(calls) == 2 and out.body["revision"] == R + 1
    assert revisions(svc, sid) == (R + 1, S + 1)  # um efeito só: o primeiro foi desfeito
    assert count_events(svc, sid, "scene_changed", after=R) == 1


def test_result_race_is_not_retried_twice_nor_for_other_constraints(
    svc, learner_in_practice, monkeypatch
):
    ctx, sid = learner_in_practice
    R, S = revisions(svc, sid)
    body = move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-1")
    calls = []

    def always_race(conn, **kwargs):
        calls.append(1)
        raise IntegrityError("insert", {}, Exception("duplicate key ... pk_command_results"))

    monkeypatch.setattr(repository, "insert_result", always_race)
    with pytest.raises(IntegrityError):
        svc.execute_command(ctx, sid, body)
    assert len(calls) == 2 and revisions(svc, sid) == (R, S)

    calls.clear()

    def other_constraint(conn, **kwargs):
        calls.append(1)
        raise IntegrityError("insert", {}, Exception("FOREIGN KEY constraint failed"))

    monkeypatch.setattr(repository, "insert_result", other_constraint)
    with pytest.raises(IntegrityError):
        svc.execute_command(ctx, sid, body)
    assert len(calls) == 1 and revisions(svc, sid) == (R, S)
