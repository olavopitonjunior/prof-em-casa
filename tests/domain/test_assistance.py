import pytest
from app.domain.division.assistance import AssistanceLedger, apply_help_effect
from pydantic import ValidationError


def test_default_ledger_is_empty():
    ledger = AssistanceLedger()
    assert ledger.level == "none" and ledger.resources == frozenset() and ledger.reasons == ()


def test_level_is_monotonic():
    ledger = apply_help_effect(AssistanceLedger(), "worked_step", "r")
    assert apply_help_effect(ledger, "prompt", "r").level == "demonstrated"
    assert apply_help_effect(ledger, "visual_hint", "r").level == "demonstrated"


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
    assert apply_help_effect(AssistanceLedger(), kind, "r").level == level


def test_prompted_can_rise_to_demonstrated():
    ledger = apply_help_effect(AssistanceLedger(), "prompt", "dica")
    assert apply_help_effect(ledger, "alternate_strategy", "outra").level == "demonstrated"


@pytest.mark.ac("AC-24")
def test_procedural_and_accessibility_are_not_help():  # AC-24 (parte)
    ledger = apply_help_effect(AssistanceLedger(), "procedural", "onde envio?")
    ledger = apply_help_effect(ledger, "accessibility", "x")
    assert ledger.level == "none" and ledger.resources == frozenset()


@pytest.mark.parametrize(
    "kind,resource",
    [("virtual_objects", "virtual_objects"), ("reference_model", "reference_model")],
)
def test_resource_kinds_add_resource_without_raising_level(kind, resource):  # D3
    ledger = apply_help_effect(AssistanceLedger(), kind, "pediu")
    assert ledger.level == "none" and ledger.resources == frozenset({resource})


def test_resources_accumulate_and_keep_existing():
    ledger = AssistanceLedger(resources=frozenset({"paper"}))
    ledger = apply_help_effect(ledger, "virtual_objects", "a")
    ledger = apply_help_effect(ledger, "reference_model", "b")
    assert ledger.resources == frozenset({"paper", "virtual_objects", "reference_model"})


def test_every_kind_appends_its_reason():
    ledger = AssistanceLedger()
    for kind in ("procedural", "accessibility", "prompt", "virtual_objects"):
        ledger = apply_help_effect(ledger, kind, f"motivo-{kind}")
    assert ledger.reasons == (
        "motivo-procedural",
        "motivo-accessibility",
        "motivo-prompt",
        "motivo-virtual_objects",
    )


def test_apply_does_not_mutate_original():
    original = AssistanceLedger()
    apply_help_effect(original, "worked_step", "r")
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
