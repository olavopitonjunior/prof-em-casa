from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.division.errors import DomainError
from app.domain.division.task import TaskSpec

PieceOrigin = Literal["content", "image", "learner_report", "task_derived"]
Projection = Literal["perspective", "top", "schematic"]
Interaction = Literal["learner", "tutor", "readonly"]

AVAILABLE = "available"


class Piece(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    origin: PieceOrigin
    observation_ref: str | None = None


class Group(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    piece_ids: tuple[str, ...]


class SceneState(BaseModel):
    """Snapshot completo da cena (Spec Parte II §4). Aplica as invariantes 1 e 2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: str
    scene_revision: int
    attempt_id: str
    task: TaskSpec
    projection: Projection
    interaction: Interaction
    groups: tuple[Group, ...]
    available_piece_ids: tuple[str, ...]
    pieces: tuple[Piece, ...]
    highlighted_ids: tuple[str, ...]
    answer_display: int | None

    @model_validator(mode="after")
    def _check_invariants(self) -> "SceneState":
        # Invariante 1: IDs únicos; cada peça aparece exatamente uma vez em um grupo ou disponível.
        piece_ids = [p.id for p in self.pieces]
        if len(set(piece_ids)) != len(piece_ids):
            raise ValueError("duplicate piece id in pieces")
        group_ids = [g.id for g in self.groups]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("duplicate group id")
        located = [pid for g in self.groups for pid in g.piece_ids] + list(self.available_piece_ids)
        if len(set(located)) != len(located):
            raise ValueError("piece located more than once")
        if set(located) != set(piece_ids):
            raise ValueError("every piece must be in exactly one location")
        # Invariante 2: total de peças = dividendo; grupos = divisor.
        if len(piece_ids) != self.task.dividend:
            raise ValueError("piece count must equal dividend")
        if len(self.groups) != self.task.divisor:
            raise ValueError("group count must equal divisor")
        return self


def initial_scene(
    task: TaskSpec,
    *,
    scene_id: str,
    attempt_id: str,
    origin: PieceOrigin = "content",
) -> SceneState:
    pieces = tuple(Piece(id=f"piece-{i:02d}", origin=origin) for i in range(1, task.dividend + 1))
    return SceneState(
        scene_id=scene_id,
        scene_revision=0,
        attempt_id=attempt_id,
        task=task,
        projection="perspective",
        interaction="learner",
        groups=tuple(Group(id=f"group-{i}", piece_ids=()) for i in range(1, task.divisor + 1)),
        available_piece_ids=tuple(p.id for p in pieces),
        pieces=pieces,
        highlighted_ids=(),
        answer_display=None,
    )


def _replace(scene: SceneState, **update: object) -> SceneState:
    """Cópia com revalidação (model_copy não valida)."""
    return SceneState.model_validate({**dict(scene), **update})


def _location_of(scene: SceneState, piece_id: str) -> str:
    if piece_id in scene.available_piece_ids:
        return AVAILABLE
    for g in scene.groups:
        if piece_id in g.piece_ids:
            return g.id
    raise DomainError("INVALID_SCENE", f"unknown piece {piece_id}")


def move_piece(
    scene: SceneState, piece_id: str, from_location: str, to_location: str
) -> SceneState:
    """Move uma peça entre "available" e grupos. Devolve nova cena; não incrementa scene_revision."""
    known = {AVAILABLE} | {g.id for g in scene.groups}
    if piece_id not in {p.id for p in scene.pieces}:
        raise DomainError("INVALID_SCENE", f"unknown piece {piece_id}")
    if from_location not in known or to_location not in known:
        raise DomainError("INVALID_SCENE", "unknown location")
    if _location_of(scene, piece_id) != from_location:
        raise DomainError("INVALID_SCENE", f"piece {piece_id} is not at {from_location}")
    if from_location == to_location:
        raise DomainError("NO_OP", "from and to are the same")

    available = scene.available_piece_ids
    groups = []
    for g in scene.groups:
        ids = g.piece_ids
        if g.id == from_location:
            ids = tuple(i for i in ids if i != piece_id)
        if g.id == to_location:
            ids = (*ids, piece_id)
        groups.append(Group(id=g.id, piece_ids=ids))
    if from_location == AVAILABLE:
        available = tuple(i for i in available if i != piece_id)
    if to_location == AVAILABLE:
        available = (*available, piece_id)
    return _replace(scene, groups=tuple(groups), available_piece_ids=available)


def set_projection(scene: SceneState, projection: Projection) -> SceneState:
    return _replace(scene, projection=projection)
