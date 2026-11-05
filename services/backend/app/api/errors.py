"""Envelope de erro HTTP (Spec Parte II §2 e §8) e o mapeamento código -> status.

Decisão R29: para o aluno, o corpo de erro leva só o `code` e campos estruturais (`retryable`,
revisões atuais, `command_id`). O texto de detalhe do domínio nunca sai para ele: uma frase como
"explanation is not sufficient" revelaria uma nota. Tutor e serviços recebem `detail`.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

from fastapi.responses import JSONResponse

from app.domain.division.errors import DomainError, ErrorCode
from app.sessions.errors import SessionError
from app.sessions.projection import Audience

# Códigos que só existem na borda HTTP (não nascem no domínio nem no serviço).
#  - PAYLOAD_TOO_LARGE: decisão R31, corpo acima de MAX_BODY_BYTES (a Spec só tem 413 para imagem).
#  - INTERNAL_ERROR: exceção não prevista; o corpo nunca leva a causa.
ApiErrorCode = Literal[*get_args(ErrorCode), "PAYLOAD_TOO_LARGE", "INTERNAL_ERROR"]

MAX_BODY_BYTES = 64 * 1024  # R31: nenhum comando, ACK ou criação chega perto disso

HTTP_STATUS: dict[ApiErrorCode, int] = {
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
    "PAYLOAD_TOO_LARGE": 413,
    "INTERNAL_ERROR": 500,
}
if not set(get_args(ErrorCode)) <= set(HTTP_STATUS):  # código novo sem status é erro de import
    raise RuntimeError("HTTP_STATUS does not cover every ErrorCode")

RETRYABLE: frozenset[ApiErrorCode] = frozenset(
    {
        "STALE_REVISION",
        "STALE_SCENE",
        "ATTEMPT_CHANGED",
        "INVALID_TRANSITION",
        "PROVIDER_UNAVAILABLE",
    }
)


# Só o que parece um id volta ao cliente: alfabeto curto e tamanho limitado. Texto livre, espaço,
# acento ou um valor de 1 MB nunca é refletido (nem amplifica a resposta).
_ECHOABLE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


def code_response(code: ApiErrorCode) -> JSONResponse:
    """Envelope sem nada do pedido: para erros da borda (corpo grande, falha interna)."""
    body = {"error": {"code": code, "retryable": code in RETRYABLE}}
    return JSONResponse(body, status_code=HTTP_STATUS[code])


def error_body(err: SessionError | DomainError, audience: Audience = "learner") -> dict:
    fields: dict = {"code": err.code, "retryable": err.code in RETRYABLE}
    body: dict = {"error": fields}
    if isinstance(err, SessionError):
        if err.current_revision is not None:
            fields["current_revision"] = err.current_revision
        if err.current_scene_revision is not None:
            fields["current_scene_revision"] = err.current_scene_revision
        if err.command_id is not None and _ECHOABLE_ID.fullmatch(err.command_id):
            body = {"command_id": err.command_id, "error": fields}
    if audience == "service" and err.detail:
        fields["detail"] = err.detail
    return body


def error_response(err: SessionError | DomainError, audience: Audience = "learner") -> JSONResponse:
    return JSONResponse(error_body(err, audience), status_code=HTTP_STATUS[err.code])
