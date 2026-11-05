"""Fluxo de captura do caderno (AC-33): envio do artefato e aplicação do resultado da análise.

`submit_artifact` e `apply_analysis_result` não são comandos do catálogo: quem as chama é a camada
de casos de uso (upload e worker de visão), nunca o cliente. Seguem o contrato de `apply_command`:
funções puras, o estado de entrada nunca é alterado e um `DomainError` não deixa efeito.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.content.loader import ContentPackage
from app.domain.division.errors import DomainError
from app.domain.division.observation import NotebookObservation, verify_observation
from app.domain.division.state import (
    ActiveArtifact,
    CommandResult,
    DomainEvent,
    SessionState,
    drop_artifact,
)

__all__ = [
    "AnalysisApplication",
    "AnalysisResult",
    "Disposition",
    "apply_analysis_result",
    "submit_artifact",
]

Disposition = Literal["applied", "already_applied", "superseded", "deferred", "discarded"]

# Fases em que um resultado vigente ainda tem onde ser aplicado: a revisão e, enquanto a criança
# revisa o registro (revise_record), o caderno. Spec §8: "reconciliar ... na fase notebook_review".
# `source_review` é da análise da fonte, que não usa `active_artifact`.
_ANALYSIS_PHASES = frozenset({"notebook_review", "notebook"})


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

    @model_validator(mode="after")
    def _result_only_when_applied(self) -> "AnalysisApplication":
        if (self.disposition == "applied") != (self.result is not None):
            raise ValueError("result exists exactly when the disposition is applied")
        return self


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
    # Normalmente já foi abandonado por open_notebook_capture; defensivo contra estado herdado.
    session, events = drop_artifact(session, reason="replaced", clear_completed=True)
    events.append(
        DomainEvent(
            type="artifact_submitted",
            attempt_id=attempt_id,
            data={
                "artifact_id": artifact_id,
                "artifact_version": artifact_version,
                "job_id": job_id,
            },
        )
    )
    updated = session.with_changes(phase="notebook_review", active_artifact=artifact)
    return CommandResult(
        session=_finish(updated, events, bump_revision=True),
        events=tuple(events),
        scene_changed=False,
    )


def _is_current(session: SessionState, result: AnalysisResult) -> bool:
    """O resultado é do artefato vigente, da tentativa ainda ativa, e a fase espera análise."""
    artifact = session.active_artifact
    attempt = session.active_attempt
    return (
        artifact is not None
        and attempt is not None
        and attempt.status == "active"
        and result.attempt_id == attempt.attempt_id
        and result.artifact_id == artifact.artifact_id
        and result.job_id == artifact.job_id
        and result.artifact_version == artifact.artifact_version
        and session.phase in _ANALYSIS_PHASES
    )


def _check_coherent(result: AnalysisResult) -> None:
    """R24: a observação tem de ser do artefato e da tentativa que o resultado declara."""
    obs = result.observation
    if (obs.artifact_id, obs.artifact_version, obs.attempt_id) != (
        result.artifact_id,
        result.artifact_version,
        result.attempt_id,
    ):
        raise DomainError("INVALID_PAYLOAD", "observation does not belong to the result")


def apply_analysis_result(
    session: SessionState,
    result: AnalysisResult,
    *,
    content: ContentPackage,
    bump_revision: bool = True,
) -> AnalysisApplication:
    _check_coherent(result)
    if session.session_status == "closed":
        return AnalysisApplication(disposition="discarded")
    attempt = session.active_attempt
    if attempt is None or not _is_current(session, result):
        return AnalysisApplication(disposition="superseded")
    if session.observation is not None:  # um job produz uma análise: a segunda entrega não vale
        return AnalysisApplication(disposition="already_applied")
    if session.session_status == "paused":
        return AnalysisApplication(disposition="deferred")
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
