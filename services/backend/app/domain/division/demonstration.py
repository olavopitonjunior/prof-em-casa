from pydantic import BaseModel, ConfigDict, StrictInt

from app.domain.division.errors import DomainError
from app.domain.division.scene import AVAILABLE, SceneState, move_piece
from app.domain.division.task import TaskSpec


class DemoStep(BaseModel):
    """Um movimento atômico do roteiro da demonstração (Spec Parte I §5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str
    round: StrictInt
    piece_id: str
    to_group: str


def demo_steps(task: TaskSpec, rounds: int) -> tuple[DemoStep, ...]:
    """Roteiro puro: na rodada r, o grupo g recebe a peça de número (r-1)*D + g (ordem de id)."""
    quotient = task.dividend // task.divisor
    if type(rounds) is not int or not 1 <= rounds <= quotient:
        raise DomainError("INVALID_PAYLOAD", f"rounds must be an integer in 1..{quotient}")
    return tuple(
        DemoStep(
            step_id=f"r{r}-g{g}",
            round=r,
            piece_id=f"piece-{(r - 1) * task.divisor + g:02d}",
            to_group=f"group-{g}",
        )
        for r in range(1, rounds + 1)
        for g in range(1, task.divisor + 1)
    )


def apply_demo_step(scene: SceneState, step: DemoStep) -> SceneState:
    """Aplica um passo. Peça fora de `available` (passo repetido) levanta INVALID_SCENE."""
    return move_piece(scene, step.piece_id, AVAILABLE, step.to_group)


def completed_rounds(scene: SceneState, task: TaskSpec) -> int:
    """Rodadas completas = mínimo das contagens por grupo."""
    return min(len(g.piece_ids) for g in scene.groups)
