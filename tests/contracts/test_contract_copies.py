import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "contracts" / "notebook-observation.schema.json"
FIXTURES = ROOT / "tests" / "fixtures"
OBSERVATIONS = ["observacao-5-5-5-5", "observacao-ambigua", "observacao-corrigida"]
SOURCE_ROOT = Path.home() / "Documents" / "ChatGPT" / "Hack Brasil"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(_load(SCHEMA))


@pytest.mark.parametrize("name", OBSERVATIONS)
def test_fixtures_valid_against_schema(name):
    validator = Draft202012Validator(_load(SCHEMA))
    validator.validate(_load(FIXTURES / f"{name}.json"))


@pytest.mark.parametrize("name", OBSERVATIONS)
def test_fixtures_are_marked_synthetic(name):
    assert _load(FIXTURES / f"{name}.json")["model_ref"] == "synthetic-fixture-not-a-model-run"


def test_schema_copy_is_byte_identical_to_source():
    source = SOURCE_ROOT / "hackbrasil-discovery" / "contracts" / "notebook-observation.schema.json"
    if not source.exists():
        pytest.skip("pasta de origem (Hack Brasil) ausente neste ambiente")
    assert (
        hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
        == hashlib.sha256(source.read_bytes()).hexdigest()
    )
