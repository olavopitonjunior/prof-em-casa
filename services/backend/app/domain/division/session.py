"""`apply_command`: guardas, handlers e projeção pública (Spec Parte I §4; Parte II §2, §4).

API pública deste módulo: `new_session`, `SessionState`, `Attempt`, `DomainEvent`,
`CommandResult`, `apply_command`, `public_snapshot`. Funções puras: o estado de entrada nunca é
alterado, e um `DomainError` deixa a sessão exatamente como estava.
"""

from typing import Any

from app.content.loader import ContentPackage, public_item
from app.domain.division.classification import ExplanationEvaluator
from app.domain.division.commands import ALLOWED_ACTORS, SCENE_COMMANDS, Actor, Command
from app.domain.division.errors import DomainError
from app.domain.division.handlers import HANDLERS, Ctx, facts_of
from app.domain.division.scene import SceneState
from app.domain.division.state import (
    Attempt,
    CommandResult,
    DomainEvent,
    SessionState,
    new_session,
)
from app.domain.division.transitions import is_allowed_in, next_phase

__all__ = [
    "Attempt",
    "CommandResult",
    "DomainEvent",
    "SessionState",
    "apply_command",
    "new_session",
    "public_snapshot",
]

# Parte II §2: continuam autorizados com revisão antiga (o campo esperado é informativo).
_IMMEDIATE_CONTROL = frozenset({"pause_session", "interrupt_turn"})
# Com a sessão em pausa, tutor e sistema não agem (Parte I §4), salvo controle de sessão.
_ALLOWED_WHILE_PAUSED = frozenset({"pause_session", "interrupt_turn", "close_session"})


def _is_immediate_control(command: Command) -> bool:
    if command.type in _IMMEDIATE_CONTROL:
        return True
    return command.type == "close_session" and command.payload.reason == "learner_stopped"


def apply_command(
    session: SessionState,
    command: Command,
    actor: Actor,
    *,
    content: ContentPackage,
    explanation_evaluator: ExplanationEvaluator,
) -> CommandResult:
    ctype = command.type
    # Autorização: um comando validado para um ator não vale como outro.
    if actor not in ALLOWED_ACTORS[ctype]:
        raise DomainError("ACTION_NOT_ALLOWED", f"{actor} cannot run {ctype}")
    # (1) sessão fechada
    if session.session_status == "closed":
        raise DomainError("ACTION_NOT_ALLOWED", "session_closed")
    # (2) tentativa
    if command.attempt_id != session.active_attempt_id:
        raise DomainError("ATTEMPT_CHANGED", "attempt_id is not the active attempt")
    # (3) e (4): revisões, salvo controle imediato
    if not _is_immediate_control(command):
        if command.expected_revision != session.revision:
            raise DomainError("STALE_REVISION", f"current revision is {session.revision}")
        if ctype in SCENE_COMMANDS and command.expected_scene_revision != session.scene_revision:
            raise DomainError("STALE_SCENE", f"current scene_revision is {session.scene_revision}")
    # (5) tabela de transições
    if not is_allowed_in(ctype, session.phase):
        raise DomainError("INVALID_TRANSITION", f"{ctype} is not allowed in {session.phase}")
    # (6) regra do handler
    if (
        session.session_status == "paused"
        and actor in ("tutor", "system")
        and ctype not in _ALLOWED_WHILE_PAUSED
    ):
        raise DomainError("ACTION_NOT_ALLOWED", "session_paused")
    handler = HANDLERS.get(ctype)
    if handler is None:
        raise DomainError("ACTION_NOT_ALLOWED", "not_in_increment_1")  # D7
    outcome = handler(Ctx(session, command, actor, content, explanation_evaluator))

    phase = next_phase(ctype, facts_of(session, answer_correct=outcome.answer_correct))
    scene_revision = session.scene_revision + (1 if outcome.scene_changed else 0)
    scene = outcome.session.scene
    if outcome.scene_changed and scene is not None:
        scene = SceneState.model_validate({**dict(scene), "scene_revision": scene_revision})
    final = outcome.session.with_changes(
        phase=phase,
        scene=scene,
        revision=session.revision + 1,
        scene_revision=scene_revision,
        last_event_seq=session.last_event_seq + len(outcome.events),
    )
    return CommandResult(
        session=final, events=tuple(outcome.events), scene_changed=outcome.scene_changed
    )


_SCENE_RESOURCES = frozenset({"virtual_objects", "reference_model"})


def _public_scene(session: SessionState, attempt: Attempt | None) -> dict[str, Any] | None:
    scene = session.scene
    if scene is None or attempt is None:
        return None
    # Parte II §4, regra 5: na questão nova sem recurso liberado, a cena não existe publicamente.
    if attempt.kind == "transfer" and not (attempt.ledger.resources & _SCENE_RESOURCES):
        return None
    data = scene.model_dump(mode="json")
    # Regra 4: só o exemplo demonstrado mostra resposta; o resto é sempre null.
    if attempt.kind != "demonstration":
        data["answer_display"] = None
    return data


def public_snapshot(session: SessionState, content: ContentPackage) -> dict[str, Any]:
    """Projeção pública: nunca inclui `private`, quociente, correção nem texto livre da criança."""
    attempt = session.active_attempt
    return {
        "session_id": session.session_id,
        "content_version": session.content_version,
        "phase": session.phase,
        "session_status": session.session_status,
        "interaction_mode": session.interaction_mode,
        "revision": session.revision,
        "scene_revision": session.scene_revision,
        "turn_epoch": session.turn_epoch,
        "last_event_seq": session.last_event_seq,
        "active_attempt_id": session.active_attempt_id,
        "return_phase": session.return_phase,
        "notebook_intent": session.notebook_intent,
        "completion": session.completion,
        "attempt": None
        if attempt is None
        else {
            "attempt_id": attempt.attempt_id,
            "kind": attempt.kind,
            "status": attempt.status,
            "assistance_level": attempt.ledger.level,
            "support_resources": sorted(attempt.ledger.resources),
            "answered": attempt.answer is not None,
            "demo_partial": attempt.demo_partial,
        },
        "item": None if attempt is None else public_item(content.items[attempt.item_id]),
        "scene": _public_scene(session, attempt),
    }
