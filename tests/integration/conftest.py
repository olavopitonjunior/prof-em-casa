"""Bancos de teste: SQLite em arquivo e um Postgres descartável (cluster próprio por sessão).

O cluster nasce sob `tmp_path_factory` (nunca em /tmp), escuta só em 127.0.0.1 numa porta livre e
é parado no teardown mesmo quando testes falham. Cada teste recebe um banco novo, clonado de
`template_tutor` (já migrado).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import uuid
import warnings
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.content.loader import load_content
from app.db.engine import create_schema, make_engine
from app.db.schema import attempts, command_results, session_events, sessions
from app.domain.division.demonstration import demo_steps
from app.sessions import repository
from app.sessions.context import ActorContext
from app.sessions.service import SessionService
from helpers import T12_4, StubEvaluator, cmd
from helpers import _raw as raw_command
from sqlalchemy import Engine, select, text

TEMPLATE_DB = "template_tutor"
HOMEBREW_BIN = Path("/opt/homebrew/bin")
START_ATTEMPTS = 5


def _find_pg_bin() -> Path | None:
    """`PG_BIN`, depois o PATH, depois o Homebrew. Só vale o diretório que tem os três binários."""
    candidates: list[Path] = []
    if os.environ.get("PG_BIN"):
        candidates.append(Path(os.environ["PG_BIN"]))
    on_path = shutil.which("initdb")
    if on_path:
        candidates.append(Path(on_path).resolve().parent)
    candidates.append(HOMEBREW_BIN)
    for directory in candidates:
        if all((directory / name).is_file() for name in ("initdb", "pg_ctl", "postgres")):
            return directory
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


@dataclass(frozen=True)
class PgCluster:
    port: int

    def url(self, dbname: str) -> str:
        return f"postgresql+psycopg://postgres@127.0.0.1:{self.port}/{dbname}"


def _log_tail(log: Path) -> str:
    return log.read_text(errors="replace")[-2000:] if log.exists() else "(sem log)"


def _start_cluster(pg_bin: Path, data: Path, log: Path) -> int:
    for _ in range(START_ATTEMPTS):  # a porta "livre" pode ser tomada entre achar e subir
        port = _free_port()
        options = f"-c listen_addresses=127.0.0.1 -c port={port} -c unix_socket_directories=''"
        options += " -c fsync=off -c synchronous_commit=off -c full_page_writes=off"
        started = _run(
            [str(pg_bin / "pg_ctl"), "-D", str(data), "-l", str(log), "-w", "-o", options, "start"]
        )
        if started.returncode == 0:
            return port
    raise RuntimeError(f"Postgres de teste não subiu: {started.stderr}\n{_log_tail(log)}")


def _stop_cluster(pg_bin: Path, data: Path, log: Path) -> None:
    """Para o cluster; se `fast` falhar, tenta `immediate`. Só avisa: nunca mascara a falha do teste."""
    if not (data / "postmaster.pid").exists():
        return  # nunca subiu, ou já parou
    for mode in ("fast", "immediate"):
        stopped = _run([str(pg_bin / "pg_ctl"), "-D", str(data), "-m", mode, "-w", "stop"])
        if stopped.returncode == 0:
            return
        warnings.warn(
            f"pg_ctl stop -m {mode} falhou ({stopped.returncode}): {stopped.stderr.strip()}\n"
            f"{_log_tail(log)}",
            RuntimeWarning,
            stacklevel=2,
        )


@pytest.fixture(scope="session")
def pg_cluster(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PgCluster]:
    pg_bin = _find_pg_bin()
    if pg_bin is None:
        message = "binários do Postgres (initdb, pg_ctl, postgres) não encontrados; defina PG_BIN"
        if os.environ.get("TUTOR_REQUIRE_PG") == "1":
            pytest.fail(message)
        pytest.skip(message)

    base = tmp_path_factory.mktemp("pg")
    data, log = base / "data", base / "pg.log"
    init = _run(
        [
            str(pg_bin / "initdb"),
            "-D",
            str(data),
            "-U",
            "postgres",
            "--auth=trust",
            "-E",
            "UTF8",
            "--locale=C",
        ]
    )
    if init.returncode != 0:
        pytest.fail(f"initdb falhou: {init.stderr}")

    try:
        port = _start_cluster(pg_bin, data, log)
        cluster = PgCluster(port)
        admin = make_engine(cluster.url("postgres"))
        try:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(f"create database {TEMPLATE_DB}"))
            template = make_engine(cluster.url(TEMPLATE_DB))
            try:
                create_schema(template)
            finally:
                template.dispose()  # o template não pode ter conexões abertas ao ser clonado
        finally:
            admin.dispose()
        yield cluster
    finally:
        _stop_cluster(pg_bin, data, log)
        shutil.rmtree(data, ignore_errors=True)


@pytest.fixture
def pg_db_url(pg_cluster: PgCluster) -> Iterator[str]:
    """Banco Postgres novo, clonado do template migrado e removido no fim."""
    name = f"t_{uuid.uuid4().hex[:12]}"
    admin = make_engine(pg_cluster.url("postgres"))
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"create database {name} template {TEMPLATE_DB}"))
        yield pg_cluster.url(name)
    finally:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"drop database if exists {name} with (force)"))
        admin.dispose()


@pytest.fixture
def pg_engine(pg_db_url: str) -> Iterator[Engine]:
    """Só Postgres, já migrado."""
    engine = make_engine(pg_db_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(params=["sqlite", "postgres"])
def db_url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'tutor.db'}"
    return request.getfixturevalue("pg_db_url")


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    """Engine nos dois bancos, com o schema criado (SQLite) ou herdado do template (Postgres)."""
    eng = make_engine(db_url)
    try:
        # SQLite cria as tabelas; no Postgres o clone do template já está migrado (sem efeito).
        create_schema(eng)
        yield eng
    finally:
        eng.dispose()


# --- Serviço de sessão (Task 4 em diante) -------------------------------------------------------

T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
TOKEN_SECRET = b"test-token-secret"


class FakeClock:
    """Relógio fixo e mutável: `advance` move o tempo sem dormir."""

    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class SeqIds:
    """Ids sequenciais e determinísticos (`ses_0001`, `evt_0002`...), seguros entre threads."""

    def __init__(self) -> None:
        self._n = 0
        self._lock = threading.Lock()

    def __call__(self, prefix: str) -> str:
        with self._lock:
            self._n += 1
            return f"{prefix}_{self._n:04d}"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_service(clock: FakeClock) -> Callable[..., SessionService]:
    """Fábrica de serviços sobre um engine dado: `make_service(engine, evaluator=...)`."""
    ids = SeqIds()

    def build(engine: Engine, **overrides) -> SessionService:
        options = {
            "token_secret": TOKEN_SECRET,
            "clock": clock,
            "ids": ids,
            **overrides,
        }
        evaluator = options.pop("evaluator", None) or StubEvaluator()
        return SessionService(engine, load_content(), evaluator, **options)

    return build


@pytest.fixture
def svc(engine: Engine, make_service: Callable[..., SessionService]) -> SessionService:
    return make_service(engine)


# --- Apoio compartilhado dos testes de sessão e da API HTTP ------------------------------------

VERSION = "division-sharing-v1"
SYSTEM = ActorContext("system", "system-service", None, None)


def request_id(n: int) -> str:
    return f"request-id-{n:08d}-abcdefgh"


def learner_ctx(created) -> ActorContext:
    return ActorContext("learner", created.session_id, created.session_id, created.controller_id)


def state_of(svc: SessionService, sid: str):
    with svc.engine.connect() as conn:
        row = repository.load_session(conn, sid, for_update=False)
    assert row is not None
    return row.state


def body_of(state, c, **over) -> bytes:
    """Corpo cru de um comando de teste, completado a partir do estado real da sessão."""
    return json.dumps({**raw_command(state, c), **over}).encode()


def send(svc: SessionService, ctx: ActorContext, sid: str, c, **over):
    return svc.execute_command(ctx, sid, body_of(state_of(svc, sid), c, **over))


def start_practice(svc: SessionService, n: int = 1):
    """Sessão criada pelo serviço e levada à prática por comandos reais (aluno e sistema)."""
    created = svc.create_session(request_id(n), VERSION)
    ctx, sid = learner_ctx(created), created.session_id
    send(svc, ctx, sid, cmd("choose_reference_activity"))
    for step in demo_steps(T12_4, 3)[:12]:
        send(svc, SYSTEM, sid, cmd("run_demo_step", actor="system", step_id=step.step_id))
    send(svc, SYSTEM, sid, cmd("finish_demonstration", actor="system", reason="completed"))
    assert state_of(svc, sid).phase == "practice"
    return ctx, sid


def move_body(
    svc, sid, *, rev, scene_rev, cmd_id, piece="piece-01", frm="available", to="group-1", **over
) -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0",
            "command_id": cmd_id,
            "session_id": sid,
            "attempt_id": state_of(svc, sid).active_attempt_id,
            "expected_revision": rev,
            "expected_scene_revision": scene_rev,
            "type": "move_piece",
            "payload": {"piece_id": piece, "from_location": frm, "to_location": to},
            **over,
        }
    ).encode()


def revisions(svc, sid) -> tuple[int, int]:
    state = state_of(svc, sid)
    return state.revision, state.scene_revision


def event_rows(engine, sid, type_: str | None = None, *, after: int = -1) -> list[dict]:
    query = select(session_events).where(
        session_events.c.session_id == sid, session_events.c.revision > after
    )
    if type_ is not None:
        query = query.where(session_events.c.type == type_)
    with engine.connect() as conn:
        return [
            dict(r) for r in conn.execute(query.order_by(session_events.c.event_seq)).mappings()
        ]


def run_parallel(n: int, fn):
    """Roda `fn(i)` em `n` threads largando juntas; devolve resultados ou exceções, em ordem."""
    barrier = threading.Barrier(n)

    def job(i):
        barrier.wait(timeout=30)
        try:
            return fn(i)
        except Exception as exc:  # noqa: BLE001 - o teste inspeciona cada resultado
            return exc

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(job, range(n)))


def dump_tables(engine, sid) -> dict:
    out = {}
    with engine.connect() as conn:
        for table in (sessions, session_events, command_results, attempts):
            query = select(table).where(table.c.session_id == sid)
            query = query.order_by(*table.primary_key.columns)
            out[table.name] = [dict(r) for r in conn.execute(query).mappings()]
    return out
