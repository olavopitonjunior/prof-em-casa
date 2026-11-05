import json
from pathlib import Path

import pytest
from app.domain.division.errors import DomainError
from app.domain.division.observation import (
    Clarification,
    NotebookObservation,
    ReconstructionUnavailable,
    Verification,
    build_reconstruction,
    validate_observation,
    verify_observation,
)
from app.domain.division.scene import SceneState
from app.domain.division.task import TaskSpec
from helpers import T24_4
from pydantic import ValidationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ids = {"scene_id": "scene-guided-001", "attempt_id": "attempt-guided-001", "scene_revision": 9}
T20_5 = TaskSpec(dividend=20, divisor=5, unit="peças")


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


def _pieces(scene: SceneState, group_id: str):
    by_id = {p.id: p for p in scene.pieces}
    group = next(g for g in scene.groups if g.id == group_id)
    return [by_id[i] for i in group.piece_ids]


def test_error_fixture_matches_spec_example():
    v = verify_observation(T24_4, 6, load_obs("observacao-5-5-5-5"), [])
    assert v.observation_id == "obs-001"
    assert v.status == "inconsistent" and v.reconstruction_allowed
    assert v.facts == {
        "task_total": 24,
        "task_groups": 4,
        "observed_group_counts": [5, 5, 5, 5],
        "represented_total": 20,
        "groups_equal": True,
        "not_represented": 4,
        "written_answer": 5,
    }
    assert set(v.issues) == {"TOTAL_MISMATCH", "WRITTEN_ANSWER_MISMATCH"}
    assert 6 not in v.facts.values()  # quociente privado não vaza para os fatos


def test_reconstruction_equals_fixture_scene():
    s = build_reconstruction(T24_4, load_obs("observacao-5-5-5-5"), [], **ids)
    expected = SceneState.model_validate_json(
        (FIXTURES / "cena-foto-5-5-5-5.json").read_text(encoding="utf-8")
    )
    assert s == expected


def test_ambiguous_is_inconclusive_and_not_reconstructable():
    v = verify_observation(T24_4, 6, load_obs("observacao-ambigua"), [])
    assert v.status == "inconclusive"
    assert not v.reconstruction_allowed
    assert "not_represented" not in v.facts and "represented_total" not in v.facts
    assert v.facts["observed_group_counts"] == [5, 5, None, 5]
    r = build_reconstruction(T24_4, load_obs("observacao-ambigua"), [], **ids)
    assert isinstance(r, ReconstructionUnavailable)


def test_clarified_count_is_learner_report():  # AC-18 (domínio)
    c = [Clarification(field_path="/groups/2/count", value=5)]
    obs = load_obs("observacao-ambigua")
    s = build_reconstruction(T24_4, obs, c, **ids)
    assert isinstance(s, SceneState)
    assert {p.origin for p in _pieces(s, "group-3")} == {"learner_report"}
    assert {p.origin for p in _pieces(s, "group-1")} == {"image"}
    assert {p.observation_ref for p in _pieces(s, "group-3")} == {"obs-002/photo-group-3"}


def test_clarified_counts_count_in_verification_and_are_listed():
    obs = load_obs("observacao-ambigua")
    v = verify_observation(T24_4, 6, obs, [Clarification(field_path="/groups/2/count", value=5)])
    assert v.status == "inconsistent" and v.reconstruction_allowed
    assert v.facts["observed_group_counts"] == [5, 5, 5, 5]
    assert v.facts["represented_total"] == 20
    assert v.facts["learner_reported_groups"] == ["photo-group-3"]


def test_clarification_changing_the_total():
    obs = load_obs("observacao-ambigua")
    v = verify_observation(T24_4, 6, obs, [Clarification(field_path="/groups/2/count", value=4)])
    assert v.facts["represented_total"] == 19
    assert v.facts["groups_equal"] is False
    assert {"TOTAL_MISMATCH", "GROUPS_UNEQUAL"} <= set(v.issues)


@pytest.mark.parametrize(
    "path", ["/groups/0/count", "/groups/9/count", "/groups/2/bbox", "/expression/answer", "x"]
)
def test_clarification_for_non_ambiguous_or_absent_path_is_rejected(path):
    obs = load_obs("observacao-ambigua")
    c = [Clarification(field_path=path, value=5)]
    with pytest.raises(DomainError) as e:
        verify_observation(T24_4, 6, obs, c)
    assert e.value.code == "INVALID_PAYLOAD"
    with pytest.raises(DomainError):
        build_reconstruction(T24_4, obs, c, **ids)


def test_duplicate_clarification_is_rejected():
    c = [
        Clarification(field_path="/groups/2/count", value=5),
        Clarification(field_path="/groups/2/count", value=4),
    ]
    with pytest.raises(DomainError) as e:
        verify_observation(T24_4, 6, load_obs("observacao-ambigua"), c)
    assert e.value.code == "INVALID_PAYLOAD"


def test_clarification_value_is_strict_and_bounded():
    for bad in (5.0, True, -1, 61, "5"):
        with pytest.raises(ValidationError):
            Clarification(field_path="/groups/2/count", value=bad)
    assert Clarification(field_path="/groups/2/count", value=5).provenance == "learner_report"


def test_corrected_is_consistent():
    v = verify_observation(T24_4, 6, load_obs("observacao-corrigida"), [])
    assert v.status == "consistent" and v.issues == () and v.reconstruction_allowed
    assert v.facts["represented_total"] == 24 and v.facts["not_represented"] == 0


def test_excess_drawn():  # Review Focus 4
    v = verify_observation(T24_4, 6, obs_with(counts=[7, 7, 7, 7]), [])
    assert v.status == "inconsistent"
    assert v.facts["excess_represented"] == 4
    assert "not_represented" not in v.facts
    assert "EXCESS_REPRESENTED" in v.issues
    assert v.reconstruction_allowed is False
    r = build_reconstruction(T24_4, obs_with(counts=[7, 7, 7, 7]), [], **ids)
    assert isinstance(r, ReconstructionUnavailable)
    assert not any(x < 0 for x in v.facts.values() if isinstance(x, int))


def test_wrong_number_of_groups():
    obs = obs_with(counts=[6, 6, 6])
    v = verify_observation(T24_4, 6, obs, [])
    assert "GROUP_COUNT_MISMATCH" in v.issues and not v.reconstruction_allowed
    assert isinstance(build_reconstruction(T24_4, obs, [], **ids), ReconstructionUnavailable)


def test_unequal_groups_within_total():
    obs = obs_with(counts=[7, 5, 6, 6])
    v = verify_observation(T24_4, 6, obs, [])
    assert "GROUPS_UNEQUAL" in v.issues and "TOTAL_MISMATCH" not in v.issues
    assert v.facts["groups_equal"] is False and v.reconstruction_allowed


def test_expression_mismatch_with_correct_groups():
    v = verify_observation(T24_4, 6, obs_with(counts=[6, 6, 6, 6], dividend=20), [])
    assert v.status == "inconsistent"
    assert "EXPRESSION_MISMATCH" in v.issues and "TOTAL_MISMATCH" not in v.issues


def test_reconstruction_of_other_task_and_partial_drawing():
    obs = obs_with(counts=[3, 3, 3, 3, 3])
    s = build_reconstruction(T20_5, obs, [], **ids)
    assert isinstance(s, SceneState)
    assert [len(g.piece_ids) for g in s.groups] == [3] * 5
    assert len(s.available_piece_ids) == 5
    assert {p.origin for p in s.pieces if p.id in s.available_piece_ids} == {"task_derived"}
    assert all(p.observation_ref is None for p in s.pieces if p.origin == "task_derived")


def test_expression_only():
    raw = load_raw("observacao-5-5-5-5")
    raw["groups"] = []
    obs = NotebookObservation.model_validate(raw)
    v = verify_observation(T24_4, 6, obs, [])
    assert v.reconstruction_allowed is False
    assert v.status == "inconsistent" and v.issues == ("WRITTEN_ANSWER_MISMATCH",)
    for key in ("represented_total", "not_represented", "observed_group_counts", "groups_equal"):
        assert key not in v.facts
    assert v.facts == {"task_total": 24, "task_groups": 4, "written_answer": 5}
    assert isinstance(build_reconstruction(T24_4, obs, [], **ids), ReconstructionUnavailable)


def test_expression_only_correct_and_unreadable():
    raw = load_raw("observacao-corrigida")
    raw["groups"] = []
    assert verify_observation(T24_4, 6, NotebookObservation.model_validate(raw), []).status == (
        "consistent"
    )
    raw["expression"].update(answer=None, uncertain=True)
    raw["ambiguities"] = [{"field_path": "/expression/answer", "reason": "illegible"}]
    raw["status"] = "needs_clarification"
    v = verify_observation(T24_4, 6, NotebookObservation.model_validate(raw), [])
    assert v.status == "inconclusive" and "written_answer" not in v.facts


def test_unresolved_non_count_ambiguity_keeps_inconclusive():
    raw = load_raw("observacao-corrigida")
    raw["status"] = "needs_clarification"
    raw["ambiguities"] = [{"field_path": "/expression/answer", "reason": "illegible"}]
    v = verify_observation(T24_4, 6, NotebookObservation.model_validate(raw), [])
    assert v.status == "inconclusive"


def test_uncertain_count_without_clarification_is_unusable():
    raw = load_raw("observacao-ambigua")
    raw["groups"][2].update(count=5)  # tem valor, mas uncertain=True
    v = verify_observation(T24_4, 6, NotebookObservation.model_validate(raw), [])
    assert v.status == "inconclusive" and not v.reconstruction_allowed


def test_verification_model_is_frozen_and_strict():
    v = verify_observation(T24_4, 6, load_obs("observacao-5-5-5-5"), [])
    assert isinstance(v, Verification)
    with pytest.raises(ValidationError):
        v.status = "consistent"


def test_extra_checks():
    ok = load_obs("observacao-5-5-5-5")
    assert validate_observation(ok) == []
    assert validate_observation(load_obs("observacao-ambigua")) == []

    raw = load_raw("observacao-5-5-5-5")
    raw["groups"][0]["bbox"]["x"] = 0.9
    assert validate_observation(NotebookObservation.model_validate(raw)) == ["BBOX_OUT_OF_BOUNDS"]

    raw = load_raw("observacao-5-5-5-5")
    raw["expression"]["bbox"]["y"] = 0.95
    assert validate_observation(NotebookObservation.model_validate(raw)) == ["BBOX_OUT_OF_BOUNDS"]

    raw = load_raw("observacao-5-5-5-5")
    raw["groups"][1]["group_id"] = "photo-group-1"
    assert validate_observation(NotebookObservation.model_validate(raw)) == ["DUPLICATE_GROUP_ID"]

    raw = load_raw("observacao-ambigua")
    raw["ambiguities"][0]["field_path"] = "/groups/7/count"
    codes = validate_observation(NotebookObservation.model_validate(raw))
    assert "DANGLING_AMBIGUITY_PATH" in codes and "UNCERTAIN_WITHOUT_AMBIGUITY" in codes

    raw = load_raw("observacao-5-5-5-5")
    raw["groups"][0]["uncertain"] = True
    assert validate_observation(NotebookObservation.model_validate(raw)) == [
        "UNCERTAIN_WITHOUT_AMBIGUITY"
    ]


def test_expression_only_without_written_answer_is_inconclusive():
    raw = load_raw("observacao-corrigida")
    raw["groups"] = []
    raw["expression"]["answer"] = None
    v = verify_observation(T24_4, 6, NotebookObservation.model_validate(raw), [])
    assert v.status == "inconclusive" and v.issues == ()
    raw["expression"]["dividend"] = 20
    v = verify_observation(T24_4, 6, NotebookObservation.model_validate(raw), [])
    assert v.status == "inconsistent" and v.issues == ("EXPRESSION_MISMATCH",)
