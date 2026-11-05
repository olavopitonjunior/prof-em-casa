"""Schema, migration e fixtures de banco (Task 1 do incremento 2).

Os testes de `pg_engine` rodam só em Postgres; os de `engine` rodam nos dois bancos.
"""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.db.engine import make_engine
from app.db.migrate import MIGRATIONS_DIR, apply_migrations
from app.db.schema import (
    analysis_jobs,
    artifacts,
    attempts,
    command_results,
    metadata,
    observations,
    render_receipts,
    session_credentials,
    session_events,
    sessions,
)
from app.domain.division.session import SessionState, new_session
from helpers import cmd, practice_with_counts, run, session_in_practice, session_in_transfer
from sqlalchemy import JSON, MetaData, UniqueConstraint, delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError
from sqlalchemy.pool import StaticPool

T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(hours=24)


# --- Jornadas de domínio (cada uma devolve todos os estados intermediários) ----------------


def _walk(start: SessionState, *steps):
    state = start
    yield state
    for step in steps:
        state = run(state, step)
        yield state


def _demo_complete():
    steps = [cmd("choose_reference_activity")]
    steps += [
        cmd("run_demo_step", actor="system", step_id=f"r{r}-g{g}")
        for r in (1, 2, 3)
        for g in (1, 2, 3, 4)
    ]
    steps.append(cmd("finish_demonstration", actor="system", reason="completed"))
    yield from _walk(new_session("s1"), *steps)


def _practice_unequal():
    """Prática [7, 5, 6, 6]: distribuição desigual, verificação e resposta."""
    moves = []
    nxt = 1
    for group, count in enumerate([7, 5, 6, 6], start=1):
        for _ in range(count):
            moves.append(
                cmd(
                    "move_piece",
                    piece_id=f"piece-{nxt:02d}",
                    from_location="available",
                    to_location=f"group-{group}",
                )
            )
            nxt += 1
    moves.append(cmd("check_distribution"))
    moves.append(cmd("submit_answer", answer=6))
    yield from _walk(session_in_practice(), *moves)


def _notebook():
    yield from _walk(
        practice_with_counts([1, 0, 0, 0]),
        cmd("enter_notebook", intent="record_solution"),
        cmd("request_help", kind="prompt", reason="preciso de uma pista"),
        cmd("return_to_activity"),
        cmd("enter_notebook", intent="try_on_paper"),
        cmd("return_to_activity"),
    )


def _transfer_with_help():
    yield from _walk(
        session_in_transfer(),
        cmd("request_help", kind="virtual_objects", reason="quero as peças"),
        cmd("enter_notebook", intent="try_on_paper"),
        cmd("return_to_activity"),
        cmd("submit_answer", answer=4),
        cmd("submit_explanation", text="5 grupos de 4 dão 20"),
        cmd("continue_after_explanation", reason="sufficient"),
        cmd("pause_session"),
        cmd("resume_session"),
        cmd("close_session", reason="learner_stopped"),
    )


ALL_DOMAIN_JOURNEYS = [_demo_complete, _practice_unequal, _notebook, _transfer_with_help]


def _dump(state: SessionState) -> dict:
    """O que vai para a coluna JSON: o que o `json` do Python consegue gravar e reler."""
    return json.loads(json.dumps(state.model_dump(mode="json")))


@pytest.mark.parametrize("journey", ALL_DOMAIN_JOURNEYS, ids=lambda j: j.__name__)
def test_session_state_json_round_trip(journey):  # Review Focus 3
    count = 0
    for state in journey():
        assert SessionState.model_validate(_dump(state)) == state
        count += 1
    assert count > 1


def test_round_trip_keeps_frozenset_ledger_resources():
    states = list(_transfer_with_help())
    helped = [s for s in states if s.active_attempt and s.active_attempt.ledger.resources]
    assert helped, "a jornada com ajuda precisa terminar com recursos no ledger"
    back = SessionState.model_validate(_dump(helped[-1]))
    assert isinstance(back.active_attempt.ledger.resources, frozenset)


# --- Utilidades ----------------------------------------------------------------------------


def _unique_sets(table):
    """PK + UNIQUE (constraint ou índice único) como conjuntos de nomes de coluna."""
    sets = {frozenset(c.name for c in table.primary_key.columns)}
    sets |= {
        frozenset(c.name for c in con.columns)
        for con in table.constraints
        if isinstance(con, UniqueConstraint)
    }
    sets |= {frozenset(c.name for c in idx.columns) for idx in table.indexes if idx.unique}
    return sets


def _foreign_keys(table):
    return {
        (
            frozenset(c.name for c in fk.columns),
            fk.elements[0].column.table.name,
            frozenset(e.column.name for e in fk.elements),
            fk.ondelete,
        )
        for fk in table.foreign_key_constraints
    }


def _session_row(session_id="s1", request_id="req-1", **over):
    row = {
        "session_id": session_id,
        "content_version": "division-sharing-v1",
        "create_request_id": request_id,
        "state": {"k": "v"},
        "revision": 0,
        "scene_revision": 0,
        "phase": "source_capture",
        "session_status": "active",
        "turn_epoch": 0,
        "last_event_seq": 0,
        "active_attempt_id": None,
        "connection_generation": 1,
        "controller_id": request_id,
        "created_at": T0,
        "updated_at": T0,
        "expires_at": T1,
    }
    return row | over


def _event_row(session_id="s1", seq=1, **over):
    row = {
        "event_id": f"{session_id}-e{seq}",
        "session_id": session_id,
        "event_seq": seq,
        "revision": 1,
        "type": "attempt_started",
        "actor": "learner",
        "command_id": None,
        "attempt_id": None,
        "occurred_at": T0,
        "data": {},
    }
    return row | over


def _artifact_row(artifact_id="a1", session_id="s1", **over):
    row = {
        "artifact_id": artifact_id,
        "session_id": session_id,
        "attempt_id": "att-1",
        "purpose": "source",
        "version": 1,
        "content_hash": None,
        "object_key": None,
        "created_at": T0,
        "expires_at": T1,
    }
    return row | over


def _job_row(job_id="j1", **over):
    row = {
        "job_id": job_id,
        "session_id": "s1",
        "artifact_id": "a1",
        "request_id": "r1",
        "status": "queued",
        "error_code": None,
        "created_at": T0,
        "updated_at": T0,
    }
    return row | over


def _attempt_row(session_id="s1", **over):
    row = {
        "session_id": session_id,
        "attempt_id": "att-1",
        "kind": "practice",
        "item_id": "task-1",
        "status": "active",
        "outcome": None,
        "assistance_level": "none",
        "support_resources": [],
        "updated_revision": 0,
    }
    return row | over


def _result_row(session_id="s1", **over):
    row = {
        "session_id": session_id,
        "command_id": "c1",
        "kind": "command",
        "body_hash": "h",
        "actor": "learner",
        "principal_id": "p",
        "http_status": 200,
        "response": {},
        "revision": 1,
        "created_at": T0,
    }
    return row | over


def _receipt_row(session_id="s1", **over):
    row = {
        "session_id": session_id,
        "receipt_id": "r1",
        "effect_id": "e1",
        "command_id": "c1",
        "scene_revision": 0,
        "connection_generation": 1,
        "status": "ok",
        "outcome": "accepted",
        "received_at": T0,
    }
    return row | over


def _observation_row(session_id="s1", **over):
    row = {
        "observation_id": "o1",
        "job_id": "j1",
        "session_id": session_id,
        "attempt_id": "att-1",
        "artifact_id": "a1",
        "document": {"groups": []},
        "created_at": T0,
    }
    return row | over


def _seed(conn, *, artifact=False, job=False):
    conn.execute(insert(sessions).values(_session_row()))
    if artifact or job:
        conn.execute(insert(artifacts).values(_artifact_row()))
    if job:
        conn.execute(insert(analysis_jobs).values(_job_row()))


# --- Postgres: migration ↔ metadata (P10) --------------------------------------------------


def test_postgres_schema_matches_metadata(pg_engine):  # P10
    reflected = MetaData()
    reflected.reflect(pg_engine)
    for name, table in metadata.tables.items():
        got = reflected.tables[name]
        assert {c.name: c.nullable for c in got.columns} == {
            c.name: c.nullable for c in table.columns
        }, name
        assert _unique_sets(got) == _unique_sets(table), name
        assert _foreign_keys(got) == _foreign_keys(table), name
    assert set(reflected.tables) - {"schema_migrations"} == set(metadata.tables)


def test_postgres_json_columns_are_jsonb(pg_engine):
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "select table_name, column_name from information_schema.columns "
                "where table_schema = 'public' and data_type = 'jsonb'"
            )
        ).all()
    expected = {
        (table.name, column.name)
        for table in metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, JSON)
    }
    assert len(expected) == 5  # state, support_resources, data, response, document
    assert {tuple(r) for r in rows} == expected


def test_migrations_are_idempotent(pg_engine):
    assert apply_migrations(pg_engine) == []


def test_apply_migrations_applies_only_new_files_in_order(pg_engine, tmp_path):
    (tmp_path / "20270101000001_b.sql").write_text("create table public.zz_b (id int primary key);")
    (tmp_path / "20270101000000_a.sql").write_text("create table public.zz_a (id int primary key);")
    assert apply_migrations(pg_engine, tmp_path) == ["20270101000000_a", "20270101000001_b"]
    assert apply_migrations(pg_engine, tmp_path) == []
    with pg_engine.connect() as conn:
        versions = (
            conn.execute(text("select version from public.schema_migrations order by version"))
            .scalars()
            .all()
        )
    assert versions == sorted(versions)
    assert versions[0] == "20261105120000_incremento_2_sessoes"
    assert versions[-2:] == ["20270101000000_a", "20270101000001_b"]


def test_failed_migration_is_atomic(pg_engine, tmp_path):
    (tmp_path / "20270201000000_good.sql").write_text("create table public.zz_ok (id int);")
    (tmp_path / "20270201000001_bad.sql").write_text("create table public.zz_bad (id int); boom;")
    with pytest.raises(Exception):  # noqa: B017 - qualquer falha de SQL serve
        apply_migrations(pg_engine, tmp_path)
    with pg_engine.connect() as conn:
        assert conn.execute(text("select to_regclass('public.zz_ok')")).scalar() is None
        assert conn.execute(text("select to_regclass('public.zz_bad')")).scalar() is None
    stems = [p.stem for p in sorted(MIGRATIONS_DIR.glob("*.sql"))]
    assert stems[0] == "20261105120000_incremento_2_sessoes"
    assert stems == sorted(stems)


def test_rls_enabled_on_every_table(pg_engine):
    with pg_engine.connect() as conn:
        off = (
            conn.execute(
                text(
                    "select relname from pg_class where relkind='r' "
                    "and relnamespace='public'::regnamespace and not relrowsecurity"
                )
            )
            .scalars()
            .all()
        )
        on = (
            conn.execute(
                text(
                    "select relname from pg_class where relkind='r' "
                    "and relnamespace='public'::regnamespace and relrowsecurity"
                )
            )
            .scalars()
            .all()
        )
        policies = conn.execute(text("select count(*) from pg_policies")).scalar()
    assert set(off) <= {"schema_migrations"}
    assert set(on) == set(metadata.tables)
    assert policies == 0  # RLS sem policy: só o backend acessa


def test_migration_starts_with_create_table_and_ends_with_rls():
    statements = [
        s.strip()
        for s in (MIGRATIONS_DIR / "20261105120000_incremento_2_sessoes.sql")
        .read_text(encoding="utf-8")
        .split(";")
        if s.strip()
    ]
    assert statements[0].startswith("create table public.")
    tail = statements[-len(metadata.tables) :]
    assert all("enable row level security" in s for s in tail)


# --- Os dois bancos: restrições ------------------------------------------------------------


def test_unique_event_seq_per_session(engine):
    with engine.begin() as conn:
        conn.execute(insert(sessions).values(_session_row("s1", "req-1")))
        conn.execute(insert(sessions).values(_session_row("s2", "req-2")))
        conn.execute(insert(session_events).values(_event_row("s1", 1)))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(session_events).values(_event_row("s1", 1, event_id="outro-id")))
    with engine.begin() as conn:  # outra sessão pode usar o mesmo event_seq
        conn.execute(insert(session_events).values(_event_row("s2", 1)))
        assert conn.execute(select(session_events.c.event_id)).all()


def test_create_request_id_is_unique(engine):
    with engine.begin() as conn:
        conn.execute(insert(sessions).values(_session_row("s1", "req-1")))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(sessions).values(_session_row("s2", "req-1")))


CHECK_CASES = {
    "revision negativa": (sessions, _session_row("sx", "req-x", revision=-1)),
    "connection_generation zero": (sessions, _session_row("sx", "req-x", connection_generation=0)),
    "credencial de outro ator": (
        session_credentials,
        {"token_hash": "h", "session_id": "s1", "actor": "tutor", "created_at": T0},
    ),
    "kind de resultado": (
        command_results,
        {
            "session_id": "s1",
            "command_id": "c1",
            "kind": "outro",
            "body_hash": "h",
            "actor": "learner",
            "principal_id": "p",
            "http_status": 200,
            "response": {},
            "revision": 1,
            "created_at": T0,
        },
    ),
    "outcome de recibo": (
        render_receipts,
        {
            "session_id": "s1",
            "receipt_id": "r1",
            "effect_id": "e1",
            "command_id": "c1",
            "scene_revision": 0,
            "connection_generation": 1,
            "status": "ok",
            "outcome": "duplicate",
            "received_at": T0,
        },
    ),
    "purpose de artefato": (artifacts, _artifact_row("a-purpose", purpose="outro")),
    "version de artefato": (artifacts, _artifact_row("a-version", version=0)),
    "status de job": (analysis_jobs, _job_row(status="done")),
}


@pytest.mark.parametrize("case", CHECK_CASES)
def test_check_constraints_reject_bad_rows(engine, case):
    table, row = CHECK_CASES[case]
    with engine.begin() as conn:
        # s1 existe para que só o CHECK (e não a FK) possa falhar; a1 idem para o job
        conn.execute(insert(sessions).values(_session_row("s1", "seed")))
        conn.execute(insert(artifacts).values(_artifact_row()))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(table).values(row))


def test_foreign_keys_are_enforced(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(session_events).values(_event_row("sem-sessao", 1)))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(sessions).values(_session_row()))
        conn.execute(insert(analysis_jobs).values(_job_row(artifact_id="inexistente")))


ORPHANS = {
    "attempts": (attempts, _attempt_row("sem-sessao")),
    "command_results": (command_results, _result_row("sem-sessao")),
    "render_receipts": (render_receipts, _receipt_row("sem-sessao")),
    "observations.session_id": (observations, _observation_row("sem-sessao")),
    "observations.artifact_id": (observations, _observation_row(artifact_id="inexistente")),
}


@pytest.mark.parametrize("case", ORPHANS)
def test_session_scoped_tables_reject_orphans(engine, case):
    table, row = ORPHANS[case]
    with engine.begin() as conn:
        _seed(conn, job=True)  # s1, a1 e j1 existem: só a coluna do caso aponta para o vazio
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(table).values(row))


def test_deleting_a_session_cascades_to_everything_it_owns(engine):
    children = [
        session_credentials,
        attempts,
        session_events,
        command_results,
        render_receipts,
        artifacts,
        analysis_jobs,
        observations,
    ]
    with engine.begin() as conn:
        _seed(conn, job=True)
        conn.execute(insert(sessions).values(_session_row("s2", "req-2")))
        conn.execute(
            insert(session_credentials).values(
                token_hash="t1", session_id="s1", actor="learner", created_at=T0
            )
        )
        conn.execute(insert(attempts).values(_attempt_row()))
        conn.execute(insert(session_events).values(_event_row("s1", 1)))
        conn.execute(insert(command_results).values(_result_row()))
        conn.execute(insert(render_receipts).values(_receipt_row()))
        conn.execute(insert(observations).values(_observation_row()))
        conn.execute(insert(attempts).values(_attempt_row("s2")))  # sobrevive
        for table in children:
            assert conn.execute(select(func.count()).select_from(table)).scalar() >= 1, table.name
    with engine.begin() as conn:
        conn.execute(delete(sessions).where(sessions.c.session_id == "s1"))
    with engine.connect() as conn:
        counts = {
            t.name: conn.execute(select(func.count()).select_from(t)).scalar() for t in children
        }
        left = conn.execute(select(sessions.c.session_id)).scalars().all()
    assert counts == {t.name: 0 for t in children} | {"attempts": 1}
    assert left == ["s2"]


def test_deleting_an_artifact_cascades_to_its_observations_and_jobs(engine):
    with engine.begin() as conn:
        _seed(conn, job=True)
        conn.execute(insert(observations).values(_observation_row()))
    with engine.begin() as conn:
        conn.execute(delete(artifacts).where(artifacts.c.artifact_id == "a1"))
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(observations)).scalar() == 0
        assert conn.execute(select(func.count()).select_from(analysis_jobs)).scalar() == 0
        assert conn.execute(select(func.count()).select_from(sessions)).scalar() == 1


def test_attempt_outcome_is_nullable_and_stored(engine):
    with engine.begin() as conn:
        _seed(conn)
        conn.execute(insert(attempts).values(_attempt_row()))
        conn.execute(
            insert(attempts).values(
                _attempt_row(attempt_id="att-2", outcome="applied_without_item_help")
            )
        )
        rows = conn.execute(select(attempts.c.attempt_id, attempts.c.outcome)).all()
    assert dict(rows) == {"att-1": None, "att-2": "applied_without_item_help"}


def test_artifact_version_is_unique_per_attempt_and_purpose(engine):
    with engine.begin() as conn:
        _seed(conn, artifact=True)
        conn.execute(insert(artifacts).values(_artifact_row("a2", version=2)))
        conn.execute(insert(artifacts).values(_artifact_row("a3", purpose="notebook")))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(artifacts).values(_artifact_row("a4")))


def test_analysis_job_defaults_and_uniqueness(engine):
    with engine.begin() as conn:
        _seed(conn, job=True)
        job = conn.execute(select(analysis_jobs)).mappings().one()
    assert job["executions"] == 0 and job["applied"] is False and job["error_code"] is None
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(analysis_jobs).values(_job_row("j2")))  # mesmo (session_id, request_id)


def test_one_observation_per_job(engine):
    obs = {
        "observation_id": "o1",
        "job_id": "j1",
        "session_id": "s1",
        "attempt_id": "att-1",
        "artifact_id": "a1",
        "document": {"groups": []},
        "created_at": T0,
    }
    with engine.begin() as conn:
        _seed(conn, job=True)
        conn.execute(insert(observations).values(obs))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(observations).values(obs | {"observation_id": "o2"}))


# --- Os dois bancos: tipos -----------------------------------------------------------------


def test_timestamps_round_trip_as_utc(engine):
    local = timezone(timedelta(hours=-3))
    written = datetime(2026, 11, 5, 9, 0, tzinfo=local)  # 12:00 UTC
    with engine.begin() as conn:
        conn.execute(insert(sessions).values(_session_row(created_at=written)))
        got = conn.execute(select(sessions.c.created_at)).scalar_one()
    assert got == T0 and got.utcoffset() == timedelta(0)


def test_naive_timestamps_are_rejected(engine):
    with pytest.raises(StatementError), engine.begin() as conn:
        conn.execute(insert(sessions).values(_session_row(created_at=datetime(2026, 11, 5, 12))))


def test_session_state_survives_the_state_column(engine):
    state = list(_transfer_with_help())[-3]  # com ajuda, papel e explicação registrados
    with engine.begin() as conn:
        conn.execute(insert(sessions).values(_session_row(state=_dump(state))))
        stored = conn.execute(select(sessions.c.state)).scalar_one()
    assert SessionState.model_validate(stored) == state


# --- make_engine ---------------------------------------------------------------------------


def test_sqlite_engine_serializes_writers_with_begin_immediate(tmp_path):
    url = f"sqlite:///{tmp_path / 'lock.db'}"
    first = make_engine(url)
    second = make_engine(f"{url}?timeout=0.2")  # não espera 30 s para provar o bloqueio
    try:
        with first.begin() as conn:
            conn.execute(text("create table t (x int)"))
        with first.begin() as holder:
            holder.execute(text("insert into t values (1)"))
            with pytest.raises(OperationalError, match="locked"), second.begin():
                pass
        with second.begin() as conn:  # liberado após o commit
            assert conn.execute(text("select count(*) from t")).scalar() == 1
    finally:
        first.dispose()
        second.dispose()


def test_sqlite_engine_enables_foreign_keys():
    engine = make_engine("sqlite://")
    try:
        with engine.connect() as conn:
            assert conn.execute(text("pragma foreign_keys")).scalar() == 1
    finally:
        engine.dispose()


def test_in_memory_sqlite_shares_one_connection():
    engine = make_engine("sqlite://")
    try:
        assert isinstance(engine.pool, StaticPool)
        with engine.begin() as conn:
            conn.execute(text("create table t (x int)"))
        with engine.connect() as conn:
            assert conn.execute(text("select count(*) from t")).scalar() == 0
    finally:
        engine.dispose()


def test_migrations_dir_points_to_the_repo_migrations():
    assert MIGRATIONS_DIR == Path(__file__).resolve().parents[2] / "supabase" / "migrations"
