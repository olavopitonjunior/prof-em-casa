"""Erro da camada `sessions`: um código estável da Spec Parte II §8 e, se couber, as revisões atuais."""

from __future__ import annotations

from app.domain.division.errors import DomainError, ErrorCode


class SessionError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        detail: str | None = None,
        *,
        current_revision: int | None = None,
        current_scene_revision: int | None = None,
        command_id: str | None = None,
    ) -> None:
        super().__init__(code if detail is None else f"{code}: {detail}")
        self.code: ErrorCode = code
        self.detail = detail
        self.current_revision = current_revision
        self.current_scene_revision = current_scene_revision
        self.command_id = command_id

    @classmethod
    def from_domain(
        cls,
        err: DomainError,
        *,
        current_revision: int | None = None,
        current_scene_revision: int | None = None,
        command_id: str | None = None,
    ) -> SessionError:
        return cls(
            err.code,
            err.detail,
            current_revision=current_revision,
            current_scene_revision=current_scene_revision,
            command_id=command_id,
        )
