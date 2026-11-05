"""Bancos de teste: SQLite em arquivo e um Postgres descartável (cluster próprio por sessão).

O cluster nasce sob `tmp_path_factory` (nunca em /tmp), escuta só em 127.0.0.1 numa porta livre e
é parado no teardown mesmo quando testes falham. Cada teste recebe um banco novo, clonado de
`template_tutor` (já migrado).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from app.db.engine import create_schema, make_engine
from sqlalchemy import Engine, text

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
        _run([str(pg_bin / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"])
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
        create_schema(
            eng
        )  # SQLite cria as tabelas; no Postgres o clone do template já está migrado
        yield eng
    finally:
        eng.dispose()
