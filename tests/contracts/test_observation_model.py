import json
from pathlib import Path

import pytest
from app.domain.division.observation import NotebookObservation
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts" / "notebook-observation.schema.json").read_text("utf-8"))
NAMES = ["observacao-5-5-5-5", "observacao-ambigua", "observacao-corrigida"]


def raw(name: str = "observacao-5-5-5-5") -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / f"{name}.json").read_text("utf-8"))


@pytest.mark.parametrize("name", NAMES)
def test_fixtures_parse(name):
    obs = NotebookObservation.model_validate(raw(name))
    assert obs.model_ref == "synthetic-fixture-not-a-model-run"


@pytest.mark.parametrize("name", NAMES)
def test_fixtures_parse_from_json(name):
    text = (ROOT / "tests" / "fixtures" / f"{name}.json").read_text("utf-8")
    assert NotebookObservation.model_validate_json(text) == NotebookObservation.model_validate(
        raw(name)
    )


def _mutations():
    def at(path, value):
        def mutate(d):
            target = d
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value

        return mutate

    return {
        "float count": at(["groups", 0, "count"], 5.0),
        "bool count": at(["groups", 0, "count"], True),
        "string count": at(["groups", 0, "count"], "5"),
        "negative count": at(["groups", 0, "count"], -1),
        "count above 60": at(["groups", 0, "count"], 61),
        "float answer": at(["expression", "answer"], 5.0),
        "answer out of range": at(["expression", "answer"], 10000),
        "float dividend": at(["expression", "dividend"], 24.0),
        "bool uncertain": at(["groups", 0, "uncertain"], 1),
        "schema_version": at(["schema_version"], "2.0"),
        "artifact_version 0": at(["artifact_version"], 0),
        "float artifact_version": at(["artifact_version"], 1.0),
        "empty observation_id": at(["observation_id"], ""),
        "bad status": at(["status"], "other"),
        "bad provenance": at(["groups", 0, "provenance"], "learner_report"),
        "bbox zero width": at(["groups", 0, "bbox", "width"], 0),
        "bbox negative x": at(["groups", 0, "bbox", "x"], -0.1),
        "bbox x above 1": at(["groups", 0, "bbox", "x"], 1.1),
        "bbox string": at(["groups", 0, "bbox", "x"], "0.1"),
        "bbox nan": at(["groups", 0, "bbox", "x"], float("nan")),
        "bad ambiguity reason": at(["ambiguities"], [{"field_path": "/a", "reason": "nope"}]),
        "empty field_path": at(["ambiguities"], [{"field_path": "", "reason": "missing"}]),
        "extra top": at(["extra"], 1),
        "extra group": at(["groups", 0, "extra"], 1),
        "extra expression": at(["expression", "extra"], 1),
        "extra bbox": at(["groups", 0, "bbox", "extra"], 1),
        "too many groups": at(["groups"], [raw()["groups"][0]] * 13),
        "needs_clarification without ambiguity": at(["status"], "needs_clarification"),
        "null count not uncertain": at(["groups", 0, "count"], None),
    }


@pytest.mark.parametrize("label", list(_mutations()))
def test_invalid_payloads_rejected_by_model(label):
    data = raw()
    _mutations()[label](data)
    with pytest.raises(ValidationError):
        NotebookObservation.model_validate(data)


def test_float_count_rejected_by_model_but_accepted_by_schema():
    data = raw()
    data["groups"][0]["count"] = 5.0
    assert Draft202012Validator(SCHEMA).is_valid(data)  # o schema aceitava
    with pytest.raises(ValidationError):
        NotebookObservation.model_validate(data)
    with pytest.raises(ValidationError):
        NotebookObservation.model_validate_json(json.dumps(data))


def test_model_is_frozen():
    obs = NotebookObservation.model_validate(raw())
    with pytest.raises(ValidationError):
        obs.status = "needs_clarification"
