"""Tabela única de transições de fase (Spec Parte I §4; decisão D7 do plano).

`TRANSITIONS[tipo] = (fases permitidas, próxima fase)`. `None` mantém a fase atual, exceto nos
quatro comandos cuja próxima fase depende do resultado: neles o segundo elemento é `None` e a regra
em `_NEXT_PHASE_RULES` decide. A tabela cobre os 30 comandos do catálogo, inclusive os que ainda
não têm handler (o `apply_command` os recusa com `not_in_increment_1`). O incremento 2 deu handler
a `open_notebook_capture`, `cancel_capture` e `retake_notebook_photo`.

Arestas que a Spec Parte I §4 não escreve (D7), todas sujeitas a atualização da Spec:
- request_reconstruction: notebook_review -> correction
- return_to_activity: explanation -> practice (item guiado) | transfer (item novo)
- submit_answer: practice -> explanation (resposta correta; sem foto, é o único caminho)
- request_help: aceito também em notebook (mantém a fase)
- enter_notebook: aceito a partir de notebook_review (revise_record)
- choose_reference_activity: aceito a partir de source_capture e source_review
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, get_args

from app.domain.division.errors import DomainError

Phase = Literal[
    "source_capture",
    "source_review",
    "demonstration",
    "practice",
    "notebook",
    "notebook_capture",
    "notebook_review",
    "correction",
    "explanation",
    "transfer",
    "summary",
]
AttemptKind = Literal["demonstration", "guided", "transfer"]

_ALL: frozenset[Phase] = frozenset(get_args(Phase))
_NOT_SUMMARY: frozenset[Phase] = _ALL - {"summary"}
_SCENE_WORK: frozenset[Phase] = frozenset({"practice", "correction", "transfer"})


def _p(*phases: Phase) -> frozenset[Phase]:
    return frozenset(phases)


TRANSITIONS: dict[str, tuple[frozenset[Phase], Phase | None]] = {
    "confirm_source": (_p("source_review"), "demonstration"),
    "clarify_source": (_p("source_review"), None),
    "retake_source_photo": (_p("source_review"), "source_capture"),
    "choose_reference_activity": (_p("source_capture", "source_review"), "demonstration"),
    "run_demo_step": (_p("demonstration"), None),
    "finish_demonstration": (_p("demonstration"), "practice"),
    "move_piece": (_SCENE_WORK, None),
    "undo_move": (_SCENE_WORK, None),
    "check_distribution": (_SCENE_WORK, None),
    "highlight_group": (_SCENE_WORK, None),
    "highlight_available": (_SCENE_WORK, None),
    "set_projection": (_SCENE_WORK, None),
    "request_help": (_SCENE_WORK | {"notebook"}, None),
    "apply_help": (_SCENE_WORK, None),
    "enter_notebook": (_SCENE_WORK | {"notebook_review"}, None),  # regra: sempre notebook
    "open_notebook_capture": (_p("notebook"), "notebook_capture"),
    "return_to_activity": (_p("notebook", "explanation"), None),  # regra: checkpoint / tipo
    "cancel_capture": (_p("notebook_capture"), "notebook"),
    "retake_notebook_photo": (_p("notebook_review"), "notebook_capture"),
    "request_reconstruction": (_p("notebook_review"), "correction"),
    "dispute_observation": (_p("notebook_review", "correction", "explanation"), None),
    "clarify_observation": (_p("notebook_review"), None),
    "submit_answer": (_SCENE_WORK, None),  # regra: depende de a resposta estar correta
    "submit_explanation": (_p("explanation", "transfer"), None),
    "continue_after_explanation": (_p("explanation"), None),  # regra: guiada -> transfer
    "set_thinking": (_NOT_SUMMARY, None),
    "pause_session": (_ALL, None),
    "resume_session": (_ALL, None),
    "interrupt_turn": (_ALL, None),
    "close_session": (_ALL, "summary"),
}


@dataclass(frozen=True)
class NextPhaseFacts:
    """Fatos mínimos de que as regras dependentes de resultado precisam."""

    phase: Phase
    attempt_kind: AttemptKind | None
    return_phase: Phase | None
    answer_correct: bool | None


def _enter_notebook(f: NextPhaseFacts) -> Phase:
    return "notebook"


def _return_to_activity(f: NextPhaseFacts) -> Phase:
    if f.phase == "notebook":
        if f.return_phase is None:
            raise DomainError("INVALID_TRANSITION", "notebook without return_phase checkpoint")
        return f.return_phase
    return "practice" if f.attempt_kind == "guided" else "transfer"


def _submit_answer(f: NextPhaseFacts) -> Phase:
    return "explanation" if f.answer_correct else f.phase


def _continue_after_explanation(f: NextPhaseFacts) -> Phase:
    return "transfer" if f.attempt_kind == "guided" else "summary"


_NEXT_PHASE_RULES: dict[str, Callable[[NextPhaseFacts], Phase]] = {
    "enter_notebook": _enter_notebook,
    "return_to_activity": _return_to_activity,
    "submit_answer": _submit_answer,
    "continue_after_explanation": _continue_after_explanation,
}


def is_allowed_in(command_type: str, phase: str) -> bool:
    entry = TRANSITIONS.get(command_type)
    return entry is not None and phase in entry[0]


def next_phase(command_type: str, facts: NextPhaseFacts) -> Phase:
    """Próxima fase de um comando já permitido na fase atual (`is_allowed_in`)."""
    rule = _NEXT_PHASE_RULES.get(command_type)
    if rule is not None:
        return rule(facts)
    target = TRANSITIONS[command_type][1]
    return facts.phase if target is None else target
