"""Configuração lida do ambiente. Nenhum segredo mora no código: a chave do token de sessão e os
tokens de serviço vêm de variáveis de ambiente (o `.env` é gerado a partir do cofre).

Tokens de serviço só existem aqui como `sha256`: o token em claro nunca é guardado. Um token
ausente desliga o ator correspondente.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.division.commands import Actor
from app.sessions.credentials import hash_token

MIN_SECRET_LENGTH = 32

_SERVICE_TOKEN_VARS: dict[str, Actor] = {
    "SERVICE_TOKEN_TUTOR": "tutor",
    "SERVICE_TOKEN_SYSTEM": "system",
    "SERVICE_TOKEN_VISION_WORKER": "vision_worker",
}


class ConfigError(RuntimeError):
    """Configuração ausente ou insegura. A mensagem cita só o nome da variável, nunca o valor."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_token_secret: bytes
    service_token_hashes: dict[str, Actor]

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        database_url = env.get("DATABASE_URL", "")
        if not database_url:
            raise ConfigError("DATABASE_URL is required")
        secret = env.get("SESSION_TOKEN_SECRET", "")
        if len(secret) < MIN_SECRET_LENGTH:
            raise ConfigError(f"SESSION_TOKEN_SECRET is required ({MIN_SECRET_LENGTH}+ characters)")
        hashes: dict[str, Actor] = {}
        for var, actor in _SERVICE_TOKEN_VARS.items():
            token = env.get(var, "")
            if not token:
                continue  # ausente desliga o ator
            if len(token) < MIN_SECRET_LENGTH:
                raise ConfigError(f"{var} is too short ({MIN_SECRET_LENGTH}+ characters)")
            digest = hash_token(token)
            if digest in hashes:
                raise ConfigError(f"{var} repeats the token of another service actor")
            hashes[digest] = actor
        return cls(
            database_url=database_url,
            session_token_secret=secret.encode("utf-8"),
            service_token_hashes=hashes,
        )
