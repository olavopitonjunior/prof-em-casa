"""Fluxo de captura do caderno (AC-33): envio do artefato e aplicação do resultado da análise.

`submit_artifact` e `apply_analysis_result` não são comandos do catálogo: quem as chama é a camada
de casos de uso (upload e worker de visão), nunca o cliente. Seguem o contrato de `apply_command`:
funções puras, o estado de entrada nunca é alterado e um `DomainError` não deixa efeito.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.content.loader import ContentPackage
from app.domain.division.errors import DomainError
from app.domain.division.observation import NotebookObservation, verify_observation
from app.domain.division.state import ActiveArtifact, CommandResult, DomainEvent, SessionState

__all__ = [
    "AnalysisApplication",
    "AnalysisResult",
    "Disposition",
    "apply_analysis_result",
    "submit_artifact",
]

Disposition = Literal["applied", "superseded", "deferred", "discarded"]


class AnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    artifact_id: str
    artifact_version: StrictInt = Field(ge=1)
    attempt_id: str
    observation: NotebookObservation


class AnalysisApplication(BaseModel):
    """`result` só existe quando `disposition == "applied"`; nos demais casos o estado não muda."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition: Disposition
    result: CommandResult | None = None


def _finish(session: SessionState, events: list[DomainEvent], *, bump_revision: bool):
    return session.with_changes(
        revision=session.revision + (1 if bump_revision else 0),
        last_event_seq=session.last_event_seq + len(events),
    )


def submit_artifact(
    session: SessionState,
    *,
    attempt_id: str,
    artifact_id: str,
    artifact_version: int,
    job_id: str,
) -> CommandResult:
    if session.session_status == "closed":
        raise DomainError("ACTION_NOT_ALLOWED", "session_closed")
    if attempt_id != session.active_attempt_id:
        raise DomainError("ATTEMPT_CHANGED", "attempt_id is not the active attempt")
    if session.phase != "notebook_capture":
        raise DomainError(
            "INVALID_TRANSITION", f"submit_artifact is not allowed in {session.phase}"
        )
    artifact = ActiveArtifact(
        artifact_id=artifact_id, artifact_version=artifact_version, job_id=job_id
    )
    events = [
        DomainEvent(
            type="artifact_submitted",
            attempt_id=attempt_id,
            data={
                "artifact_id": artifact_id,
                "artifact_version": artifact_version,
                "job_id": job_id,
            },
        )
    ]
    # Uma foto nova invalida o que a anterior produziu: a análise volta a "pending".
    updated = session.with_changes(
        phase="notebook_review", active_artifact=artifact, observation=None, verification=None
    )
    return CommandResult(
        session=_finish(updated, events, bump_revision=True),
        events=tuple(events),
        scene_changed=False,
    )


def _is_current(session: SessionState, result: AnalysisResult) -> bool:
    artifact = session.active_artifact
    return (
        result.attempt_id == session.active_attempt_id
        and artifact is not None
        and result.artifact_id == artifact.artifact_id
        and result.job_id == artifact.job_id
        and result.artifact_version == artifact.artifact_version
    )


def apply_analysis_result(
    session: SessionState,
    result: AnalysisResult,
    *,
    content: ContentPackage,
    bump_revision: bool = True,
) -> AnalysisApplication:
    if session.session_status == "closed":
        return AnalysisApplication(disposition="discarded")
    if not _is_current(session, result):
        return AnalysisApplication(disposition="superseded")
    if session.session_status == "paused":
        return AnalysisApplication(disposition="deferred")
    attempt = session.active_attempt
    if attempt is None:  # inalcançável: _is_current exige attempt_id == active_attempt_id
        return AnalysisApplication(disposition="superseded")
    item = content.items[attempt.item_id]
    verification = verify_observation(item.task, item.private.quotient, result.observation, [])
    events = [
        DomainEvent(
            type="analysis_completed",
            attempt_id=attempt.attempt_id,
            data={
                "job_id": result.job_id,
                "artifact_id": result.artifact_id,
                "artifact_version": result.artifact_version,
                "observation_id": result.observation.observation_id,
                "verification_status": verification.status,
                "issues": list(verification.issues),
                "reconstruction_allowed": verification.reconstruction_allowed,
            },
        )
    ]
    updated = session.with_changes(observation=result.observation, verification=verification)
    final = _finish(updated, events, bump_revision=bump_revision)
    return AnalysisApplication(
        disposition="applied",
        result=CommandResult(session=final, events=tuple(events), scene_changed=False),
    )
