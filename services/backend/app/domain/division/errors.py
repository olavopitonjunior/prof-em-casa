from typing import Literal

# Códigos de erro da Spec, Parte II §8 "Erros", mais `STALE_TURN` (extensão R30: a Spec exige
# recusar turno antigo do tutor, mas não nomeia o código).
ErrorCode = Literal[
    "INVALID_PAYLOAD",
    "UNAUTHENTICATED",
    "ACTION_NOT_ALLOWED",
    "CONTROL_LOST",
    "NOT_FOUND",
    "STALE_REVISION",
    "STALE_SCENE",
    "STALE_TURN",
    "ATTEMPT_CHANGED",
    "IDEMPOTENCY_CONFLICT",
    "INVALID_TRANSITION",
    "IMAGE_TOO_LARGE",
    "UNSUPPORTED_IMAGE",
    "INVALID_SCENE",
    "NO_OP",
    "UNSUPPORTED_CONTENT",
    "SESSION_LIMIT",
    "PROVIDER_UNAVAILABLE",
]


class DomainError(Exception):
    """Erro de domínio com código estável. Herda de Exception (não ValueError) para
    atravessar validadores Pydantic sem ser embrulhado em ValidationError."""

    def __init__(self, code: ErrorCode, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}: {detail}")
        self.code: ErrorCode = code
        self.detail = detail
