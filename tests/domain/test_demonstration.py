import pytest
from app.domain.division.demonstration import (
    DemoStep,
    apply_demo_step,
    completed_rounds,
    demo_steps,
)
from app.domain.division.errors import DomainError
from app.domain.division.scene import initial_scene
from helpers import T12_4
from pydantic import ValidationError


def _demo_scene():
    return initial_scene(T12_4, scene_id="demo", attempt_id="a-demo")


def _apply_first(n: int):
    s = _demo_scene()
    for st in demo_steps(T12_4, rounds=3)[:n]:
        s = apply_demo_step(s, st)
    return s


def test_ac03_full_demo():
    steps = demo_steps(T12_4, rounds=3)
    assert len(steps) == 12 and steps[0].step_id == "r1-g1"
    s = _demo_scene()
    for st in steps:
        s = apply_demo_step(s, st)
    assert [len(g.piece_ids) for g in s.groups] == [3, 3, 3, 3] and s.available_piece_ids == ()
    assert len({p for g in s.groups for p in g.piece_ids}) == 12  # sem duplicar
    assert completed_rounds(s, T12_4) == 3


def test_steps_are_stable_and_ordered():
    steps = demo_steps(T12_4, rounds=3)
    assert [st.step_id for st in steps[:5]] == ["r1-g1", "r1-g2", "r1-g3", "r1-g4", "r2-g1"]
    assert steps[0] == DemoStep(step_id="r1-g1", round=1, piece_id="piece-01", to_group="group-1")
    assert steps[5] == DemoStep(step_id="r2-g2", round=2, piece_id="piece-06", to_group="group-2")
    assert steps[-1].piece_id == "piece-12" and steps[-1].to_group == "group-4"
    assert len({st.piece_id for st in steps}) == 12
    assert demo_steps(T12_4, rounds=3) == steps  # pura


def test_partial_rounds_only_prefix():
    assert len(demo_steps(T12_4, rounds=1)) == 4


def test_rounds_counted_midway():
    s = _apply_first(6)  # [2,2,1,1]
    assert [len(g.piece_ids) for g in s.groups] == [2, 2, 1, 1]
    assert completed_rounds(s, T12_4) == 1


def test_rounds_counted_edges():
    assert completed_rounds(_demo_scene(), T12_4) == 0
    assert completed_rounds(_apply_first(4), T12_4) == 1
    assert completed_rounds(_apply_first(3), T12_4) == 0


def test_reapplying_step_rejected():
    steps = demo_steps(T12_4, rounds=3)
    s = apply_demo_step(_demo_scene(), steps[0])
    with pytest.raises(DomainError) as e:
        apply_demo_step(s, steps[0])
    assert e.value.code == "INVALID_SCENE"


@pytest.mark.parametrize("rounds", [0, -1, 4, 3.0, True])
def test_invalid_rounds_rejected(rounds):
    with pytest.raises(DomainError) as e:
        demo_steps(T12_4, rounds=rounds)
    assert e.value.code == "INVALID_PAYLOAD"


def test_demostep_strict_and_frozen():
    with pytest.raises(ValidationError):
        DemoStep(step_id="r1-g1", round=1.0, piece_id="piece-01", to_group="group-1")
    with pytest.raises(ValidationError):
        DemoStep(step_id="r1-g1", round=True, piece_id="piece-01", to_group="group-1")
    with pytest.raises(ValidationError):
        DemoStep(step_id="r1-g1", round=1, piece_id="piece-01", to_group="group-1", extra=1)
    st = demo_steps(T12_4, rounds=1)[0]
    with pytest.raises(ValidationError):
        st.round = 2
