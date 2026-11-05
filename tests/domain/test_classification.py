import pytest
from app.domain.division.assistance import AssistanceLedger, apply_help_effect
from app.domain.division.classification import (
    ExplanationResult,
    classify_attempt,
    evaluate_artifact_explanation,
)
from app.domain.division.observation import NotebookObservation, verify_observation
from app.domain.division.task import TaskSpec
from helpers import T24_4, load_obs, load_raw, obs_with
from pydantic import ValidationError

S = ExplanationResult(rating="sufficient", modality="text", evidence="5 grupos de 4 = 20")
P = ExplanationResult(rating="partial", modality="text", evidence="falou só o total")
U = ExplanationResult(rating="unclear", modality="text", evidence="não relacionou")


def test_ac22_applied_without_item_help():
    paper = AssistanceLedger(resources=frozenset({"paper"}))
    assert classify_attempt(True, S, paper) == "applied_without_item_help"


def test_accessibility_and_procedural_keep_without_item_help():
    ledger = apply_help_effect(AssistanceLedger(), "procedural", "onde envio?")
    ledger = apply_help_effect(ledger, "accessibility", "fonte maior")
    assert classify_attempt(True, S, ledger) == "applied_without_item_help"


def test_ac23_answer_alone_is_partial_evidence():
    assert classify_attempt(True, None, AssistanceLedger()) == "answer_correct_evidence_partial"


@pytest.mark.parametrize("explanation", [P, U])
def test_partial_or_unclear_explanation_is_partial_evidence(explanation):
    assert classify_attempt(True, explanation, AssistanceLedger()) == (
        "answer_correct_evidence_partial"
    )


def test_ac24_objects_make_it_supported():
    ledger = apply_help_effect(AssistanceLedger(), "virtual_objects", "pediu objetos")
    assert classify_attempt(True, S, ledger) == "applied_with_support"


def test_reference_model_makes_it_supported():
    ledger = apply_help_effect(AssistanceLedger(), "reference_model", "pediu modelo")
    assert classify_attempt(True, S, ledger) == "applied_with_support"


def test_counting_aid_is_a_conceptual_resource():
    ledger = AssistanceLedger(resources=frozenset({"counting_aid"}))
    assert classify_attempt(True, S, ledger) == "applied_with_support"


@pytest.mark.parametrize("kind", ["prompt", "visual_hint", "worked_step", "alternate_strategy"])
def test_conceptual_help_makes_it_supported(kind):
    ledger = apply_help_effect(AssistanceLedger(), kind, "r")
    assert classify_attempt(True, S, ledger) == "applied_with_support"


def test_text_rephrase_is_not_a_conceptual_resource():
    ledger = AssistanceLedger(resources=frozenset({"paper", "text_rephrase"}))
    assert classify_attempt(True, S, ledger) == "applied_without_item_help"


def test_spec_wins_support_needs_sufficient_explanation():
    # Spec "Classificação final": applied_with_support exige explicação suficiente;
    # resposta correta com explicação parcial/ausente é answer_correct_evidence_partial.
    ledger = apply_help_effect(AssistanceLedger(), "worked_step", "r")
    assert classify_attempt(True, None, ledger) == "answer_correct_evidence_partial"
    assert classify_attempt(True, P, ledger) == "answer_correct_evidence_partial"


def test_wrong_answer_needs_review_even_with_help():
    ledger = apply_help_effect(AssistanceLedger(), "worked_step", "r")
    assert classify_attempt(False, S, AssistanceLedger()) == "needs_review"
    assert classify_attempt(False, None, ledger) == "needs_review"


def test_no_answer_is_not_attempted():
    assert classify_attempt(None, None, AssistanceLedger()) == "not_attempted"
    assert classify_attempt(None, S, AssistanceLedger()) == "not_attempted"


def test_disputed_evidence_is_inconclusive_over_everything():
    assert classify_attempt(True, S, AssistanceLedger(), evidence_disputed=True) == "inconclusive"
    assert classify_attempt(False, S, AssistanceLedger(), evidence_disputed=True) == "inconclusive"
    assert classify_attempt(None, None, AssistanceLedger(), evidence_disputed=True) == (
        "inconclusive"
    )


def test_evidence_disputed_is_keyword_only():
    with pytest.raises(TypeError):
        classify_attempt(True, S, AssistanceLedger(), True)  # type: ignore[misc]


def test_explanation_result_is_strict_frozen():
    with pytest.raises(ValidationError):
        ExplanationResult(rating="great", modality="text", evidence="x")
    with pytest.raises(ValidationError):
        ExplanationResult(rating="sufficient", modality="video", evidence="x")
    with pytest.raises(ValidationError):
        ExplanationResult(rating="sufficient", modality="text", evidence="x", extra=1)
    with pytest.raises(ValidationError):
        S.rating = "partial"


def _expression_only(**expression) -> NotebookObservation:
    raw = load_raw("observacao-corrigida")
    raw["groups"] = []
    raw["expression"].update(expression)
    return NotebookObservation.model_validate(raw)


def test_artifact_explanation_corrected_drawing_is_sufficient():
    v = verify_observation(T24_4, 6, load_obs("observacao-corrigida"), [])
    result = evaluate_artifact_explanation(T24_4, v)
    assert result.rating == "sufficient" and result.modality == "artifact"
    assert result.evidence == "4 grupos de 6 = 24"


def test_artifact_explanation_ambiguous_is_unclear():
    v = verify_observation(T24_4, 6, load_obs("observacao-ambigua"), [])
    assert v.status == "inconclusive"
    result = evaluate_artifact_explanation(T24_4, v)
    assert result.rating == "unclear" and result.modality == "artifact"


def test_artifact_explanation_wrong_drawing_is_unclear_without_leaking_quotient():
    v = verify_observation(T24_4, 6, load_obs("observacao-5-5-5-5"), [])
    assert v.status == "inconsistent"
    result = evaluate_artifact_explanation(T24_4, v)
    assert result.rating == "unclear"
    assert result.evidence == "desenho não mostra grupos iguais que somem o total"


def test_artifact_explanation_correct_drawing_with_wrong_written_answer_is_faithful():
    v = verify_observation(T24_4, 6, obs_with(counts=[6, 6, 6, 6], answer=5), [])
    assert v.status == "inconsistent" and v.issues == ("WRITTEN_ANSWER_MISMATCH",)
    result = evaluate_artifact_explanation(T24_4, v)
    assert result.rating == "unclear"
    assert result.evidence == (
        "desenho mostra 4 grupos de 6 = 24, mas a resposta ou expressão escrita não confere"
    )


def test_artifact_explanation_expression_only_is_partial():
    v = verify_observation(T24_4, 6, _expression_only(), [])
    assert v.status == "consistent" and "observed_group_counts" not in v.facts
    result = evaluate_artifact_explanation(T24_4, v)
    assert result.rating == "partial" and result.modality == "artifact"
    assert result.evidence == "4 grupos de 6 = 24"


def test_artifact_explanation_expression_only_wrong_answer_is_unclear_and_does_not_leak():
    v = verify_observation(T24_4, 6, _expression_only(answer=5), [])
    assert "WRITTEN_ANSWER_MISMATCH" in v.issues
    result = evaluate_artifact_explanation(T24_4, v)
    assert result.rating == "unclear"
    assert result.evidence == "expressão escrita não confere com a tarefa"


def test_artifact_explanation_expression_mismatch_is_unclear():
    v = verify_observation(T24_4, 6, _expression_only(dividend=20, divisor=5, answer=4), [])
    assert "EXPRESSION_MISMATCH" in v.issues
    assert evaluate_artifact_explanation(T24_4, v).rating == "unclear"


def test_artifact_explanation_expression_without_answer_is_unclear():
    v = verify_observation(T24_4, 6, _expression_only(answer=None), [])
    assert v.status == "inconclusive"
    assert evaluate_artifact_explanation(T24_4, v).rating == "unclear"


def test_artifact_explanation_20_div_5_analogue_is_sufficient():
    task = TaskSpec(dividend=20, divisor=5, unit="peças")
    obs = obs_with(counts=[4, 4, 4, 4, 4], dividend=20, divisor=5, answer=4)
    v = verify_observation(task, 4, obs, [])
    result = evaluate_artifact_explanation(task, v)
    assert result.rating == "sufficient"
    assert result.evidence == "5 grupos de 4 = 20"
