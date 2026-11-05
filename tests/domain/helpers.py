from app.domain.division.scene import Group, SceneState, initial_scene
from app.domain.division.task import TaskSpec

T24_4 = TaskSpec(dividend=24, divisor=4, unit="peças")


def scene_with_counts(task: TaskSpec, counts: list[int]) -> SceneState:
    """Cena com `counts[i]` peças no grupo i+1 (peças atribuídas em ordem de id); o resto fica disponível."""
    base = initial_scene(task, scene_id="s", attempt_id="a")
    ids = [p.id for p in base.pieces]
    groups, pos = [], 0
    for g, n in zip(base.groups, counts, strict=True):
        groups.append(Group(id=g.id, piece_ids=tuple(ids[pos : pos + n])))
        pos += n
    return SceneState.model_validate(
        {**dict(base), "groups": tuple(groups), "available_piece_ids": tuple(ids[pos:])}
    )


T12_4 = TaskSpec(dividend=12, divisor=4, unit="peças")
