"""Leitura e escrita da sessão em SQLAlchemy Core. Toda função recebe uma `Connection`: a
transação é de quem chama (o `SessionService`), nunca daqui.

`sessions.state` é a fonte da verdade (decisão P1); `session_events` é o log durável e `attempts`
é um modelo de leitura derivado do estado. Eventos e resultados guardam exatamente o que o
domínio devolveu.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Connection, func, insert, select, update

from app.db.schema import (
    analysis_jobs,
    artifacts,
    attempts,
    command_results,
    observations,
    render_receipts,
    session_credentials,
    session_events,
    sessions,
)
from app.domain.division.state import SessionState
from app.sessions.errors import SessionError
from app.sessions.projection import EventRecord


class NewEvent(Protocol):
    """O que `append_events` precisa de um evento: os `DomainEvent` do domínio servem, e também os
    eventos da camada `sessions` (`control_claimed`), que não são comandos do catálogo."""

    @property
    def type(self) -> str: ...
    @property
    def attempt_id(self) -> str | None: ...
    @property
    def data(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class SessionEvent:
    type: str
    attempt_id: str | None
    data: Mapping[str, Any]


@dataclass(frozen=True)
class SessionRow:
    state: SessionState
    connection_generation: int
    controller_id: str
    expires_at: datetime


@dataclass(frozen=True)
class StoredResult:
    kind: str
    body_hash: str
    actor: str
    principal_id: str
    http_status: int
    response: dict[str, Any]
    revision: int


def _summary_columns(state: SessionState) -> dict[str, Any]:
    """Colunas denormalizadas de `sessions`: o que as consultas precisam sem abrir o JSON."""
    return {
        "state": state.model_dump(mode="json"),
        "revision": state.revision,
        "scene_revision": state.scene_revision,
        "phase": state.phase,
        "session_status": state.session_status,
        "turn_epoch": state.turn_epoch,
        "last_event_seq": state.last_event_seq,
        "active_attempt_id": state.active_attempt_id,
    }


# --- sessão -------------------------------------------------------------------------------------


def load_session(conn: Connection, session_id: str, *, for_update: bool) -> SessionRow | None:
    """`for_update` trava a linha até o fim da transação (Postgres). No SQLite o `BEGIN IMMEDIATE`
    do engine já serializa os escritores, e a cláusula não existe."""
    query = select(
        sessions.c.state,
        sessions.c.connection_generation,
        sessions.c.controller_id,
        sessions.c.expires_at,
    ).where(sessions.c.session_id == session_id)
    if for_update and conn.dialect.name == "postgresql":
        query = query.with_for_update()
    found = conn.execute(query).one_or_none()
    if found is None:
        return None
    return SessionRow(
        state=SessionState.model_validate(found.state),
        connection_generation=found.connection_generation,
        controller_id=found.controller_id,
        expires_at=found.expires_at,
    )


def find_session_id_by_request(conn: Connection, create_request_id: str) -> str | None:
    return conn.execute(
        select(sessions.c.session_id).where(sessions.c.create_request_id == create_request_id)
    ).scalar_one_or_none()


def insert_session(
    conn: Connection,
    *,
    create_request_id: str,
    row: SessionRow,
    token_hash: str,
    now: datetime,
) -> None:
    """Cria a sessão e a credencial do aluno. `IntegrityError` se o `request_id` já foi usado."""
    state = row.state
    conn.execute(
        insert(sessions).values(
            session_id=state.session_id,
            content_version=state.content_version,
            create_request_id=create_request_id,
            connection_generation=row.connection_generation,
            controller_id=row.controller_id,
            created_at=now,
            updated_at=now,
            expires_at=row.expires_at,
            **_summary_columns(state),
        )
    )
    conn.execute(
        insert(session_credentials).values(
            token_hash=token_hash, session_id=state.session_id, actor="learner", created_at=now
        )
    )


def save_session(
    conn: Connection, *, expected_revision: int, row: SessionRow, now: datetime
) -> None:
    """Grava o novo estado só se a revisão ainda é a esperada: segunda defesa contra escrita
    concorrente, depois do `FOR UPDATE`."""
    state = row.state
    result = conn.execute(
        update(sessions)
        .where(sessions.c.session_id == state.session_id, sessions.c.revision == expected_revision)
        .values(
            connection_generation=row.connection_generation,
            controller_id=row.controller_id,
            updated_at=now,
            **_summary_columns(state),
        )
    )
    if result.rowcount != 1:
        raise SessionError("STALE_REVISION")


# --- eventos ------------------------------------------------------------------------------------


def append_events(
    conn: Connection,
    session_id: str,
    events: Sequence[NewEvent],
    *,
    first_seq: int,
    revision: int,
    actor: str,
    command_id: str | None,
    now: datetime,
    event_id: Callable[[], str],
) -> list[EventRecord]:
    """Grava os eventos do domínio como vieram, com `event_seq` contínuo a partir de `first_seq`.
    `event_id` gera um id opaco por evento."""
    records = [
        EventRecord(
            event_id=event_id(),
            session_id=session_id,
            event_seq=first_seq + offset,
            revision=revision,
            type=event.type,
            actor=actor,
            command_id=command_id,
            attempt_id=event.attempt_id,
            occurred_at=now,
            data=dict(event.data),
        )
        for offset, event in enumerate(events)
    ]
    if records:
        conn.execute(
            insert(session_events),
            [
                {
                    "event_id": r.event_id,
                    "session_id": r.session_id,
                    "event_seq": r.event_seq,
                    "revision": r.revision,
                    "type": r.type,
                    "actor": r.actor,
                    "command_id": r.command_id,
                    "attempt_id": r.attempt_id,
                    "occurred_at": r.occurred_at,
                    "data": r.data,
                }
                for r in records
            ],
        )
    return records


def list_events(
    conn: Connection, session_id: str, *, after_seq: int, limit: int
) -> list[EventRecord]:
    """Eventos com `event_seq > after_seq`, em ordem, no máximo `limit`."""
    rows = conn.execute(
        select(session_events)
        .where(session_events.c.session_id == session_id, session_events.c.event_seq > after_seq)
        .order_by(session_events.c.event_seq)
        .limit(limit)
    ).mappings()
    return [
        EventRecord(
            event_id=r["event_id"],
            session_id=r["session_id"],
            event_seq=r["event_seq"],
            revision=r["revision"],
            type=r["type"],
            actor=r["actor"],
            command_id=r["command_id"],
            attempt_id=r["attempt_id"],
            occurred_at=r["occurred_at"],
            data=r["data"],
        )
        for r in rows
    ]


# --- credenciais --------------------------------------------------------------------------------


def find_credential(conn: Connection, token_hash: str) -> tuple[str, str] | None:
    """`(session_id, actor)` da credencial de sessão com esse hash, se existir."""
    found = conn.execute(
        select(session_credentials.c.session_id, session_credentials.c.actor).where(
            session_credentials.c.token_hash == token_hash
        )
    ).one_or_none()
    return None if found is None else (found.session_id, found.actor)


# --- ACK de render ------------------------------------------------------------------------------


def receipt_exists(conn: Connection, session_id: str, receipt_id: str) -> bool:
    return (
        conn.execute(
            select(render_receipts.c.receipt_id).where(
                render_receipts.c.session_id == session_id,
                render_receipts.c.receipt_id == receipt_id,
            )
        ).first()
        is not None
    )


def insert_receipt(
    conn: Connection,
    *,
    session_id: str,
    receipt_id: str,
    effect_id: str,
    command_id: str,
    scene_revision: int,
    connection_generation: int,
    status: str,
    outcome: str,
    now: datetime,
) -> None:
    conn.execute(
        insert(render_receipts).values(
            session_id=session_id,
            receipt_id=receipt_id,
            effect_id=effect_id,
            command_id=command_id,
            scene_revision=scene_revision,
            connection_generation=connection_generation,
            status=status,
            outcome=outcome,
            received_at=now,
        )
    )


# --- tentativas ---------------------------------------------------------------------------------


def upsert_attempts(
    conn: Connection, state: SessionState, *, outcomes: Mapping[str, str] | None = None
) -> None:
    """Mantém `attempts` em dia com o estado. Só toca a linha que mudou (e então grava
    `updated_revision`). `outcomes` traz o resultado classificado por tentativa (do evento
    `attempt_evaluated` deste comando); sem ele, o `outcome` já gravado fica como está."""
    outcomes = outcomes or {}
    existing = {
        row.attempt_id: row
        for row in conn.execute(
            select(
                attempts.c.attempt_id,
                attempts.c.kind,
                attempts.c.item_id,
                attempts.c.status,
                attempts.c.outcome,
                attempts.c.assistance_level,
                attempts.c.support_resources,
            ).where(attempts.c.session_id == state.session_id)
        )
    }
    for attempt in state.attempts:
        wanted: dict[str, Any] = {
            "kind": attempt.kind,
            "item_id": attempt.item_id,
            "status": attempt.status,
            "assistance_level": attempt.ledger.level,
            "support_resources": sorted(attempt.ledger.resources),
        }
        current = existing.get(attempt.attempt_id)
        outcome = outcomes.get(attempt.attempt_id, current.outcome if current else None)
        wanted["outcome"] = outcome
        if current is None:
            conn.execute(
                insert(attempts).values(
                    session_id=state.session_id,
                    attempt_id=attempt.attempt_id,
                    updated_revision=state.revision,
                    **wanted,
                )
            )
        elif any(getattr(current, key) != value for key, value in wanted.items()):
            conn.execute(
                update(attempts)
                .where(
                    attempts.c.session_id == state.session_id,
                    attempts.c.attempt_id == attempt.attempt_id,
                )
                .values(updated_revision=state.revision, **wanted)
            )


# --- resultados idempotentes --------------------------------------------------------------------


def find_result(conn: Connection, session_id: str, command_id: str) -> StoredResult | None:
    found = conn.execute(
        select(
            command_results.c.kind,
            command_results.c.body_hash,
            command_results.c.actor,
            command_results.c.principal_id,
            command_results.c.http_status,
            command_results.c.response,
            command_results.c.revision,
        ).where(
            command_results.c.session_id == session_id,
            command_results.c.command_id == command_id,
        )
    ).one_or_none()
    if found is None:
        return None
    return StoredResult(
        kind=found.kind,
        body_hash=found.body_hash,
        actor=found.actor,
        principal_id=found.principal_id,
        http_status=found.http_status,
        response=found.response,
        revision=found.revision,
    )


def insert_result(
    conn: Connection,
    *,
    session_id: str,
    command_id: str,
    kind: str,
    body_hash: str,
    actor: str,
    principal_id: str,
    http_status: int,
    response: dict[str, Any],
    revision: int,
    now: datetime,
) -> None:
    """`IntegrityError` se a chave `(session_id, command_id)` já foi gravada por outra transação."""
    conn.execute(
        insert(command_results).values(
            session_id=session_id,
            command_id=command_id,
            kind=kind,
            body_hash=body_hash,
            actor=actor,
            principal_id=principal_id,
            http_status=http_status,
            response=response,
            revision=revision,
            created_at=now,
        )
    )


# --- artefatos, jobs de análise e observações ----------------------------------------------------

# Jobs que ainda podem receber ou reconciliar um resultado: o `applied` marca a aplicação.
_OPEN_JOB_STATUSES = ("queued", "running", "ready", "needs_clarification")


@dataclass(frozen=True)
class JobRow:
    job_id: str
    session_id: str
    artifact_id: str
    artifact_version: int
    attempt_id: str
    status: str
    applied: bool


def next_artifact_version(
    conn: Connection, session_id: str, attempt_id: str, purpose: str = "notebook"
) -> int:
    """`1 + max(version)` por `(session_id, attempt_id, purpose)`. Chamado com a sessão travada."""
    highest = conn.execute(
        select(func.max(artifacts.c.version)).where(
            artifacts.c.session_id == session_id,
            artifacts.c.attempt_id == attempt_id,
            artifacts.c.purpose == purpose,
        )
    ).scalar_one()
    return 1 + (highest or 0)


def insert_artifact(
    conn: Connection,
    *,
    artifact_id: str,
    session_id: str,
    attempt_id: str,
    purpose: str,
    version: int,
    expires_at: datetime,
    now: datetime,
) -> None:
    """No incremento 2 não há armazenamento de objeto: `object_key` e `content_hash` ficam nulos."""
    conn.execute(
        insert(artifacts).values(
            artifact_id=artifact_id,
            session_id=session_id,
            attempt_id=attempt_id,
            purpose=purpose,
            version=version,
            content_hash=None,
            object_key=None,
            created_at=now,
            expires_at=expires_at,
        )
    )


def insert_job(
    conn: Connection,
    *,
    job_id: str,
    session_id: str,
    artifact_id: str,
    request_id: str,
    now: datetime,
) -> None:
    conn.execute(
        insert(analysis_jobs).values(
            job_id=job_id,
            session_id=session_id,
            artifact_id=artifact_id,
            request_id=request_id,
            status="queued",
            executions=0,
            applied=False,
            created_at=now,
            updated_at=now,
        )
    )


def find_job(conn: Connection, job_id: str) -> JobRow | None:
    found = conn.execute(
        select(
            analysis_jobs.c.job_id,
            analysis_jobs.c.session_id,
            analysis_jobs.c.artifact_id,
            analysis_jobs.c.status,
            analysis_jobs.c.applied,
            artifacts.c.version,
            artifacts.c.attempt_id,
        )
        .select_from(
            analysis_jobs.join(artifacts, artifacts.c.artifact_id == analysis_jobs.c.artifact_id)
        )
        .where(analysis_jobs.c.job_id == job_id)
    ).one_or_none()
    if found is None:
        return None
    return JobRow(
        job_id=found.job_id,
        session_id=found.session_id,
        artifact_id=found.artifact_id,
        artifact_version=found.version,
        attempt_id=found.attempt_id,
        status=found.status,
        applied=bool(found.applied),
    )


def update_job(
    conn: Connection,
    job_id: str,
    *,
    status: str,
    applied: bool,
    now: datetime,
    count_execution: bool = False,
) -> None:
    values: dict[str, Any] = {"status": status, "applied": applied, "updated_at": now}
    if count_execution:
        values["executions"] = analysis_jobs.c.executions + 1
    conn.execute(update(analysis_jobs).where(analysis_jobs.c.job_id == job_id).values(**values))


def supersede_jobs(
    conn: Connection, session_id: str, job_ids: Sequence[str], *, now: datetime
) -> None:
    """Marca como `superseded` os jobs abertos e ainda não aplicados (inclusive os adiados)."""
    if not job_ids:
        return
    conn.execute(
        update(analysis_jobs)
        .where(
            analysis_jobs.c.session_id == session_id,
            analysis_jobs.c.job_id.in_(list(job_ids)),
            analysis_jobs.c.status.in_(_OPEN_JOB_STATUSES),
            analysis_jobs.c.applied.is_(False),
        )
        .values(status="superseded", updated_at=now)
    )


def insert_observation(
    conn: Connection,
    *,
    observation_id: str,
    job_id: str,
    session_id: str,
    attempt_id: str,
    artifact_id: str,
    document: dict[str, Any],
    now: datetime,
) -> None:
    """Só a observação estruturada (R28): nenhum texto livre da criança existe aqui."""
    conn.execute(
        insert(observations).values(
            observation_id=observation_id,
            job_id=job_id,
            session_id=session_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            document=document,
            created_at=now,
        )
    )


def load_observation_document(conn: Connection, job_id: str) -> dict[str, Any] | None:
    found = conn.execute(
        select(observations.c.document).where(observations.c.job_id == job_id)
    ).scalar_one_or_none()
    return None if found is None else dict(found)
