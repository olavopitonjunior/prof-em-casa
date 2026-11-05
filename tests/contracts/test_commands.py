import json
from typing import get_args

import pytest
from app.domain.division.assistance import HelpKind
from app.domain.division.commands import (
    ALLOWED_ACTORS,
    SCENE_COMMANDS,
    CommandEnvelope,
    CommandType,
    RequestHelpKind,
    SceneCommandEnvelope,
    parse_command,
)
from app.domain.division.errors import DomainError
from pydantic import ValidationError

BASE = {
    "schema_version": "1.0",
    "command_id": "c1",
    "session_id": "s1",
    "attempt_id": "a1",
    "expected_revision": 3,
    "type": "check_distribution",
    "payload": {},
}

# Um corpo válido por tipo (sem campos de turno/cena; o helper os acrescenta).
PAYLOADS: dict[str, dict] = {
    "confirm_source": {"analysis_id": "an1", "item_id": "demo-12-4"},
    "clarify_source": {"analysis_id": "an1", "field_path": "task.dividend", "value": 12},
    "retake_source_photo": {},
    "choose_reference_activity": {"content_version": "division-sharing-v1"},
    "run_demo_step": {"step_id": "r1-g1"},
    "finish_demonstration": {"reason": "completed"},
    "move_piece": {"piece_id": "piece-01", "from_location": "available", "to_location": "group-1"},
    "undo_move": {"target_command_id": "c0"},
    "check_distribution": {},
    "highlight_group": {"group_id": "group-1"},
    "highlight_available": {},
    "set_projection": {"projection": "top"},
    "request_help": {"kind": "prompt", "reason": "não sei começar"},
    "apply_help": {"intervention_id": "iv1", "step_id": "r1-g1"},
    "enter_notebook": {"intent": "record_solution"},
    "open_notebook_capture": {},
    "return_to_activity": {},
    "cancel_capture": {},
    "retake_notebook_photo": {},
    "request_reconstruction": {"observation_id": "obs1"},
    "dispute_observation": {"observation_id": "obs1", "field_path": "groups[0].count"},
    "clarify_observation": {
        "observation_id": "obs1",
        "field_path": "groups[0].count",
        "value": 5,
    },
    "submit_answer": {"answer": 6, "explanation": None},
    "submit_explanation": {"modality": "text", "text": "dividi igualmente"},
    "continue_after_explanation": {"reason": "sufficient"},
    "set_thinking": {"enabled": True},
    "pause_session": {},
    "resume_session": {},
    "interrupt_turn": {"turn_id": "turn-006"},
    "close_session": {"reason": "learner_stopped"},
}


def cmd(type_: str, actor: str = "learner", **over) -> dict:
    d = {**BASE, "type": type_, "payload": PAYLOADS[type_]}
    if type_ in SCENE_COMMANDS:
        d["expected_scene_revision"] = 1
    if actor == "tutor":
        d["turn_id"] = "turn-006"
        d["turn_epoch"] = 2
    d.update(over)
    return d


def code_of(raw, actor="learner") -> str:
    with pytest.raises(DomainError) as e:
        parse_command(raw, actor)
    return e.value.code


@pytest.mark.parametrize(
    "bad",
    [
        "{not json",
        {**BASE, "extra": 1},
        {**BASE, "actor": "tutor"},
        {**BASE, "expected_revision": 3.0},
        {**BASE, "expected_revision": True},  # Review Focus 1
        {**BASE, "type": "submit_answer", "payload": {"answer": True, "explanation": None}},
        {**BASE, "type": "submit_answer", "payload": {"answer": float("nan"), "explanation": None}},
        {**BASE, "type": "set_phase", "payload": {"phase": "summary"}},  # nada de set_phase
        {
            **BASE,
            "type": "move_piece",
            "payload": {"piece_id": "p", "from_location": "available", "to_location": "group-1"},
        },  # sem expected_scene_revision
        {**BASE, "type": "run_demo_step", "payload": {"step_id": "r1-g1", "js": "alert(1)"}},
    ],
)
def test_ac39_rejects(bad):
    with pytest.raises(DomainError) as e:
        parse_command(bad, "learner")
    assert e.value.code in {"INVALID_PAYLOAD", "ACTION_NOT_ALLOWED"}


def test_actor_gate():
    with pytest.raises(DomainError) as e:
        parse_command(
            {
                **BASE,
                "type": "highlight_group",
                "expected_scene_revision": 1,
                "payload": {"group_id": "group-1"},
            },
            "learner",
        )
    assert e.value.code == "ACTION_NOT_ALLOWED"


def test_catalog_complete():
    assert len(ALLOWED_ACTORS) == 30 and set(ALLOWED_ACTORS) == set(get_args(CommandType))
    assert set(PAYLOADS) == set(get_args(CommandType))


def test_every_type_parses_for_each_allowed_actor_and_only_those():
    for type_, actors in ALLOWED_ACTORS.items():
        for actor in ("learner", "tutor", "system", "vision_worker"):
            raw = cmd(type_, actor)
            if actor in actors:
                parsed = parse_command(raw, actor)
                assert parsed.type == type_
            else:
                assert code_of(raw, actor) == "ACTION_NOT_ALLOWED", (type_, actor)


def test_actor_columns_match_spec_table():
    expect = {
        "confirm_source": "L", "clarify_source": "L", "retake_source_photo": "L",
        "choose_reference_activity": "L", "run_demo_step": "TS", "finish_demonstration": "LS",
        "move_piece": "L", "undo_move": "L", "check_distribution": "L", "highlight_group": "T",
        "highlight_available": "T", "set_projection": "LT", "request_help": "L",
        "apply_help": "TS", "enter_notebook": "L", "open_notebook_capture": "L",
        "return_to_activity": "L", "cancel_capture": "L", "retake_notebook_photo": "L",
        "request_reconstruction": "L", "dispute_observation": "L", "clarify_observation": "L",
        "submit_answer": "L", "submit_explanation": "L", "continue_after_explanation": "LS",
        "set_thinking": "L", "pause_session": "L", "resume_session": "L",
        "interrupt_turn": "LS", "close_session": "LS",
    }  # fmt: skip
    names = {"L": "learner", "T": "tutor", "S": "system"}
    assert {k: frozenset(names[c] for c in v) for k, v in expect.items()} == ALLOWED_ACTORS


def test_vision_worker_has_no_commands():
    assert all("vision_worker" not in a for a in ALLOWED_ACTORS.values())


def test_scene_commands_are_the_eight():
    assert SCENE_COMMANDS == frozenset(
        {
            "move_piece", "undo_move", "highlight_group", "highlight_available",
            "set_projection", "run_demo_step", "apply_help", "request_reconstruction",
        }
    )  # fmt: skip


def test_request_help_kind_is_subset_of_help_kind():
    kinds = set(get_args(RequestHelpKind))
    assert kinds <= set(get_args(HelpKind))
    assert not kinds & {"procedural", "accessibility"}
    assert kinds == {
        "prompt", "visual_hint", "worked_step", "alternate_strategy",
        "virtual_objects", "reference_model",
    }  # fmt: skip


@pytest.mark.parametrize("kind", ["virtual_objects", "reference_model"])
def test_request_help_accepts_d3_resources_for_learner(kind):
    parsed = parse_command(cmd("request_help", payload={"kind": kind, "reason": "r"}), "learner")
    assert parsed.payload.kind == kind


@pytest.mark.parametrize("kind", ["procedural", "accessibility", "x"])
def test_request_help_rejects_other_kinds(kind):
    raw = cmd("request_help", payload={"kind": kind, "reason": "r"})
    assert code_of(raw) == "INVALID_PAYLOAD"


# ---- JSON / entrada ----------------------------------------------------------------------


def test_accepts_str_and_bytes_and_dict_equally():
    raw = cmd("move_piece")
    text = json.dumps(raw)
    a = parse_command(raw, "learner")
    assert parse_command(text, "learner") == a
    assert parse_command(text.encode(), "learner") == a


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity"])
def test_json_rejects_non_finite_constants(text):
    body = json.dumps(cmd("submit_answer")).replace('"answer": 6', f'"answer": {text}')
    assert code_of(body) == "INVALID_PAYLOAD"
    assert code_of(body.encode()) == "INVALID_PAYLOAD"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_dict_rejects_non_finite_anywhere(bad):
    assert code_of(cmd("submit_answer", payload={"answer": bad, "explanation": None})) == (
        "INVALID_PAYLOAD"
    )
    deep = cmd("clarify_source", payload={**PAYLOADS["clarify_source"], "value": [{"a": bad}]})
    assert code_of(deep) == "INVALID_PAYLOAD"


@pytest.mark.parametrize(
    "raw",
    [b"\xff\xfe", b"", "", "[]", "3", "null", '"x"', None, 5, ["a"]],
)
def test_garbage_input_is_invalid_payload(raw):
    assert code_of(raw) == "INVALID_PAYLOAD"


def test_duplicate_json_keys_rejected():
    body = '{"schema_version":"1.0","schema_version":"1.0"}'
    assert code_of(body) == "INVALID_PAYLOAD"


def test_actor_in_json_rejected_even_when_same_as_context():
    assert code_of({**cmd("check_distribution"), "actor": "learner"}) == "INVALID_PAYLOAD"


# ---- envelope ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["schema_version", "command_id", "session_id", "attempt_id", "expected_revision", "type",
     "payload"],
)  # fmt: skip
def test_missing_required_envelope_field(field):
    raw = cmd("check_distribution")
    del raw[field]
    assert code_of(raw) == "INVALID_PAYLOAD"


def test_attempt_id_may_be_null_but_not_omitted():
    assert parse_command(cmd("check_distribution", attempt_id=None), "learner").attempt_id is None


@pytest.mark.parametrize(
    "over",
    [
        {"schema_version": "2.0"},
        {"schema_version": 1.0},
        {"command_id": ""},
        {"command_id": 5},
        {"session_id": ""},
        {"attempt_id": 7},
        {"expected_revision": -1},
        {"expected_revision": "3"},
        {"expected_revision": None},
        {"payload": None},
        {"payload": []},
        {"type": 5},
        {"type": None},
    ],
)
def test_bad_envelope_values(over):
    assert code_of(cmd("check_distribution", **over)) == "INVALID_PAYLOAD"


def test_envelope_class_exposes_common_fields():
    assert {
        "schema_version", "command_id", "session_id", "attempt_id", "expected_revision",
        "turn_id", "turn_epoch",
    } == set(CommandEnvelope.model_fields)  # fmt: skip
    assert set(SceneCommandEnvelope.model_fields) - set(CommandEnvelope.model_fields) == {
        "expected_scene_revision"
    }


# ---- expected_scene_revision -------------------------------------------------------------


@pytest.mark.parametrize("type_", sorted(SCENE_COMMANDS))
def test_scene_commands_require_expected_scene_revision(type_):
    actor = "learner" if "learner" in ALLOWED_ACTORS[type_] else "tutor"
    raw = cmd(type_, actor)
    del raw["expected_scene_revision"]
    assert code_of(raw, actor) == "INVALID_PAYLOAD"
    raw["expected_scene_revision"] = None
    assert code_of(raw, actor) == "INVALID_PAYLOAD"
    for bad in (-1, 1.0, True, "1"):
        raw["expected_scene_revision"] = bad
        assert code_of(raw, actor) == "INVALID_PAYLOAD"


@pytest.mark.parametrize("type_", sorted(set(PAYLOADS) - SCENE_COMMANDS))
def test_non_scene_commands_forbid_expected_scene_revision(type_):
    actor = "learner" if "learner" in ALLOWED_ACTORS[type_] else "tutor"
    raw = cmd(type_, actor, expected_scene_revision=1)
    assert code_of(raw, actor) == "INVALID_PAYLOAD"


# ---- turn_id / turn_epoch ----------------------------------------------------------------


def test_tutor_requires_both_turn_fields():
    ok = cmd("highlight_group", "tutor")
    assert parse_command(ok, "tutor").turn_epoch == 2
    for drop in (["turn_id"], ["turn_epoch"], ["turn_id", "turn_epoch"]):
        raw = {k: v for k, v in ok.items() if k not in drop}
        assert code_of(raw, "tutor") == "INVALID_PAYLOAD"
    for bad in (
        {"turn_id": None},
        {"turn_epoch": None},
        {"turn_id": ""},
        {"turn_epoch": -1},
        {"turn_epoch": 2.0},
        {"turn_epoch": True},
    ):
        assert code_of({**ok, **bad}, "tutor") == "INVALID_PAYLOAD"


def test_learner_forbids_turn_fields():
    raw = cmd("check_distribution")
    for extra in ({"turn_id": "t"}, {"turn_epoch": 1}, {"turn_id": "t", "turn_epoch": 1}):
        assert code_of({**raw, **extra}) == "INVALID_PAYLOAD"
    # null explícito também conta como presença indevida
    assert code_of({**raw, "turn_id": None}) == "INVALID_PAYLOAD"


def test_system_turn_fields_are_optional_but_paired():
    raw = cmd("run_demo_step", "system")
    assert parse_command(raw, "system").turn_id is None
    both = {**raw, "turn_id": "t", "turn_epoch": 0}
    assert parse_command(both, "system").turn_epoch == 0
    assert code_of({**raw, "turn_id": "t"}, "system") == "INVALID_PAYLOAD"
    assert code_of({**raw, "turn_epoch": 1}, "system") == "INVALID_PAYLOAD"


def test_actor_gate_runs_after_shape_and_before_turn_rules():
    # forma válida + ator errado => ACTION_NOT_ALLOWED (mesmo com campos de turno do ator errado)
    assert code_of(cmd("highlight_group", "tutor"), "learner") == "ACTION_NOT_ALLOWED"
    assert code_of(cmd("check_distribution"), "tutor") == "ACTION_NOT_ALLOWED"
    # forma inválida + ator errado => INVALID_PAYLOAD
    bad = {**cmd("highlight_group"), "payload": {"group_id": 5}}
    assert code_of(bad, "learner") == "INVALID_PAYLOAD"


# ---- payloads ----------------------------------------------------------------------------

EMPTY = [t for t, p in PAYLOADS.items() if p == {}]


@pytest.mark.parametrize("type_", EMPTY)
def test_empty_payloads_reject_any_key(type_):
    actor = "learner" if "learner" in ALLOWED_ACTORS[type_] else "tutor"
    base = cmd(type_, actor)
    assert parse_command(base, actor)
    assert code_of({**base, "payload": {"x": 1}}, actor) == "INVALID_PAYLOAD"
    assert code_of({**base, "payload": {"js": None}}, actor) == "INVALID_PAYLOAD"


def test_empty_payload_set():
    assert set(EMPTY) == {
        "retake_source_photo", "check_distribution", "highlight_available",
        "open_notebook_capture", "return_to_activity", "cancel_capture",
        "retake_notebook_photo", "pause_session", "resume_session",
    }  # fmt: skip


@pytest.mark.parametrize("type_", [t for t in PAYLOADS if PAYLOADS[t]])
def test_payload_rejects_extra_and_missing_keys(type_):
    actor = "learner" if "learner" in ALLOWED_ACTORS[type_] else "tutor"
    good = PAYLOADS[type_]
    assert code_of(cmd(type_, actor, payload={**good, "extra": 1}), actor) == "INVALID_PAYLOAD"
    for key in good:
        short = {k: v for k, v in good.items() if k != key}
        if type_ in {"dispute_observation", "submit_explanation"} and key in {
            "field_path", "text", "reason",
        }:  # fmt: skip
            continue  # campos alternativos: cobertos em testes próprios
        assert code_of(cmd(type_, actor, payload=short), actor) == "INVALID_PAYLOAD", (type_, key)
    assert code_of(cmd(type_, actor, payload={}), actor) == "INVALID_PAYLOAD"


@pytest.mark.parametrize(
    "type_, payload",
    [
        ("submit_answer", {"answer": 6.0, "explanation": None}),
        ("submit_answer", {"answer": "6", "explanation": None}),
        ("submit_answer", {"answer": 6, "explanation": 3}),
        ("submit_answer", {"answer": 6}),
        ("set_thinking", {"enabled": 1}),
        ("set_thinking", {"enabled": "true"}),
        ("set_projection", {"projection": "front"}),
        ("finish_demonstration", {"reason": "done"}),
        ("continue_after_explanation", {"reason": "completed"}),
        ("close_session", {"reason": "sufficient"}),
        ("enter_notebook", {"intent": "free"}),
        ("choose_reference_activity", {"content_version": "division-sharing-v2"}),
        ("move_piece", {"piece_id": "", "from_location": "available", "to_location": "group-1"}),
        ("move_piece", {"piece_id": "p", "from_location": "available", "to_location": 3}),
        ("move_piece", {"piece_id": "p", "from_location": "a b", "to_location": "group-1"}),
        ("run_demo_step", {"step_id": "<script>"}),
        ("run_demo_step", {"step_id": ""}),
        ("run_demo_step", {"step_id": None}),
        ("run_demo_step", {"step_id": "x" * 500}),
        ("clarify_source", {"analysis_id": "a", "field_path": "p", "value": True}),
        ("clarify_source", {"analysis_id": "a", "field_path": "p", "value": 1.5}),
        ("clarify_source", {"analysis_id": "a", "field_path": "p", "value": None}),
        ("clarify_observation", {"observation_id": "o", "field_path": "p", "value": [1]}),
        ("clarify_observation", {"observation_id": "o", "field_path": "p", "value": True}),
        ("request_help", {"kind": "prompt", "reason": ""}),
        ("request_help", {"kind": "prompt", "reason": 3}),
        ("request_help", {"kind": "prompt", "reason": "x" * 1000}),
        ("interrupt_turn", {"turn_id": 5}),
    ],
)
def test_strict_payload_values_rejected(type_, payload):
    actor = "learner"
    if type_ in {"interrupt_turn"}:
        actor = "learner"
    assert code_of(cmd(type_, actor, payload=payload), actor) == "INVALID_PAYLOAD"


def test_submit_answer_accepts_int_and_text_or_null_explanation():
    for expl in (None, "dividi em 4"):
        p = parse_command(
            cmd("submit_answer", payload={"answer": 0, "explanation": expl}), "learner"
        )
        assert p.payload.answer == 0 and p.payload.explanation == expl


def test_dispute_observation_needs_field_path_or_reason():
    ok = cmd("dispute_observation")
    assert parse_command(ok, "learner")
    only_reason = cmd(
        "dispute_observation", payload={"observation_id": "o", "reason": "contou mal"}
    )
    assert parse_command(only_reason, "learner")
    both = cmd(
        "dispute_observation",
        payload={"observation_id": "o", "field_path": "groups[0].count", "reason": "x"},
    )
    assert parse_command(both, "learner")
    neither = cmd("dispute_observation", payload={"observation_id": "o"})
    assert code_of(neither) == "INVALID_PAYLOAD"
    for bad in ({"field_path": None, "reason": None}, {"field_path": "", "reason": None}):
        assert code_of(cmd("dispute_observation", payload={"observation_id": "o", **bad})) == (
            "INVALID_PAYLOAD"
        )


def test_submit_explanation_text_xor_artifact():
    for modality in ("text", "voice_transcript"):
        assert parse_command(
            cmd("submit_explanation", payload={"modality": modality, "text": "oi"}), "learner"
        )
        assert (
            code_of(cmd("submit_explanation", payload={"modality": modality, "artifact_id": "ar1"}))
            == "INVALID_PAYLOAD"
        )
    assert parse_command(
        cmd("submit_explanation", payload={"modality": "artifact", "artifact_id": "ar1"}),
        "learner",
    )
    for bad in (
        {"modality": "artifact", "text": "oi"},
        {"modality": "artifact"},
        {"modality": "text"},
        {"modality": "text", "text": "oi", "artifact_id": "ar1"},
        {"modality": "text", "text": ""},
        {"modality": "text", "text": None},
        {"modality": "video", "text": "oi"},
    ):
        assert code_of(cmd("submit_explanation", payload=bad)) == "INVALID_PAYLOAD", bad


def test_commands_are_frozen():
    parsed = parse_command(cmd("check_distribution"), "learner")
    with pytest.raises(ValidationError):
        parsed.command_id = "other"  # type: ignore[misc]


def test_json_overflowing_float_is_rejected():
    body = json.dumps(cmd("submit_answer")).replace('"answer": 6', '"answer": 1e999')
    assert code_of(body) == "INVALID_PAYLOAD"
