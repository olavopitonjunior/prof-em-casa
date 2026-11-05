import pytest
from app.domain.division.assistance import AssistanceLedger, apply_help_effect
from pydantic import ValidationError


def test_default_ledger_is_empty():
    ledger = AssistanceLedger()
    assert ledger.level == "none" and ledger.resources == frozenset()


def test_level_is_monotonic():
    ledger = apply_help_effect(AssistanceLedger(), "worked_step")
    assert apply_help_effect(ledger, "prompt").level == "demonstrated"
    assert apply_help_effect(ledger, "visual_hint").level == "demonstrated"


@pytest.mark.parametrize(
    "kind,level",
    [
        ("prompt", "prompted"),
        ("visual_hint", "prompted"),
        ("worked_step", "demonstrated"),
        ("alternate_strategy", "demonstrated"),
    ],
)
def test_conceptual_help_raises_level(kind, level):
    assert apply_help_effect(AssistanceLedger(), kind).level == level


def test_prompted_can_rise_to_demonstrated():
    ledger = apply_help_effect(AssistanceLedger(), "prompt")
    assert apply_help_effect(ledger, "alternate_strategy").level == "demonstrated"


@pytest.mark.ac("AC-24")
def test_procedural_and_accessibility_are_not_help():  # AC-24 (parte)
    ledger = apply_help_effect(AssistanceLedger(), "procedural")
    ledger = apply_help_effect(ledger, "accessibility")
    assert ledger.level == "none" and ledger.resources == frozenset()


@pytest.mark.parametrize(
    "kind,resource",
    [("virtual_objects", "virtual_objects"), ("reference_model", "reference_model")],
)
def test_resource_kinds_add_resource_without_raising_level(kind, resource):  # D3
    ledger = apply_help_effect(AssistanceLedger(), kind)
    assert ledger.level == "none" and ledger.resources == frozenset({resource})


def test_resources_accumulate_and_keep_existing():
    ledger = AssistanceLedger(resources=frozenset({"paper"}))
    ledger = apply_help_effect(ledger, "virtual_objects")
    ledger = apply_help_effect(ledger, "reference_model")
    assert ledger.resources == frozenset({"paper", "virtual_objects", "reference_model"})


def test_ledger_has_no_place_for_the_free_text_reason():
    """R28 / AC-45: o registro guarda nível e recursos, nunca o texto da criança."""
    assert set(AssistanceLedger.model_fields) == {"level", "resources"}


def test_apply_does_not_mutate_original():
    original = AssistanceLedger()
    apply_help_effect(original, "worked_step")
    assert original == AssistanceLedger()


def test_ledger_is_frozen_and_forbids_extras():
    ledger = AssistanceLedger()
    with pytest.raises(ValidationError):
        ledger.level = "prompted"
    with pytest.raises(ValidationError):
        AssistanceLedger(extra=1)
    with pytest.raises(ValidationError):
        AssistanceLedger(level="nope")
    with pytest.raises(ValidationError):
        AssistanceLedger(resources=frozenset({"calculator"}))
