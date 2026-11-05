"""`SessionService`: casos de uso da sessão persistida (Spec Parte II §2, ordem obrigatória).

Autorizar -> procurar a chave idempotente -> validar o hash do corpo -> schema e guardas ->
transação curta (estado + eventos + resultado) -> resposta. O domínio (`apply_command`) é puro;
aqui ficam a transação, a trava da linha da sessão e a gravação.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.content.loader import ContentPackage
from app.domain.division.classification import ExplanationEvaluator
from app.domain.division.commands import load_json_object, parse_command
from app.domain.division.errors import DomainError
from app.domain.division.session import apply_command
from app.domain.division.state import new_session
from app.sessions import repository
from app.sessions.context import ActorContext, Clock, IdFactory, default_ids, utc_now
from app.sessions.credentials import derive_session_token, hash_token
from app.sessions.errors import SessionError
from app.sessions.projection import session_view
from app.sessions.repository import SessionRow, StoredResult

# Decisão P2: o request_id é o segredo de onde sai o token, então precisa de alta entropia.
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{22,128}")
# NUL e substitutos soltos não existem em texto Unicode válido e o JSONB do Postgres os recusa.
_BAD_TEXT_RE = re.compile("[\x00\ud800-\udfff]")


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
    ) -> None:
        self.engine = engine
        self.content = content
        self.evaluator = evaluator
        self._secret = token_secret
        self._clock = clock
        self._ids = ids
        self._ttl = session_ttl

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
                # O controle original é o próprio request_id. Nunca devolve o controlador
                # vigente: quem repete o POST não herda um controle tomado depois.
                return CreatedSession(
                    session_id=existing,
                    session_token=token,
                    controller_id=request_id,
                    connection_generation=row.connection_generation,
                    snapshot=session_view(
                        row.state,
                        self.content,
                        connection_generation=row.connection_generation,
                    ),
                    replay=True,
                )
            state = new_session(self._ids("ses"))
            row = SessionRow(
                state=state,
                connection_generation=1,
                controller_id=request_id,
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
            controller_id=request_id,
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
            after = result.session
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
                result.events,
                first_seq=before.last_event_seq + 1,
                revision=after.revision,
                actor=ctx.actor,
                command_id=command_id,
                now=now,
                event_id=lambda: self._ids("evt"),
            )
            outcomes = {
                e.attempt_id: e.data["outcome"]
                for e in result.events
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
        if write and ctx.actor == "learner" and ctx.controller_id != row.controller_id:
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
