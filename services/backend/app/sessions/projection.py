"""Projeção pública de eventos e da sessão (P8): o que a tela da criança vê e o que só o serviço vê.

A projeção da criança é uma lista de permitidos por tipo de evento: só as chaves listadas em
`LEARNER_EVENT_FIELDS` passam. Um tipo ausente da lista ou uma chave nova num handler fica de fora
por omissão. `LEARNER_EXCLUDED_FIELDS` registra as chaves que os handlers emitem e que ficam de fora
de propósito; o teste de deriva exige que toda chave emitida esteja numa das duas listas.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.content.loader import ContentPackage
from app.domain.division.session import public_snapshot
from app.domain.division.state import SessionState

Audience = Literal["learner", "service"]

# Chaves que nunca saem para a criança, em nenhum nível de aninhamento.
FORBIDDEN_LEARNER_KEYS = frozenset(
    {
        "answer",
        "correct",
        "outcome",
        "rating",
        "evidence",
        "issues",
        "quotient",
        "private",
        "reason_text",
    }
)


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    session_id: str
    event_seq: int
    revision: int
    type: str
    actor: str
    command_id: str | None
    attempt_id: str | None
    occurred_at: datetime
    data: dict[str, Any]


def _f(*keys: str) -> frozenset[str]:
    return frozenset(keys)


# Tipos do domínio (`EventType`) mais `control_claimed` (Task 5). Fatos da cena e do fluxo que a
# criança já vê passam; correção, nota, resposta e texto livre não. `analysis_superseded.reason` é
# um código de fluxo (retake, recapture, attempt_changed, attempt_closed, replaced, revise_record,
# left_notebook, left_capture, left_flow, session_closed): depende de por onde a criança saiu, não
# de a resposta estar certa, então passa.
LEARNER_EVENT_FIELDS: dict[str, frozenset[str]] = {
    "source_confirmed": _f("origin", "content_version"),
    "attempt_started": _f(
        "kind",
        "item_id",
        "after_partial_demonstration",
        "completed_rounds",
        "demo_finish_reason",
        "requested_by",
    ),
    "demo_step_completed": _f("step_id", "round", "piece_id", "to_group", "round_completed"),
    "scene_changed": _f("reason", "step_id", "piece_id", "from_location", "to_location"),
    "distribution_checked": _f(
        "group_counts",
        "assigned_total",
        "available_total",
        "groups_equal",
        "all_assigned",
        "valid_partition",
        "intervention",
        "intervention_targets",
    ),
    "help_granted": _f("kind", "assistance_level", "support_resources", "has_reason"),
    "notebook_entered": _f("intent", "return_phase"),
    "returned_to_activity": _f("from_phase", "to_phase"),
    "artifact_submitted": _f("artifact_id", "artifact_version"),
    "analysis_completed": _f("artifact_id", "artifact_version", "observation_id"),
    "analysis_superseded": _f("artifact_id", "reason"),
    "observation_disputed": _f(),  # nenhum handler o emite ainda
    "observation_clarified": _f(),  # nenhum handler o emite ainda
    "answer_submitted": _f(),
    "explanation_evaluated": _f("modality"),
    "attempt_evaluated": _f(),
    "session_paused": _f("turn_epoch"),
    "session_resumed": _f("turn_epoch"),
    "session_closed": _f("reason", "completion"),
    "control_claimed": _f("connection_generation", "turn_epoch"),
}

# Chaves emitidas pelos handlers e deixadas de fora de propósito:
# - answer/correct: a resposta e a correção;
# - rating/evidence: a nota da explicação e o que o avaliador viu;
# - outcome/final: o resultado classificado da tentativa;
# - verification_status/issues/reconstruction_allowed: dizem se o caderno está certo;
# - reason (texto livre da criança) nunca é emitido: help_granted leva só has_reason (R28);
# - job_id: identificador interno do trabalho de análise.
LEARNER_EXCLUDED_FIELDS: dict[str, frozenset[str]] = {
    "artifact_submitted": _f("job_id"),
    "analysis_completed": _f("job_id", "verification_status", "issues", "reconstruction_allowed"),
    "analysis_superseded": _f("job_id"),
    "answer_submitted": _f("answer", "correct"),
    "explanation_evaluated": _f("rating", "evidence"),
    "attempt_evaluated": _f("outcome", "final"),
}


def project_event(event: EventRecord, audience: Audience) -> dict[str, Any]:
    if audience == "service":
        return {
            "event_id": event.event_id,
            "event_seq": event.event_seq,
            "revision": event.revision,
            "type": event.type,
            "actor": event.actor,
            "command_id": event.command_id,
            "attempt_id": event.attempt_id,
            "occurred_at": event.occurred_at.isoformat(),
            "data": dict(event.data),
        }
    allowed = LEARNER_EVENT_FIELDS.get(event.type, frozenset())
    return {
        "event_id": event.event_id,
        "event_seq": event.event_seq,
        "revision": event.revision,
        "type": event.type,
        "attempt_id": event.attempt_id,
        "occurred_at": event.occurred_at.isoformat(),
        "data": {k: v for k, v in event.data.items() if k in allowed},
    }


def session_view(
    state: SessionState, content: ContentPackage, *, connection_generation: int
) -> dict[str, Any]:
    return public_snapshot(state, content) | {"connection_generation": connection_generation}
