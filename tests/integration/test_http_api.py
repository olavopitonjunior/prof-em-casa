"""Task 7: rotas `/v1`, envelope de erro e plateia (R29), em SQLite e Postgres.

A sessão chega à prática por comandos reais pelo serviço (como em `test_session_commands`); o que
se testa aqui é a borda HTTP: status, envelope, cabeçalhos, 404 indistinguível (AC-40) e o corte
do texto de detalhe do domínio para o aluno (R29).
"""

import json
from typing import get_args

import pytest
from app.api.app import create_app
from app.api.errors import HTTP_STATUS, MAX_BODY_BYTES, RETRYABLE, error_body, error_response
from app.db.schema import sessions
from app.domain.division.errors import DomainError, ErrorCode
from app.sessions.context import ActorContext
from app.sessions.credentials import derive_session_token, hash_token
from app.sessions.errors import SessionError
from app.sessions.evaluator import UnavailableEvaluator
from conftest import (
    TOKEN_SECRET,
    VERSION,
    body_of,
    move_body,
    moved_effect,
    request_id,
    revisions,
    send,
    start_practice,
    state_of,
)
from fastapi.testclient import TestClient
from helpers import cmd
from sqlalchemy import func, select

TUTOR_TOKEN = "fake-tutor-service-token-for-tests-only"
SYSTEM_TOKEN = "fake-system-service-token-for-tests-only"
LEARNER_ERROR_KEYS = {"code", "retryable", "current_revision", "current_scene_revision"}


# --- apoio ---------------------------------------------------------------------------------------


@pytest.fixture
def svc(engine, make_service):
    return make_service(
        engine,
        service_token_hashes={
            hash_token(TUTOR_TOKEN): "tutor",
            hash_token(SYSTEM_TOKEN): "system",
        },
    )


@pytest.fixture
def client(svc):
    with TestClient(create_app(svc)) as c:
        yield c


def auth(token, controller=None) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if controller is not None:
        headers["X-Controller-Id"] = controller
    return headers


class Practice:
    """Sessão em prática: id, token da sessão, controlador vigente e os cabeçalhos do aluno."""

    def __init__(self, svc, n: int):
        ctx, self.sid = start_practice(svc, n)
        self.token = derive_session_token(TOKEN_SECRET, request_id(n))
        self.controller = ctx.controller_id
        self.headers = auth(self.token, self.controller)
        self.cmd_url = f"/v1/sessions/{self.sid}/commands"
        self.sess_url = f"/v1/sessions/{self.sid}"


@pytest.fixture
def practice(svc):
    return Practice(svc, 1)


@pytest.fixture
def two_sessions(svc):
    return Practice(svc, 1), Practice(svc, 2)


def revision(client, p: Practice) -> int:
    return client.get(p.sess_url, headers=p.headers).json()["revision"]


def fresh_move(svc, p: Practice, cmd_id="c-move-1", **over) -> bytes:
    rev, scene = revisions(svc, p.sid)
    return move_body(svc, p.sid, rev=rev, scene_rev=scene, cmd_id=cmd_id, **over)


# --- tabelas -------------------------------------------------------------------------------------


def test_every_error_code_has_a_status_and_the_tables_match_the_spec():
    http_only = {
        "PAYLOAD_TOO_LARGE",
        "INTERNAL_ERROR",
        "METHOD_NOT_ALLOWED",
        "UNSUPPORTED_MEDIA_TYPE",
    }
    assert set(HTTP_STATUS) == set(get_args(ErrorCode)) | http_only
    assert HTTP_STATUS["PAYLOAD_TOO_LARGE"] == 413 and HTTP_STATUS["INTERNAL_ERROR"] == 500
    assert HTTP_STATUS["METHOD_NOT_ALLOWED"] == 405
    assert HTTP_STATUS["UNSUPPORTED_MEDIA_TYPE"] == 415
    assert HTTP_STATUS["STALE_TURN"] == 409 and "STALE_TURN" not in RETRYABLE  # extensão R30
    assert RETRYABLE == {
        "STALE_REVISION",
        "STALE_SCENE",
        "ATTEMPT_CHANGED",
        "INVALID_TRANSITION",
        "PROVIDER_UNAVAILABLE",
    }
    spec = {
        "INVALID_PAYLOAD": 400,
        "UNAUTHENTICATED": 401,
        "ACTION_NOT_ALLOWED": 403,
        "CONTROL_LOST": 403,
        "NOT_FOUND": 404,
        "IDEMPOTENCY_CONFLICT": 409,
        "IMAGE_TOO_LARGE": 413,
        "UNSUPPORTED_IMAGE": 415,
        "INVALID_SCENE": 422,
        "NO_OP": 422,
        "UNSUPPORTED_CONTENT": 422,
        "SESSION_LIMIT": 429,
        "PROVIDER_UNAVAILABLE": 503,
    }
    assert {code: HTTP_STATUS[code] for code in spec} == spec


# --- criação -------------------------------------------------------------------------------------


def test_create_session_201_then_replay_header(client):
    body = {"request_id": request_id(7), "content_version": VERSION}
    first = client.post("/v1/sessions", json=body)
    again = client.post("/v1/sessions", json=body)
    assert first.status_code == again.status_code == 201
    assert "Idempotent-Replay" not in first.headers
    assert again.headers["Idempotent-Replay"] == "true"
    assert "replay" not in first.json()
    assert set(first.json()) == {
        "session_id",
        "session_token",
        "controller_id",
        "connection_generation",
        "snapshot",
    }
    assert again.json()["session_id"] == first.json()["session_id"]
    token, sid = first.json()["session_token"], first.json()["session_id"]
    got = client.get(f"/v1/sessions/{sid}", headers=auth(token))
    assert got.status_code == 200 and got.json()["session_id"] == sid


# --- AC-26 / AC-27 -------------------------------------------------------------------------------


@pytest.mark.ac("AC-26")
def test_http_replay_header_and_single_effect(client, svc, practice):
    body = fresh_move(svc, practice)
    before = revision(client, practice)
    first = client.post(practice.cmd_url, content=body, headers=practice.headers)
    again = client.post(practice.cmd_url, content=body, headers=practice.headers)
    assert first.status_code == again.status_code == 200
    assert "Idempotent-Replay" not in first.headers
    assert again.headers["Idempotent-Replay"] == "true"
    assert again.json() == first.json() and first.json()["revision"] == before + 1
    assert revision(client, practice) == before + 1  # um efeito só
    assert set(first.json()) == {
        "command_id",
        "status",
        "revision",
        "scene_revision",
        "event_seq",
        "scene_effect",
    }


@pytest.mark.ac("AC-27")
@pytest.mark.parametrize(
    "variant,status,code",
    [
        ("same_id_other_body", 409, "IDEMPOTENCY_CONFLICT"),
        ("stale_revision", 409, "STALE_REVISION"),
        ("other_attempt", 409, "ATTEMPT_CHANGED"),
        ("wrong_origin", 422, "INVALID_SCENE"),
    ],
)
def test_ac27_http_codes(client, svc, practice, variant, status, code):
    p = practice
    R, S = revisions(svc, p.sid)
    if variant == "same_id_other_body":
        client.post(p.cmd_url, content=fresh_move(svc, p), headers=p.headers)
        R, S = revisions(svc, p.sid)
    bodies = {
        "same_id_other_body": move_body(
            svc, p.sid, rev=R, scene_rev=S, cmd_id="c-move-1", piece="piece-02"
        ),
        "stale_revision": move_body(svc, p.sid, rev=R - 1, scene_rev=S, cmd_id="c-stale"),
        "other_attempt": move_body(
            svc, p.sid, rev=R, scene_rev=S, cmd_id="c-other", attempt_id="attempt-1-demonstration"
        ),
        "wrong_origin": move_body(svc, p.sid, rev=R, scene_rev=S, cmd_id="c-origin", frm="group-2"),
    }
    r = client.post(p.cmd_url, content=bodies[variant], headers=p.headers)
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert r.json()["error"]["retryable"] is (code in RETRYABLE)
    assert revision(client, p) == R


def test_stale_revision_carries_current_revisions(client, svc, practice):
    R, S = revisions(svc, practice.sid)
    body = move_body(svc, practice.sid, rev=R - 1, scene_rev=S, cmd_id="c-stale")
    r = client.post(practice.cmd_url, content=body, headers=practice.headers)
    assert r.json() == {
        "command_id": "c-stale",
        "error": {
            "code": "STALE_REVISION",
            "retryable": True,
            "current_revision": R,
            "current_scene_revision": S,
        },
    }


# --- AC-39: borda --------------------------------------------------------------------------------


@pytest.mark.ac("AC-39")
@pytest.mark.parametrize(
    "kind", ["broken_json", "duplicate_keys", "nan", "extra_field", "actor_in_body", "unknown_type"]
)
def test_ac39_http_edge_rejects_without_mutation(client, svc, practice, kind):
    base = json.loads(fresh_move(svc, practice))
    raw = {
        "broken_json": b"{",
        "duplicate_keys": b'{"a":1,"a":2}',
        "nan": json.dumps(base)
        .replace('"expected_revision": ', '"expected_revision": NaN, "x": ')
        .encode(),
        "extra_field": json.dumps({**base, "surprise": 1}).encode(),
        "actor_in_body": json.dumps({**base, "actor": "tutor"}).encode(),
        "unknown_type": json.dumps({**base, "type": "no_such_command"}).encode(),
    }[kind]
    R = revision(client, practice)
    r = client.post(practice.cmd_url, content=raw, headers=practice.headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PAYLOAD"
    assert revision(client, practice) == R


# --- AC-40: sessão de outro é sessão inexistente -------------------------------------------------

ROUTES = [
    ("GET", "/v1/sessions/{id}"),
    ("POST", "/v1/sessions/{id}/commands"),
    ("POST", "/v1/sessions/{id}/claim-control"),
    ("POST", "/v1/sessions/{id}/render-receipts"),
    ("GET", "/v1/sessions/{id}/events?after_seq=0"),
]


def body_for(path: str, sid: str, known_command: bytes) -> bytes | None:
    if path.endswith("/commands"):
        return known_command  # `command_id` conhecido de B, apontando para a URL pedida
    if path.endswith("/claim-control"):
        return json.dumps({"request_id": request_id(9), "expected_revision": 0}).encode()
    if path.endswith("/render-receipts"):
        return json.dumps(
            {
                "schema_version": "1.0",
                "receipt_id": "receipt-001",
                "effect_id": "effect-1",
                "command_id": "cmd-1",
                "session_id": sid,
                "attempt_id": None,
                "scene_revision": 0,
                "connection_generation": 1,
                "status": "render_applied",
            }
        ).encode()
    return None


@pytest.mark.ac("AC-40")
@pytest.mark.parametrize("method,path", ROUTES)
def test_ac40_token_a_on_session_b(client, svc, two_sessions, method, path):
    a, b = two_sessions
    known = fresh_move(svc, b, cmd_id="c-known-of-b")

    def call(sid):
        return client.request(
            method,
            path.format(id=sid),
            headers={**a.headers, "Content-Type": "application/json"},
            content=body_for(path, sid, known),
        )

    foreign, ghost = call(b.sid), call("ses_doesnotexist")
    assert foreign.status_code == ghost.status_code == 404
    assert foreign.content == ghost.content  # byte a byte
    assert foreign.json() == {"error": {"code": "NOT_FOUND", "retryable": False}}
    assert b.sid not in foreign.text
    assert dict(foreign.headers).keys() == dict(ghost.headers).keys()


@pytest.mark.ac("AC-40")
def test_ac40_service_token_on_missing_session_is_the_same_404(client, svc, two_sessions):
    _, b = two_sessions
    ghost = client.get("/v1/sessions/ses_doesnotexist", headers=auth(TUTOR_TOKEN))
    assert ghost.status_code == 404
    assert ghost.json() == {"error": {"code": "NOT_FOUND", "retryable": False}}
    assert client.get(b.sess_url, headers=auth(TUTOR_TOKEN)).status_code == 200


# --- autenticação --------------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}, auth("not-a-known-token")],
    ids=["missing", "wrong-scheme", "empty-bearer", "unknown-token"],
)
def test_missing_or_unknown_token_401(client, practice, method, path, headers):
    r = client.request(method, path.format(id=practice.sid), headers=headers, content=b"{}")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "UNAUTHENTICATED", "retryable": False}}


def test_missing_controller_header_loses_control_on_writes_only(client, svc, practice):
    token_only = auth(practice.token)
    assert client.get(practice.sess_url, headers=token_only).status_code == 200
    r = client.post(practice.cmd_url, content=fresh_move(svc, practice), headers=token_only)
    assert r.status_code == 403 and r.json()["error"]["code"] == "CONTROL_LOST"


# --- corpo e URL ---------------------------------------------------------------------------------


def test_url_body_session_mismatch_400(client, svc, practice):
    other = json.loads(fresh_move(svc, practice))
    other["session_id"] = "ses_somewhere_else"
    r = client.post(practice.cmd_url, content=json.dumps(other).encode(), headers=practice.headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PAYLOAD"
    receipt = {
        "schema_version": "1.0",
        "receipt_id": "receipt-001",
        "effect_id": "effect-1",
        "command_id": "cmd-1",
        "session_id": "ses_somewhere_else",
        "attempt_id": None,
        "scene_revision": 0,
        "connection_generation": 1,
        "status": "render_applied",
    }
    r = client.post(f"{practice.sess_url}/render-receipts", json=receipt, headers=practice.headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PAYLOAD"


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {"json": {"request_id": request_id(1), "content_version": VERSION, "extra": 1}},
        {"json": {"request_id": 5, "content_version": VERSION}},
        {"json": {"request_id": request_id(1)}},
        {"json": ["not", "an", "object"]},
        {"content": b"{not json", "headers": {"Content-Type": "application/json"}},
    ],
)
def test_fastapi_validation_mapped_to_invalid_payload(client, request_kwargs):
    r = client.post("/v1/sessions", **request_kwargs)
    assert r.status_code == 400  # nunca o 422 padrão do FastAPI
    assert r.json() == {"error": {"code": "INVALID_PAYLOAD", "retryable": False}}


def test_bad_query_and_body_on_other_routes_are_400(client, practice):
    r = client.get(f"{practice.sess_url}/events?after_seq=-1", headers=practice.headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PAYLOAD"
    r = client.get(f"{practice.sess_url}/events?after_seq=abc", headers=practice.headers)
    assert r.status_code == 400
    r = client.post(
        f"{practice.sess_url}/claim-control",
        json={"request_id": request_id(5), "expected_revision": "0"},
        headers=practice.headers,
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PAYLOAD"


def test_unknown_route_uses_the_error_envelope(client):
    r = client.get("/v1/nothing-here")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "NOT_FOUND", "retryable": False}}


def test_wrong_method_uses_the_error_envelope_without_detail(client, practice):
    for method, url in (("DELETE", practice.sess_url), ("GET", practice.cmd_url)):
        r = client.request(method, url, headers=practice.headers)
        assert r.status_code == 405
        assert r.json() == {"error": {"code": "METHOD_NOT_ALLOWED", "retryable": False}}
        assert "Method Not Allowed" not in r.text and "detail" not in r.text


@pytest.mark.parametrize("value", ["100000000000000000000", str(2**31), str(2**63)])
def test_after_seq_is_bounded_and_never_a_500(client, practice, value):
    r = client.get(f"{practice.sess_url}/events?after_seq={value}", headers=practice.headers)
    assert r.status_code == 400
    assert r.json() == {"error": {"code": "INVALID_PAYLOAD", "retryable": False}}


def test_after_seq_at_the_ceiling_is_accepted(client, practice):
    from app.domain.division.commands import MAX_REVISION

    r = client.get(f"{practice.sess_url}/events?after_seq={MAX_REVISION}", headers=practice.headers)
    assert r.status_code == 200 and r.json() == {"events": []}


@pytest.mark.parametrize(
    "content_type", [None, "text/plain", "application/x-www-form-urlencoded", "application/jsonx"]
)
def test_command_requires_json_content_type_415_without_mutation(
    client, svc, practice, content_type
):
    R = revision(client, practice)
    headers = auth(practice.token, practice.controller)
    headers.pop("Content-Type")
    if content_type is not None:
        headers["Content-Type"] = content_type
    r = client.post(practice.cmd_url, content=fresh_move(svc, practice), headers=headers)
    assert r.status_code == 415
    assert r.json() == {"error": {"code": "UNSUPPORTED_MEDIA_TYPE", "retryable": False}}
    assert revision(client, practice) == R


def test_command_content_type_with_charset_is_accepted(client, svc, practice):
    headers = auth(practice.token, practice.controller)
    headers["Content-Type"] = "Application/JSON; charset=utf-8"
    r = client.post(practice.cmd_url, content=fresh_move(svc, practice), headers=headers)
    assert r.status_code == 200


def test_content_type_is_checked_after_authentication(client, svc, practice):
    r = client.post(
        practice.cmd_url, content=fresh_move(svc, practice), headers={"Content-Type": "text/plain"}
    )
    assert r.status_code == 401


# --- rotas que faltavam --------------------------------------------------------------------------


def test_claim_control_takes_over_and_old_controller_loses_it(client, svc, practice):
    p = practice
    R = revision(client, p)
    new_id = request_id(5)
    r = client.post(
        f"{p.sess_url}/claim-control",
        json={"request_id": new_id, "expected_revision": R},
        headers=p.headers,
    )
    assert r.status_code == 200
    assert r.json()["controller_id"] == new_id and r.json()["connection_generation"] == 2
    old = client.post(p.cmd_url, content=fresh_move(svc, p), headers=p.headers)
    assert old.status_code == 403 and old.json()["error"]["code"] == "CONTROL_LOST"
    new = client.post(
        p.cmd_url, content=fresh_move(svc, p, cmd_id="c-new"), headers=auth(p.token, new_id)
    )
    assert new.status_code == 200


def test_render_receipt_200_and_duplicate(client, svc, practice):
    live = moved_effect(svc, learner_ctx_of(practice), practice.sid)
    receipt = {
        "schema_version": "1.0",
        "receipt_id": "receipt-001",
        "session_id": practice.sid,
        "connection_generation": 1,
        "status": "render_applied",
        **live,
    }
    url = f"{practice.sess_url}/render-receipts"
    first = client.post(url, json=receipt, headers=practice.headers)
    again = client.post(url, json=receipt, headers=practice.headers)
    assert first.status_code == 200 and first.json() == {
        "receipt_id": "receipt-001",
        "outcome": "accepted",
    }
    assert again.json()["outcome"] == "duplicate"
    wrong = {**receipt, "receipt_id": "receipt-002", "effect_id": "effect-0"}
    assert client.post(url, json=wrong, headers=practice.headers).json()["outcome"] == "stale"


def test_events_after_seq_and_learner_projection(client, svc, practice):
    p = practice
    everything = client.get(f"{p.sess_url}/events?after_seq=0", headers=p.headers)
    assert everything.status_code == 200
    events = everything.json()["events"]
    assert events and all(e["event_seq"] > 0 for e in events)
    last = events[-1]["event_seq"]
    tail = client.get(f"{p.sess_url}/events?after_seq={last - 1}", headers=p.headers).json()
    assert [e["event_seq"] for e in tail["events"]] == [last]
    assert client.get(f"{p.sess_url}/events?after_seq={last}", headers=p.headers).json() == {
        "events": []
    }
    assert "outcome" not in json.dumps(events) and "rating" not in json.dumps(events)


# --- plateia do erro (R29) -----------------------------------------------------------------------


def learner_ctx_of(p: Practice) -> ActorContext:
    return ActorContext("learner", p.sid, p.sid, p.controller)


def test_provider_unavailable_503(engine, make_service):
    svc = make_service(engine, evaluator=UnavailableEvaluator())
    p = Practice(svc, 1)
    send(svc, learner_ctx_of(p), p.sid, cmd("submit_answer", answer=6))
    body = body_of(state_of(svc, p.sid), cmd("submit_explanation", text="4 grupos de 6 dão 24"))
    with TestClient(create_app(svc)) as client:
        r = client.post(p.cmd_url, content=body, headers=p.headers)
    assert r.status_code == 503
    error = r.json()["error"]
    assert (error["code"], error["retryable"]) == ("PROVIDER_UNAVAILABLE", True)
    assert set(error) <= LEARNER_ERROR_KEYS and "detail" not in error


def test_r29_learner_error_never_carries_domain_text(engine, make_service):
    """O texto de detalhe do domínio (`explanation evaluator not configured`, `piece is not in
    group-2`...) é do tutor, não do aluno: o corpo só leva código e campos estruturais."""
    svc = make_service(engine, evaluator=UnavailableEvaluator())
    p = Practice(svc, 1)
    send(svc, learner_ctx_of(p), p.sid, cmd("submit_answer", answer=6))
    explain = body_of(state_of(svc, p.sid), cmd("submit_explanation", text="4 grupos de 6 dão 24"))
    R, S = revisions(svc, p.sid)
    cases = [
        explain,  # PROVIDER_UNAVAILABLE, detalhe "explanation evaluator not configured"
        move_body(svc, p.sid, rev=R, scene_rev=S, cmd_id="c-origin", frm="group-2"),  # domínio
        move_body(svc, p.sid, rev=R - 1, scene_rev=S, cmd_id="c-stale"),  # STALE_REVISION
        b"{",  # carga inválida: o detalhe do serviço também fica de fora
    ]
    with TestClient(create_app(svc)) as client:
        for raw in cases:
            r = client.post(p.cmd_url, content=raw, headers=p.headers)
            assert r.status_code >= 400
            error = r.json()["error"]
            assert set(error) <= LEARNER_ERROR_KEYS, error
            assert "detail" not in error and "message" not in error
    # O mesmo erro, montado para o aluno, e o serviço guardam texto; só o serviço o recebe.
    err = DomainError("PROVIDER_UNAVAILABLE", "explanation evaluator not configured")
    assert "detail" not in error_body(err, "learner")["error"]
    assert "explanation" not in json.dumps(error_body(err, "learner"))
    assert error_body(err, "service")["error"]["detail"] == "explanation evaluator not configured"
    assert error_body(SessionError("NO_OP", "x"), "learner")["error"] == {
        "code": "NO_OP",
        "retryable": False,
    }


def test_r29_tutor_receives_the_detail(client, svc, practice):
    """`highlight_group` autentica e valida; o domínio o recusa com um detalhe que o tutor lê."""
    state = state_of(svc, practice.sid)
    body = body_of(state, cmd("highlight_group", actor="tutor"))
    r = client.post(practice.cmd_url, content=body, headers=auth(TUTOR_TOKEN))
    assert r.status_code == 403
    assert r.json()["error"] == {
        "code": "ACTION_NOT_ALLOWED",
        "retryable": False,
        "current_revision": state.revision,
        "current_scene_revision": state.scene_revision,
        "detail": "not_in_increment_1",
    }


def test_stale_tutor_turn_is_409_not_retryable(client, svc, practice):
    state = state_of(svc, practice.sid)
    raw = json.loads(body_of(state, cmd("highlight_group", actor="tutor")))
    raw["turn_epoch"] = state.turn_epoch + 7
    r = client.post(practice.cmd_url, content=json.dumps(raw).encode(), headers=auth(TUTOR_TOKEN))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "STALE_TURN" and r.json()["error"]["retryable"] is False


# --- STALE_SCENE e os status sem rota que os emita -----------------------------------------------


def test_stale_scene_is_409_retryable(client, svc, practice):
    R, S = revisions(svc, practice.sid)
    body = move_body(svc, practice.sid, rev=R, scene_rev=S - 1, cmd_id="c-stale-scene")
    r = client.post(practice.cmd_url, content=body, headers=practice.headers)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "STALE_SCENE" and r.json()["error"]["retryable"] is True
    assert revision(client, practice) == R


@pytest.mark.parametrize(
    "code,status", [("UNSUPPORTED_IMAGE", 415), ("IMAGE_TOO_LARGE", 413), ("SESSION_LIMIT", 429)]
)
def test_error_response_status_for_codes_without_a_route(code, status):
    """Nenhuma rota do incremento 2 emite estes códigos; o mapeamento e o envelope valem assim
    mesmo. O detalhe do domínio fica fora do corpo do aluno."""
    response = error_response(DomainError(code, "secret domain text"))
    assert response.status_code == status
    assert json.loads(response.body) == {"error": {"code": code, "retryable": False}}


# --- R31: tamanho do corpo -----------------------------------------------------------------------

TOO_LARGE = {"error": {"code": "PAYLOAD_TOO_LARGE", "retryable": False}}


def session_count(svc) -> int:
    with svc.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(sessions)).scalar_one()


def padded(base: bytes, size: int) -> bytes:
    """Mesmo JSON com um campo de enchimento, do tamanho exato pedido."""
    obj = json.loads(base)
    obj["padding"] = ""
    overhead = len(json.dumps(obj).encode())
    obj["padding"] = "x" * (size - overhead)
    out = json.dumps(obj).encode()
    assert len(out) == size
    return out


def test_oversized_command_body_is_413_without_mutation(client, svc, practice):
    R = revision(client, practice)
    big = padded(fresh_move(svc, practice), MAX_BODY_BYTES + 1)
    r = client.post(practice.cmd_url, content=big, headers=practice.headers)
    assert r.status_code == 413 and r.json() == TOO_LARGE
    assert revision(client, practice) == R


def test_chunked_oversized_body_without_content_length_is_413(client, svc, practice):
    R = revision(client, practice)
    big = padded(fresh_move(svc, practice), MAX_BODY_BYTES * 4)

    def chunks():
        for i in range(0, len(big), 8192):
            yield big[i : i + 8192]

    r = client.post(practice.cmd_url, content=chunks(), headers=practice.headers)
    assert r.status_code == 413 and r.json() == TOO_LARGE
    assert revision(client, practice) == R


def test_body_at_the_limit_still_reaches_the_validation(client, svc, practice):
    at_limit = padded(fresh_move(svc, practice), MAX_BODY_BYTES)
    r = client.post(practice.cmd_url, content=at_limit, headers=practice.headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PAYLOAD"  # campo extra


def test_oversized_create_session_is_413_and_creates_nothing(client, svc):
    body = {"request_id": request_id(1), "content_version": VERSION}
    big = padded(json.dumps(body).encode(), MAX_BODY_BYTES + 1)
    r = client.post("/v1/sessions", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json() == TOO_LARGE
    assert session_count(svc) == 0


def test_oversized_body_is_cut_before_authentication(client, practice):
    r = client.post(practice.cmd_url, content=b"x" * (MAX_BODY_BYTES + 1))
    assert r.status_code == 413 and r.json() == TOO_LARGE


# --- I2: nada do que o cliente mandou volta sem validar ------------------------------------------


@pytest.mark.parametrize("bad", ["x" * 60_000, "my secret id", "ñ", "a\nb", "id/with/slash"])
def test_unvalidated_command_id_is_never_echoed(client, svc, practice, bad):
    raw = json.loads(fresh_move(svc, practice))
    raw["command_id"] = bad
    r = client.post(practice.cmd_url, content=json.dumps(raw).encode(), headers=practice.headers)
    assert r.status_code == 400 and r.json() == {
        "error": {"code": "INVALID_PAYLOAD", "retryable": False}
    }
    assert len(r.content) < 200 and bad not in r.text


def test_valid_command_id_is_still_echoed(client, svc, practice):
    R, S = revisions(svc, practice.sid)
    body = move_body(svc, practice.sid, rev=R - 1, scene_rev=S, cmd_id="c-ok_1.2:3")
    r = client.post(practice.cmd_url, content=body, headers=practice.headers)
    assert r.json()["command_id"] == "c-ok_1.2:3"


def test_one_megabyte_command_id_is_cut_small(client, svc, practice):
    raw = json.loads(fresh_move(svc, practice))
    raw["command_id"] = "x" * 1_000_000
    r = client.post(practice.cmd_url, content=json.dumps(raw).encode(), headers=practice.headers)
    assert r.status_code == 413 and len(r.content) < 200


# --- erro inesperado -----------------------------------------------------------------------------


def test_unexpected_exception_is_500_in_the_envelope_without_detail(svc, practice, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom with a secret: 4 grupos de 6")

    monkeypatch.setattr(svc, "get_snapshot", boom)
    with TestClient(create_app(svc), raise_server_exceptions=False) as client:
        r = client.get(practice.sess_url, headers=practice.headers)
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "INTERNAL_ERROR", "retryable": False}}
    assert "boom" not in r.text and "secret" not in r.text
