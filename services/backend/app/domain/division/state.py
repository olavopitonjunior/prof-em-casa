"""Estado de sessão, tentativas e eventos de domínio (Spec Parte I §4; Parte II §9).

Tudo é imutável. `with_changes` revalida o modelo inteiro, então nenhuma transição produz um
estado que viole as invariantes, e o estado de entrada nunca é alterado.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.domain.division.assistance import AssistanceLedger
from app.domain.division.classification import ExplanationResult
from app.domain.division.observation import NotebookObservation, Verification
from app.domain.division.scene import SceneState
from app.domain.division.transitions import AttemptKind, Phase

CONTENT_VERSION = "division-sharing-v1"

SessionStatus = Literal["active", "paused", "closed"]
InteractionMode = Literal["ready", "thinking", "writing"]
NotebookIntent = Literal["record_solution", "try_on_paper", "revise_record"]
Completion = Literal["partial", "complete"]

# Parte II §9, mais `returned_to_activity` (extensão: a Spec não nomeia o evento de saída do caderno).
EventType = Literal[
    "source_confirmed",
    "attempt_started",
    "demo_step_completed",
    "scene_changed",
    "distribution_checked",
    "help_granted",
    "notebook_entered",
    "returned_to_activity",
    "artifact_submitted",
    "analysis_completed",
    "analysis_superseded",
    "observation_disputed",
    "observation_clarified",
    "answer_submitted",
    "explanation_evaluated",
    "attempt_evaluated",
    "session_paused",
    "session_resumed",
    "session_closed",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def with_changes(self, **changes: Any):
        """Cópia revalidada (`model_copy` não valida)."""
        return type(self).model_validate({**dict(self), **changes})


class ActiveArtifact(_Frozen):
    """Foto do caderno em análise: só a última enviada vale (AC-33)."""

    artifact_id: str
    artifact_version: StrictInt = Field(ge=1)
    job_id: str


class Attempt(_Frozen):
    attempt_id: str
    kind: AttemptKind
    item_id: str
    status: Literal["active", "closed"]
    ledger: AssistanceLedger = AssistanceLedger()
    answer: StrictInt | None = None
    explanation: ExplanationResult | None = None
    demo_partial: bool = False


class SessionState(_Frozen):
    session_id: str
    content_version: str
    phase: Phase
    session_status: SessionStatus
    interaction_mode: InteractionMode
    revision: StrictInt = Field(ge=0)
    scene_revision: StrictInt = Field(ge=0)
    turn_epoch: StrictInt = Field(ge=0)
    active_attempt_id: str | None
    attempts: tuple[Attempt, ...]
    scene: SceneState | None
    last_event_seq: StrictInt = Field(ge=0)
    # Checkpoint do caderno (Parte I §4) e fechamento. Acrescentados à lista do plano.
    return_phase: Phase | None = None
    notebook_intent: NotebookIntent | None = None
    completion: Completion | None = None
    # Captura do caderno (AC-33): artefato vigente e o resultado da análise já aplicado.
    active_artifact: ActiveArtifact | None = None
    observation: NotebookObservation | None = None
    verification: Verification | None = None

    @model_validator(mode="after")
    def _check_invariants(self) -> "SessionState":
        ids = [a.attempt_id for a in self.attempts]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate attempt id")
        if self.active_attempt_id is not None and self.active_attempt_id not in ids:
            raise ValueError("active_attempt_id must name an existing attempt")
        if sum(a.status == "active" for a in self.attempts) > 1:
            raise ValueError("at most one active attempt")
        if self.scene is not None and self.scene.scene_revision > self.scene_revision:
            raise ValueError("scene is newer than the session scene_revision")
        return self

    @property
    def active_attempt(self) -> Attempt | None:
        for a in self.attempts:
            if a.attempt_id == self.active_attempt_id:
                return a
        return None


class DomainEvent(_Frozen):
    type: EventType
    attempt_id: str | None
    data: dict[str, Any]


class CommandResult(_Frozen):
    session: SessionState
    events: tuple[DomainEvent, ...]
    scene_changed: bool


def new_session(session_id: str) -> SessionState:
    return SessionState(
        session_id=session_id,
        content_version=CONTENT_VERSION,
        phase="source_capture",
        session_status="active",
        interaction_mode="ready",
        revision=0,
        scene_revision=0,
        turn_epoch=0,
        active_attempt_id=None,
        attempts=(),
        scene=None,
        last_event_seq=0,
    )
