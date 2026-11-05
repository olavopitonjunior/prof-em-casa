"""Aceite do incremento 2 (sessão persistida): um teste por AC, cada um jogando a jornada inteira.

A jornada parte de `POST /v1/sessions` e avança só por HTTP: `choose_reference_activity` (aluno),
`run_demo_step` e `finish_demonstration` (token de serviço `system`), depois a prática. Exceção
(P6): AC-33 e AC-37 usam `SessionService.complete_analysis` com o ator `vision_worker`, porque
não há rota de análise neste incremento. Todos rodam em SQLite e em Postgres (`db_url`). O
avaliador de explicação é um stub; nenhuma foto, voz ou criança real entra aqui.
"""

import json
import uuid

import pytest
from app.api.app import create_app
from app.domain.division.commands import SCENE_COMMANDS
from app.domain.division.demonstration import demo_steps
from app.domain.division.observation import NotebookObservation
from app.sessions.context import ActorContext
from app.sessions.credentials import hash_token
from app.sessions.repository import analysis_jobs
from fastapi.testclient import TestClient
from helpers import T12_4, cmd, load_raw
from integration.conftest import VERSION, request_id
from sqlalchemy import update

pytestmark = pytest.mark.acceptance

TUTOR_TOKEN = "fake-tutor-service-token-for-tests-only"
SYSTEM_TOKEN = "fake-system-service-token-for-tests-only"
WORKER = ActorContext("vision_worker", "vision_worker-service", None, None)


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


class Tab:
    """Uma aba do aluno: sessão, token e controlador, falando só HTTP."""

    def __init__(self, client, svc, n: int):
        self.client, self.svc = client, svc
        created = client.post(
            "/v1/sessions", json={"request_id": request_id(n), "content_version": VERSION}
        )
        assert created.status_code == 201
        body = created.json()
        self.sid, self.token, self.controller = (
            body["session_id"],
            body["session_token"],
            body["controller_id"],
        )
        self.url = f"/v1/sessions/{self.sid}"
        self.n = 0  # contador dos command_id

    # -- cabeçalhos e leituras --
    def headers(self, token=None, controller="own") -> dict:
        h = {"Authorization": f"Bearer {token or self.token}", "Content-Type": "application/json"}
        controller = self.controller if controller == "own" else controller
        if controller:
            h["X-Controller-Id"] = controller
        return h

    @property
    def ctx(self) -> ActorContext:
        return ActorContext("learner", self.sid, self.sid, self.controller)

    def snapshot(self, **kw) -> dict:
        r = self.client.get(self.url, headers=self.headers(**kw))
        assert r.status_code == 200
        return r.json()

    def events(self, after_seq: int, **kw) -> list[dict]:
        r = self.client.get(f"{self.url}/events?after_seq={after_seq}", headers=self.headers(**kw))
        assert r.status_code == 200
        return r.json()["events"]

    # -- comandos --
    def body(self, c, snap=None, command_id=None, **over) -> bytes:
        snap = snap or self.snapshot()
        self.n += 1
        raw = {
            "schema_version": "1.0",
            "command_id": command_id or f"acc-{self.n:03d}-{c.type}",
            "session_id": self.sid,
            "attempt_id": snap["active_attempt_id"],
            "expected_revision": snap["revision"],
            "type": c.type,
            "payload": c.payload,
        }
        if c.type in SCENE_COMMANDS:
            raw["expected_scene_revision"] = snap["scene_revision"]
        if c.actor == "tutor":
            raw["turn_id"], raw["turn_epoch"] = "turn-1", snap["turn_epoch"]
        raw.update(c.envelope)
        raw.update(over)
        return json.dumps(raw).encode()

    def post(self, body: bytes, token=None, **kw):
        return self.client.post(
            f"{self.url}/commands", content=body, headers=self.headers(token, **kw)
        )

    def send(self, c, token=None, **over):
        r = self.post(self.body(c, **over), token=token)
        assert r.status_code == 200, r.text
        return r.json()

    def to_practice(self) -> "Tab":
        self.send(cmd("choose_reference_activity"))
        for step in demo_steps(T12_4, 3)[:12]:
            self.send(cmd("run_demo_step", actor="system", step_id=step.step_id), SYSTEM_TOKEN)
        self.send(cmd("finish_demonstration", actor="system", reason="completed"), SYSTEM_TOKEN)
        assert self.snapshot()["phase"] == "practice"
        return self

    def move(self, piece="piece-01", frm="available", to="group-1", **over) -> bytes:
        c = cmd("move_piece", piece_id=piece, from_location=frm, to_location=to)
        return self.body(c, **over)

    def to_capture(self) -> "Tab":
        self.to_practice()
        self.send(cmd("enter_notebook", intent="try_on_paper"))
        self.send(cmd("open_notebook_capture"))
        assert self.snapshot()["phase"] == "notebook_capture"
        return self

    # -- artefato e análise: sem rota neste incremento (P6) --
    def submit(self, rid: str) -> dict:
        snap = self.snapshot()
        return self.svc.submit_notebook_artifact(
            self.ctx,
            self.sid,
            request_id=rid,
            expected_revision=snap["revision"],
            attempt_id=snap["active_attempt_id"],
        )

    def observation(self, sub: dict) -> NotebookObservation:
        raw = load_raw("observacao-5-5-5-5")
        raw.update(
            artifact_id=sub["artifact_id"],
            artifact_version=sub["artifact_version"],
            attempt_id=self.snapshot()["active_attempt_id"],
            observation_id=f"worker-{uuid.uuid4().hex[:8]}",
        )
        return NotebookObservation.model_validate(raw)

    def complete(self, sub: dict) -> str:
        return self.svc.complete_analysis(WORKER, sub["job_id"], self.observation(sub))


def pieces_in(snap: dict, group_id: str) -> list[str]:
    (group,) = [g for g in snap["scene"]["groups"] if g["id"] == group_id]
    return group["piece_ids"]


def types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


# --- AC-26 ---------------------------------------------------------------------------------------


@pytest.mark.ac("AC-26")
def test_ac26_same_body_twice_has_one_effect(client, svc, db_url):
    tab = Tab(client, svc, 1).to_practice()
    before = tab.snapshot()
    body = tab.move(command_id="acc-move-1")

    first = tab.post(body)
    again = tab.post(body)

    assert first.status_code == again.status_code == 200
    assert "Idempotent-Replay" not in first.headers
    assert again.headers["Idempotent-Replay"] == "true"
    assert again.json() == first.json()
    assert first.json()["revision"] == before["revision"] + 1
    after = tab.snapshot()
    assert after["revision"] == before["revision"] + 1  # nenhuma revisão extra
    assert after["scene_revision"] == before["scene_revision"] + 1
    assert pieces_in(after, "group-1") == ["piece-01"]  # a peça foi movida uma vez só
    assert types(tab.events(before["last_event_seq"])).count("scene_changed") == 1


# --- AC-27 ---------------------------------------------------------------------------------------


@pytest.mark.ac("AC-27")
def test_ac27_rejections_name_the_code_and_leave_no_trace(client, svc, db_url):
    tab = Tab(client, svc, 1).to_practice()
    assert tab.post(tab.move(command_id="acc-move-1")).status_code == 200
    snap = tab.snapshot()
    R = snap["revision"]
    cases = [
        # mesmo command_id, outro corpo: o que faltava no incremento 1
        (
            tab.move(piece="piece-02", command_id="acc-move-1", snap=snap),
            409,
            "IDEMPOTENCY_CONFLICT",
        ),
        (
            tab.move(piece="piece-02", command_id="acc-stale", expected_revision=R - 1),
            409,
            "STALE_REVISION",
        ),
        (
            tab.move(
                piece="piece-02", command_id="acc-attempt", attempt_id="attempt-1-demonstration"
            ),
            409,
            "ATTEMPT_CHANGED",
        ),
        (tab.move(piece="piece-02", frm="group-2", command_id="acc-origin"), 422, "INVALID_SCENE"),
    ]
    for body, status, code in cases:
        r = tab.post(body)
        assert (r.status_code, r.json()["error"]["code"]) == (status, code), r.text
        assert tab.snapshot() == snap  # nenhuma mutação parcial: snapshot idêntico
    assert types(tab.events(snap["last_event_seq"])) == []
    # a rejeição não ocupa o command_id: o mesmo id, agora com corpo válido, é aceito (P5)
    ok = tab.post(tab.move(piece="piece-02", command_id="acc-stale"))
    assert ok.status_code == 200 and ok.json()["revision"] == R + 1


# --- AC-33 ---------------------------------------------------------------------------------------


@pytest.mark.ac("AC-33")
def test_ac33_slow_v1_does_not_overwrite_v2(client, svc, engine, db_url):
    tab = Tab(client, svc, 1).to_capture()
    v1 = tab.submit("up-1")
    tab.send(cmd("retake_notebook_photo"))
    v2 = tab.submit("up-2")
    assert (v1["artifact_version"], v2["artifact_version"]) == (1, 2)

    assert tab.complete(v1) == "superseded"  # a foto lenta chega depois da v2
    analysis = tab.snapshot()["analysis"]
    assert analysis["artifact_id"] == v2["artifact_id"] and analysis["status"] == "pending"

    assert tab.complete(v2) == "applied"
    assert tab.snapshot()["analysis"]["status"] == "available"

    # tentativa trocada: a foto v3 fica obsoleta quando a criança segue para a questão nova
    tab.send(cmd("retake_notebook_photo"))
    v3 = tab.submit("up-3")
    stale_obs = tab.observation(v3)
    tab.send(cmd("retake_notebook_photo"))
    tab.send(cmd("cancel_capture"))
    tab.send(cmd("return_to_activity"))
    tab.send(cmd("submit_answer", answer=6))
    tab.send(cmd("continue_after_explanation", reason="learner_skipped"))
    snap = tab.snapshot()
    assert snap["phase"] == "transfer" and snap["active_attempt_id"] != stale_obs.attempt_id
    assert svc.complete_analysis(WORKER, v3["job_id"], stale_obs) == "superseded"
    assert tab.snapshot() == snap and snap["analysis"] is None  # não vaza para o item novo

    # job reaberto à força (`queued`): na jornada normal toda saída da captura já supersede o job
    # (acima). Aqui o resultado da tentativa antiga é recusado porque deixou de ser o do artefato
    # vigente (na transferência `active_artifact` é None, e o check de artefato dispara antes do
    # de tentativa). O que este caso prova é que o job é superseded quando não casa mais com o
    # artefato/tentativa atuais, sem tocar o item novo. A guarda de tentativa isolada não é
    # coberta por este teste de aceite: está em unit, em
    # tests/domain/test_analysis.py::test_result_with_matching_artifact_but_another_attempt_is_superseded.
    with engine.begin() as conn:
        conn.execute(
            update(analysis_jobs)
            .where(analysis_jobs.c.job_id == v3["job_id"])
            .values(status="queued", applied=False)
        )
    assert svc.complete_analysis(WORKER, v3["job_id"], stale_obs) == "superseded"
    assert tab.snapshot() == snap and snap["analysis"] is None


# --- AC-36 ---------------------------------------------------------------------------------------


@pytest.mark.ac("AC-36")
def test_ac36_lost_response_is_replayed_and_state_is_reconcilable(client, svc, db_url):
    tab = Tab(client, svc, 1).to_practice()
    before = tab.snapshot()
    body = tab.move(command_id="acc-move-1")

    tab.post(body)  # a resposta se perde: o cliente a descarta
    retry = tab.post(body)  # e reenvia o mesmo corpo

    assert retry.status_code == 200 and retry.headers["Idempotent-Replay"] == "true"
    confirmed = tab.snapshot()
    assert pieces_in(confirmed, "group-1") == ["piece-01"]  # movida uma vez só
    assert confirmed["revision"] == before["revision"] + 1 == retry.json()["revision"]
    # reconciliar: o snapshot e o log de eventos concordam sobre o que foi confirmado
    events = tab.events(before["last_event_seq"])
    assert types(events).count("scene_changed") == 1
    assert events[-1]["event_seq"] == confirmed["last_event_seq"] == retry.json()["event_seq"]
    assert tab.events(confirmed["last_event_seq"]) == []  # nada mais a baixar


# --- AC-37 ---------------------------------------------------------------------------------------


@pytest.mark.ac("AC-37")
def test_ac37_pause_defers_and_closed_session_discards(client, svc, db_url):
    # pausa: a análise fica guardada, sem aplicar e sem evento, até a retomada
    tab = Tab(client, svc, 1).to_capture()
    sub = tab.submit("up-1")
    tab.send(cmd("pause_session"))
    paused = tab.snapshot()
    assert tab.complete(sub) == "deferred"
    assert tab.snapshot() == paused and paused["analysis"]["status"] == "pending"

    out = tab.send(cmd("resume_session"))
    assert out["revision"] == paused["revision"] + 1  # reconciliação em uma só revisão (P7)
    events = tab.events(paused["last_event_seq"])
    assert types(events) == ["session_resumed", "analysis_completed"]
    assert tab.snapshot()["analysis"]["status"] == "available"

    # controle positivo: sem pausa nem fechamento o mesmo resultado entra (o descarte abaixo
    # não é vácuo)
    live = Tab(client, svc, 4).to_capture()
    live_sub = live.submit("up-1")
    assert live.complete(live_sub) == "applied"
    assert live.snapshot()["analysis"]["status"] == "available"

    # fechada: resultado tardio não entra e nada muda
    other = Tab(client, svc, 2).to_capture()
    late = other.submit("up-1")
    other.send(cmd("close_session", reason="learner_stopped"))
    closed = other.snapshot()
    assert other.complete(late) == "discarded"
    assert other.snapshot() == closed

    # o tutor não age em sessão pausada nem fechada (aqui na prática, onde o comando seria válido)
    talk = Tab(client, svc, 3).to_practice()

    def tutor_is_refused():
        frozen = talk.snapshot()
        r = talk.post(talk.body(cmd("highlight_group", actor="tutor")), token=TUTOR_TOKEN)
        assert r.status_code == 403 and r.json()["error"]["code"] == "ACTION_NOT_ALLOWED", r.text
        assert talk.snapshot() == frozen

    talk.send(cmd("pause_session"))
    tutor_is_refused()
    talk.send(cmd("resume_session"))
    talk.send(cmd("close_session"))
    tutor_is_refused()


# --- AC-38 ---------------------------------------------------------------------------------------


@pytest.mark.ac("AC-38")
def test_ac38_second_tab_takes_control_without_forking_state(client, svc, db_url):
    tab_a = Tab(client, svc, 1).to_practice()
    before = tab_a.snapshot()
    rid_b = request_id(77)
    claim = client.post(
        f"{tab_a.url}/claim-control",
        json={"request_id": rid_b, "expected_revision": before["revision"]},
        headers=tab_a.headers(controller=rid_b),
    )
    assert claim.status_code == 200
    assert claim.json()["controller_id"] == rid_b and claim.json()["connection_generation"] == 2

    # a aba A perdeu a escrita (mesmo com a revisão certa) e o ACK
    lost = tab_a.post(tab_a.move(command_id="acc-old-tab"))
    assert lost.status_code == 403 and lost.json()["error"]["code"] == "CONTROL_LOST"
    receipt = {
        "schema_version": "1.0",
        "receipt_id": "receipt-001",
        "effect_id": "effect-1",
        "command_id": "cmd-1",
        "session_id": tab_a.sid,
        "attempt_id": None,
        "scene_revision": before["scene_revision"],
        "connection_generation": 1,
        "status": "render_applied",
    }
    ack = client.post(f"{tab_a.url}/render-receipts", json=receipt, headers=tab_a.headers())
    assert ack.status_code == 403 and ack.json()["error"]["code"] == "CONTROL_LOST"

    # uma linha de revisão só: as duas abas leem o mesmo estado
    seen_a, seen_b = tab_a.snapshot(), tab_a.snapshot(controller=rid_b)
    assert seen_a == seen_b and seen_a["revision"] == before["revision"] + 1
    assert seen_a["connection_generation"] == 2

    # a aba B segue escrevendo
    moved = tab_a.post(tab_a.move(command_id="acc-new-tab"), controller=rid_b)
    assert moved.status_code == 200 and moved.json()["revision"] == before["revision"] + 2
    assert pieces_in(tab_a.snapshot(), "group-1") == ["piece-01"]


# --- AC-40 ---------------------------------------------------------------------------------------


@pytest.mark.ac("AC-40")
def test_ac40_credential_of_a_sees_nothing_of_b(client, svc, db_url):
    a = Tab(client, svc, 1).to_practice()
    b = Tab(client, svc, 2).to_practice()
    known = b.move(command_id="acc-known-of-b")  # command_id conhecido de B
    assert b.post(known).status_code == 200
    receipt = {
        "schema_version": "1.0",
        "receipt_id": "receipt-001",
        "effect_id": "effect-1",
        "command_id": "cmd-1",
        "session_id": b.sid,
        "attempt_id": None,
        "scene_revision": 0,
        "connection_generation": 1,
        "status": "render_applied",
    }
    claim = {"request_id": request_id(9), "expected_revision": 0}
    calls = [
        ("GET", "", None),
        ("POST", "/commands", known),  # retry idempotente do comando de B
        ("POST", "/claim-control", json.dumps(claim).encode()),
        ("POST", "/render-receipts", json.dumps(receipt).encode()),
        ("GET", "/events?after_seq=0", None),
    ]
    b_before = b.snapshot()
    for method, suffix, content in calls:
        headers = {**a.headers(), "Content-Type": "application/json"}
        foreign = client.request(
            method, f"/v1/sessions/{b.sid}{suffix}", headers=headers, content=content
        )
        ghost = client.request(
            method, f"/v1/sessions/ses_doesnotexist{suffix}", headers=headers, content=content
        )
        assert foreign.status_code == ghost.status_code == 404, (method, suffix)
        assert foreign.content == ghost.content  # byte a byte: não distingue existência
        assert foreign.json() == {"error": {"code": "NOT_FOUND", "retryable": False}}
        assert b.sid not in foreign.text
    assert b.snapshot() == b_before  # as tentativas não mexeram em B
    # o token de serviço enxerga qualquer sessão (A e B); o do aluno só a própria
    service = {"Authorization": f"Bearer {TUTOR_TOKEN}"}
    assert client.get(a.url, headers=service).status_code == 200
    assert client.get(b.url, headers=service).status_code == 200
