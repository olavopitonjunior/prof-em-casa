"""Contexto de execução da camada `sessions`: relógio, fábrica de ids e o ator autenticado."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.division.commands import Actor

Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]


def utc_now() -> datetime:
    return datetime.now(UTC)


def default_ids(prefix: str) -> str:
    """Id opaco: o prefixo só diz o tipo; o resto é aleatório e não codifica ordem nem conteúdo."""
    return f"{prefix}_{secrets.token_urlsafe(12)}"


@dataclass(frozen=True)
class ActorContext:
    """Quem chama, já autenticado. `actor` nunca vem do corpo do pedido.

    `session_id` é a única sessão que a credencial alcança (`None` nos atores de serviço, que
    alcançam todas). `controller_id` é o cabeçalho `X-Controller-Id` do aluno (decisão P3).
    """

    actor: Actor
    principal_id: str
    session_id: str | None
    controller_id: str | None
