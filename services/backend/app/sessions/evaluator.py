"""Avaliador de explicação de produção no incremento 2 (decisão P9): ainda não há LLM (G4/G5)."""

from __future__ import annotations

from app.domain.division.classification import ExplanationResult
from app.domain.division.errors import DomainError


class UnavailableEvaluator:
    """Não finge avaliar: a explicação por texto responde 503 até o avaliador real entrar."""

    def evaluate(self, item_id: str, text: str) -> ExplanationResult:
        raise DomainError("PROVIDER_UNAVAILABLE", "explanation evaluator not configured")
