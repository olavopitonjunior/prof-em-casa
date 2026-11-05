from pathlib import Path

import pytest
from app.domain.division.errors import DomainError
from app.domain.division.scene import SceneState, initial_scene, move_piece, set_projection
from helpers import T24_4, scene_with_counts
from pydantic import ValidationError

FIXTURE = Path(__file__).parent.parent / "fixtures" / "cena-foto-5-5-5-5.json"


def test_initial_scene_24_4():
    s = initial_scene(T24_4, scene_id="s", attempt_id="a")
    assert len(s.pieces) == 24 and len(s.groups) == 4 and len(s.available_piece_ids) == 24
    assert s.pieces[0].id == "piece-01" and s.pieces[-1].id == "piece-24"
    assert [g.id for g in s.groups] == ["group-1", "group-2", "group-3", "group-4"]
    assert s.answer_display is None and s.scene_revision == 0
    assert {p.origin for p in s.pieces} == {"content"}


def test_initial_scene_origin():
    s = initial_scene(T24_4, scene_id="s", attempt_id="a", origin="task_derived")
    assert {p.origin for p in s.pieces} == {"task_derived"}


def test_fixture_scene_satisfies_invariants():
    s = SceneState.model_validate_json(FIXTURE.read_text())
    assert s.scene_revision == 9 and len(s.available_piece_ids) == 4


def _fixture_dict() -> dict:
    return SceneState.model_validate_json(FIXTURE.read_text()).model_dump(mode="json")


@pytest.mark.parametrize("mutate", ["drop_piece", "duplicate_piece", "extra_group"])
def test_invariant_violations_rejected(mutate):
    d = _fixture_dict()
    if mutate == "drop_piece":
        d["available_piece_ids"].pop()  # peça some das localizações
    elif mutate == "duplicate_piece":
        d["available_piece_ids"][0] = d["groups"][0]["piece_ids"][0]  # aparece 2x
    else:
        d["groups"].append({"id": "group-5", "piece_ids": []})
    with pytest.raises(ValidationError):
        SceneState.model_validate(d)


def test_piece_count_must_equal_dividend():
    d = _fixture_dict()
    d["pieces"].pop()
    d["available_piece_ids"].pop()
    with pytest.raises(ValidationError):
        SceneState.model_validate(d)


def test_duplicate_piece_definition_rejected():
    d = _fixture_dict()
    d["pieces"][1]["id"] = d["pieces"][0]["id"]
    with pytest.raises(ValidationError):
        SceneState.model_validate(d)


def test_extra_fields_forbidden_and_frozen():
    d = _fixture_dict()
    d["surprise"] = 1
    with pytest.raises(ValidationError):
        SceneState.model_validate(d)
    s = initial_scene(T24_4, scene_id="s", attempt_id="a")
    with pytest.raises(ValidationError):
        s.scene_revision = 3


def test_move_and_errors_keep_input_intact():
    s = initial_scene(T24_4, scene_id="s", attempt_id="a")
    s2 = move_piece(s, "piece-01", "available", "group-1")
    assert s2.groups[0].piece_ids == ("piece-01",) and "piece-01" not in s2.available_piece_ids
    assert s2.scene_revision == s.scene_revision
    assert len(s.available_piece_ids) == 24 and s.groups[0].piece_ids == ()
    for args, code in [
        (("piece-99", "available", "group-1"), "INVALID_SCENE"),
        (("piece-01", "available", "group-2"), "INVALID_SCENE"),  # origem divergente em s2
        (("piece-02", "available", "group-9"), "INVALID_SCENE"),
        (("piece-02", "group-9", "group-1"), "INVALID_SCENE"),
        (("piece-02", "available", "available"), "NO_OP"),
        (("piece-01", "group-1", "group-1"), "NO_OP"),
    ]:
        with pytest.raises(DomainError) as e:
            move_piece(s2, *args)
        assert e.value.code == code
    assert s2.groups[0].piece_ids == ("piece-01",)  # sem mutação parcial


def test_move_between_groups_and_back():
    s = initial_scene(T24_4, scene_id="s", attempt_id="a")
    s = move_piece(s, "piece-03", "available", "group-2")
    s = move_piece(s, "piece-03", "group-2", "group-4")
    assert s.groups[1].piece_ids == () and s.groups[3].piece_ids == ("piece-03",)
    s = move_piece(s, "piece-03", "group-4", "available")
    assert "piece-03" in s.available_piece_ids and s.groups[3].piece_ids == ()
    assert len(s.available_piece_ids) == 24


def test_projection_change_preserves_ids_and_counts():  # AC-09 (domínio)
    s = initial_scene(T24_4, scene_id="s", attempt_id="a")
    s2 = move_piece(s, "piece-01", "available", "group-1")
    s3 = set_projection(s2, "schematic")
    assert s3.projection == "schematic"
    assert [g.piece_ids for g in s3.groups] == [g.piece_ids for g in s2.groups]
    assert s3.available_piece_ids == s2.available_piece_ids
    assert s3.pieces == s2.pieces and s3.scene_revision == s2.scene_revision


def test_set_projection_rejects_unknown_projection():
    s = initial_scene(T24_4, scene_id="s", attempt_id="a")
    with pytest.raises(ValidationError):
        set_projection(s, "isometric")  # type: ignore[arg-type]


def test_scene_with_counts_helper():
    s = scene_with_counts(T24_4, [5, 5, 5, 5])
    assert [len(g.piece_ids) for g in s.groups] == [5, 5, 5, 5]
    assert s.available_piece_ids == ("piece-21", "piece-22", "piece-23", "piece-24")


@pytest.mark.parametrize("field", ["scene_revision", "answer_display"])
@pytest.mark.parametrize("bad", [True, False, 5.0, 6.5, -1, "3"])
def test_scene_ints_are_strict_and_non_negative(field, bad):
    d = _fixture_dict()
    d[field] = bad
    with pytest.raises(ValidationError):
        SceneState.model_validate(d)


def test_scene_ints_accept_valid_values():
    d = _fixture_dict()
    d["scene_revision"], d["answer_display"] = 0, 0
    s = SceneState.model_validate(d)
    assert s.scene_revision == 0 and s.answer_display == 0
