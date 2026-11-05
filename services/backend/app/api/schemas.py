"""Modelos de entrada (estritos) e de saída da API. Só descrevem o contrato; a regra mora no serviço."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class CreateSessionRequest(_Strict):
    request_id: StrictStr
    content_version: StrictStr


class ClaimControlRequest(_Strict):
    request_id: StrictStr
    expected_revision: StrictInt


class CreatedSessionResponse(BaseModel):
    session_id: str
    session_token: str
    controller_id: str
    connection_generation: int
    snapshot: dict[str, Any]


class SceneEffect(BaseModel):
    effect_id: str
    requires_ack: Literal["render_applied"]


class CommandAccepted(BaseModel):
    command_id: str
    status: Literal["accepted"]
    revision: int
    scene_revision: int
    event_seq: int
    scene_effect: SceneEffect | None


class ClaimControlResponse(BaseModel):
    controller_id: str
    connection_generation: int
    revision: int
    turn_epoch: int


class ReceiptResponse(BaseModel):
    receipt_id: str
    outcome: Literal["accepted", "duplicate", "stale"]


class EventsResponse(BaseModel):
    events: list[dict[str, Any]]


class ErrorBody(BaseModel):
    code: str
    retryable: bool
    current_revision: int | None = None
    current_scene_revision: int | None = None
    detail: str | None = None


class ErrorEnvelope(BaseModel):
    command_id: str | None = None
    error: ErrorBody
