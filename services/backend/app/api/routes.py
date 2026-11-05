"""Rotas `/v1` (Spec Parte II §8). Finas: autenticam, entregam ao serviço e devolvem o resultado."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import TypeAdapter

from app.api.deps import get_ctx, get_service
from app.api.schemas import (
    ClaimControlRequest,
    ClaimControlResponse,
    CommandAccepted,
    CreatedSessionResponse,
    CreateSessionRequest,
    ErrorEnvelope,
    EventsResponse,
    ReceiptResponse,
)
from app.domain.division.commands import Command
from app.sessions.context import ActorContext
from app.sessions.receipts import RenderReceipt
from app.sessions.service import SessionService

REPLAY_HEADER = "Idempotent-Replay"

Service = Annotated[SessionService, Depends(get_service)]
Ctx = Annotated[ActorContext, Depends(get_ctx)]

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorEnvelope, "description": description}
    for status, description in {
        400: "INVALID_PAYLOAD",
        401: "UNAUTHENTICATED",
        403: "ACTION_NOT_ALLOWED, CONTROL_LOST",
        404: "NOT_FOUND (sessão inexistente, expirada ou de outra credencial)",
        409: "STALE_REVISION, STALE_SCENE, STALE_TURN, ATTEMPT_CHANGED, "
        "IDEMPOTENCY_CONFLICT, INVALID_TRANSITION",
        413: "IMAGE_TOO_LARGE",
        415: "UNSUPPORTED_IMAGE",
        422: "INVALID_SCENE, NO_OP, UNSUPPORTED_CONTENT",
        429: "SESSION_LIMIT",
        503: "PROVIDER_UNAVAILABLE",
    }.items()
}

# O corpo do comando chega cru (para rejeitar chave duplicada e NaN no serviço); o contrato
# documenta a união discriminada. `$defs` é movido para `components.schemas` em `app.py`.
COMMAND_SCHEMA = TypeAdapter(Command).json_schema(ref_template="#/components/schemas/{model}")

router = APIRouter(prefix="/v1", responses=_ERROR_RESPONSES)


@router.post(
    "/sessions",
    status_code=201,
    response_model=CreatedSessionResponse,
    summary="Cria a sessão (ou devolve a mesma, no replay do request_id)",
)
def create_session(
    body: CreateSessionRequest, service: Service, response: Response
) -> dict[str, Any]:
    created = service.create_session(body.request_id, body.content_version)
    if created.replay:
        response.headers[REPLAY_HEADER] = "true"
    return {
        "session_id": created.session_id,
        "session_token": created.session_token,
        "controller_id": created.controller_id,
        "connection_generation": created.connection_generation,
        "snapshot": created.snapshot,
    }


@router.get("/sessions/{session_id}", summary="Snapshot público da sessão")
def get_session(session_id: str, service: Service, ctx: Ctx) -> dict[str, Any]:
    return service.get_snapshot(ctx, session_id)


@router.post(
    "/sessions/{session_id}/commands",
    response_model=CommandAccepted,
    summary="Executa um comando (idempotente por command_id)",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": COMMAND_SCHEMA}},
        }
    },
)
async def post_command(
    session_id: str, request: Request, service: Service, ctx: Ctx, response: Response
) -> dict[str, Any]:
    raw = await request.body()
    outcome = await run_in_threadpool(service.execute_command, ctx, session_id, raw)
    response.status_code = outcome.status_code
    if outcome.replay:
        response.headers[REPLAY_HEADER] = "true"
    return outcome.body


@router.post(
    "/sessions/{session_id}/claim-control",
    response_model=ClaimControlResponse,
    summary="Assume o controle da sessão neste dispositivo",
)
def claim_control(
    session_id: str, body: ClaimControlRequest, service: Service, ctx: Ctx
) -> dict[str, Any]:
    return service.claim_control(ctx, session_id, body.request_id, body.expected_revision)


@router.post(
    "/sessions/{session_id}/render-receipts",
    response_model=ReceiptResponse,
    summary="ACK de render (não muda a revisão)",
)
def post_render_receipt(
    session_id: str, body: RenderReceipt, service: Service, ctx: Ctx
) -> dict[str, Any]:
    return service.record_render_receipt(ctx, session_id, body)


@router.get(
    "/sessions/{session_id}/events",
    response_model=EventsResponse,
    summary="Eventos com event_seq > after_seq, na projeção do ator",
)
def list_events(
    session_id: str,
    service: Service,
    ctx: Ctx,
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return {"events": service.list_events(ctx, session_id, after_seq)}
