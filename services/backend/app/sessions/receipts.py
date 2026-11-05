"""ACK de render (Spec Parte II §5): o modelo estrito que o controlador envia."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
)

from app.sessions.errors import SessionError

_Id = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
_Counter = Annotated[StrictInt, Field(ge=0, le=2_147_483_647)]  # INTEGER do Postgres

ReceiptStatus = Literal[
    "render_applied", "animation_completed", "settled_by_interruption", "render_failed"
]


class RenderReceipt(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    receipt_id: _Id
    effect_id: _Id
    command_id: _Id
    session_id: _Id
    attempt_id: _Id | None
    scene_revision: _Counter
    connection_generation: Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]
    status: ReceiptStatus


def parse_render_receipt(raw: dict[str, Any]) -> RenderReceipt:
    """Valida o corpo do ACK; qualquer falha vira `INVALID_PAYLOAD` com o caminho do campo."""
    try:
        return RenderReceipt.model_validate(raw)
    except ValidationError as exc:
        where = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors()[:5]
        )
        raise SessionError("INVALID_PAYLOAD", where) from None
