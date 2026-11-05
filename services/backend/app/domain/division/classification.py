"""Avaliação de explicação por artefato e classificação final da tentativa (Spec Parte I §7).

A nota da explicação chega pré-avaliada (D2): o domínio avalia só a modalidade `artifact`.
O avaliador por LLM fica adiado; `ExplanationEvaluator` é apenas um Protocol.
Os rótulos são por tentativa e nunca significam "dominou divisão".
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from app.domain.division.assistance import AssistanceLedger
from app.domain.division.observation import Verification
from app.domain.division.task import TaskSpec

AttemptOutcome = Literal[
    "applied_without_item_help",
    "applied_with_support",
    "answer_correct_evidence_partial",
    "needs_review",
    "inconclusive",
    "not_attempted",
]

# Papel e reformulação de texto não são recurso conceitual.
_NON_CONCEPTUAL = frozenset({"paper", "text_rephrase"})


class ExplanationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rating: Literal["sufficient", "partial", "unclear"]
    modality: Literal["text", "voice_transcript", "artifact"]
    evidence: str


class ExplanationEvaluator(Protocol):
    """Contrato do avaliador de explicação livre. Sem implementação neste incremento (D2)."""

    def evaluate(self, item_id: str, text: str) -> ExplanationResult: ...


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def evaluate_artifact_explanation(task: TaskSpec, verification: Verification) -> ExplanationResult:
    """Avalia o desenho/caderno. A evidência é montada só com `facts`, nunca com o quociente privado."""
    facts = verification.facts
    counts = facts.get("observed_group_counts")

    def result(rating: Literal["sufficient", "partial", "unclear"], evidence: str):
        return ExplanationResult(rating=rating, modality="artifact", evidence=evidence)

    if counts:  # há grupos observados
        if (
            verification.status == "consistent"
            and facts.get("task_groups") == len(counts)
            and facts.get("groups_equal") is True
            and _is_int(facts.get("represented_total"))
        ):
            return result(
                "sufficient",
                f"{len(counts)} grupos de {counts[0]} = {facts['represented_total']}",
            )
        if verification.status == "inconclusive":
            return result("unclear", "desenho ainda não pôde ser lido com segurança")
        total = facts.get("represented_total")
        if (
            facts.get("task_groups") == len(counts)
            and facts.get("groups_equal") is True
            and _is_int(total)
            and total == facts.get("task_total")
        ):  # desenho correto; só a expressão/resposta escrita diverge
            return result(
                "unclear",
                f"desenho mostra {len(counts)} grupos de {counts[0]} = {total}, "
                "mas a resposta ou expressão escrita não confere",
            )
        return result("unclear", "desenho não mostra grupos iguais que somem o total")

    # Sem grupos: só a expressão. Parcial se ela é consistente com a tarefa.
    expression_ok = verification.status != "inconclusive" and not (
        {"EXPRESSION_MISMATCH", "WRITTEN_ANSWER_MISMATCH"} & set(verification.issues)
    )
    if expression_ok:
        groups, total = facts.get("task_groups"), facts.get("task_total")
        answer = facts.get("written_answer")
        if _is_int(groups) and _is_int(total) and _is_int(answer):
            return result("partial", f"{groups} grupos de {answer} = {total}")
        return result("partial", "expressão escrita confere com a tarefa")
    return result("unclear", "expressão escrita não confere com a tarefa")


def classify_attempt(
    answer_correct: bool | None,
    explanation: ExplanationResult | None,
    ledger: AssistanceLedger,
    *,
    evidence_disputed: bool = False,
) -> AttemptOutcome:
    """`answer_correct=None` significa que a criança não respondeu."""
    if evidence_disputed:
        return "inconclusive"
    if answer_correct is None:
        return "not_attempted"
    if answer_correct is False:
        return "needs_review"
    # Spec: with_support exige explicação suficiente; parcial/ausente é sempre evidência parcial.
    if explanation is None or explanation.rating != "sufficient":
        return "answer_correct_evidence_partial"
    if ledger.level != "none" or (ledger.resources - _NON_CONCEPTUAL):
        return "applied_with_support"
    return "applied_without_item_help"
