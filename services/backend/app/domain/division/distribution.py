from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt

from app.domain.division.scene import SceneState
from app.domain.division.task import TaskSpec


class DistributionVerification(BaseModel):
    """Fatos sobre a distribuição atual (Spec Parte I §5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_counts: tuple[StrictInt, ...]
    assigned_total: StrictInt
    available_total: StrictInt
    groups_equal: bool
    all_assigned: bool
    valid_partition: bool


class InitialIntervention(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Literal["compare_groups", "check_total_use", "offer_guided_round"] | None
    target_ids: tuple[str, ...]


def verify_distribution(task: TaskSpec, scene: SceneState) -> DistributionVerification:
    """Função pura: não altera a cena."""
    counts = tuple(len(g.piece_ids) for g in scene.groups)
    assigned = sum(counts)
    available = len(scene.available_piece_ids)
    groups_equal = len(set(counts)) <= 1
    all_assigned = available == 0
    valid = (
        len(counts) == task.divisor and groups_equal and all_assigned and assigned == task.dividend
    )
    return DistributionVerification(
        group_counts=counts,
        assigned_total=assigned,
        available_total=available,
        groups_equal=groups_equal,
        all_assigned=all_assigned,
        valid_partition=valid,
    )


def select_initial_intervention(
    scene: SceneState, verification: DistributionVerification
) -> InitialIntervention:
    """Intervenção inicial (Spec Parte I §5), na ordem: vazia, válida, desiguais, uso do total."""
    if verification.assigned_total == 0:
        return InitialIntervention(code="offer_guided_round", target_ids=())
    if verification.valid_partition:
        return InitialIntervention(code=None, target_ids=())
    if not verification.groups_equal:
        counts = verification.group_counts
        # index() devolve o primeiro em caso de empate.
        hi = counts.index(max(counts))
        lo = counts.index(min(counts))
        targets = tuple(scene.groups[i].id for i in sorted({hi, lo}))
        return InitialIntervention(code="compare_groups", target_ids=targets)
    if verification.available_total > 0:
        return InitialIntervention(
            code="check_total_use", target_ids=tuple(scene.available_piece_ids)
        )
    return InitialIntervention(code=None, target_ids=())
