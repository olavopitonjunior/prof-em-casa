"""Fábrica da aplicação FastAPI.

`create_app(service)` não lê o ambiente. `get_app()` monta o serviço de produção a partir das
variáveis de ambiente; o módulo expõe `app` por `__getattr__` para que `uvicorn app.api.app:app`
funcione sem ler o ambiente no import (testes e geração do contrato importam o módulo à vontade).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import error_response
from app.api.routes import router
from app.content.loader import load_content
from app.db.engine import create_schema, make_engine
from app.domain.division.errors import DomainError
from app.sessions.errors import SessionError
from app.sessions.evaluator import UnavailableEvaluator
from app.sessions.projection import Audience
from app.sessions.service import SessionService
from app.settings import Settings

API_VERSION = "0.2.0"


def _audience(request: Request) -> Audience:
    return getattr(request.state, "audience", "learner")


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionError)
    async def _session_error(request: Request, exc: SessionError) -> JSONResponse:
        return error_response(exc, _audience(request))

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return error_response(exc, _audience(request))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Nunca o 422 padrão do FastAPI: o corpo do erro de validação ecoaria a entrada.
        return error_response(SessionError("INVALID_PAYLOAD"), _audience(request))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:  # rota inexistente: mesmo envelope do recurso inexistente
            return error_response(SessionError("NOT_FOUND"), _audience(request))
        return await http_exception_handler(request, exc)


def _install_openapi(app: FastAPI) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            from fastapi.openapi.utils import get_openapi

            spec = get_openapi(
                title=app.title,
                version=app.version,
                description=app.description,
                routes=app.routes,
            )
            # O esquema da união de comandos traz seus modelos em `$defs`; as referências apontam
            # para `components.schemas`, então os modelos vão para lá.
            schemas = spec.setdefault("components", {}).setdefault("schemas", {})
            for path in spec["paths"].values():
                for operation in path.values():
                    media = (
                        operation.get("requestBody", {}).get("content", {}).get("application/json")
                    )
                    if media is not None and media["schema"].get("$defs"):
                        schemas.update(media["schema"].pop("$defs"))
            app.openapi_schema = spec
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def create_app(service: SessionService) -> FastAPI:
    app = FastAPI(
        title="Prof em Casa",
        version=API_VERSION,
        description="API de sessão do tutor de divisão (Spec Parte II).",
    )
    app.state.service = service
    _install_error_handlers(app)
    app.include_router(router)
    _install_openapi(app)
    return app


def build_service(settings: Settings) -> SessionService:
    engine = make_engine(settings.database_url)
    if engine.dialect.name == "sqlite":
        create_schema(engine)  # desenvolvimento; no Postgres as migrations vêm do Supabase
    return SessionService(
        engine,
        load_content(),
        UnavailableEvaluator(),  # decisão P9: ainda não há avaliador de explicação
        token_secret=settings.session_token_secret,
        service_token_hashes=settings.service_token_hashes,
    )


@lru_cache(maxsize=1)
def get_app() -> FastAPI:
    return create_app(build_service(Settings.from_env()))


def __getattr__(name: str) -> Any:
    if name == "app":
        return get_app()
    raise AttributeError(name)
