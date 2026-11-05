"""Envelope de erro HTTP (Spec Parte II §2 e §8) e o mapeamento código -> status.

Decisão R29: para o aluno, o corpo de erro leva só o `code` e campos estruturais (`retryable`,
revisões atuais, `command_id`). O texto de detalhe do domínio nunca sai para ele: uma frase como
"explanation is not sufficient" revelaria uma nota. Tutor e serviços recebem `detail`.
"""

from __future__ import annotations

from typing import get_args

from fastapi.responses import JSONResponse

from app.domain.division.errors import DomainError, ErrorCode
from app.sessions.errors import SessionError
from app.sessions.projection import Audience

HTTP_STATUS: dict[ErrorCode, int] = {
    "INVALID_PAYLOAD": 400,
    "UNAUTHENTICATED": 401,
    "ACTION_NOT_ALLOWED": 403,
    "CONTROL_LOST": 403,
    "NOT_FOUND": 404,
    "STALE_REVISION": 409,
    "STALE_SCENE": 409,
    "STALE_TURN": 409,  # extensão R30: a Spec não nomeia o turno antigo do tutor; não repetível
    "ATTEMPT_CHANGED": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "INVALID_TRANSITION": 409,
    "IMAGE_TOO_LARGE": 413,
    "UNSUPPORTED_IMAGE": 415,
    "INVALID_SCENE": 422,
    "NO_OP": 422,
    "UNSUPPORTED_CONTENT": 422,
    "SESSION_LIMIT": 429,
    "PROVIDER_UNAVAILABLE": 503,
}
assert set(HTTP_STATUS) == set(get_args(ErrorCode))  # código novo sem status é erro de import

RETRYABLE: frozenset[ErrorCode] = frozenset(
    {
        "STALE_REVISION",
        "STALE_SCENE",
        "ATTEMPT_CHANGED",
        "INVALID_TRANSITION",
        "PROVIDER_UNAVAILABLE",
    }
)


def error_body(err: SessionError | DomainError, audience: Audience = "learner") -> dict:
    fields: dict = {"code": err.code, "retryable": err.code in RETRYABLE}
    body: dict = {"error": fields}
    if isinstance(err, SessionError):
        if err.current_revision is not None:
            fields["current_revision"] = err.current_revision
        if err.current_scene_revision is not None:
            fields["current_scene_revision"] = err.current_scene_revision
        if err.command_id is not None:
            body = {"command_id": err.command_id, "error": fields}
    if audience == "service" and err.detail:
        fields["detail"] = err.detail
    return body


def error_response(err: SessionError | DomainError, audience: Audience = "learner") -> JSONResponse:
    return JSONResponse(error_body(err, audience), status_code=HTTP_STATUS[err.code])
