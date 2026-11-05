"""Contrato HTTP: `contracts/openapi.json` é o `app.openapi()` commitado (gere com
`uv run python scripts/export_openapi.py`)."""

import json
from pathlib import Path

from app.api.app import create_app
from app.content.loader import load_content
from app.db.engine import make_engine
from app.sessions.evaluator import UnavailableEvaluator
from app.sessions.service import SessionService

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = "/v1/sessions/{session_id}/commands"


def fake_service() -> SessionService:
    return SessionService(
        make_engine("sqlite://"), load_content(), UnavailableEvaluator(), token_secret=b"x" * 32
    )


def command_schema(spec: dict) -> dict:
    return spec["paths"][COMMANDS]["post"]["requestBody"]["content"]["application/json"]["schema"]


def test_openapi_committed_matches_app():
    committed = json.loads((ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    live = json.loads(json.dumps(create_app(fake_service()).openapi()))
    assert committed == live


def test_openapi_has_routes_and_command_union():
    spec = create_app(fake_service()).openapi()
    assert {
        "/v1/sessions",
        COMMANDS,
        "/v1/sessions/{session_id}/claim-control",
        "/v1/sessions/{session_id}/render-receipts",
        "/v1/sessions/{session_id}/events",
    } <= set(spec["paths"])
    assert len(command_schema(spec)["oneOf"]) == 30


def test_openapi_command_refs_resolve_and_no_default_422():
    spec = create_app(fake_service()).openapi()
    schemas = spec["components"]["schemas"]
    for option in command_schema(spec)["oneOf"]:
        assert option["$ref"].rsplit("/", 1)[1] in schemas
    assert "$defs" not in json.dumps(spec)
    assert "HTTPValidationError" not in schemas
    assert not any(
        "422" in op.get("responses", {}) and "HTTPValidation" in json.dumps(op["responses"]["422"])
        for path in spec["paths"].values()
        for op in path.values()
    )
