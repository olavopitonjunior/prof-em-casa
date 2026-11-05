"""Observação estrita do caderno, verificação determinística e reconstrução de cena.

Espelha contracts/notebook-observation.schema.json (Spec Parte II §6) com tipos estritos:
inteiros nunca aceitam bool nem float (inclusive 5.0), e nenhum modelo aceita campos extras.
O quociente é conteúdo privado: só entra em comparações, nunca em `facts`.
"""

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

from app.domain.division.errors import DomainError
from app.domain.division.scene import Group, Piece, SceneState
from app.domain.division.task import TaskSpec

_EPS = 1e-9  # tolerância de ponto flutuante: 0.1 + 0.9 não pode ser sinalizado como > 1
_COUNT_PATH = re.compile(r"^/groups/(0|[1-9][0-9]*)/count$")
_UNDER_GROUP = re.compile(r"^/groups/(0|[1-9][0-9]*)(/.*)?$")
_GROUP_PATH = re.compile(r"^/groups/(0|[1-9][0-9]*)(/count|/bbox)?$")
_EXPRESSION_PATHS = {
    "/expression",
    "/expression/dividend",
    "/expression/divisor",
    "/expression/answer",
}

_Frozen = ConfigDict(frozen=True, extra="forbid")
_NonEmpty = Annotated[str, Field(min_length=1)]
_ExprInt = Annotated[StrictInt, Field(ge=-9999, le=9999)]


class BBox(BaseModel):
    model_config = _Frozen

    x: StrictFloat | StrictInt = Field(ge=0, le=1, allow_inf_nan=False)
    y: StrictFloat | StrictInt = Field(ge=0, le=1, allow_inf_nan=False)
    width: StrictFloat | StrictInt = Field(gt=0, le=1, allow_inf_nan=False)
    height: StrictFloat | StrictInt = Field(gt=0, le=1, allow_inf_nan=False)


class ObservedExpression(BaseModel):
    model_config = _Frozen

    dividend: _ExprInt | None
    divisor: _ExprInt | None
    answer: _ExprInt | None
    bbox: BBox | None
    uncertain: StrictBool


class ObservedGroup(BaseModel):
    model_config = _Frozen

    group_id: _NonEmpty
    count: Annotated[StrictInt, Field(ge=0, le=60)] | None
    bbox: BBox
    provenance: Literal["image"]
    uncertain: StrictBool

    @model_validator(mode="after")
    def _null_count_is_uncertain(self) -> "ObservedGroup":
        if self.count is None and not self.uncertain:
            raise ValueError("a null count requires uncertain=true")
        return self


class Ambiguity(BaseModel):
    model_config = _Frozen

    field_path: _NonEmpty
    reason: Literal[
        "illegible",
        "missing",
        "overlap",
        "cropped",
        "conflicting_marks",
        "unsupported_representation",
    ]


class NotebookObservation(BaseModel):
    model_config = _Frozen

    schema_version: Literal["1.0"]
    observation_id: _NonEmpty
    artifact_id: _NonEmpty
    attempt_id: _NonEmpty
    model_ref: _NonEmpty
    prompt_version: _NonEmpty
    artifact_version: Annotated[StrictInt, Field(ge=1)]
    status: Literal["usable", "needs_clarification"]
    expression: ObservedExpression
    groups: Annotated[tuple[ObservedGroup, ...], Field(max_length=12)]
    ambiguities: tuple[Ambiguity, ...]

    @model_validator(mode="after")
    def _needs_clarification_has_ambiguity(self) -> "NotebookObservation":
        if self.status == "needs_clarification" and not self.ambiguities:
            raise ValueError("needs_clarification requires at least one ambiguity")
        return self


class Clarification(BaseModel):
    """Contagem informada pela criança para resolver uma ambiguidade (procedência learner_report)."""

    model_config = _Frozen

    field_path: _NonEmpty
    value: Annotated[StrictInt, Field(ge=0, le=60)]
    provenance: Literal["learner_report"] = "learner_report"


class Verification(BaseModel):
    model_config = _Frozen

    observation_id: str
    status: Literal["consistent", "inconsistent", "inconclusive"]
    facts: dict[str, Any]
    # Códigos de divergência com a tarefa e, quando `validate_observation` reprova o documento,
    # os códigos dessa validação (ex.: DUPLICATE_GROUP_ID); nesse caso o status é "inconclusive".
    issues: tuple[str, ...]
    reconstruction_allowed: bool


@dataclass(frozen=True)
class ReconstructionUnavailable:
    reason: str


def _bbox_out_of_bounds(box: BBox | None) -> bool:
    return box is not None and (box.x + box.width > 1 + _EPS or box.y + box.height > 1 + _EPS)


def validate_observation(obs: NotebookObservation) -> list[str]:
    """Checagens extras que o schema não cobre. Devolve códigos, sem repetição, em ordem fixa."""
    codes: list[str] = []

    def add(code: str) -> None:
        if code not in codes:
            codes.append(code)

    if _bbox_out_of_bounds(obs.expression.bbox) or any(
        _bbox_out_of_bounds(g.bbox) for g in obs.groups
    ):
        add("BBOX_OUT_OF_BOUNDS")
    group_ids = [g.group_id for g in obs.groups]
    if len(set(group_ids)) != len(group_ids):
        add("DUPLICATE_GROUP_ID")
    for amb in obs.ambiguities:
        if not _path_exists(obs, amb.field_path):
            add("DANGLING_AMBIGUITY_PATH")
    paths = {a.field_path for a in obs.ambiguities}
    for i, g in enumerate(obs.groups):
        if g.uncertain and f"/groups/{i}/count" not in paths:
            add("UNCERTAIN_WITHOUT_AMBIGUITY")
    return codes


def _path_exists(obs: NotebookObservation, path: str) -> bool:
    if path in _EXPRESSION_PATHS:
        return True
    m = _GROUP_PATH.match(path)
    return m is not None and int(m.group(1)) < len(obs.groups)


@dataclass(frozen=True)
class _Counts:
    values: tuple[int | None, ...]  # contagem efetiva por grupo; None = inutilizável
    learner_reported: tuple[int, ...]  # índices vindos de clarificação
    resolved_groups: frozenset[int]  # grupos resolvidos por clarificação de /groups/{i}/count


def _ambiguous_group_indexes(obs: NotebookObservation) -> set[int]:
    """Grupos com ambiguidade em /groups/{i} ou em qualquer caminho abaixo dele."""
    found: set[int] = set()
    for a in obs.ambiguities:
        m = _UNDER_GROUP.match(a.field_path)
        if m is not None:
            found.add(int(m.group(1)))
    return found


def _unreadable_expression_fields(obs: NotebookObservation) -> frozenset[str]:
    """Campos da expressão com ambiguidade em /expression ou abaixo, seja qual for obs.status."""
    fields: set[str] = set()
    for a in obs.ambiguities:
        path = a.field_path
        if path == "/expression":
            fields |= {"dividend", "divisor", "answer"}
        elif path.startswith("/expression/"):
            name = path.removeprefix("/expression/")
            fields |= (
                {name}
                if name in {"dividend", "divisor", "answer"}
                else {
                    "dividend",
                    "divisor",
                    "answer",
                }
            )
    return frozenset(fields)


def _resolve_counts(obs: NotebookObservation, clarifications: list[Clarification]) -> _Counts:
    ambiguous = _ambiguous_group_indexes(obs)
    given: dict[int, int] = {}
    for c in clarifications:
        m = _COUNT_PATH.match(c.field_path)
        if m is None or int(m.group(1)) >= len(obs.groups):
            raise DomainError("INVALID_PAYLOAD", f"clarification for unknown path {c.field_path}")
        i = int(m.group(1))
        g = obs.groups[i]
        if not (g.count is None or g.uncertain or i in ambiguous):
            raise DomainError("INVALID_PAYLOAD", f"{c.field_path} is not ambiguous")
        if i in given:
            raise DomainError("INVALID_PAYLOAD", f"duplicate clarification for {c.field_path}")
        given[i] = c.value
    values: list[int | None] = []
    for i, g in enumerate(obs.groups):
        if i in given:
            values.append(given[i])
        elif g.count is None or g.uncertain or i in ambiguous:
            values.append(None)
        else:
            values.append(g.count)
    return _Counts(
        values=tuple(values),
        learner_reported=tuple(sorted(given)),
        resolved_groups=frozenset(given),
    )


def _unresolved_ambiguities(obs: NotebookObservation, counts: _Counts) -> list[Ambiguity]:
    def resolved(path: str) -> bool:
        m = _UNDER_GROUP.match(path)
        return m is not None and int(m.group(1)) in counts.resolved_groups

    return [a for a in obs.ambiguities if not resolved(a.field_path)]


def _reconstruction_blocker(
    task: TaskSpec, obs: NotebookObservation, counts: _Counts
) -> str | None:
    values = counts.values
    if not values:
        return "NO_GROUPS"
    if validate_observation(obs):
        return "INVALID_OBSERVATION"
    if _unreadable_expression_fields(obs):
        return "UNRESOLVED_EXPRESSION_AMBIGUITY"
    if any(v is None for v in values):
        return "UNUSABLE_COUNTS"
    if obs.status == "needs_clarification" and _unresolved_ambiguities(obs, counts):
        return "UNRESOLVED_AMBIGUITY"  # mesma condição que torna a verificação inconclusiva
    if len(values) != task.divisor:
        return "GROUP_COUNT_MISMATCH"
    if sum(v for v in values if v is not None) > task.dividend:
        return "EXCESS_REPRESENTED"
    return None


_ISSUE_ORDER = (
    "TOTAL_MISMATCH",
    "GROUP_COUNT_MISMATCH",
    "GROUPS_UNEQUAL",
    "EXCESS_REPRESENTED",
    "EXPRESSION_MISMATCH",
    "WRITTEN_ANSWER_MISMATCH",
)
_VALIDATION_ORDER = (
    "BBOX_OUT_OF_BOUNDS",
    "DUPLICATE_GROUP_ID",
    "DANGLING_AMBIGUITY_PATH",
    "UNCERTAIN_WITHOUT_AMBIGUITY",
)


def verify_observation(
    task: TaskSpec,
    quotient: int,
    obs: NotebookObservation,
    clarifications: list[Clarification],
) -> Verification:
    """Verificação determinística. `quotient` é privado: só é comparado, nunca copiado para `facts`."""
    counts = _resolve_counts(obs, clarifications)
    values = counts.values
    expr = obs.expression
    all_usable = all(v is not None for v in values)
    issues: list[str] = []
    facts: dict[str, Any] = {"task_total": task.dividend, "task_groups": task.divisor}

    # Expressão: só vale o que está legível. Ambiguidade em /expression ou abaixo (qualquer
    # obs.status) torna o campo ilegível; expression.uncertain torna todos ilegíveis.
    unreadable = _unreadable_expression_fields(obs)
    all_readable = not expr.uncertain

    def read(name: str, value: int | None) -> int | None:
        return value if all_readable and name not in unreadable else None

    dividend = read("dividend", expr.dividend)
    divisor = read("divisor", expr.divisor)
    answer = read("answer", expr.answer)
    if (dividend is not None and dividend != task.dividend) or (
        divisor is not None and divisor != task.divisor
    ):
        issues.append("EXPRESSION_MISMATCH")
    if answer is not None:
        facts["written_answer"] = answer
        if answer != quotient:
            issues.append("WRITTEN_ANSWER_MISMATCH")

    if values:
        facts["observed_group_counts"] = list(values)
        if len(values) != task.divisor:
            issues.append("GROUP_COUNT_MISMATCH")
        if all_usable:
            known = [v for v in values if v is not None]
            total = sum(known)
            facts["represented_total"] = total
            facts["groups_equal"] = len(set(known)) == 1
            if total <= task.dividend:
                facts["not_represented"] = task.dividend - total
            else:
                facts["excess_represented"] = total - task.dividend
                issues.append("EXCESS_REPRESENTED")
            if total != task.dividend:
                issues.append("TOTAL_MISMATCH")
            if len(set(known)) != 1:
                issues.append("GROUPS_UNEQUAL")
        if counts.learner_reported:
            facts["learner_reported_groups"] = [
                obs.groups[i].group_id for i in counts.learner_reported
            ]

    unresolved = _unresolved_ambiguities(obs, counts)
    if values:
        inconclusive = not all_usable
    else:  # só expressão: sem evidência de grupos, decide pela expressão e pela resposta escrita
        inconclusive = answer is None and not issues
    if obs.status == "needs_clarification" and unresolved:
        inconclusive = True
    if unreadable:  # ambiguidade de expressão vale independentemente do status declarado
        inconclusive = True
    invalid = validate_observation(obs)
    if invalid:  # documento incoerente nunca vira "consistente" nem alimenta reconstrução
        inconclusive = True
        issues.extend(invalid)

    if inconclusive:
        status = "inconclusive"
    elif issues:
        status = "inconsistent"
    else:
        status = "consistent"
    return Verification(
        observation_id=obs.observation_id,
        status=status,
        facts=facts,
        issues=tuple(i for i in (*_ISSUE_ORDER, *_VALIDATION_ORDER) if i in issues),
        reconstruction_allowed=_reconstruction_blocker(task, obs, counts) is None,
    )


def build_reconstruction(
    task: TaskSpec,
    obs: NotebookObservation,
    clarifications: list[Clarification],
    *,
    scene_id: str,
    attempt_id: str,
    scene_revision: int,
) -> SceneState | ReconstructionUnavailable:
    """Monta a cena a partir da foto. photo groups[i] vira group-{i+1}; faltantes são task_derived."""
    counts = _resolve_counts(obs, clarifications)
    blocker = _reconstruction_blocker(task, obs, counts)
    if blocker is not None:
        return ReconstructionUnavailable(reason=blocker)

    pieces: list[Piece] = []
    groups: list[Group] = []
    for i, (photo_group, n) in enumerate(zip(obs.groups, counts.values, strict=True)):
        origin: Literal["image", "learner_report"] = (
            "learner_report" if i in counts.learner_reported else "image"
        )
        ref = f"{obs.observation_id}/{photo_group.group_id}"
        ids: list[str] = []
        for _ in range(n or 0):
            pid = f"piece-{len(pieces) + 1:02d}"
            pieces.append(Piece(id=pid, origin=origin, observation_ref=ref))
            ids.append(pid)
        groups.append(Group(id=f"group-{i + 1}", piece_ids=tuple(ids)))
    available: list[str] = []
    while len(pieces) < task.dividend:
        pid = f"piece-{len(pieces) + 1:02d}"
        pieces.append(Piece(id=pid, origin="task_derived", observation_ref=None))
        available.append(pid)
    return SceneState(
        scene_id=scene_id,
        scene_revision=scene_revision,
        attempt_id=attempt_id,
        task=task,
        projection="perspective",
        interaction="learner",
        groups=tuple(groups),
        available_piece_ids=tuple(available),
        pieces=tuple(pieces),
        highlighted_ids=(),
        answer_display=None,
    )
