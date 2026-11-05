"""Token opaco da sessão (decisão P2): derivado do `request_id`, guardado só como hash."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping

from app.domain.division.commands import Actor


def derive_session_token(secret: bytes, request_id: str) -> str:
    """`base64url(HMAC-SHA256(secret, "session-token:" + request_id))`, sem preenchimento."""
    mac = hmac.new(secret, f"session-token:{request_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")


def hash_token(token: str) -> str:
    """Só o sha256 do token vai para o banco."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def match_service_token(token: str, hashes: Mapping[str, Actor]) -> Actor | None:
    """Ator dono do token de serviço, ou `None`. Compara em tempo constante contra todos os
    hashes, sem sair no primeiro acerto."""
    digest = hash_token(token)
    found: Actor | None = None
    for known, actor in hashes.items():
        if hmac.compare_digest(known, digest):
            found = actor
    return found
