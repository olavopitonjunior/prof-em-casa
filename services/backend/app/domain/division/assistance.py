"""Registro de ajuda pedagógica por item (Spec Parte I §7, "Ajuda e recursos").

O nível nunca diminui. Perguntas de procedimento e acessibilidade não são ajuda conceitual.
Objetos virtuais e modelo de referência (D3) acrescentam recurso, mas não elevam o nível.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

AssistanceLevel = Literal["none", "prompted", "demonstrated"]
SupportResource = Literal[
    "paper", "virtual_objects", "reference_model", "counting_aid", "text_rephrase"
]
HelpKind = Literal[
    "prompt",
    "visual_hint",
    "worked_step",
    "alternate_strategy",
    "virtual_objects",
    "reference_model",
    "procedural",
    "accessibility",
]

_RANK: dict[AssistanceLevel, int] = {"none": 0, "prompted": 1, "demonstrated": 2}
_LEVEL_OF_KIND: dict[str, AssistanceLevel] = {
    "prompt": "prompted",
    "visual_hint": "prompted",
    "worked_step": "demonstrated",
    "alternate_strategy": "demonstrated",
}
_RESOURCE_OF_KIND: dict[str, SupportResource] = {
    "virtual_objects": "virtual_objects",
    "reference_model": "reference_model",
}


class AssistanceLedger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    level: AssistanceLevel = "none"
    resources: frozenset[SupportResource] = frozenset()


def apply_help_effect(ledger: AssistanceLedger, kind: HelpKind) -> AssistanceLedger:
    """Devolve um novo registro. O texto livre da criança nunca entra aqui (R28, AC-45)."""
    level = ledger.level
    target = _LEVEL_OF_KIND.get(kind)
    if target is not None and _RANK[target] > _RANK[level]:
        level = target
    resources = ledger.resources
    resource = _RESOURCE_OF_KIND.get(kind)
    if resource is not None:
        resources = resources | {resource}
    return AssistanceLedger(level=level, resources=resources)
