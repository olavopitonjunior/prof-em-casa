"""Task 5: autenticação, controle, ACK e retomada por eventos (AC-38, AC-40), em SQLite e Postgres.

A sessão chega à prática por comandos reais pelo serviço (como em `test_session_commands`). Os
testes com threads usam o SQLite em arquivo sob `tmp_path` (fixture `db_url`), nunca `:memory:`.
"""

import json
from datetime import timedelta

import pytest
from app.db.schema import render_receipts, session_events, sessions
from app.domain.division.demonstration import demo_steps
from app.sessions.context import ActorContext
from app.sessions.credentials import derive_session_token, hash_token
from app.sessions.errors import SessionError
from app.sessions.projection import FORBIDDEN_LEARNER_KEYS
from app.sessions.receipts import RenderReceipt, parse_render_receipt
from conftest import TOKEN_SECRET
from helpers import T12_4, cmd
from helpers import _raw as raw_command
from sqlalchemy import func, select
from test_session_commands import (
    SYSTEM,
    VERSION,
    body_of,
    event_rows,
    move_body,
    request_id,
    revisions,
    run_parallel,
    send,
    start_practice,
    state_of,
)

RID_B = "tab-b-request-id-0000000002"
RID_C = "tab-c-request-id-0000000003"
FAKE_TUTOR_TOKEN = "fake-tutor-service-token-for-tests-only"
FAKE_SYSTEM_TOKEN = "fake-system-service-token-for-tests-only"


# --- apoio ---------------------------------------------------------------------------------------


@pytest.fixture
def svc(engine, make_service):
    """Serviço com tokens de serviço falsos para tutor e sistema (visão fica desligada)."""
    return make_service(
        engine,
        service_token_hashes={
            hash_token(FAKE_TUTOR_TOKEN): "tutor",
            hash_token(FAKE_SYSTEM_TOKEN): "system",
        },
    )


@pytest.fixture
def two_tabs(svc):
    """Mesmo token, dois controller ids: a aba A criou a sessão, a aba B ainda não assumiu."""
    tab_a, sid = start_practice(svc)
    tab_b = ActorContext("learner", sid, sid, RID_B)
    return tab_a, tab_b, sid


def receipt(sid, *, generation=1, scene_revision=0, receipt_id="receipt-001", **over):
    raw = {
        "schema_version": "1.0",
        "receipt_id": receipt_id,
        "effect_id": "effect-1",
        "command_id": "cmd-1",
        "session_id": sid,
        "attempt_id": None,
        "scene_revision": scene_revision,
        "connection_generation": generation,
        "status": "render_applied",
        **over,
    }
    return parse_render_receipt(raw)


def keys_of(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()


def count_rows(engine, table, sid) -> int:
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(table).where(table.c.session_id == sid)
        ).scalar_one()


# --- autenticação --------------------------------------------------------------------------------


def test_session_token_authenticates_the_learner_of_that_session(svc):
    created = svc.create_session(request_id(1), VERSION)
    ctx = svc.authenticate(created.session_token, created.controller_id)
    assert ctx == ActorContext(
        "learner", created.session_id, created.session_id, created.controller_id
    )
    assert svc.authenticate(created.session_token, None).controller_id is None


@pytest.mark.parametrize("bearer", [None, "", "not-a-known-token", "x" * 500])
def test_unknown_and_missing_token_unauthenticated(svc, bearer):
    svc.create_session(request_id(1), VERSION)
    with pytest.raises(SessionError) as e:
        svc.authenticate(bearer, "any")
    assert e.value.code == "UNAUTHENTICATED"


def test_token_signed_with_another_secret_is_unknown(svc):
    svc.create_session(request_id(1), VERSION)
    forged = derive_session_token(b"some-other-secret", request_id(1))
    assert forged != derive_session_token(TOKEN_SECRET, request_id(1))
    with pytest.raises(SessionError) as e:
        svc.authenticate(forged, request_id(1))
    assert e.value.code == "UNAUTHENTICATED"


def test_service_token_gives_a_service_actor_without_session(svc):
    tutor = svc.authenticate(FAKE_TUTOR_TOKEN, "ignored-header")
    assert tutor == ActorContext("tutor", "tutor-service", None, None)
    assert svc.authenticate(FAKE_SYSTEM_TOKEN, None).actor == "system"


def test_vision_worker_is_off_without_its_token(svc):
    with pytest.raises(SessionError) as e:
        svc.authenticate("fake-vision-service-token-not-configured", None)
    assert e.value.code == "UNAUTHENTICATED"


def test_tutor_service_token_runs_tutor_command(svc):
    created = svc.create_session(request_id(1), VERSION)
    sid = created.session_id
    learner = svc.authenticate(created.session_token, created.controller_id)
    send(svc, learner, sid, cmd("choose_reference_activity"))
    tutor = svc.authenticate(FAKE_TUTOR_TOKEN, None)
    before = state_of(svc, sid)
    step = demo_steps(T12_4, 3)[0].step_id
    out = send(svc, tutor, sid, cmd("run_demo_step", actor="tutor", step_id=step))
    assert out.status_code == 200 and out.body["revision"] == before.revision + 1
    actors = {e["actor"] for e in event_rows(svc.engine, sid, after=before.revision)}
    assert actors == {"tutor"}
    # O ator vem da credencial, nunca do corpo: o aluno não executa o comando do tutor.
    with pytest.raises(SessionError) as e:
        send(svc, learner, sid, cmd("run_demo_step", actor="tutor", step_id=step))
    assert e.value.code in {"INVALID_PAYLOAD", "ACTION_NOT_ALLOWED"}


def test_tutor_scene_command_reaches_the_domain(svc, two_tabs):
    """`highlight_group` autentica e valida (turn_id/turn_epoch); o domínio ainda não o implementa
    (D7, `not_in_increment_1`), então a recusa vem de lá e não da camada de acesso."""
    _, _, sid = two_tabs
    tutor = svc.authenticate(FAKE_TUTOR_TOKEN, None)
    body = json.loads(body_of(state_of(svc, sid), cmd("highlight_group", actor="tutor")))
    assert body["turn_id"] and body["turn_epoch"] == state_of(svc, sid).turn_epoch
    with pytest.raises(SessionError) as e:
        svc.execute_command(tutor, sid, json.dumps(body).encode())
    assert (e.value.code, e.value.detail) == ("ACTION_NOT_ALLOWED", "not_in_increment_1")


# --- AC-38: segunda aba assume o controle ---------------------------------------------------------


@pytest.mark.ac("AC-38")
def test_ac38_second_tab_takes_control(svc, two_tabs):
    tab_a, tab_b, sid = two_tabs
    R, S = revisions(svc, sid)
    E = state_of(svc, sid).turn_epoch
    out = svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R)
    assert out == {
        "controller_id": RID_B,
        "connection_generation": 2,
        "revision": R + 1,
        "turn_epoch": E + 1,
    }
    # A aba A perdeu a escrita, mesmo com a revisão certa; nada mudou.
    with pytest.raises(SessionError) as e:
        svc.execute_command(
            tab_a, sid, move_body(svc, sid, rev=R + 1, scene_rev=S, cmd_id="c-old-tab")
        )
    assert e.value.code == "CONTROL_LOST"
    # ...e perdeu o ACK.
    with pytest.raises(SessionError) as e:
        svc.record_render_receipt(tab_a, sid, receipt(sid, generation=1))
    assert e.value.code == "CONTROL_LOST"
    assert count_rows(svc.engine, render_receipts, sid) == 0
    # O ACK da geração anterior, mesmo vindo do controlador novo, é obsoleto.
    assert svc.record_render_receipt(tab_b, sid, receipt(sid, generation=1))["outcome"] == "stale"
    # Sem bifurcação: uma linha de revisão, lida por qualquer aba.
    assert svc.get_snapshot(tab_a, sid)["revision"] == R + 1
    assert svc.get_snapshot(tab_b, sid)["connection_generation"] == 2
    # A aba B segue escrevendo normalmente.
    moved = svc.execute_command(
        tab_b, sid, move_body(svc, sid, rev=R + 1, scene_rev=S, cmd_id="c-new-tab")
    )
    assert moved.body["revision"] == R + 2
    assert svc.record_render_receipt(
        tab_b, sid, receipt(sid, generation=2, scene_revision=S + 1, receipt_id="receipt-002")
    ) == {"receipt_id": "receipt-002", "outcome": "accepted"}


def test_old_controller_cannot_pause(svc, two_tabs):
    tab_a, tab_b, sid = two_tabs
    R, _ = revisions(svc, sid)
    svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R)
    with pytest.raises(SessionError) as e:
        send(svc, tab_a, sid, cmd("pause_session"))
    assert e.value.code == "CONTROL_LOST"
    assert state_of(svc, sid).session_status == "active"
    send(svc, tab_b, sid, cmd("pause_session"))
    assert state_of(svc, sid).session_status == "paused"


def test_header_missing_or_wrong_cannot_write(svc, two_tabs):
    _, _, sid = two_tabs
    created_token = derive_session_token(TOKEN_SECRET, request_id(1))
    for header in (None, "somebody-else"):
        ctx = svc.authenticate(created_token, header)
        with pytest.raises(SessionError) as e:
            send(svc, ctx, sid, cmd("pause_session"))
        assert e.value.code == "CONTROL_LOST"
        assert svc.get_snapshot(ctx, sid)["revision"] == revisions(svc, sid)[0]  # leitura livre


def test_claim_control_records_a_projected_event(svc, two_tabs):
    _, tab_b, sid = two_tabs
    state = state_of(svc, sid)
    svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=state.revision)
    after = state_of(svc, sid)
    assert after.last_event_seq == state.last_event_seq + 1
    assert after.turn_epoch == state.turn_epoch + 1
    (row,) = event_rows(svc.engine, sid, "control_claimed")
    assert row["event_seq"] == after.last_event_seq and row["revision"] == after.revision
    assert row["command_id"] == RID_B
    assert row["data"] == {"connection_generation": 2, "turn_epoch": state.turn_epoch + 1}
    (projected,) = [e for e in svc.list_events(tab_b, sid, after_seq=state.last_event_seq) if True]
    assert projected["type"] == "control_claimed" and projected["data"] == row["data"]


def test_claim_control_replay_is_idempotent(svc, two_tabs):
    _, tab_b, sid = two_tabs
    R, _ = revisions(svc, sid)
    first = svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R)
    again = svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R)
    assert again == first and again["connection_generation"] == 2
    assert revisions(svc, sid)[0] == R + 1
    assert len(event_rows(svc.engine, sid, "control_claimed")) == 1
    # O replay chega depois que outra aba assumiu: devolve a resposta original, sem retomar o controle.
    tab_c = ActorContext("learner", sid, sid, RID_C)
    svc.claim_control(tab_c, sid, request_id=RID_C, expected_revision=R + 1)
    assert svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R) == first
    with pytest.raises(SessionError) as e:
        send(svc, tab_b, sid, cmd("pause_session"))
    assert e.value.code == "CONTROL_LOST"
    assert state_of(svc, sid).revision == R + 2


def test_claim_control_same_request_with_other_revision_conflicts(svc, two_tabs):
    _, tab_b, sid = two_tabs
    R, _ = revisions(svc, sid)
    svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R)
    with pytest.raises(SessionError) as e:
        svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R + 1)
    assert e.value.code == "IDEMPOTENCY_CONFLICT"


def test_claim_control_request_id_cannot_reuse_a_command_id(svc, two_tabs):
    tab_a, tab_b, sid = two_tabs
    R, S = revisions(svc, sid)
    svc.execute_command(tab_a, sid, move_body(svc, sid, rev=R, scene_rev=S, cmd_id=RID_B))
    with pytest.raises(SessionError) as e:
        svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R + 1)
    assert e.value.code == "IDEMPOTENCY_CONFLICT"


def test_claim_control_with_stale_revision(svc, two_tabs):
    _, tab_b, sid = two_tabs
    R, _ = revisions(svc, sid)
    before = state_of(svc, sid)
    with pytest.raises(SessionError) as e:
        svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R - 1)
    assert e.value.code == "STALE_REVISION" and e.value.current_revision == R
    assert state_of(svc, sid) == before
    assert event_rows(svc.engine, sid, "control_claimed") == []
    # Rejeição não ocupa o request_id (P5): repetir com a revisão certa funciona.
    assert svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R)["revision"] == R + 1


def test_claim_control_on_closed_session_is_refused(svc, two_tabs):
    tab_a, tab_b, sid = two_tabs
    send(svc, tab_a, sid, cmd("close_session"))
    R, _ = revisions(svc, sid)
    assert state_of(svc, sid).session_status == "closed"
    with pytest.raises(SessionError) as e:
        svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R)
    assert e.value.code == "ACTION_NOT_ALLOWED"
    assert state_of(svc, sid).revision == R


@pytest.mark.parametrize("who", ["tutor", "system"])
def test_service_actors_cannot_claim_control(svc, two_tabs, who):
    _, _, sid = two_tabs
    ctx = ActorContext(who, f"{who}-service", None, None)
    with pytest.raises(SessionError) as e:
        svc.claim_control(ctx, sid, request_id=RID_B, expected_revision=revisions(svc, sid)[0])
    assert e.value.code == "ACTION_NOT_ALLOWED"


@pytest.mark.parametrize("rid", ["curto", "a" * 21 + "!", "x" * 129, ""])
def test_claim_control_rejects_a_weak_request_id(svc, two_tabs, rid):
    _, tab_b, sid = two_tabs
    with pytest.raises(SessionError) as e:
        svc.claim_control(tab_b, sid, request_id=rid, expected_revision=revisions(svc, sid)[0])
    assert e.value.code == "INVALID_PAYLOAD"


@pytest.mark.parametrize("rev", [-1, 2**31, True, "3", None])
def test_claim_control_rejects_a_bad_revision(svc, two_tabs, rev):
    _, tab_b, sid = two_tabs
    with pytest.raises(SessionError) as e:
        svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=rev)
    assert e.value.code == "INVALID_PAYLOAD"


def test_concurrent_claims_have_one_winner(svc, two_tabs):
    _, _, sid = two_tabs
    R, _ = revisions(svc, sid)
    rids = [f"claim-request-id-{n:010d}-abc" for n in range(4)]

    def claim(i):
        ctx = ActorContext("learner", sid, sid, rids[i])
        return svc.claim_control(ctx, sid, request_id=rids[i], expected_revision=R)

    results = run_parallel(4, claim)
    winners = [r for r in results if isinstance(r, dict)]
    losers = [r for r in results if isinstance(r, SessionError)]
    assert len(winners) == 1 and len(losers) == 3, results
    assert {e.code for e in losers} == {"STALE_REVISION"}
    state = state_of(svc, sid)
    assert state.revision == R + 1
    assert len(event_rows(svc.engine, sid, "control_claimed")) == 1
    with svc.engine.connect() as conn:
        row = conn.execute(select(sessions.c.connection_generation, sessions.c.controller_id)).one()
    assert row.connection_generation == 2 and row.controller_id in rids


# --- ACK de render ------------------------------------------------------------------------------


def test_receipt_duplicate_and_no_revision_change(svc, two_tabs):
    tab_a, _, sid = two_tabs
    R, S = revisions(svc, sid)
    first = svc.record_render_receipt(tab_a, sid, receipt(sid, scene_revision=S))
    assert first == {"receipt_id": "receipt-001", "outcome": "accepted"}
    again = svc.record_render_receipt(tab_a, sid, receipt(sid, scene_revision=S))
    assert again == {"receipt_id": "receipt-001", "outcome": "duplicate"}
    # Mesmo id com outro conteúdo continua sendo o mesmo ACK.
    other = receipt(sid, scene_revision=S, status="render_failed")
    assert svc.record_render_receipt(tab_a, sid, other)["outcome"] == "duplicate"
    assert count_rows(svc.engine, render_receipts, sid) == 1
    assert revisions(svc, sid) == (R, S)
    with svc.engine.connect() as conn:
        row = conn.execute(select(render_receipts)).mappings().one()
    assert (row["outcome"], row["status"], row["connection_generation"]) == (
        "accepted",
        "render_applied",
        1,
    )


def test_receipt_stale_when_generation_differs_or_scene_is_ahead(svc, two_tabs):
    tab_a, _, sid = two_tabs
    _, S = revisions(svc, sid)
    outcomes = {
        name: svc.record_render_receipt(tab_a, sid, receipt(sid, receipt_id=name, **over))[
            "outcome"
        ]
        for name, over in {
            "older-generation": {"generation": 1, "scene_revision": S + 1},
            "newer-generation": {"generation": 2, "scene_revision": S},
            "future-scene": {"generation": 1, "scene_revision": S + 1},
            "current": {"generation": 1, "scene_revision": S},
            "older-scene": {"generation": 1, "scene_revision": max(S - 1, 0)},
        }.items()
    }
    assert outcomes == {
        "older-generation": "stale",
        "newer-generation": "stale",
        "future-scene": "stale",
        "current": "accepted",
        "older-scene": "accepted",
    }
    with svc.engine.connect() as conn:
        rows = conn.execute(select(render_receipts.c.receipt_id, render_receipts.c.outcome))
        stored = {r.receipt_id: r.outcome for r in rows}
    assert stored == outcomes


@pytest.mark.parametrize(
    "status",
    ["render_applied", "animation_completed", "settled_by_interruption", "render_failed"],
)
def test_receipt_accepts_every_spec_status(svc, two_tabs, status):
    tab_a, _, sid = two_tabs
    _, S = revisions(svc, sid)
    out = svc.record_render_receipt(tab_a, sid, receipt(sid, scene_revision=S, status=status))
    assert out["outcome"] == "accepted"


@pytest.mark.parametrize(
    "over",
    [
        {"status": "done"},
        {"extra_field": 1},
        {"schema_version": "2.0"},
        {"connection_generation": 0},
        {"connection_generation": "1"},
        {"scene_revision": -1},
        {"scene_revision": 2**31},
        {"receipt_id": ""},
        {"receipt_id": "a" * 129},
        {"receipt_id": "bad id"},
    ],
)
def test_receipt_model_is_strict(over):
    with pytest.raises(SessionError) as e:
        receipt("ses_x", **over)
    assert e.value.code == "INVALID_PAYLOAD"
    assert isinstance(receipt("ses_x"), RenderReceipt)


def test_receipt_for_another_session_id_in_body_is_invalid(svc, two_tabs):
    tab_a, _, sid = two_tabs
    with pytest.raises(SessionError) as e:
        svc.record_render_receipt(tab_a, sid, receipt("ses_other"))
    assert e.value.code == "INVALID_PAYLOAD"
    assert count_rows(svc.engine, render_receipts, sid) == 0


def test_only_the_controlling_learner_sends_receipts(svc, two_tabs):
    _, _, sid = two_tabs
    tutor = svc.authenticate(FAKE_TUTOR_TOKEN, None)
    with pytest.raises(SessionError) as e:
        svc.record_render_receipt(tutor, sid, receipt(sid))
    assert e.value.code == "ACTION_NOT_ALLOWED"


# --- eventos: retomada incremental -----------------------------------------------------------------


def test_events_after_seq_projected_for_learner(svc, two_tabs):
    tab_a, _, sid = two_tabs
    send(svc, tab_a, sid, cmd("request_help"))
    send(svc, tab_a, sid, cmd("submit_answer", answer=3))
    last = state_of(svc, sid).last_event_seq
    assert last > 4
    events = svc.list_events(tab_a, sid, after_seq=3)
    assert [e["event_seq"] for e in events] == list(range(4, last + 1))
    assert {"answer_submitted", "attempt_evaluated", "help_granted"} <= {e["type"] for e in events}
    for event in events:
        assert not keys_of(event) & FORBIDDEN_LEARNER_KEYS
        assert "actor" not in event and "command_id" not in event
    assert svc.list_events(tab_a, sid, after_seq=last) == []
    assert [e["event_seq"] for e in svc.list_events(tab_a, sid)][:2] == [1, 2]  # padrão: do início


def test_events_service_view_keeps_the_full_record(svc, two_tabs):
    tab_a, _, sid = two_tabs
    send(svc, tab_a, sid, cmd("submit_answer", answer=3))
    tutor = svc.authenticate(FAKE_TUTOR_TOKEN, None)
    events = svc.list_events(tutor, sid, after_seq=0)
    evaluated = next(e for e in events if e["type"] == "attempt_evaluated")
    assert "outcome" in evaluated["data"] and evaluated["actor"] == "learner"
    seqs = [e["event_seq"] for e in events]
    assert seqs == sorted(seqs) == list(range(1, len(seqs) + 1))
    with svc.engine.connect() as conn:
        stored = conn.execute(select(func.count()).select_from(session_events)).scalar_one()
    assert len(seqs) == stored


def test_events_are_paged_by_limit_without_gaps(svc, two_tabs):
    tab_a, _, sid = two_tabs
    last = state_of(svc, sid).last_event_seq
    seen, cursor = [], 0
    while True:
        page = svc.list_events(tab_a, sid, after_seq=cursor, limit=3)
        assert len(page) <= 3
        if not page:
            break
        seen += [e["event_seq"] for e in page]
        cursor = page[-1]["event_seq"]
    assert seen == list(range(1, last + 1))


@pytest.mark.parametrize("kwargs", [{"after_seq": -1}, {"limit": 0}, {"limit": 1001}])
def test_events_reject_bad_cursor_or_limit(svc, two_tabs, kwargs):
    tab_a, _, sid = two_tabs
    with pytest.raises(SessionError) as e:
        svc.list_events(tab_a, sid, **kwargs)
    assert e.value.code == "INVALID_PAYLOAD"


# --- AC-40 e expiração ----------------------------------------------------------------------------


@pytest.mark.ac("AC-40")
def test_ac40_service_level_cross_session(svc):
    a = svc.create_session(request_id(1), VERSION)
    b = svc.create_session(request_id(2), VERSION)
    ctx_a = svc.authenticate(a.session_token, a.controller_id)
    ctx_b = svc.authenticate(b.session_token, b.controller_id)
    sid_a, sid_b = a.session_id, b.session_id
    # B faz um trabalho real, para que haja algo a vazar (inclusive uma chave idempotente conhecida).
    body_b = json.dumps(
        {
            **raw_command(state_of(svc, sid_b), cmd("choose_reference_activity")),
            "command_id": "known-id",
        }
    ).encode()
    svc.execute_command(ctx_b, sid_b, body_b)
    snapshot_b = dict(dump_state(svc, sid_b))
    absent = "ses_does_not_exist"

    def attempts_on(target):
        calls = {
            "get": lambda: svc.get_snapshot(ctx_a, target),
            "command": lambda: svc.execute_command(ctx_a, target, body_b),
            "claim": lambda: svc.claim_control(
                ctx_a, target, request_id=RID_B, expected_revision=0
            ),
            "receipt": lambda: svc.record_render_receipt(
                ctx_a, target, receipt(target, generation=1)
            ),
            "events": lambda: svc.list_events(ctx_a, target),
        }
        errors = {}
        for name, call in calls.items():
            with pytest.raises(SessionError) as e:
                call()
            errors[name] = (e.value.code, e.value.detail, e.value.current_revision)
        return errors

    on_b, on_absent = attempts_on(sid_b), attempts_on(absent)
    assert {code for code, _, _ in on_b.values()} == {"NOT_FOUND"}
    assert on_b == on_absent  # indistinguível de uma sessão que não existe
    assert dump_state(svc, sid_b) == snapshot_b  # nada de B mudou
    assert count_rows(svc.engine, render_receipts, sid_b) == 0
    assert event_rows(svc.engine, sid_b, "control_claimed") == []
    # B lê o que é seu e A continua só com o que é seu.
    assert svc.get_snapshot(ctx_b, sid_b)["session_id"] == sid_b
    assert svc.get_snapshot(ctx_a, sid_a)["session_id"] == sid_a
    # Credencial de B não alcança A (simetria) e serviço alcança as duas.
    with pytest.raises(SessionError) as e:
        svc.get_snapshot(ctx_b, sid_a)
    assert e.value.code == "NOT_FOUND"
    assert svc.get_snapshot(SYSTEM, sid_a)["session_id"] == sid_a


def dump_state(svc, sid) -> dict:
    state = state_of(svc, sid)
    return {
        "state": state.model_dump(mode="json"),
        "events": svc.list_events(SYSTEM, sid),
    }


def test_expired_session_is_not_found(svc, two_tabs, clock):
    tab_a, _, sid = two_tabs
    R, S = revisions(svc, sid)
    clock.advance(timedelta(hours=24) - timedelta(minutes=1))
    assert svc.get_snapshot(tab_a, sid)["session_id"] == sid  # ainda vale
    clock.advance(timedelta(minutes=1) + timedelta(seconds=1))
    calls = [
        lambda: svc.get_snapshot(tab_a, sid),
        lambda: svc.list_events(tab_a, sid),
        lambda: svc.execute_command(
            tab_a, sid, move_body(svc, sid, rev=R, scene_rev=S, cmd_id="c-late")
        ),
        lambda: svc.claim_control(tab_a, sid, request_id=RID_B, expected_revision=R),
        lambda: svc.record_render_receipt(tab_a, sid, receipt(sid)),
        lambda: svc.get_snapshot(SYSTEM, sid),
        lambda: svc.list_events(SYSTEM, sid),
    ]
    for call in calls:
        with pytest.raises(SessionError) as e:
            call()
        assert e.value.code == "NOT_FOUND"
    # Autenticar ainda funciona (prova quem é); a sessão é que não existe mais.
    assert (
        svc.authenticate(derive_session_token(TOKEN_SECRET, request_id(1)), None).session_id == sid
    )
