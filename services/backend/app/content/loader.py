import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError, model_validator

from app.domain.division.errors import DomainError
from app.domain.division.task import TaskSpec

CONTENT_ROOT = Path(__file__).resolve().parents[4] / "content"
_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PrivateItem(_Frozen):
    quotient: StrictInt
    explanation_criteria: list[str]


class ContentItem(_Frozen):
    item_id: str
    role: Literal["demonstration", "guided", "transfer"]
    task: TaskSpec
    statement: str
    private: PrivateItem

    @model_validator(mode="after")
    def _quotient_matches_task(self) -> "ContentItem":
        if self.task.dividend // self.task.divisor != self.private.quotient:
            raise DomainError("UNSUPPORTED_CONTENT", f"{self.item_id}: quotient mismatch")
        return self


class DemoScript(_Frozen):
    item_id: str
    rounds: StrictInt


class InterventionText(_Frozen):
    code: str
    text: str


class ContentPackage(_Frozen):
    version: str
    items: dict[str, ContentItem]
    demonstration: DemoScript
    interventions: dict[str, InterventionText]


def _read(directory: Path, name: str):
    return json.loads((directory / name).read_text(encoding="utf-8"))


_CORRUPT = (
    ValidationError,
    KeyError,
    TypeError,
    AttributeError,
    FileNotFoundError,
    json.JSONDecodeError,
    UnicodeDecodeError,
)


def load_content(
    version: str = "division-sharing-v1", *, base_dir: Path | None = None
) -> ContentPackage:
    """Carrega o pacote versionado. Qualquer defeito do conteúdo vira UNSUPPORTED_CONTENT
    (encadeado com `from`), nunca uma exceção crua de Pydantic, JSON ou arquivo."""
    directory = (CONTENT_ROOT if base_dir is None else base_dir) / version
    if not _VERSION_RE.match(version) or not directory.is_dir():
        raise DomainError("UNSUPPORTED_CONTENT", f"unknown content version: {version}")
    try:
        raw_items = _read(directory, "items.json")
        items: dict[str, ContentItem] = {}
        for raw in raw_items:
            item = ContentItem(**raw)
            if item.item_id in items:
                raise DomainError("UNSUPPORTED_CONTENT", f"duplicate item_id: {item.item_id}")
            items[item.item_id] = item
        demonstration = DemoScript(**_read(directory, "demonstration.json"))
        if demonstration.item_id not in items:
            raise DomainError("UNSUPPORTED_CONTENT", "demonstration item missing from package")
        interventions = {
            code: InterventionText(code=code, text=text)
            for code, text in _read(directory, "interventions.json").items()
        }
        return ContentPackage(
            version=version, items=items, demonstration=demonstration, interventions=interventions
        )
    except _CORRUPT as exc:
        raise DomainError(
            "UNSUPPORTED_CONTENT", f"corrupt content package {version}: {type(exc).__name__}"
        ) from exc


def public_item(item: ContentItem) -> dict:
    """Visão pública do item: sem `private`, sem quociente e sem passos resolvidos.
    Só o item de demonstração revela a expressão resolvida."""
    data = {
        "item_id": item.item_id,
        "role": item.role,
        "task": {
            "dividend": item.task.dividend,
            "divisor": item.task.divisor,
            "unit": item.task.unit,
        },
        "statement": item.statement,
    }
    if item.role == "demonstration":
        data["demo_expression"] = (
            f"{item.task.dividend} ÷ {item.task.divisor} = {item.private.quotient}"
        )
    return data
