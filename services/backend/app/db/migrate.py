"""Aplicador mínimo das migrations SQL de `supabase/migrations/` num Postgres local ou de teste.

Em produção quem aplica é o Supabase CLI; aqui a tabela `schema_migrations` (`public`) existe só
para o banco local/de teste saber o que já rodou. Ela não faz parte de `metadata`.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, text

# services/backend/app/db/migrate.py -> raiz do repositório
MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "supabase" / "migrations"

# Serializa dois processos que migram o mesmo banco ao mesmo tempo.
_ADVISORY_LOCK_KEY = 2026_1105_01


def apply_migrations(engine: Engine, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Aplica, em ordem de nome, os `*.sql` ainda ausentes de `schema_migrations`.

    Tudo numa única transação: ou aplica todas as pendentes ou nenhuma. Devolve as versões
    aplicadas (o nome do arquivo sem `.sql`); rodar de novo devolve `[]`.
    """
    if engine.dialect.name != "postgresql":
        raise RuntimeError("apply_migrations só vale para Postgres; no SQLite use create_schema")
    files = sorted(directory.glob("*.sql"))
    applied: list[str] = []
    with engine.begin() as conn:
        conn.execute(text("select pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        conn.exec_driver_sql(
            "create table if not exists public.schema_migrations ("
            "version text primary key, "
            "applied_at timestamptz not null default now())"
        )
        done = set(conn.execute(text("select version from public.schema_migrations")).scalars())
        for path in files:
            if path.stem in done:
                continue
            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
            conn.execute(
                text("insert into public.schema_migrations (version) values (:version)"),
                {"version": path.stem},
            )
            applied.append(path.stem)
    return applied
