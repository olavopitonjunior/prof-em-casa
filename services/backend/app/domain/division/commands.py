"""Envelope de comando e catálogo estrito de 30 tipos (Spec Parte II §2 e §3; AC-39).

Todo modelo usa `strict=True` e `extra="forbid"`: bool, float (inclusive 5.0) e string numérica
não passam por inteiro, e nenhum campo desconhecido é aceito. `actor` nunca vem do JSON: é o
contexto autenticado, passado a `parse_command`. Ordem de erros: entrada/JSON/schema inválidos
-> INVALID_PAYLOAD; forma válida mas ator fora de ALLOWED_ACTORS -> ACTION_NOT_ALLOWED; depois,
regras de turno que dependem do ator (INVALID_PAYLOAD).
"""

import json
import math
from typing import Annotated, Any, Literal, Self, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.domain.division.assistance import HelpKind
from app.domain.division.errors import DomainError

Actor = Literal["learner", "tutor", "system", "vision_worker"]

CommandType = Literal[
    "confirm_source",
    "clarify_source",
    "retake_source_photo",
    "choose_reference_activity",
    "run_demo_step",
    "finish_demonstration",
    "move_piece",
    "undo_move",
    "check_distribution",
    "highlight_group",
    "highlight_available",
    "set_projection",
    "request_help",
    "apply_help",
    "enter_notebook",
    "open_notebook_capture",
    "return_to_activity",
    "cancel_capture",
    "retake_notebook_photo",
    "request_reconstruction",
    "dispute_observation",
    "clarify_observation",
    "submit_answer",
    "submit_explanation",
    "continue_after_explanation",
    "set_thinking",
    "pause_session",
    "resume_session",
    "interrupt_turn",
    "close_session",
]

# D3 (decisão posterior do usuário, acima da tabela da Spec §3): `request_help.kind` é HelpKind
# sem procedural e accessibility, que só o tutor registra. Subconjunto de HelpKind (assert e teste).
RequestHelpKind = Literal[
    "prompt",
    "visual_hint",
    "worked_step",
    "alternate_strategy",
    "virtual_objects",
    "reference_model",
]
assert set(get_args(RequestHelpKind)) <= set(get_args(HelpKind))

# Comandos de cena: exigem `expected_scene_revision`; os demais o proíbem.
SCENE_COMMANDS: frozenset[str] = frozenset(
    {
        "move_piece",
        "undo_move",
        "highlight_group",
        "highlight_available",
        "set_projection",
        "run_demo_step",
        "apply_help",
        "request_reconstruction",
    }
)

_STRICT = ConfigDict(strict=True, extra="forbid", frozen=True)

_Id = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
_FieldPath = Annotated[
    StrictStr, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.\[\]-]+$")
]
_ShortText = Annotated[StrictStr, StringConstraints(min_length=1, max_length=500)]
_LongText = Annotated[StrictStr, StringConstraints(min_length=1, max_length=2000)]
_Number = Annotated[StrictInt, Field(ge=-9999, le=9999)]  # mesma faixa da observação
_ClarifiedValue = _Number | _ShortText
MAX_REVISION = 2_147_483_647  # INTEGER do Postgres
_Revision = Annotated[StrictInt, Field(ge=0, le=MAX_REVISION)]


class CommandEnvelope(BaseModel):
    """Campos comuns da Parte II §2. `type` e `payload` vêm de cada comando concreto."""

    model_config = _STRICT

    schema_version: Literal["1.0"]
    command_id: _Id
    session_id: _Id
    attempt_id: _Id | None  # obrigatório; null antes da confirmação da fonte
    expected_revision: _Revision
    turn_id: _Id | None = None
    turn_epoch: _Revision | None = None

    @model_validator(mode="after")
    def _turn_fields_come_in_pairs(self) -> Self:
        if (self.turn_id is None) != (self.turn_epoch is None):
            raise ValueError("turn_id e turn_epoch andam juntos")
        return self


class SceneCommandEnvelope(CommandEnvelope):
    expected_scene_revision: _Revision


class _Payload(BaseModel):
    model_config = _STRICT


class ConfirmSourcePayload(_Payload):
    analysis_id: _Id
    item_id: _Id


class ClarifySourcePayload(_Payload):
    analysis_id: _Id
    field_path: _FieldPath
    value: _ClarifiedValue


class RetakeSourcePhotoPayload(_Payload):
    """Payload vazio: só `{}` é aceito."""


class ChooseReferenceActivityPayload(_Payload):
    content_version: Literal["division-sharing-v1"]


class RunDemoStepPayload(_Payload):
    step_id: _Id


class FinishDemonstrationPayload(_Payload):
    reason: Literal["completed", "learner_requested"]


class MovePiecePayload(_Payload):
    piece_id: _Id
    from_location: _Id  # "available" ou um group_id
    to_location: _Id


class UndoMovePayload(_Payload):
    target_command_id: _Id


class CheckDistributionPayload(_Payload):
    """Payload vazio: só `{}` é aceito."""


class HighlightGroupPayload(_Payload):
    group_id: _Id


class HighlightAvailablePayload(_Payload):
    """Payload vazio: só `{}` é aceito."""


class SetProjectionPayload(_Payload):
    projection: Literal["perspective", "top", "schematic"]


class RequestHelpPayload(_Payload):
    kind: RequestHelpKind
    reason: _ShortText


class ApplyHelpPayload(_Payload):
    intervention_id: _Id
    step_id: _Id


class EnterNotebookPayload(_Payload):
    intent: Literal["record_solution", "try_on_paper", "revise_record"]


class OpenNotebookCapturePayload(_Payload):
    """Payload vazio: só `{}` é aceito."""


class ReturnToActivityPayload(_Payload):
    """Payload vazio: só `{}` é aceito."""


class CancelCapturePayload(_Payload):
    """Payload vazio: só `{}` é aceito."""


class RetakeNotebookPhotoPayload(_Payload):
    """Payload vazio: só `{}` é aceito."""


class RequestReconstructionPayload(_Payload):
    observation_id: _Id


class DisputeObservationPayload(_Payload):
    observation_id: _Id
    field_path: _FieldPath | None = None
    reason: _ShortText | None = None

    @model_validator(mode="after")
    def _field_path_or_reason(self) -> Self:
        if self.field_path is None and self.reason is None:
            raise ValueError("informe field_path ou reason")
        return self


class ClarifyObservationPayload(_Payload):
    observation_id: _Id
    field_path: _FieldPath
    value: _ClarifiedValue


class SubmitAnswerPayload(_Payload):
    answer: _Number
    explanation: _LongText | None  # obrigatório, mas pode ser null


class SubmitExplanationPayload(_Payload):
    modality: Literal["text", "voice_transcript", "artifact"]
    text: _LongText | None = None
    artifact_id: _Id | None = None

    @model_validator(mode="after")
    def _text_xor_artifact(self) -> Self:
        if self.modality == "artifact":
            if self.artifact_id is None or self.text is not None:
                raise ValueError("modality=artifact exige artifact_id e proíbe text")
        elif self.text is None or self.artifact_id is not None:
            raise ValueError("modality=text|voice_transcript exige text e proíbe artifact_id")
        return self


class ContinueAfterExplanationPayload(_Payload):
    reason: Literal["sufficient", "learner_skipped"]


class SetThinkingPayload(_Payload):
    enabled: StrictBool


class PauseSessionPayload(_Payload):
    """Payload vazio: só `{}` é aceito."""


class ResumeSessionPayload(_Payload):
    """Payload vazio: só `{}` é aceito."""


class InterruptTurnPayload(_Payload):
    turn_id: _Id


class CloseSessionPayload(_Payload):
    reason: Literal["completed", "learner_stopped", "limit_reached"]


class ConfirmSourceCommand(CommandEnvelope):
    type: Literal["confirm_source"]
    payload: ConfirmSourcePayload


class ClarifySourceCommand(CommandEnvelope):
    type: Literal["clarify_source"]
    payload: ClarifySourcePayload


class RetakeSourcePhotoCommand(CommandEnvelope):
    type: Literal["retake_source_photo"]
    payload: RetakeSourcePhotoPayload


class ChooseReferenceActivityCommand(CommandEnvelope):
    type: Literal["choose_reference_activity"]
    payload: ChooseReferenceActivityPayload


class RunDemoStepCommand(SceneCommandEnvelope):
    type: Literal["run_demo_step"]
    payload: RunDemoStepPayload


class FinishDemonstrationCommand(CommandEnvelope):
    type: Literal["finish_demonstration"]
    payload: FinishDemonstrationPayload


class MovePieceCommand(SceneCommandEnvelope):
    type: Literal["move_piece"]
    payload: MovePiecePayload


class UndoMoveCommand(SceneCommandEnvelope):
    type: Literal["undo_move"]
    payload: UndoMovePayload


class CheckDistributionCommand(CommandEnvelope):
    type: Literal["check_distribution"]
    payload: CheckDistributionPayload


class HighlightGroupCommand(SceneCommandEnvelope):
    type: Literal["highlight_group"]
    payload: HighlightGroupPayload


class HighlightAvailableCommand(SceneCommandEnvelope):
    type: Literal["highlight_available"]
    payload: HighlightAvailablePayload


class SetProjectionCommand(SceneCommandEnvelope):
    type: Literal["set_projection"]
    payload: SetProjectionPayload


class RequestHelpCommand(CommandEnvelope):
    type: Literal["request_help"]
    payload: RequestHelpPayload


class ApplyHelpCommand(SceneCommandEnvelope):
    type: Literal["apply_help"]
    payload: ApplyHelpPayload


class EnterNotebookCommand(CommandEnvelope):
    type: Literal["enter_notebook"]
    payload: EnterNotebookPayload


class OpenNotebookCaptureCommand(CommandEnvelope):
    type: Literal["open_notebook_capture"]
    payload: OpenNotebookCapturePayload


class ReturnToActivityCommand(CommandEnvelope):
    type: Literal["return_to_activity"]
    payload: ReturnToActivityPayload


class CancelCaptureCommand(CommandEnvelope):
    type: Literal["cancel_capture"]
    payload: CancelCapturePayload


class RetakeNotebookPhotoCommand(CommandEnvelope):
    type: Literal["retake_notebook_photo"]
    payload: RetakeNotebookPhotoPayload


class RequestReconstructionCommand(SceneCommandEnvelope):
    type: Literal["request_reconstruction"]
    payload: RequestReconstructionPayload


class DisputeObservationCommand(CommandEnvelope):
    type: Literal["dispute_observation"]
    payload: DisputeObservationPayload


class ClarifyObservationCommand(CommandEnvelope):
    type: Literal["clarify_observation"]
    payload: ClarifyObservationPayload


class SubmitAnswerCommand(CommandEnvelope):
    type: Literal["submit_answer"]
    payload: SubmitAnswerPayload


class SubmitExplanationCommand(CommandEnvelope):
    type: Literal["submit_explanation"]
    payload: SubmitExplanationPayload


class ContinueAfterExplanationCommand(CommandEnvelope):
    type: Literal["continue_after_explanation"]
    payload: ContinueAfterExplanationPayload


class SetThinkingCommand(CommandEnvelope):
    type: Literal["set_thinking"]
    payload: SetThinkingPayload


class PauseSessionCommand(CommandEnvelope):
    type: Literal["pause_session"]
    payload: PauseSessionPayload


class ResumeSessionCommand(CommandEnvelope):
    type: Literal["resume_session"]
    payload: ResumeSessionPayload


class InterruptTurnCommand(CommandEnvelope):
    type: Literal["interrupt_turn"]
    payload: InterruptTurnPayload


class CloseSessionCommand(CommandEnvelope):
    type: Literal["close_session"]
    payload: CloseSessionPayload


Command = Annotated[
    ConfirmSourceCommand
    | ClarifySourceCommand
    | RetakeSourcePhotoCommand
    | ChooseReferenceActivityCommand
    | RunDemoStepCommand
    | FinishDemonstrationCommand
    | MovePieceCommand
    | UndoMoveCommand
    | CheckDistributionCommand
    | HighlightGroupCommand
    | HighlightAvailableCommand
    | SetProjectionCommand
    | RequestHelpCommand
    | ApplyHelpCommand
    | EnterNotebookCommand
    | OpenNotebookCaptureCommand
    | ReturnToActivityCommand
    | CancelCaptureCommand
    | RetakeNotebookPhotoCommand
    | RequestReconstructionCommand
    | DisputeObservationCommand
    | ClarifyObservationCommand
    | SubmitAnswerCommand
    | SubmitExplanationCommand
    | ContinueAfterExplanationCommand
    | SetThinkingCommand
    | PauseSessionCommand
    | ResumeSessionCommand
    | InterruptTurnCommand
    | CloseSessionCommand,
    Field(discriminator="type"),
]
_COMMAND = TypeAdapter(Command)

# Colunas L/T/S da Spec §3 (L=learner, T=tutor, S=system). vision_worker não emite comandos.
ALLOWED_ACTORS: dict[str, frozenset[Actor]] = {
    "confirm_source": frozenset({"learner"}),
    "clarify_source": frozenset({"learner"}),
    "retake_source_photo": frozenset({"learner"}),
    "choose_reference_activity": frozenset({"learner"}),
    "run_demo_step": frozenset({"tutor", "system"}),
    "finish_demonstration": frozenset({"learner", "system"}),
    "move_piece": frozenset({"learner"}),
    "undo_move": frozenset({"learner"}),
    "check_distribution": frozenset({"learner"}),
    "highlight_group": frozenset({"tutor"}),
    "highlight_available": frozenset({"tutor"}),
    "set_projection": frozenset({"learner", "tutor"}),
    "request_help": frozenset({"learner"}),
    "apply_help": frozenset({"tutor", "system"}),
    "enter_notebook": frozenset({"learner"}),
    "open_notebook_capture": frozenset({"learner"}),
    "return_to_activity": frozenset({"learner"}),
    "cancel_capture": frozenset({"learner"}),
    "retake_notebook_photo": frozenset({"learner"}),
    "request_reconstruction": frozenset({"learner"}),
    "dispute_observation": frozenset({"learner"}),
    "clarify_observation": frozenset({"learner"}),
    "submit_answer": frozenset({"learner"}),
    "submit_explanation": frozenset({"learner"}),
    "continue_after_explanation": frozenset({"learner", "system"}),
    "set_thinking": frozenset({"learner"}),
    "pause_session": frozenset({"learner"}),
    "resume_session": frozenset({"learner"}),
    "interrupt_turn": frozenset({"learner", "system"}),
    "close_session": frozenset({"learner", "system"}),
}

assert set(ALLOWED_ACTORS) == set(get_args(CommandType))


def _reject_constant(name: str) -> Any:
    raise ValueError(f"constante JSON não finita: {name}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"chave JSON duplicada: {key}")
        out[key] = value
    return out


def _check_finite(value: Any) -> None:
    """Rejeita NaN/inf em qualquer profundidade (dict chega do código, não do json.loads)."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("número não finito")
    elif isinstance(value, dict):
        for item in value.values():
            _check_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_finite(item)


def load_json_object(raw: bytes | str | dict) -> dict[str, Any]:
    """Lê o corpo como objeto JSON estrito (sem chaves duplicadas, NaN ou inf). Pública: a camada
    `sessions` lê o `command_id` por aqui antes de chamar `parse_command`."""
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).decode("utf-8")
        if isinstance(raw, str):
            raw = json.loads(
                raw, parse_constant=_reject_constant, object_pairs_hook=_no_duplicate_keys
            )
        if not isinstance(raw, dict):
            raise TypeError("o comando deve ser um objeto JSON")
        _check_finite(raw)
    except (ValueError, TypeError, RecursionError) as exc:  # JSON e UTF-8 inválidos incluídos
        raise DomainError("INVALID_PAYLOAD", str(exc)[:200]) from None
    return raw


_load = load_json_object  # nome antigo (incremento 1)


def parse_command(raw: bytes | str | dict, actor: Actor) -> Command:
    """Valida o corpo de um comando e o ator que o enviou. `actor` é contexto, nunca JSON."""
    data = load_json_object(raw)
    if "actor" in data:
        raise DomainError("INVALID_PAYLOAD", "actor não é aceito no corpo")
    try:
        command = _COMMAND.validate_python(data)
    except ValidationError as exc:
        where = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors()[:5]
        )
        raise DomainError("INVALID_PAYLOAD", where) from None
    if actor not in ALLOWED_ACTORS[command.type]:
        raise DomainError("ACTION_NOT_ALLOWED", f"{actor} não pode executar {command.type}")
    present = command.model_fields_set & {"turn_id", "turn_epoch"}
    if actor == "tutor":
        if command.turn_id is None or command.turn_epoch is None:
            raise DomainError("INVALID_PAYLOAD", "tutor exige turn_id e turn_epoch")
    elif actor == "learner" and present:
        raise DomainError("INVALID_PAYLOAD", "aluno não envia turn_id/turn_epoch")
    return command
