"""Escreve `contracts/openapi.json` a partir do app (indentação 2, chaves ordenadas).

Não lê o ambiente nem abre banco: o serviço é só um marcador, porque o contrato não depende dele.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "backend"))

from app.api.app import create_app
from app.content.loader import load_content
from app.db.engine import make_engine
from app.sessions.evaluator import UnavailableEvaluator
from app.sessions.service import SessionService

TARGET = ROOT / "contracts" / "openapi.json"


def build_spec() -> dict:
    service = SessionService(
        make_engine("sqlite://"), load_content(), UnavailableEvaluator(), token_secret=b"x" * 32
    )
    return create_app(service).openapi()


def main() -> None:
    TARGET.write_text(
        json.dumps(build_spec(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"escrito {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
