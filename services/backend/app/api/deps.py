"""Dependências das rotas: o serviço e o ator autenticado."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from app.sessions.context import ActorContext
from app.sessions.service import SessionService


def get_service(request: Request) -> SessionService:
    return request.app.state.service


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def get_ctx(
    request: Request,
    service: Annotated[SessionService, Depends(get_service)],
    authorization: Annotated[str | None, Header()] = None,
    x_controller_id: Annotated[str | None, Header()] = None,
) -> ActorContext:
    """Token -> ator (P3: `X-Controller-Id` identifica a aba). Guarda a plateia em `request.state`
    para que o handler de erro saiba se pode incluir o detalhe (R29)."""
    ctx = service.authenticate(_bearer(authorization), x_controller_id)
    request.state.audience = "learner" if ctx.actor == "learner" else "service"
    return ctx
