import json
from pathlib import Path

from app.domain.division.observation import NotebookObservation
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

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_raw(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def load_obs(name: str) -> NotebookObservation:
    return NotebookObservation.model_validate(load_raw(name))


def obs_with(base: str = "observacao-5-5-5-5", *, counts=None, **expression) -> NotebookObservation:
    raw = load_raw(base)
    if counts is not None:
        template = raw["groups"][0]
        raw["groups"] = [
            {**template, "group_id": f"photo-group-{i + 1}", "count": c}
            for i, c in enumerate(counts)
        ]
    raw["expression"].update(expression)
    return NotebookObservation.model_validate(raw)
