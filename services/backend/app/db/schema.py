"""Schema relacional da sessão persistida (incremento 2), em SQLAlchemy Core.

Fonte do SQLite (`metadata.create_all`) e referência do Postgres: a migration em
`supabase/migrations/` é escrita à mão e um teste reflete o banco migrado para compará-la com
`metadata` (decisão P10). Mudou aqui, muda lá.

Convenções:
- JSON usa `JSONB` no Postgres e `JSON` no SQLite.
- Timestamps usam `UtcDateTime`: o valor gravado tem de ter fuso (é convertido para UTC) e o valor
  lido volta sempre como `datetime` com `tzinfo=UTC`, também no SQLite, que não guarda fuso.
- Toda coluna é `NOT NULL`, salvo as marcadas `nullable=True`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """`DateTime(timezone=True)` que só aceita valores com fuso e sempre devolve UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamp sem fuso horário: use um datetime com tzinfo")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:  # SQLite devolve ingênuo; o que foi gravado era UTC
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def _json() -> JSON:
    return JSON().with_variant(JSONB, "postgresql")


metadata = MetaData()

sessions = Table(
    "sessions",
    metadata,
    Column("session_id", Text, primary_key=True),
    Column("content_version", Text, nullable=False),
    Column("create_request_id", Text, nullable=False),
    Column("state", _json(), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("scene_revision", Integer, nullable=False),
    Column("phase", Text, nullable=False),
    Column("session_status", Text, nullable=False),
    Column("turn_epoch", Integer, nullable=False),
    Column("last_event_seq", Integer, nullable=False),
    Column("active_attempt_id", Text, nullable=True),
    Column("connection_generation", Integer, nullable=False),
    Column("controller_id", Text, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    Column("expires_at", UtcDateTime, nullable=False),
    UniqueConstraint("create_request_id", name="uq_sessions_create_request_id"),
    CheckConstraint("revision >= 0", name="ck_sessions_revision"),
    CheckConstraint("connection_generation >= 1", name="ck_sessions_connection_generation"),
)

session_credentials = Table(
    "session_credentials",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column(
        "session_id", Text, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    ),
    Column("actor", Text, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    CheckConstraint("actor = 'learner'", name="ck_session_credentials_actor"),
)

attempts = Table(
    "attempts",
    metadata,
    Column(
        "session_id", Text, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    ),
    Column("attempt_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("item_id", Text, nullable=False),  # o task_id da Spec Parte II §9
    Column("status", Text, nullable=False),
    Column("outcome", Text, nullable=True),  # o "resultado" da tentativa (Spec Parte II §9)
    Column("assistance_level", Text, nullable=False),
    Column("support_resources", _json(), nullable=False),
    Column("updated_revision", Integer, nullable=False),
    PrimaryKeyConstraint("session_id", "attempt_id", name="pk_attempts"),
)

session_events = Table(
    "session_events",
    metadata,
    Column("event_id", Text, primary_key=True),
    Column(
        "session_id", Text, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    ),
    Column("event_seq", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("type", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("command_id", Text, nullable=True),
    Column("attempt_id", Text, nullable=True),
    Column("occurred_at", UtcDateTime, nullable=False),
    Column("data", _json(), nullable=False),
    UniqueConstraint("session_id", "event_seq", name="uq_session_events_session_seq"),
)

command_results = Table(
    "command_results",
    metadata,
    Column(
        "session_id", Text, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    ),
    Column("command_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("body_hash", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("principal_id", Text, nullable=False),
    Column("http_status", Integer, nullable=False),
    Column("response", _json(), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    PrimaryKeyConstraint("session_id", "command_id", name="pk_command_results"),
    CheckConstraint("kind in ('command', 'claim_control')", name="ck_command_results_kind"),
)

render_receipts = Table(
    "render_receipts",
    metadata,
    Column(
        "session_id", Text, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    ),
    Column("receipt_id", Text, nullable=False),
    Column("effect_id", Text, nullable=False),
    Column("command_id", Text, nullable=False),
    Column("scene_revision", Integer, nullable=False),
    Column("connection_generation", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("received_at", UtcDateTime, nullable=False),
    PrimaryKeyConstraint("session_id", "receipt_id", name="pk_render_receipts"),
    CheckConstraint("outcome in ('accepted', 'stale')", name="ck_render_receipts_outcome"),
)

artifacts = Table(
    "artifacts",
    metadata,
    Column("artifact_id", Text, primary_key=True),
    Column(
        "session_id", Text, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    ),
    Column("attempt_id", Text, nullable=False),
    Column("purpose", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("content_hash", Text, nullable=True),
    Column("object_key", Text, nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("expires_at", UtcDateTime, nullable=False),
    UniqueConstraint(
        "session_id",
        "attempt_id",
        "purpose",
        "version",
        name="uq_artifacts_attempt_purpose_version",
    ),
    CheckConstraint("purpose in ('source', 'notebook')", name="ck_artifacts_purpose"),
    CheckConstraint("version >= 1", name="ck_artifacts_version"),
)

analysis_jobs = Table(
    "analysis_jobs",
    metadata,
    Column("job_id", Text, primary_key=True),
    Column(
        "session_id", Text, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    ),
    Column(
        "artifact_id", Text, ForeignKey("artifacts.artifact_id", ondelete="CASCADE"), nullable=False
    ),
    Column("request_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("executions", Integer, nullable=False, server_default=text("0")),
    Column("applied", Boolean, nullable=False, server_default=false()),
    Column("error_code", Text, nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    UniqueConstraint("session_id", "request_id", name="uq_analysis_jobs_session_request"),
    CheckConstraint(
        "status in ('queued', 'running', 'ready', 'needs_clarification', 'failed', 'superseded')",
        name="ck_analysis_jobs_status",
    ),
)

observations = Table(
    "observations",
    metadata,
    Column("observation_id", Text, primary_key=True),
    Column("job_id", Text, ForeignKey("analysis_jobs.job_id", ondelete="CASCADE"), nullable=False),
    Column(
        "session_id", Text, ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False
    ),
    Column("attempt_id", Text, nullable=False),
    Column(
        "artifact_id", Text, ForeignKey("artifacts.artifact_id", ondelete="CASCADE"), nullable=False
    ),
    Column("document", _json(), nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    UniqueConstraint("job_id", name="uq_observations_job_id"),
)

__all__ = [
    "UtcDateTime",
    "analysis_jobs",
    "artifacts",
    "attempts",
    "command_results",
    "metadata",
    "observations",
    "render_receipts",
    "session_credentials",
    "session_events",
    "sessions",
]
