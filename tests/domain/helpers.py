import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.content.loader import load_content
from app.domain.division.classification import ExplanationResult
from app.domain.division.commands import SCENE_COMMANDS, parse_command
from app.domain.division.demonstration import demo_steps
from app.domain.division.observation import NotebookObservation
from app.domain.division.scene import Group, SceneState, initial_scene
from app.domain.division.session import (
    Attempt,
    CommandResult,
    SessionState,
    apply_command,
    new_session,
)
from app.domain.division.task import TaskSpec

T24_4 = TaskSpec(dividend=24, divisor=4, unit="peças")


def scene_with_counts(task: TaskSpec, counts: list[int]) -> SceneState:
    """Cena com `counts[i]` peças no grupo i+1 (peças atribuídas em ordem de id); o resto fica disponível."""
    base = initial_scene(task, scene_id="s", attempt_id="a")
    ids = [p.id for p in base.pieces]
    groups, pos = [], 0
    for g, n in zip(base.groups, counts, strict=True):
        groups.append(Group(id=g.id, piece_ids=tuple(ids[pos : pos + n])))
        pos += n
    return SceneState.model_validate(
        {**dict(base), "groups": tuple(groups), "available_piece_ids": tuple(ids[pos:])}
    )


T12_4 = TaskSpec(dividend=12, divisor=4, unit="peças")

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_raw(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def load_obs(name: str) -> NotebookObservation:
    return NotebookObservation.model_validate(load_raw(name))


def obs_with(base: str = "observacao-5-5-5-5", *, counts=None, **expression) -> NotebookObservation:
    raw = load_raw(base)
    if counts is not None:
        template = raw["groups"][0]
        raw["groups"] = [
            {**template, "group_id": f"photo-group-{i + 1}", "count": c}
            for i, c in enumerate(counts)
        ]
    raw["expression"].update(expression)
    return NotebookObservation.model_validate(raw)


# --- Sessão (Task 8) -------------------------------------------------------------------------

CONTENT = load_content()


class StubEvaluator:
    """Avaliador de explicação de teste (D2): devolve sempre a nota configurada."""

    def __init__(self, rating: str = "sufficient") -> None:
        self.rating = rating
        self.calls: list[tuple[str, str]] = []

    def evaluate(self, item_id: str, text: str) -> ExplanationResult:
        self.calls.append((item_id, text))
        return ExplanationResult(rating=self.rating, modality="text", evidence="stub")


_ENVELOPE_KEYS = {
    "command_id",
    "session_id",
    "attempt_id",
    "expected_revision",
    "expected_scene_revision",
    "turn_id",
    "turn_epoch",
}
_DEFAULT_PAYLOADS: dict[str, dict] = {
    "choose_reference_activity": {"content_version": "division-sharing-v1"},
    "run_demo_step": {"step_id": "r1-g1"},
    "finish_demonstration": {"reason": "learner_requested"},
    "move_piece": {"piece_id": "piece-01", "from_location": "available", "to_location": "group-1"},
    "check_distribution": {},
    "request_help": {"kind": "prompt", "reason": "preciso de uma pista"},
    "enter_notebook": {"intent": "try_on_paper"},
    "return_to_activity": {},
    "submit_answer": {"answer": 6, "explanation": None},
    "submit_explanation": {"modality": "text", "text": "5 grupos de 4 dão 20"},
    "continue_after_explanation": {"reason": "learner_skipped"},
    "pause_session": {},
    "close_session": {"reason": "learner_stopped"},
    "undo_move": {"target_command_id": "c0"},
    "highlight_group": {"group_id": "group-1"},
    "set_projection": {"projection": "top"},
    "apply_help": {"intervention_id": "iv1", "step_id": "r1-g1"},
    "set_thinking": {"enabled": True},
    "resume_session": {},
    "interrupt_turn": {"turn_id": "turn-1"},
    "confirm_source": {"analysis_id": "an1", "item_id": "demo-12-4"},
    "open_notebook_capture": {},
}


@dataclass(frozen=True)
class Cmd:
    """Intenção de teste: o `run` completa o envelope a partir da sessão e passa por parse_command."""

    type: str
    actor: str = "learner"
    payload: dict = field(default_factory=dict)
    envelope: dict = field(default_factory=dict)


def cmd(type_: str, actor: str = "learner", **over: Any) -> Cmd:
    """`cmd("move_piece", piece_id=..., expected_revision=0)`: chaves de envelope vão para o
    envelope, `payload=` substitui o payload inteiro, o resto é mesclado ao payload padrão."""
    envelope = {k: over.pop(k) for k in list(over) if k in _ENVELOPE_KEYS}
    payload = over.pop("payload", None)
    if payload is None:
        payload = {**_DEFAULT_PAYLOADS.get(type_, {}), **over}
    elif over:
        raise TypeError(f"campos soltos junto de payload=: {sorted(over)}")
    return Cmd(type=type_, actor=actor, payload=payload, envelope=envelope)


def _raw(session: SessionState, c: Cmd) -> dict:
    raw: dict[str, Any] = {
        "schema_version": "1.0",
        "command_id": f"cmd-{session.revision + 1}-{c.type}",
        "session_id": session.session_id,
        "attempt_id": session.active_attempt_id,
        "expected_revision": session.revision,
        "type": c.type,
        "payload": c.payload,
    }
    if c.type in SCENE_COMMANDS:
        raw["expected_scene_revision"] = session.scene_revision
    if c.actor == "tutor":
        raw["turn_id"], raw["turn_epoch"] = "turn-1", session.turn_epoch
    raw.update(c.envelope)
    return raw


def apply(
    session: SessionState, c: Cmd, *, as_actor: str | None = None, evaluator=None, content=None
) -> CommandResult:
    command = parse_command(_raw(session, c), c.actor)
    return apply_command(
        session,
        command,
        as_actor or c.actor,
        content=content or CONTENT,
        explanation_evaluator=evaluator or StubEvaluator(),
    )


def run(session: SessionState, c: Cmd, **kw) -> SessionState:
    return apply(session, c, **kw).session


def attempt(session: SessionState, kind: str) -> Attempt:
    found = [a for a in session.attempts if a.kind == kind]
    assert len(found) == 1, f"esperava 1 tentativa {kind}, achei {len(found)}"
    return found[0]


def session_after_demo_steps(n: int) -> SessionState:
    s = run(new_session("s1"), cmd("choose_reference_activity"))
    for st in demo_steps(T12_4, 3)[:n]:
        s = run(s, cmd("run_demo_step", actor="system", step_id=st.step_id))
    return s


def session_in_practice() -> SessionState:
    s = session_after_demo_steps(12)
    return run(s, cmd("finish_demonstration", actor="system", reason="completed"))


def practice_with_counts(counts: list[int]) -> SessionState:
    """Prática (24 peças) com `counts[i]` peças no grupo i+1, movidas por comandos reais."""
    s, nxt = session_in_practice(), 1
    for g, n in enumerate(counts, start=1):
        for _ in range(n):
            s = run(
                s,
                cmd(
                    "move_piece",
                    piece_id=f"piece-{nxt:02d}",
                    from_location="available",
                    to_location=f"group-{g}",
                ),
            )
            nxt += 1
    return s


def session_in_transfer() -> SessionState:
    """Atalho de teste: jornada real até a questão nova (explicação suficiente -> transfer)."""
    s = session_in_practice()
    s = run(s, cmd("submit_answer", answer=6))
    s = run(s, cmd("submit_explanation", text="4 grupos de 6 dão 24"))
    return run(s, cmd("continue_after_explanation", reason="sufficient"))


# --- Captura do caderno (increment 2, Task 2) ---------------------------------------------------


def in_notebook_capture() -> SessionState:
    """Prática -> enter_notebook(record_solution) -> open_notebook_capture."""
    s = run(session_in_practice(), cmd("enter_notebook", intent="record_solution"))
    return run(s, cmd("open_notebook_capture"))


def submitted(s: SessionState, artifact_id: str, version: int, job_id: str) -> SessionState:
    from app.domain.division.analysis import submit_artifact

    return submit_artifact(
        s,
        attempt_id=s.active_attempt_id,
        artifact_id=artifact_id,
        artifact_version=version,
        job_id=job_id,
    ).session


GUIDED_ID = "attempt-2-guided"  # demonstração é attempt-1; a guiada, attempt-2


def in_review() -> SessionState:
    """Foto 1 enviada (art-1 v1, job-1): fase notebook_review, análise pendente."""
    s = submitted(in_notebook_capture(), "art-1", 1, "job-1")
    assert s.active_attempt_id == GUIDED_ID
    return s


def result_for(job_id: str, artifact_id: str, version: int, *, attempt_id=None, obs=None):
    """Resultado coerente: a observação leva os mesmos ids do resultado (R24)."""
    from app.domain.division.analysis import AnalysisResult

    attempt_id = attempt_id or GUIDED_ID
    base = (obs or load_obs("observacao-5-5-5-5")).model_dump(mode="json")
    observation = NotebookObservation.model_validate(
        {**base, "artifact_id": artifact_id, "attempt_id": attempt_id, "artifact_version": version}
    )
    return AnalysisResult(
        job_id=job_id,
        artifact_id=artifact_id,
        artifact_version=version,
        attempt_id=attempt_id,
        observation=observation,
    )
