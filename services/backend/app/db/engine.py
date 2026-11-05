"""Criação do engine e do schema, em SQLite (testes e desenvolvimento) e Postgres (Supabase)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool

from app.db.migrate import apply_migrations
from app.db.schema import metadata

_SQLITE_BUSY_TIMEOUT_SECONDS = 30


def make_engine(url: str) -> Engine:
    """Engine para `sqlite` ou `postgresql+psycopg`.

    SQLite: chaves estrangeiras ligadas e `BEGIN IMMEDIATE` em toda transação, o que serializa os
    escritores (o pysqlite não emite BEGIN sozinho para SELECT nem para DDL). Isso também faz
    cada leitura transacional esperar o escritor corrente. URL em memória usa `StaticPool`, para
    que todas as conexões vejam o mesmo banco.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return create_engine(url)

    connect_args: dict = {"check_same_thread": False}
    if "timeout" not in parsed.query:
        connect_args["timeout"] = _SQLITE_BUSY_TIMEOUT_SECONDS
    options: dict = {"connect_args": connect_args}
    in_memory = parsed.database in (None, "", ":memory:") or "mode=memory" in str(parsed)
    if in_memory:
        options["poolclass"] = StaticPool
    engine = create_engine(url, **options)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, connection_record) -> None:
        # Desliga o BEGIN automático do pysqlite; o evento `begin` abaixo emite o nosso.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def create_schema(engine: Engine) -> None:
    """SQLite: `metadata.create_all`. Postgres: aplica as migrations de `supabase/migrations/`."""
    if engine.dialect.name == "sqlite":
        metadata.create_all(engine)
    else:
        apply_migrations(engine)
