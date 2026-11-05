import pytest
from app.domain.division.distribution import (
    DistributionVerification,
    InitialIntervention,
    select_initial_intervention,
    verify_distribution,
)
from helpers import T24_4, scene_with_counts
from pydantic import ValidationError


def _sv(counts):
    scene = scene_with_counts(T24_4, counts)
    return scene, verify_distribution(T24_4, scene)


def test_ac05_unequal_7_5_6_6():
    s = scene_with_counts(T24_4, [7, 5, 6, 6])
    v = verify_distribution(T24_4, s)
    assert (v.groups_equal, v.all_assigned, v.valid_partition, v.assigned_total) == (
        False,
        True,
        False,
        24,
    )
    assert v.group_counts == (7, 5, 6, 6)
    i = select_initial_intervention(s, v)
    assert i.code == "compare_groups" and set(i.target_ids) == {"group-1", "group-2"}


def test_ac06_equal_5_5_5_5_with_4_available():
    s = scene_with_counts(T24_4, [5, 5, 5, 5])
    v = verify_distribution(T24_4, s)
    assert (v.groups_equal, v.all_assigned, v.available_total) == (True, False, 4)
    i = select_initial_intervention(s, v)
    assert i.code == "check_total_use" and len(i.target_ids) == 4
    assert i.target_ids == s.available_piece_ids


def test_unequal_and_incomplete_prefers_compare():  # Review Focus 2 / D6
    i = select_initial_intervention(*_sv([6, 6, 6, 2]))
    assert i.code == "compare_groups" and set(i.target_ids) == {"group-1", "group-4"}


def test_compare_targets_in_group_order_with_ties_first():
    # maior no grupo 3, menor no grupo 2 (primeiro entre empates): ordem de grupo
    i = select_initial_intervention(*_sv([6, 4, 8, 4]))
    assert i.target_ids == ("group-2", "group-3")
    # empates no maior e no menor: o primeiro de cada
    i = select_initial_intervention(*_sv([7, 5, 7, 5]))
    assert i.target_ids == ("group-1", "group-2")


def test_valid_and_empty():
    scene, v = _sv([6, 6, 6, 6])
    assert v.valid_partition is True and v.available_total == 0
    assert select_initial_intervention(scene, v) == InitialIntervention(code=None, target_ids=())
    scene, v = _sv([0, 0, 0, 0])
    assert (v.groups_equal, v.all_assigned, v.valid_partition) == (True, False, False)
    i = select_initial_intervention(scene, v)
    assert i.code == "offer_guided_round" and i.target_ids == ()


def test_verification_does_not_mutate_scene():
    scene = scene_with_counts(T24_4, [7, 5, 6, 6])
    before = scene.model_copy(deep=True)
    v = verify_distribution(T24_4, scene)
    select_initial_intervention(scene, v)
    assert scene == before


def test_results_are_frozen_and_strict():
    _, v = _sv([6, 6, 6, 6])
    with pytest.raises(ValidationError):
        v.assigned_total = 1
    with pytest.raises(ValidationError):
        DistributionVerification(
            group_counts=(6.0, 6, 6, 6),
            assigned_total=24,
            available_total=0,
            groups_equal=True,
            all_assigned=True,
            valid_partition=True,
        )
    with pytest.raises(ValidationError):
        InitialIntervention(code="other", target_ids=())
    with pytest.raises(ValidationError):
        InitialIntervention(code=None, target_ids=(), extra=1)
