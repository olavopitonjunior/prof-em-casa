"""`SessionService`: casos de uso da sessão persistida (Spec Parte II §2, ordem obrigatória).

Autorizar -> procurar a chave idempotente -> validar o hash do corpo -> schema e guardas ->
transação curta (estado + eventos + resultado) -> resposta. O domínio (`apply_command`) é puro;
aqui ficam a transação, a trava da linha da sessão e a gravação.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.content.loader import ContentPackage
from app.domain.division.analysis import (
    AnalysisResult,
    Disposition,
    apply_analysis_result,
    submit_artifact,
)
from app.domain.division.classification import ExplanationEvaluator
from app.domain.division.commands import MAX_REVISION, Actor, load_json_object, parse_command
from app.domain.division.errors import DomainError
from app.domain.division.observation import NotebookObservation
from app.domain.division.session import apply_command
from app.domain.division.state import DomainEvent, SessionState, new_session
from app.sessions import repository
from app.sessions.context import ActorContext, Clock, IdFactory, default_ids, utc_now
from app.sessions.credentials import derive_session_token, hash_token, match_service_token
from app.sessions.errors import SessionError
from app.sessions.projection import Audience, project_event, session_view
from app.sessions.receipts import RenderReceipt
from app.sessions.repository import SessionEvent, SessionRow, StoredResult

# Decisão P2: o request_id é o segredo de onde sai o token, então precisa de alta entropia.
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{22,128}")
MAX_EVENTS_PAGE = 1000
# NUL e substitutos soltos não existem em texto Unicode válido e o JSONB do Postgres os recusa.
_BAD_TEXT_RE = re.compile("[\x00\ud800-\udfff]")


MAX_BEARER_LENGTH = 512
# Motivo do `analysis_superseded` que não encerra o job: o resultado tardio de uma sessão fechada
# é registrado como `discarded` (AC-37), não como `superseded`.
_KEEP_JOB_REASONS = frozenset({"session_closed"})


def _same_controller(presented: str | None, current: str) -> bool:
    """Compara o `X-Controller-Id` com o vigente em tempo constante. Texto que não é UTF-8
    válido (substituto solto) simplesmente não é o controlador."""
    if presented is None:
        return False
    try:
        return hmac.compare_digest(presented.encode("utf-8"), current.encode("utf-8"))
    except UnicodeEncodeError:
        return False


@dataclass(frozen=True)
class CreatedSession:
    session_id: str
    session_token: str
    controller_id: str
    connection_generation: int
    snapshot: dict[str, Any]
    replay: bool


@dataclass(frozen=True)
class CommandOutcome:
    status_code: int
    body: dict[str, Any]
    replay: bool


def _check_text(value: Any) -> None:
    if isinstance(value, str):
        if _BAD_TEXT_RE.search(value):
            raise SessionError("INVALID_PAYLOAD", "invalid character in text")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_text(key)
            _check_text(item)
    elif isinstance(value, list):
        for item in value:
            _check_text(item)


def body_hash(actor: str, body: dict[str, Any]) -> str:
    """Decisão P5: sha256 do JSON canônico de `{"actor", "body"}`. O corpo já foi lido como objeto,
    então ordem das chaves e espaços não mudam o hash; outro ator muda."""
    try:
        canonical = json.dumps(
            {"actor": actor, "body": body},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except RecursionError:
        raise SessionError("INVALID_PAYLOAD", "body too deeply nested") from None


def _is_result_race(exc: IntegrityError) -> bool:
    """A chave `(session_id, command_id)` foi gravada por outra transação no meio do caminho."""
    return "command_results" in str(exc.orig)


class SessionService:
    def __init__(
        self,
        engine: Engine,
        content: ContentPackage,
        evaluator: ExplanationEvaluator,
        *,
        token_secret: bytes,
        clock: Clock = utc_now,
        ids: IdFactory = default_ids,
        session_ttl: timedelta = timedelta(hours=24),
        service_token_hashes: Mapping[str, Actor] | None = None,
    ) -> None:
        self.engine = engine
        self.content = content
        self.evaluator = evaluator
        self._secret = token_secret
        self._clock = clock
        self._ids = ids
        self._ttl = session_ttl
        self._service_hashes: Mapping[str, Actor] = dict(service_token_hashes or {})

    # --- autenticação ----------------------------------------------------------------------------

    def authenticate(self, bearer: str | None, controller_id: str | None) -> ActorContext:
        """Token -> ator. Só prova quem chama: a sessão alcançada e o controle vêm depois.

        Token de serviço alcança todas as sessões (`session_id=None`). Token de sessão alcança só a
        sua e é sempre o aluno; `controller_id` é o cabeçalho `X-Controller-Id` (decisão P3).
        """
        if not bearer or len(bearer) > MAX_BEARER_LENGTH or _BAD_TEXT_RE.search(bearer):
            raise SessionError("UNAUTHENTICATED")  # lixo nunca chega ao hash nem ao banco
        service_actor = match_service_token(bearer, self._service_hashes)
        if service_actor is not None:
            return ActorContext(service_actor, f"{service_actor}-service", None, None)
        with self.engine.connect() as conn:
            found = repository.find_credential(conn, hash_token(bearer))
        if found is None:
            raise SessionError("UNAUTHENTICATED")
        session_id, _actor = found  # a coluna só admite 'learner' (CHECK)
        return ActorContext("learner", session_id, session_id, controller_id)

    # --- criação ---------------------------------------------------------------------------------

    def create_session(self, request_id: str, content_version: str) -> CreatedSession:
        if content_version != self.content.version:
            raise SessionError("UNSUPPORTED_CONTENT", f"unknown content version: {content_version}")
        if not _REQUEST_ID_RE.fullmatch(request_id):
            raise SessionError(
                "INVALID_PAYLOAD", "request_id must be 22 to 128 url-safe characters"
            )
        token = derive_session_token(self._secret, request_id)
        try:
            return self._create_once(request_id, token)
        except IntegrityError:
            # Outra criação com o mesmo request_id gravou primeiro: esta vira o replay dela.
            return self._create_once(request_id, token)

    def _create_once(self, request_id: str, token: str) -> CreatedSession:
        now = self._clock()
        with self.engine.begin() as conn:
            existing = repository.find_session_id_by_request(conn, request_id)
            if existing is not None:
                row = repository.load_session(conn, existing, for_update=False)
                assert row is not None  # a chave estrangeira garante; o CASCADE apaga os dois
                # Sem troca de controle (geração 1), devolve o id original: quem perdeu a
                # resposta se recupera. Depois de uma troca devolve um id novo que não controla
                # nada, para que o replay nunca entregue o controlador vigente.
                controller_id = (
                    row.controller_id if row.connection_generation == 1 else self._ids("ctl")
                )
                return CreatedSession(
                    session_id=existing,
                    session_token=token,
                    controller_id=controller_id,
                    connection_generation=row.connection_generation,
                    snapshot=session_view(
                        row.state,
                        self.content,
                        connection_generation=row.connection_generation,
                    ),
                    replay=True,
                )
            state = new_session(self._ids("ses"))
            # O controlador da primeira aba é um id aleatório do servidor, independente do
            # request_id (de onde sai o token): vazar o cabeçalho X-Controller-Id não revela o token.
            controller_id = self._ids("ctl")
            row = SessionRow(
                state=state,
                connection_generation=1,
                controller_id=controller_id,
                expires_at=now + self._ttl,
            )
            repository.insert_session(
                conn,
                create_request_id=request_id,
                row=row,
                token_hash=hash_token(token),
                now=now,
            )
        return CreatedSession(
            session_id=state.session_id,
            session_token=token,
            controller_id=controller_id,
            connection_generation=1,
            snapshot=session_view(state, self.content, connection_generation=1),
            replay=False,
        )

    # --- leitura ---------------------------------------------------------------------------------

    def get_snapshot(self, ctx: ActorContext, session_id: str) -> dict[str, Any]:
        self._reject_foreign_session(ctx, session_id)
        with self.engine.connect() as conn:
            row = repository.load_session(conn, session_id, for_update=False)
        self._authorize(ctx, row, write=False)
        assert row is not None
        return session_view(
            row.state, self.content, connection_generation=row.connection_generation
        )

    def list_events(
        self, ctx: ActorContext, session_id: str, after_seq: int = 0, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Retomada incremental: eventos com `event_seq > after_seq`, na projeção do ator. O
        aluno nunca recebe correção (a lista de permitidos de `project_event`)."""
        if after_seq < 0 or not 1 <= limit <= MAX_EVENTS_PAGE:
            raise SessionError("INVALID_PAYLOAD", "after_seq must be >= 0 and 1 <= limit <= 1000")
        self._reject_foreign_session(ctx, session_id)
        with self.engine.connect() as conn:
            row = repository.load_session(conn, session_id, for_update=False)
            self._authorize(ctx, row, write=False)
            records = repository.list_events(conn, session_id, after_seq=after_seq, limit=limit)
        audience: Audience = "learner" if ctx.actor == "learner" else "service"
        return [project_event(record, audience) for record in records]

    # --- comando ---------------------------------------------------------------------------------

    def execute_command(
        self, ctx: ActorContext, session_id: str, raw_body: bytes
    ) -> CommandOutcome:
        try:
            return self._execute_once(ctx, session_id, raw_body)
        except IntegrityError as exc:
            if not _is_result_race(exc):
                raise
        # Passo 7: a corrida pela chave idempotente é tratada uma vez. A segunda tentativa
        # enxerga o resultado do vencedor e vira replay; se falhar de novo, o erro sobe.
        return self._execute_once(ctx, session_id, raw_body)

    def _execute_once(self, ctx: ActorContext, session_id: str, raw_body: bytes) -> CommandOutcome:
        self._reject_foreign_session(ctx, session_id)  # 1. autorizar
        with self.engine.connect() as conn:
            row = repository.load_session(conn, session_id, for_update=False)
            self._authorize(ctx, row, write=True)
            body, command_id = self._read_body(raw_body, session_id)  # 2.
            digest = body_hash(ctx.actor, body)  # 3.
            replay = self._replay_of(conn, session_id, command_id, digest)  # 4.
            if replay is not None:
                return replay
        try:
            command = parse_command(body, ctx.actor)  # 5.
        except DomainError as err:
            raise SessionError.from_domain(err, command_id=command_id) from None
        return self._apply(ctx, session_id, command, command_id, digest)  # 6.

    def _apply(
        self, ctx: ActorContext, session_id: str, command: Any, command_id: str, digest: str
    ) -> CommandOutcome:
        now = self._clock()
        with self.engine.begin() as conn:
            row = repository.load_session(conn, session_id, for_update=True)
            self._authorize(ctx, row, write=True)  # o controle pode ter mudado desde o passo 1
            assert row is not None
            replay = self._replay_of(conn, session_id, command_id, digest)
            if replay is not None:
                return replay
            before = row.state
            try:
                result = apply_command(
                    before,
                    command,
                    ctx.actor,
                    content=self.content,
                    explanation_evaluator=self.evaluator,
                )
            except DomainError as err:
                raise SessionError.from_domain(
                    err,
                    current_revision=before.revision,
                    current_scene_revision=before.scene_revision,
                    command_id=command_id,
                ) from None
            after, events = result.session, list(result.events)
            if command.type == "resume_session":
                # P7: a reconciliação entra na mesma transação e na mesma revisão da retomada.
                after, extra = self._reconcile_on_resume(conn, session_id, after, now)
                events += extra
            self._supersede_jobs(conn, session_id, events, now)
            repository.save_session(
                conn,
                expected_revision=before.revision,
                row=SessionRow(
                    state=after,
                    connection_generation=row.connection_generation,
                    controller_id=row.controller_id,
                    expires_at=row.expires_at,
                ),
                now=now,
            )
            repository.append_events(
                conn,
                session_id,
                events,
                first_seq=before.last_event_seq + 1,
                revision=after.revision,
                actor=ctx.actor,
                command_id=command_id,
                now=now,
                event_id=lambda: self._ids("evt"),
            )
            outcomes = {
                e.attempt_id: e.data["outcome"]
                for e in events
                if e.type == "attempt_evaluated" and e.attempt_id and "outcome" in e.data
            }
            repository.upsert_attempts(conn, after, outcomes=outcomes)
            response = {
                "command_id": command_id,
                "status": "accepted",
                "revision": after.revision,
                "scene_revision": after.scene_revision,
                "event_seq": after.last_event_seq,
                "scene_effect": (
                    {
                        "effect_id": f"effect-{after.scene_revision}",
                        "requires_ack": "render_applied",
                    }
                    if result.scene_changed
                    else None
                ),
            }
            repository.insert_result(
                conn,
                session_id=session_id,
                command_id=command_id,
                kind="command",
                body_hash=digest,
                actor=ctx.actor,
                principal_id=ctx.principal_id,
                http_status=200,
                response=response,
                revision=after.revision,
                now=now,
            )
        return CommandOutcome(status_code=200, body=response, replay=False)

    # --- artefato e análise do caderno -----------------------------------------------------------

    def submit_notebook_artifact(
        self,
        ctx: ActorContext,
        session_id: str,
        *,
        request_id: str,
        expected_revision: int,
        attempt_id: str,
    ) -> dict[str, Any]:
        """Envio da foto do caderno: cria o artefato (sem objeto no incremento 2), o job `queued` e
        a mudança de fase numa só transação (outbox implícito, Parte II §8). Só o controlador
        vigente. O replay por `(session_id, request_id)` devolve o dicionário original."""
        self._reject_foreign_session(ctx, session_id)
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise SessionError("INVALID_PAYLOAD", "request_id must be 1 to 128 characters")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise SessionError("INVALID_PAYLOAD", "attempt_id is required")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or not 0 <= expected_revision <= MAX_REVISION
        ):
            raise SessionError("INVALID_PAYLOAD", "expected_revision must be a valid revision")
        try:
            _check_text({"request_id": request_id, "attempt_id": attempt_id})
        except RecursionError:  # pragma: no cover - dois textos simples
            raise SessionError("INVALID_PAYLOAD", "invalid text") from None
        now = self._clock()
        with self.engine.begin() as conn:
            row = repository.load_session(conn, session_id, for_update=True)
            self._authorize(ctx, row, write=True)
            assert row is not None
            if ctx.actor != "learner":
                raise SessionError("ACTION_NOT_ALLOWED", "only the learner submits the notebook")
            digest = body_hash(
                ctx.actor,
                {
                    "type": "submit_notebook_artifact",
                    "request_id": request_id,
                    "expected_revision": expected_revision,
                    "attempt_id": attempt_id,
                },
            )
            stored = repository.find_result(conn, session_id, request_id)
            if stored is not None:
                if stored.kind != "command" or stored.body_hash != digest:
                    raise SessionError("IDEMPOTENCY_CONFLICT", command_id=request_id)
                return dict(stored.response)
            before = row.state
            # Mesma ordem de `apply_command`: sessão fechada, tentativa, revisão e, por fim, a fase.
            if before.session_status == "closed":
                raise SessionError("ACTION_NOT_ALLOWED", "session_closed", command_id=request_id)
            if attempt_id != before.active_attempt_id:
                raise SessionError(
                    "ATTEMPT_CHANGED",
                    "attempt_id is not the active attempt",
                    current_revision=before.revision,
                    command_id=request_id,
                )
            if before.revision != expected_revision:
                raise SessionError(
                    "STALE_REVISION",
                    f"current revision is {before.revision}",
                    current_revision=before.revision,
                    current_scene_revision=before.scene_revision,
                    command_id=request_id,
                )
            artifact_id, job_id = self._ids("art"), self._ids("job")
            version = repository.next_artifact_version(conn, session_id, attempt_id)
            try:
                result = submit_artifact(
                    before,
                    attempt_id=attempt_id,
                    artifact_id=artifact_id,
                    artifact_version=version,
                    job_id=job_id,
                )
            except DomainError as err:
                raise SessionError.from_domain(
                    err,
                    current_revision=before.revision,
                    current_scene_revision=before.scene_revision,
                    command_id=request_id,
                ) from None
            after, events = result.session, list(result.events)
            repository.insert_artifact(
                conn,
                artifact_id=artifact_id,
                session_id=session_id,
                attempt_id=attempt_id,
                purpose="notebook",
                version=version,
                expires_at=row.expires_at,
                now=now,
            )
            repository.insert_job(
                conn,
                job_id=job_id,
                session_id=session_id,
                artifact_id=artifact_id,
                request_id=request_id,
                now=now,
            )
            self._supersede_jobs(conn, session_id, events, now)
            repository.save_session(
                conn,
                expected_revision=before.revision,
                row=SessionRow(
                    state=after,
                    connection_generation=row.connection_generation,
                    controller_id=row.controller_id,
                    expires_at=row.expires_at,
                ),
                now=now,
            )
            repository.append_events(
                conn,
                session_id,
                events,
                first_seq=before.last_event_seq + 1,
                revision=after.revision,
                actor=ctx.actor,
                command_id=request_id,
                now=now,
                event_id=lambda: self._ids("evt"),
            )
            response = {
                "artifact_id": artifact_id,
                "artifact_version": version,
                "job_id": job_id,
                "revision": after.revision,
            }
            # `kind="command"`: o CHECK do banco só admite 'command' e 'claim_control'. O hash do
            # corpo leva o tipo, então este resultado nunca confunde com o de um comando comum.
            repository.insert_result(
                conn,
                session_id=session_id,
                command_id=request_id,
                kind="command",
                body_hash=digest,
                actor=ctx.actor,
                principal_id=ctx.principal_id,
                http_status=200,
                response=response,
                revision=after.revision,
                now=now,
            )
        return response

    def complete_analysis(
        self, ctx: ActorContext, job_id: str, observation: NotebookObservation
    ) -> Disposition:
        """Entrega do worker de visão. Trava a sessão do job, grava a observação e deixa o domínio
        decidir (`apply_analysis_result`). Job já terminal devolve a disposição anterior, sem efeito."""
        if ctx.actor != "vision_worker":
            raise SessionError("ACTION_NOT_ALLOWED", "only the vision worker completes analyses")
        now = self._clock()
        with self.engine.begin() as conn:
            found = repository.find_job(conn, job_id)
            if found is None:
                raise SessionError("NOT_FOUND")
            row = repository.load_session(conn, found.session_id, for_update=True)
            self._authorize(ctx, row, write=False)
            assert row is not None
            job = repository.find_job(conn, job_id)  # relido com a sessão travada
            assert job is not None
            state = row.state
            if job.status not in ("queued", "running"):
                return self._previous_disposition(job, state)
            # R24 e opacidade: o id da observação é do servidor, sem semântica nem texto do worker.
            observation = observation.model_copy(update={"observation_id": str(uuid.uuid4())})
            result = AnalysisResult(
                job_id=job.job_id,
                artifact_id=job.artifact_id,
                artifact_version=job.artifact_version,
                attempt_id=job.attempt_id,
                observation=observation,
            )
            try:
                applied = apply_analysis_result(state, result, content=self.content)
            except DomainError as err:
                raise SessionError.from_domain(
                    err,
                    current_revision=state.revision,
                    current_scene_revision=state.scene_revision,
                ) from None
            disposition = applied.disposition
            done = observation.status if observation.status != "usable" else "ready"
            if disposition == "superseded":
                repository.update_job(
                    conn, job_id, status="superseded", applied=False, now=now, count_execution=True
                )
                return disposition
            if disposition != "already_applied":
                repository.insert_observation(
                    conn,
                    observation_id=observation.observation_id,
                    job_id=job.job_id,
                    session_id=job.session_id,
                    attempt_id=job.attempt_id,
                    artifact_id=job.artifact_id,
                    document=observation.model_dump(mode="json"),
                    now=now,
                )
            if applied.result is not None:  # só quando a disposição é "applied"
                after = applied.result.session
                repository.save_session(
                    conn,
                    expected_revision=state.revision,
                    row=SessionRow(
                        state=after,
                        connection_generation=row.connection_generation,
                        controller_id=row.controller_id,
                        expires_at=row.expires_at,
                    ),
                    now=now,
                )
                repository.append_events(
                    conn,
                    job.session_id,
                    applied.result.events,
                    first_seq=state.last_event_seq + 1,
                    revision=after.revision,
                    actor=ctx.actor,
                    command_id=None,
                    now=now,
                    event_id=lambda: self._ids("evt"),
                )
            repository.update_job(
                conn,
                job_id,
                status=done,
                applied=disposition in ("applied", "already_applied"),
                now=now,
                count_execution=True,
            )
        return disposition

    @staticmethod
    def _previous_disposition(job: repository.JobRow, state: SessionState) -> Disposition:
        """A disposição de um job já terminal, reconstruída do que ficou gravado."""
        if job.status == "superseded":
            return "superseded"
        if job.applied:
            return "applied"
        if job.status in ("ready", "needs_clarification") and state.session_status != "closed":
            return "deferred"
        return "discarded"

    def _reconcile_on_resume(
        self, conn: Connection, session_id: str, state: SessionState, now: Any
    ) -> tuple[SessionState, list[DomainEvent]]:
        """Na retomada, aplica o resultado que chegou durante a pausa (job `ready` ou
        `needs_clarification` ainda com `applied=false`). Sem nova revisão: `bump_revision=False`."""
        artifact = state.active_artifact
        if artifact is None:
            return state, []
        job = repository.find_job(conn, artifact.job_id)
        if (
            job is None
            or job.session_id != session_id
            or job.applied
            or job.status not in ("ready", "needs_clarification")
        ):
            return state, []
        document = repository.load_observation_document(conn, job.job_id)
        if document is None:
            return state, []
        result = AnalysisResult(
            job_id=job.job_id,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            attempt_id=job.attempt_id,
            observation=NotebookObservation.model_validate(document),
        )
        applied = apply_analysis_result(state, result, content=self.content, bump_revision=False)
        if applied.disposition == "applied" and applied.result is not None:
            repository.update_job(conn, job.job_id, status=job.status, applied=True, now=now)
            return applied.result.session, list(applied.result.events)
        if applied.disposition == "superseded":
            repository.supersede_jobs(conn, session_id, [job.job_id], now=now)
        return state, []

    @staticmethod
    def _supersede_jobs(
        conn: Connection, session_id: str, events: list[DomainEvent], now: Any
    ) -> None:
        """Todo `analysis_superseded` do domínio encerra o job na mesma transação (retake, saída do
        fluxo, nova captura), salvo o fechamento da sessão, que vira `discarded` no resultado."""
        job_ids = [
            e.data["job_id"]
            for e in events
            if e.type == "analysis_superseded"
            and e.data.get("job_id")
            and e.data.get("reason") not in _KEEP_JOB_REASONS
        ]
        repository.supersede_jobs(conn, session_id, job_ids, now=now)

    # --- controle --------------------------------------------------------------------------------

    def claim_control(
        self, ctx: ActorContext, session_id: str, request_id: str, expected_revision: int
    ) -> dict[str, Any]:
        """Decisão P4: o dispositivo que chama vira o controlador. Sobe `connection_generation`,
        `turn_epoch` e `revision` numa única transação e grava `control_claimed`. Não exige ser o
        controlador atual; é o caso da segunda aba."""
        self._reject_foreign_session(ctx, session_id)
        if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
            raise SessionError(
                "INVALID_PAYLOAD", "request_id must be 22 to 128 url-safe characters"
            )
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or not 0 <= expected_revision <= MAX_REVISION
        ):
            raise SessionError("INVALID_PAYLOAD", "expected_revision must be a valid revision")
        now = self._clock()
        with self.engine.begin() as conn:
            row = repository.load_session(conn, session_id, for_update=True)
            self._authorize(ctx, row, write=False)
            assert row is not None
            if ctx.actor != "learner":
                raise SessionError("ACTION_NOT_ALLOWED", "only the learner device holds control")
            digest = body_hash(
                ctx.actor,
                {
                    "type": "claim_control",
                    "request_id": request_id,
                    "expected_revision": expected_revision,
                },
            )
            stored = repository.find_result(conn, session_id, request_id)
            if stored is not None:
                if stored.kind != "claim_control" or stored.body_hash != digest:
                    raise SessionError("IDEMPOTENCY_CONFLICT", command_id=request_id)
                return dict(stored.response)
            before = row.state
            if before.session_status == "closed":
                raise SessionError("ACTION_NOT_ALLOWED", "session_closed")
            if before.revision != expected_revision:
                raise SessionError(
                    "STALE_REVISION",
                    f"current revision is {before.revision}",
                    current_revision=before.revision,
                    current_scene_revision=before.scene_revision,
                )
            generation = row.connection_generation + 1
            event = SessionEvent(
                "control_claimed",
                before.active_attempt_id,
                {"connection_generation": generation, "turn_epoch": before.turn_epoch + 1},
            )
            after = before.with_changes(
                turn_epoch=before.turn_epoch + 1,
                revision=before.revision + 1,
                last_event_seq=before.last_event_seq + 1,
            )
            repository.save_session(
                conn,
                expected_revision=before.revision,
                row=SessionRow(
                    state=after,
                    connection_generation=generation,
                    controller_id=request_id,
                    expires_at=row.expires_at,
                ),
                now=now,
            )
            repository.append_events(
                conn,
                session_id,
                [event],
                first_seq=before.last_event_seq + 1,
                revision=after.revision,
                actor=ctx.actor,
                command_id=request_id,
                now=now,
                event_id=lambda: self._ids("evt"),
            )
            response = {
                "controller_id": request_id,
                "connection_generation": generation,
                "revision": after.revision,
                "turn_epoch": after.turn_epoch,
            }
            repository.insert_result(
                conn,
                session_id=session_id,
                command_id=request_id,
                kind="claim_control",
                body_hash=digest,
                actor=ctx.actor,
                principal_id=ctx.principal_id,
                http_status=200,
                response=response,
                revision=after.revision,
                now=now,
            )
        return response

    # --- ACK de render ---------------------------------------------------------------------------

    def record_render_receipt(
        self, ctx: ActorContext, session_id: str, receipt: RenderReceipt
    ) -> dict[str, Any]:
        """Registra o ACK sem tocar o domínio: nunca muda `revision`. Só o controlador vigente
        escreve (P3); ACK de geração antiga ou de cena futura é gravado como `stale`."""
        self._reject_foreign_session(ctx, session_id)
        if receipt.session_id != session_id:
            raise SessionError("INVALID_PAYLOAD", "session_id mismatch")
        now = self._clock()
        with self.engine.begin() as conn:
            row = repository.load_session(conn, session_id, for_update=True)
            self._authorize(ctx, row, write=True)
            assert row is not None
            if ctx.actor != "learner":
                raise SessionError(
                    "ACTION_NOT_ALLOWED", "only the controlling device sends receipts"
                )
            if repository.receipt_exists(conn, session_id, receipt.receipt_id):
                return {"receipt_id": receipt.receipt_id, "outcome": "duplicate"}
            stale = (
                receipt.connection_generation != row.connection_generation
                or receipt.scene_revision > row.state.scene_revision
            )
            outcome = "stale" if stale else "accepted"
            repository.insert_receipt(
                conn,
                session_id=session_id,
                receipt_id=receipt.receipt_id,
                effect_id=receipt.effect_id,
                command_id=receipt.command_id,
                scene_revision=receipt.scene_revision,
                connection_generation=receipt.connection_generation,
                status=receipt.status,
                outcome=outcome,
                now=now,
            )
        return {"receipt_id": receipt.receipt_id, "outcome": outcome}

    # --- passos compartilhados -------------------------------------------------------------------

    @staticmethod
    def _reject_foreign_session(ctx: ActorContext, session_id: str) -> None:
        """Credencial de outra sessão responde exatamente como sessão inexistente (AC-40): a
        checagem vem antes de qualquer leitura, então nada de `session_id` vaza."""
        if ctx.session_id is not None and ctx.session_id != session_id:
            raise SessionError("NOT_FOUND")

    def _authorize(self, ctx: ActorContext, row: SessionRow | None, *, write: bool) -> None:
        if row is None or row.expires_at <= self._clock():
            raise SessionError("NOT_FOUND")  # decisão P11: expirada é igual a inexistente
        if (
            write
            and ctx.actor == "learner"
            and not _same_controller(ctx.controller_id, row.controller_id)
        ):
            raise SessionError("CONTROL_LOST")  # decisão P3

    @staticmethod
    def _read_body(raw_body: bytes, session_id: str) -> tuple[dict[str, Any], str]:
        try:
            body = load_json_object(raw_body)
        except DomainError as err:
            raise SessionError.from_domain(err) from None
        try:
            _check_text(body)
        except RecursionError:
            raise SessionError("INVALID_PAYLOAD", "body too deeply nested") from None
        command_id = body.get("command_id")
        if not isinstance(command_id, str):
            raise SessionError("INVALID_PAYLOAD", "command_id is required")
        if body.get("session_id") != session_id:
            raise SessionError("INVALID_PAYLOAD", "session_id mismatch", command_id=command_id)
        return body, command_id

    @staticmethod
    def _replay_of(
        conn: Connection, session_id: str, command_id: str, digest: str
    ) -> CommandOutcome | None:
        stored: StoredResult | None = repository.find_result(conn, session_id, command_id)
        if stored is None:
            return None
        if stored.kind != "command" or stored.body_hash != digest:
            raise SessionError("IDEMPOTENCY_CONFLICT", command_id=command_id)
        return CommandOutcome(status_code=stored.http_status, body=stored.response, replay=True)
