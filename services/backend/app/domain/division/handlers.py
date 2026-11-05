"""Handlers dos comandos executáveis (regra (6) da ordem de guardas): incremento 1 mais o fluxo
de captura do caderno.

Cada handler recebe um `Ctx` e devolve um `Outcome`: o novo estado SEM fase, revisões nem
`last_event_seq` (o `apply_command` completa isso), os eventos e se a cena mudou. Handlers nunca
alteram o estado de entrada. Os demais comandos do catálogo não têm handler (D7).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.content.loader import ContentItem, ContentPackage
from app.domain.division.assistance import AssistanceLedger, apply_help_effect
from app.domain.division.classification import (
    ExplanationEvaluator,
    ExplanationResult,
    classify_attempt,
)
from app.domain.division.commands import Actor
from app.domain.division.demonstration import apply_demo_step, completed_rounds, demo_steps
from app.domain.division.distribution import select_initial_intervention, verify_distribution
from app.domain.division.errors import DomainError
from app.domain.division.scene import SceneState, initial_scene, move_piece
from app.domain.division.state import Attempt, DomainEvent, SessionState, drop_artifact
from app.domain.division.transitions import AttemptKind, NextPhaseFacts, next_phase


@dataclass(frozen=True)
class Ctx:
    session: SessionState
    command: Any  # Command já validado por parse_command; o handler lê `.payload`
    actor: Actor
    content: ContentPackage
    evaluator: ExplanationEvaluator


@dataclass
class Outcome:
    session: SessionState
    events: list[DomainEvent] = field(default_factory=list)
    scene_changed: bool = False
    answer_correct: bool | None = None  # alimenta a regra de fase de submit_answer


# --- utilidades -------------------------------------------------------------------------------


def _event(type_: str, attempt_id: str | None, **data: Any) -> DomainEvent:
    return DomainEvent(type=type_, attempt_id=attempt_id, data=data)  # type: ignore[arg-type]


def _active(s: SessionState) -> Attempt:
    attempt = s.active_attempt
    if attempt is None or attempt.status != "active":
        raise DomainError("INVALID_TRANSITION", "no active attempt")
    return attempt


def _item_of(content: ContentPackage, attempt: Attempt) -> ContentItem:
    return content.items[attempt.item_id]


def _item_by_role(content: ContentPackage, role: str) -> ContentItem:
    for item in content.items.values():
        if item.role == role:
            return item
    raise DomainError("UNSUPPORTED_CONTENT", f"content package has no {role} item")


def _with_attempt(s: SessionState, attempt: Attempt, **changes: Any) -> SessionState:
    attempts = tuple(attempt if a.attempt_id == attempt.attempt_id else a for a in s.attempts)
    return s.with_changes(attempts=attempts, **changes)


def _start_attempt(
    s: SessionState, kind: AttemptKind, item: ContentItem
) -> tuple[Attempt, SceneState]:
    attempt_id = f"attempt-{len(s.attempts) + 1}-{kind}"
    attempt = Attempt(attempt_id=attempt_id, kind=kind, item_id=item.item_id, status="active")
    scene = initial_scene(item.task, scene_id=f"scene-{attempt_id}", attempt_id=attempt_id)
    return attempt, scene


def _answer_correct(content: ContentPackage, attempt: Attempt, answer: int | None) -> bool | None:
    if answer is None:
        return None
    return answer == _item_of(content, attempt).private.quotient


def _outcome_event(content: ContentPackage, attempt: Attempt, *, final: bool) -> DomainEvent:
    outcome = classify_attempt(
        _answer_correct(content, attempt, attempt.answer), attempt.explanation, attempt.ledger
    )
    return _event("attempt_evaluated", attempt.attempt_id, outcome=outcome, final=final)


def _evaluate(ctx: Ctx, attempt: Attempt, modality: str, text: str) -> ExplanationResult:
    raw = ctx.evaluator.evaluate(attempt.item_id, text)
    # A modalidade é a do comando (a nota vem do avaliador).
    return ExplanationResult(rating=raw.rating, modality=modality, evidence=raw.evidence)  # type: ignore[arg-type]


def _explanation_event(attempt: Attempt, result: ExplanationResult) -> DomainEvent:
    return _event(
        "explanation_evaluated",
        attempt.attempt_id,
        rating=result.rating,
        modality=result.modality,
        evidence=result.evidence,
    )


def _help_snapshot(attempt: Attempt) -> dict[str, Any]:
    return {
        "assistance_level": attempt.ledger.level,
        "support_resources": sorted(attempt.ledger.resources),
    }


def facts_of(s: SessionState, *, answer_correct: bool | None = None) -> NextPhaseFacts:
    """Fatos de pré-estado para as regras de próxima fase."""
    attempt = s.active_attempt
    return NextPhaseFacts(
        phase=s.phase,
        attempt_kind=None if attempt is None else attempt.kind,
        return_phase=s.return_phase,
        answer_correct=answer_correct,
    )


def _scene(s: SessionState) -> SceneState:
    if s.scene is None:
        raise DomainError("ACTION_NOT_ALLOWED", "scene_not_available")
    return s.scene


# --- handlers ---------------------------------------------------------------------------------


def choose_reference_activity(ctx: Ctx) -> Outcome:
    s = ctx.session
    if ctx.command.payload.content_version != ctx.content.version:
        raise DomainError("UNSUPPORTED_CONTENT", "content version is not the loaded package")
    item = ctx.content.items[ctx.content.demonstration.item_id]
    attempt, scene = _start_attempt(s, "demonstration", item)
    events = [
        _event(
            "source_confirmed", None, origin="reference_activity", content_version=s.content_version
        ),
        _event("attempt_started", attempt.attempt_id, kind="demonstration", item_id=item.item_id),
        _event("scene_changed", attempt.attempt_id, reason="scene_created"),
    ]
    updated = s.with_changes(
        attempts=(*s.attempts, attempt), active_attempt_id=attempt.attempt_id, scene=scene
    )
    return Outcome(updated, events, scene_changed=True)


def run_demo_step(ctx: Ctx) -> Outcome:
    s, step_id = ctx.session, ctx.command.payload.step_id
    attempt, scene = _active(s), _scene(s)
    task = scene.task
    steps = demo_steps(task, ctx.content.demonstration.rounds)
    if step_id not in {st.step_id for st in steps}:
        raise DomainError("INVALID_PAYLOAD", "step is not part of the demonstration script")
    done = task.dividend - len(scene.available_piece_ids)
    if done >= len(steps):
        raise DomainError("INVALID_TRANSITION", "demonstration script already complete")
    step = steps[done]
    if step.step_id != step_id:
        raise DomainError("INVALID_TRANSITION", "step out of order")
    new_scene = apply_demo_step(scene, step)
    rounds = completed_rounds(new_scene, task)
    if done + 1 == len(steps):  # Parte II §4, regra 4: resposta demonstrada no exemplo
        new_scene = SceneState.model_validate(
            {**dict(new_scene), "answer_display": _item_of(ctx.content, attempt).private.quotient}
        )
    events = [
        _event(
            "demo_step_completed",
            attempt.attempt_id,
            step_id=step.step_id,
            round=step.round,
            piece_id=step.piece_id,
            to_group=step.to_group,
            round_completed=rounds >= step.round,
        ),
        _event("scene_changed", attempt.attempt_id, reason="demo_step", step_id=step.step_id),
    ]
    return Outcome(s.with_changes(scene=new_scene), events, scene_changed=True)


def finish_demonstration(ctx: Ctx) -> Outcome:
    s, reason = ctx.session, ctx.command.payload.reason
    demo, scene = _active(s), _scene(s)
    total = ctx.content.demonstration.rounds
    done = completed_rounds(scene, scene.task)
    if reason == "completed":
        if done < total:
            raise DomainError("INVALID_TRANSITION", "demonstration script is not complete")
    else:  # learner_requested: o tutor/sistema não pula a demonstração (Parte I §5)
        if ctx.actor != "learner":
            raise DomainError("ACTION_NOT_ALLOWED", "only the learner can end the demo early")
        if done < 1:
            raise DomainError("INVALID_TRANSITION", "no completed round yet")
    partial = done < total
    guided, guided_scene = _start_attempt(s, "guided", _item_by_role(ctx.content, "guided"))
    closed_demo = demo.with_changes(status="closed", demo_partial=partial)
    attempts = tuple(closed_demo if a.attempt_id == demo.attempt_id else a for a in s.attempts)
    updated = s.with_changes(
        attempts=(*attempts, guided), active_attempt_id=guided.attempt_id, scene=guided_scene
    )
    events = [
        _event(
            "attempt_started",
            guided.attempt_id,
            kind="guided",
            item_id=guided.item_id,
            after_partial_demonstration=partial,
            completed_rounds=done,
            demo_finish_reason=reason,  # o pedido explícito da criança fica registrado
            requested_by=ctx.actor,
        ),
        _event("scene_changed", guided.attempt_id, reason="scene_created"),
    ]
    return Outcome(updated, events, scene_changed=True)


def do_move_piece(ctx: Ctx) -> Outcome:
    s, p = ctx.session, ctx.command.payload
    scene = _scene(s)
    new_scene = move_piece(scene, p.piece_id, p.from_location, p.to_location)
    event = _event(
        "scene_changed",
        s.active_attempt_id,
        reason="piece_moved",
        piece_id=p.piece_id,
        from_location=p.from_location,
        to_location=p.to_location,
    )
    return Outcome(s.with_changes(scene=new_scene), [event], scene_changed=True)


def check_distribution(ctx: Ctx) -> Outcome:
    s = ctx.session
    scene = _scene(s)
    facts = verify_distribution(scene.task, scene)
    intervention = select_initial_intervention(scene, facts)
    event = _event(
        "distribution_checked",
        s.active_attempt_id,
        group_counts=list(facts.group_counts),
        assigned_total=facts.assigned_total,
        available_total=facts.available_total,
        groups_equal=facts.groups_equal,
        all_assigned=facts.all_assigned,
        valid_partition=facts.valid_partition,
        intervention=intervention.code,
        intervention_targets=list(intervention.target_ids),
    )
    return Outcome(s, [event])


def request_help(ctx: Ctx) -> Outcome:
    s, p = ctx.session, ctx.command.payload
    attempt = _active(s)
    if p.kind == "alternate_strategy" and attempt.kind == "transfer":
        # D4: só existe roteiro 20+4 para o item 24÷4.
        raise DomainError("UNSUPPORTED_CONTENT", "alternate_strategy has no script for this item")
    # A assistência é gravada antes de qualquer recurso ser liberado (Parte I §7).
    attempt = attempt.with_changes(ledger=apply_help_effect(attempt.ledger, p.kind))
    events = [
        _event(
            "help_granted",
            attempt.attempt_id,
            kind=p.kind,
            has_reason=bool(p.reason),  # o texto da criança não vira evento (R28, AC-45)
            **_help_snapshot(attempt),
        )
    ]
    updated = _with_attempt(s, attempt)
    scene_changed = False
    opens_scene = p.kind in ("virtual_objects", "reference_model")
    if opens_scene and attempt.kind == "transfer" and s.scene is None:  # D3
        item = _item_of(ctx.content, attempt)
        scene = initial_scene(
            item.task, scene_id=f"scene-{attempt.attempt_id}", attempt_id=attempt.attempt_id
        )
        updated = updated.with_changes(scene=scene)
        events.append(_event("scene_changed", attempt.attempt_id, reason="resource_granted"))
        scene_changed = True
    return Outcome(updated, events, scene_changed)


def enter_notebook(ctx: Ctx) -> Outcome:
    s, intent = ctx.session, ctx.command.payload.intent
    if s.phase == "notebook_review" and intent != "revise_record":
        raise DomainError("INVALID_TRANSITION", "only revise_record re-enters from review")
    return_phase = s.phase if s.phase in ("practice", "correction", "transfer") else s.return_phase
    updated = s.with_changes(
        interaction_mode="writing", return_phase=return_phase, notebook_intent=intent
    )
    if intent == "try_on_paper":  # papel é recurso de apoio, não ajuda: o nível não sobe
        attempt = _active(s)
        ledger = attempt.ledger
        paper = AssistanceLedger(level=ledger.level, resources=ledger.resources | {"paper"})
        updated = _with_attempt(updated, attempt.with_changes(ledger=paper))
    event = _event(
        "notebook_entered", s.active_attempt_id, intent=intent, return_phase=return_phase
    )
    return Outcome(updated, [event])


def return_to_activity(ctx: Ctx) -> Outcome:
    s = ctx.session
    target = next_phase("return_to_activity", facts_of(s))
    updated = s.with_changes(interaction_mode="ready", return_phase=None, notebook_intent=None)
    event = _event("returned_to_activity", s.active_attempt_id, from_phase=s.phase, to_phase=target)
    return Outcome(updated, [event])


def open_notebook_capture(ctx: Ctx) -> Outcome:
    """notebook -> notebook_capture (a fase vem da tabela). Uma foto nova (R23) abandona o artefato
    anterior, que pode existir depois de `revise_record`."""
    updated, events = drop_artifact(ctx.session, reason="recapture", clear_completed=True)
    return Outcome(updated, events)


def cancel_capture(ctx: Ctx) -> Outcome:
    """notebook_capture -> notebook. Mantém o checkpoint; em captura não há artefato vigente."""
    return Outcome(ctx.session)


def retake_notebook_photo(ctx: Ctx) -> Outcome:
    """notebook_review -> notebook_capture. A foto descartada deixa de valer (R26: um evento só se
    a análise ainda estava pendente)."""
    updated, events = drop_artifact(ctx.session, reason="retake", clear_completed=True)
    return Outcome(updated, events)


def submit_answer(ctx: Ctx) -> Outcome:
    s, p = ctx.session, ctx.command.payload
    attempt = _active(s)
    correct = bool(_answer_correct(ctx.content, attempt, p.answer))
    events = [_event("answer_submitted", attempt.attempt_id, answer=p.answer, correct=correct)]
    explanation = attempt.explanation
    if p.explanation is not None:
        explanation = _evaluate(ctx, attempt, "text", p.explanation)
        events.append(_explanation_event(attempt, explanation))
    attempt = attempt.with_changes(answer=p.answer, explanation=explanation)
    events.append(_outcome_event(ctx.content, attempt, final=False))
    return Outcome(_with_attempt(s, attempt), events, answer_correct=correct)


def submit_explanation(ctx: Ctx) -> Outcome:
    s, p = ctx.session, ctx.command.payload
    if p.modality == "artifact":  # exige o fluxo de foto (incremento 4)
        raise DomainError("ACTION_NOT_ALLOWED", "not_in_increment_1")
    attempt = _active(s)
    result = _evaluate(ctx, attempt, p.modality, p.text)
    attempt = attempt.with_changes(explanation=result)
    events = [_explanation_event(attempt, result)]
    if attempt.answer is not None:
        events.append(_outcome_event(ctx.content, attempt, final=False))
    return Outcome(_with_attempt(s, attempt), events)


def continue_after_explanation(ctx: Ctx) -> Outcome:
    s, reason = ctx.session, ctx.command.payload.reason
    attempt = _active(s)
    if reason == "sufficient":
        if attempt.explanation is None or attempt.explanation.rating != "sufficient":
            raise DomainError("INVALID_TRANSITION", "explanation is not sufficient")
    elif ctx.actor != "learner":  # a escolha de seguir sem explicar é da criança
        raise DomainError("ACTION_NOT_ALLOWED", "only the learner can skip the explanation")
    closed = attempt.with_changes(status="closed")
    events = [_outcome_event(ctx.content, closed, final=True)]
    updated = _with_attempt(s, closed).with_changes(
        interaction_mode="ready", return_phase=None, notebook_intent=None
    )
    if attempt.kind != "guided":
        # Análise ainda pendente não terá mais onde ser aplicada; a já concluída fica como evidência.
        updated, dropped = drop_artifact(updated, reason="attempt_closed", clear_completed=False)
        return Outcome(updated, [*events, *dropped])
    # A foto do caderno pertence à tentativa guiada: não passa para a questão nova.
    updated, dropped = drop_artifact(updated, reason="attempt_changed", clear_completed=True)
    events += dropped
    transfer, _ = _start_attempt(s, "transfer", _item_by_role(ctx.content, "transfer"))
    updated = updated.with_changes(
        attempts=(*updated.attempts, transfer), active_attempt_id=transfer.attempt_id, scene=None
    )
    events += [
        _event("attempt_started", transfer.attempt_id, kind="transfer", item_id=transfer.item_id),
        _event("scene_changed", transfer.attempt_id, reason="scene_hidden"),
    ]
    return Outcome(updated, events, scene_changed=True)


def pause_session(ctx: Ctx) -> Outcome:
    s = ctx.session
    if s.session_status == "paused":
        raise DomainError("NO_OP", "session is already paused")
    updated = s.with_changes(session_status="paused", turn_epoch=s.turn_epoch + 1)
    event = _event("session_paused", s.active_attempt_id, turn_epoch=updated.turn_epoch)
    return Outcome(updated, [event])


def resume_session(ctx: Ctx) -> Outcome:
    """Parte II §2: sem isenção de revisão (só pause/interrupt/learner_stopped têm); só da pausa.
    Mantém fase, cena e turn_epoch: a pausa já invalidou os turnos antigos do tutor."""
    s = ctx.session
    if s.session_status != "paused":
        raise DomainError("NO_OP", "session is not paused")
    updated = s.with_changes(session_status="active")
    event = _event("session_resumed", s.active_attempt_id, turn_epoch=updated.turn_epoch)
    return Outcome(updated, [event])


def close_session(ctx: Ctx) -> Outcome:
    s, reason = ctx.session, ctx.command.payload.reason
    if reason == "completed" and s.phase != "summary":
        raise DomainError("INVALID_TRANSITION", "completed requires the evidence flow")
    events: list[DomainEvent] = []
    updated = s
    attempt = s.active_attempt
    if attempt is not None and attempt.status == "active":
        if attempt.kind != "demonstration":
            events.append(_outcome_event(ctx.content, attempt, final=True))
        updated = _with_attempt(s, attempt.with_changes(status="closed"))
    completion = "complete" if reason == "completed" else "partial"
    # A análise pendente não terá mais onde ser aplicada (o resultado será descartado).
    updated, dropped = drop_artifact(updated, reason="session_closed", clear_completed=False)
    events += dropped
    updated = updated.with_changes(
        session_status="closed",
        completion=completion,
        interaction_mode="ready",
        return_phase=None,
        notebook_intent=None,
    )
    events.append(
        _event("session_closed", s.active_attempt_id, reason=reason, completion=completion)
    )
    return Outcome(updated, events)


HANDLERS: dict[str, Callable[[Ctx], Outcome]] = {
    "choose_reference_activity": choose_reference_activity,
    "run_demo_step": run_demo_step,
    "finish_demonstration": finish_demonstration,
    "move_piece": do_move_piece,
    "check_distribution": check_distribution,
    "request_help": request_help,
    "enter_notebook": enter_notebook,
    "return_to_activity": return_to_activity,
    "open_notebook_capture": open_notebook_capture,
    "cancel_capture": cancel_capture,
    "retake_notebook_photo": retake_notebook_photo,
    "submit_answer": submit_answer,
    "submit_explanation": submit_explanation,
    "continue_after_explanation": continue_after_explanation,
    "pause_session": pause_session,
    "resume_session": resume_session,
    "close_session": close_session,
}
