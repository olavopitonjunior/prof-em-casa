"""Reaproveita os bancos de teste de `tests/integration/conftest.py` (SQLite e Postgres descartável).

Os fixtures são reexportados, não copiados. Se a suíte inteira roda, o cluster Postgres sobe uma
vez para a integração e outra para o aceite; cada um é parado no teardown.
"""

from integration.conftest import (  # noqa: F401
    clock,
    db_url,
    engine,
    make_service,
    pg_cluster,
    pg_db_url,
    pg_engine,
)
