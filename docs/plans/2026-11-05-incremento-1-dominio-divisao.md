# Incremento 1 — Conteúdo, tipos e domínio puro da divisão · Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Núcleo Python puro (sem HTTP, banco, voz ou visão real) que carrega o pacote `division-sharing-v1`, valida comandos/cenas/observações e aplica as regras pedagógicas determinísticas, provando AC-03–06, 21–24, 27 e 39 com testes.

**Architecture:** Funções puras sobre modelos Pydantic v2 estritos e imutáveis (`frozen`). `apply_command(session, command, actor) -> CommandResult` devolve um novo `SessionState` mais eventos de domínio, ou um `DomainError`, sem efeito colateral. Persistência, idempotência por `(session_id, command_id)`, HTTP e adapters ficam para o incremento 2+. O conteúdo é JSON versionado: a parte privada (quocientes, critérios) só é lida pelo domínio, e a projeção pública nunca a inclui.

**Tech Stack:** Python 3.12, Pydantic 2.x, pytest, jsonschema (só nos testes de contrato), ruff, uv, mise.

**Spec:** `docs/spec/Spec.md` e `docs/spec/PRD.MD`, cópias de `~/Documents/ChatGPT/Hack Brasil/` (Parte I §4–7, Parte II §1–4 e §6, Parte III §2–3, Parte IV).

## Decisões assumidas (revisar antes de executar)

| # | Decisão | Default deste plano | Se você discordar |
|---|---|---|---|
| D1 | Repositório | Novo e público, `~/dev/prof-em-casa` (GitHub `prof-em-casa`), criado depois de 04/11 21h. A pasta de discovery não vira repositório de código | Trocar o nome no Task 1; nada mais muda |
| D2 | Avaliador da explicação | O domínio recebe um `ExplanationResult` pronto. Ele só avalia sozinho a modalidade `artifact`, a partir da `Verification` do desenho. Texto e voz passam por uma porta `ExplanationEvaluator` (Protocol), com stub nos testes; o LLM entra no incremento 5 | Se a v1 usar rubrica por toque, o Task 6 ganha `evaluate_choice_explanation` |
| D3 | Lacuna "pedir objetos na questão nova" | `request_help.kind` ganha `virtual_objects` e `reference_model`. Eles adicionam recurso (`support_resources`) sem subir o `assistance_level`; mesmo assim, a classificação cai em `applied_with_support` | Alterar o enum no Task 7 |
| D4 | `alternate_strategy` na questão nova | Rejeitado com `UNSUPPORTED_CONTENT` (422), porque só existe roteiro 20+4 para o item 24÷4 | Escrever roteiro para 20÷5 no conteúdo |
| D5 | Código para peça desconhecida, duplicada ou com origem errada | `INVALID_SCENE` (422). Mover para o mesmo lugar dá `NO_OP` (422) sem nova revisão | Trocar a constante no Task 2 |
| D6 | Distribuição desigual **e** incompleta (ex.: `[6,6,6,2]` + 4 disponíveis) | Intervenção `compare_groups`, porque a desigualdade vem antes do total. `check_total_use` só se aplica quando os grupos são iguais | Inverter a prioridade no Task 3 |
| D7 | Tabela de transições | Um único `TRANSITIONS` em código cobre os 30 comandos e fecha as divergências entre a tabela de fases e o catálogo. Exemplo: `request_reconstruction` leva `notebook_review` → `correction`. No incremento 1, só os handlers listados no Task 8 são executáveis; os demais devolvem `ACTION_NOT_ALLOWED` com `detail="not_in_increment_1"` | — |

## Global Constraints

- `schema_version="1.0"`; `content_version="division-sharing-v1"`; itens `demo-12-4` (12/4 → 3), `guided-24-4` (24/4 → 6), `transfer-20-5` (20/5 → 4).
- Limites do motor: dividendo inteiro ≤ 30, divisor 2–6, divisão exata, e somente itens do pacote versionado.
- Identificadores de protocolo em inglês; textos para a criança em pt-BR. Contagens são inteiras: `bool`, `float` (inclusive `5.0`) e NaN são rejeitados, e comandos não aceitam campos extras.
- `revision` e `scene_revision` começam em 0. Cada transação aceita soma exatamente +1 em `revision`; `scene_revision` só sobe quando a cena persistida muda.
- `actor` vem do contexto de credencial (`learner|tutor|system|vision_worker`) e nunca do JSON do comando.
- Os textos dos conteúdos nunca chamam as peças disponíveis de "resto".
- Fixtures sintéticas mantêm `model_ref: "synthetic-fixture-not-a-model-run"`; nenhuma vira "leitura de modelo".
- Nenhum código ou asset do `~/dev/live-roleplay`.
- Regra do usuário: antes de cada `git commit`, rodar `scripts/preflight-git.sh` (criado no Task 1) e invocar o agente `orchestrator`. REPROVADO = não commitar.

## Review Focus

1. **`bool` em campo inteiro** (`"answer": true`, `"dividend": true`): em Python, `bool` é subclasse de `int`. Espera-se `INVALID_PAYLOAD`. Teste no Task 7.
2. **Distribuição desigual e incompleta** (`[6,6,6,2]` + 4): espera-se exatamente uma intervenção (`compare_groups`, alvos `group-1` e `group-4`) e nenhum movimento automático. Teste no Task 3.
3. **`finish_demonstration` no meio da 2ª rodada** (6 movimentos, cena `[2,2,1,1]`): é aceito, porque há uma rodada completa e pedido explícito. Grava `demonstration_partial` e a tentativa guiada começa com 24 peças disponíveis, sem herdar a cena da demo. Teste no Task 8.
4. **Observação com total desenhado acima do dividendo** (`[7,7,7,7]` no 24÷4): espera-se `excess_represented=4`, nenhum `not_represented` negativo e `reconstruction_allowed=false`. Teste no Task 5.
5. **`move_piece` com `to_location` igual a um grupo de outra cena ou inexistente** (`group-9`): espera-se `INVALID_SCENE`, com o estado de entrada intacto (mesmo objeto, mesma revisão). Teste no Task 2.

---

## Estrutura de arquivos

```text
mise.toml                                    # python 3.12, uv
pyproject.toml                               # deps, pytest (pythonpath=services/backend), ruff
scripts/preflight-git.sh                     # ruff + pytest + gitleaks antes do orchestrator
docs/spec/{Spec.md,PRD.MD}                    # cópia versionada (Parte IV)
contracts/notebook-observation.schema.json   # cópia da discovery; teste garante igualdade de hash
content/division-sharing-v1/
  items.json                                 # público + privado por item
  demonstration.json                         # roteiro de 3 rodadas da demo
  interventions.json                         # escada de ajuda e textos pt-BR
services/backend/app/content/loader.py       # load_content, public_item
services/backend/app/domain/division/
  errors.py          # DomainError, ErrorCode
  scene.py           # Task, Piece, Group, SceneState, invariantes, move_piece, initial_scene
  distribution.py    # verify_distribution, select_initial_intervention
  demonstration.py   # demo_steps, apply_demo_step
  observation.py     # NotebookObservation, validate_observation, verify_observation, build_reconstruction
  assistance.py      # AssistanceLedger, apply_help_effect
  classification.py  # ExplanationResult, evaluate_artifact_explanation, classify_attempt
  commands.py        # modelos de comando (união discriminada), parse_command, ALLOWED_ACTORS
  transitions.py     # TRANSITIONS
  session.py         # SessionState, Attempt, apply_command, public_snapshot
tests/fixtures/      # cópia dos 4 JSON sintéticos da discovery
tests/contracts/     # schema × fixtures, schema × modelo Pydantic
tests/domain/        # um arquivo por módulo
tests/acceptance/test_increment_1.py         # um teste por AC, de ponta a ponta no domínio
.github/workflows/ci.yml
```

---

### Task 1: Bootstrap do repositório e pacote de conteúdo

**Files:**
- Create: `mise.toml`, `pyproject.toml`, `scripts/preflight-git.sh`, `.github/workflows/ci.yml`, `docs/spec/*`, `contracts/notebook-observation.schema.json`, `tests/fixtures/*.json`, `content/division-sharing-v1/{items,demonstration,interventions}.json`, `services/backend/app/content/loader.py`
- Test: `tests/domain/test_content.py`, `tests/contracts/test_contract_copies.py`

**Interfaces:**
- Produces:
  - `load_content(version: str = "division-sharing-v1") -> ContentPackage`, com `items: dict[str, ContentItem]`, `demonstration: DemoScript` e `interventions: dict[str, InterventionText]`.
  - `ContentItem` tem `item_id`, `role: Literal["demonstration","guided","transfer"]`, `task: TaskSpec` (`dividend`, `divisor`, `unit`), `statement: str` e `private: PrivateItem` (`quotient: int`, `explanation_criteria: list[str]`).
  - `public_item(item: ContentItem) -> dict`: sem `private`, sem quociente e sem passos resolvidos. Exceção: o item `demonstration` inclui `"demo_expression": "12 ÷ 4 = 3"`.

- [ ] **Step 1:** `uv init`, depois `uv add pydantic` e `uv add --dev pytest jsonschema ruff`. No `pyproject.toml`, `[tool.pytest.ini_options] pythonpath=["services/backend"]` e `testpaths=["tests"]`. No `mise.toml`, `python = "3.12"`. Copie Spec, PRD, schema e os 4 fixtures de `~/Documents/ChatGPT/Hack Brasil/` sem alterar nada.
- [ ] **Step 2: Testes que falham**

```python
# tests/domain/test_content.py
def test_items_have_spec_values():
    c = load_content()
    assert {k: (i.task.dividend, i.task.divisor, i.private.quotient) for k, i in c.items.items()} == {
        "demo-12-4": (12, 4, 3), "guided-24-4": (24, 4, 6), "transfer-20-5": (20, 5, 4)}

def test_public_item_hides_answers():
    c = load_content()
    for key in ("guided-24-4", "transfer-20-5"):
        dumped = json.dumps(public_item(c.items[key]), ensure_ascii=False)
        assert "private" not in dumped and "quotient" not in dumped
    assert '"6"' not in json.dumps(public_item(c.items["guided-24-4"]))
    assert public_item(c.items["demo-12-4"])["demo_expression"] == "12 ÷ 4 = 3"

def test_engine_limits_rejected():  # dividend<=30, divisor 2..6, divisão exata
    for bad in [(32, 4), (24, 7), (25, 4), (24, 1)]:
        with pytest.raises(DomainError) as e: TaskSpec(dividend=bad[0], divisor=bad[1], unit="peças")
        assert e.value.code == "UNSUPPORTED_CONTENT"

def test_no_resto_in_learner_copy():
    raw = Path("content/division-sharing-v1/interventions.json").read_text().lower()
    assert "resto" not in raw
```

```python
# tests/contracts/test_contract_copies.py
def test_fixtures_valid_against_schema(): ...   # os 3 observacao-*.json validam com Draft202012Validator
def test_fixtures_are_marked_synthetic(): ...   # model_ref == "synthetic-fixture-not-a-model-run"
```

- [ ] **Step 3:** Rode `uv run pytest tests/domain/test_content.py tests/contracts -v`. Esperado: FAIL (`ImportError`/arquivos ausentes).
- [ ] **Step 4:** Escreva os 3 JSON de conteúdo e o `loader.py`.
  - `TaskSpec` valida os limites e levanta `DomainError("UNSUPPORTED_CONTENT")`. `errors.py` (`DomainError(code: ErrorCode, detail: str | None = None)` e `ErrorCode` como `Literal` dos códigos da Parte II §8) entra neste task.
  - `items.json`: enunciados copiados de `fixtures/atividade-divisao.md`.
  - `demonstration.json`: `{"item_id":"demo-12-4","rounds":3}`.
  - `interventions.json`: textos curtos pt-BR por código: `compare_groups`, `check_total_use`, `offer_guided_round`, `relate_divisor_to_containers`, `count_one_group`, `confirm_motor_intent`, `alternate_strategy_20_4`.
- [ ] **Step 5:** Rode `uv run pytest -v`. Esperado: PASS. Depois crie `preflight-git.sh` (`ruff check . && pytest -q && gitleaks protect --staged`) e o `ci.yml` (`uv sync && uv run ruff check . && uv run pytest -q`).
- [ ] **Step 6:** Rode `scripts/preflight-git.sh`, invoque o `orchestrator` e então `git commit -m "chore: bootstrap repo e conteúdo division-sharing-v1"`.

---

### Task 2: Modelo de cena, invariantes e `move_piece`

**Files:**
- Create: `services/backend/app/domain/division/scene.py`
- Test: `tests/domain/test_scene.py`

**Interfaces:**
- Consumes: `TaskSpec` e `DomainError` (Task 1).
- Produces:
  - `PieceOrigin = Literal["content","image","learner_report","task_derived"]`.
  - `Piece(id, origin, observation_ref: str | None)`, `Group(id, piece_ids: tuple[str, ...])`.
  - `SceneState(scene_id, scene_revision: int, attempt_id, task: TaskSpec, projection: Literal["perspective","top","schematic"], interaction: Literal["learner","tutor","readonly"], groups: tuple[Group, ...], available_piece_ids: tuple[str, ...], pieces: tuple[Piece, ...], highlighted_ids: tuple[str, ...], answer_display: int | None)`. É `frozen` e `extra="forbid"`; um `model_validator` aplica as invariantes 1 e 2 da Parte II §4.
  - `initial_scene(task, *, scene_id, attempt_id, origin: PieceOrigin = "content") -> SceneState`: ids `piece-01..NN` (zero à esquerda, 2 dígitos), `group-1..D`, tudo disponível.
  - `move_piece(scene, piece_id, from_location, to_location) -> SceneState`, em que `location` é `"available"` ou um `group_id`. Levanta `DomainError("INVALID_SCENE")` para peça ou destino desconhecido, ou origem divergente, e `DomainError("NO_OP")` quando `from == to`. A cena devolvida mantém `scene_revision`, que quem incrementa é o `session`.
  - `set_projection(scene, projection) -> SceneState`.

- [ ] **Step 1: Testes que falham**

```python
def test_initial_scene_24_4():
    s = initial_scene(TaskSpec(dividend=24, divisor=4, unit="peças"), scene_id="s", attempt_id="a")
    assert len(s.pieces) == 24 and len(s.groups) == 4 and len(s.available_piece_ids) == 24
    assert s.pieces[0].id == "piece-01" and s.answer_display is None

def test_fixture_scene_satisfies_invariants():
    SceneState.model_validate_json(Path("tests/fixtures/cena-foto-5-5-5-5.json").read_text())

@pytest.mark.parametrize("mutate", ["drop_piece", "duplicate_piece", "extra_group"])
def test_invariant_violations_rejected(mutate): ...   # ValidationError

def test_move_and_errors_keep_input_intact():
    s = initial_scene(...)
    s2 = move_piece(s, "piece-01", "available", "group-1")
    assert s2.groups[0].piece_ids == ("piece-01",) and "piece-01" not in s2.available_piece_ids
    for args, code in [(("piece-99","available","group-1"),"INVALID_SCENE"),
                       (("piece-01","available","group-2"),"INVALID_SCENE"),   # origem divergente em s2
                       (("piece-02","available","group-9"),"INVALID_SCENE"),   # Review Focus 5
                       (("piece-02","available","available"),"NO_OP")]:
        with pytest.raises(DomainError) as e: move_piece(s2, *args)
        assert e.value.code == code
    assert s2.groups[0].piece_ids == ("piece-01",)  # sem mutação parcial

def test_projection_change_preserves_ids_and_counts():  # AC-09 (domínio)
    ...  # set_projection(s2, "schematic"): mesmo multiset de piece ids por grupo
```

- [ ] **Step 2:** Rode `uv run pytest tests/domain/test_scene.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente `scene.py` conforme as Interfaces acima.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e o `orchestrator`; depois `git commit -m "feat(domain): cena, invariantes e move_piece"`.

---

### Task 3: `verify_distribution` e intervenção inicial

**Files:**
- Create: `services/backend/app/domain/division/distribution.py`
- Test: `tests/domain/test_distribution.py`

**Interfaces:**
- Consumes: `SceneState` e `TaskSpec` (Task 2).
- Produces:
  - `DistributionVerification(group_counts: tuple[int, ...], assigned_total: int, available_total: int, groups_equal: bool, all_assigned: bool, valid_partition: bool)`.
  - `verify_distribution(task, scene) -> DistributionVerification`. A fórmula de `valid_partition` está na Parte I §5.
  - `InitialIntervention(code: Literal["compare_groups","check_total_use","offer_guided_round"] | None, target_ids: tuple[str, ...])`.
  - `select_initial_intervention(scene, verification) -> InitialIntervention`. Regras, nesta ordem:
    1. nenhuma peça atribuída → `offer_guided_round`;
    2. `valid_partition` → `None`;
    3. grupos desiguais → `compare_groups`, com alvos no maior e no menor grupo (empate: o primeiro na ordem). Ver D6;
    4. grupos iguais e peças disponíveis → `check_total_use`, com alvos nas peças disponíveis.

- [ ] **Step 1: Testes que falham** (helper `scene_with_counts(task, counts)` em `tests/domain/helpers.py`)

```python
def test_ac05_unequal_7_5_6_6():
    s = scene_with_counts(T24_4, [7, 5, 6, 6])
    v = verify_distribution(T24_4, s)
    assert (v.groups_equal, v.all_assigned, v.valid_partition, v.assigned_total) == (False, True, False, 24)
    i = select_initial_intervention(s, v)
    assert i.code == "compare_groups" and set(i.target_ids) == {"group-1", "group-2"}

def test_ac06_equal_5_5_5_5_with_4_available():
    s = scene_with_counts(T24_4, [5, 5, 5, 5])
    v = verify_distribution(T24_4, s)
    assert (v.groups_equal, v.all_assigned, v.available_total) == (True, False, 4)
    i = select_initial_intervention(s, v)
    assert i.code == "check_total_use" and len(i.target_ids) == 4

def test_unequal_and_incomplete_prefers_compare():  # Review Focus 2 / D6
    i = select_initial_intervention(*_sv([6, 6, 6, 2]))
    assert i.code == "compare_groups" and set(i.target_ids) == {"group-1", "group-4"}

def test_valid_and_empty(): ...  # [6,6,6,6] → valid_partition True, code None; [0,0,0,0] → offer_guided_round

def test_verification_does_not_mutate_scene(): ...  # a cena de entrada continua igual (==)
```

- [ ] **Step 2:** Rode `uv run pytest tests/domain/test_distribution.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente `distribution.py`.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e o `orchestrator`; depois `git commit -m "feat(domain): verify_distribution e intervenção inicial"`.

---

### Task 4: Roteiro da demonstração

**Files:**
- Create: `services/backend/app/domain/division/demonstration.py`
- Test: `tests/domain/test_demonstration.py`

**Interfaces:**
- Consumes: `DemoScript` (Task 1); `initial_scene` e `move_piece` (Task 2).
- Produces:
  - `DemoStep(step_id: str, round: int, piece_id: str, to_group: str)`.
  - `demo_steps(task, rounds: int) -> tuple[DemoStep, ...]`. Cada rodada move a próxima peça disponível (ordem de id) para `group-1..D`. `step_id = f"r{round}-g{g}"`.
  - `apply_demo_step(scene, step) -> SceneState`, que levanta `INVALID_SCENE` se a peça não estiver disponível.
  - `completed_rounds(scene, task) -> int`, que é o mínimo das contagens por grupo.

- [ ] **Step 1: Testes que falham**

```python
def test_ac03_full_demo():
    steps = demo_steps(T12_4, rounds=3)
    assert len(steps) == 12 and steps[0].step_id == "r1-g1"
    s = initial_scene(T12_4, scene_id="demo", attempt_id="a-demo")
    for st in steps: s = apply_demo_step(s, st)
    assert [len(g.piece_ids) for g in s.groups] == [3, 3, 3, 3] and s.available_piece_ids == ()
    assert len({p for g in s.groups for p in g.piece_ids}) == 12   # sem duplicar

def test_rounds_counted_midway():
    s = _apply_first(6)   # [2,2,1,1]
    assert completed_rounds(s, T12_4) == 1

def test_reapplying_step_rejected(): ...  # apply_demo_step com step já aplicado → INVALID_SCENE
```

- [ ] **Step 2:** Rode `uv run pytest tests/domain/test_demonstration.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente `demonstration.py`.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e o `orchestrator`; depois `git commit -m "feat(domain): roteiro da demonstração"`.

---

### Task 5: Observação estrita, `verify_observation` e reconstrução

**Files:**
- Create: `services/backend/app/domain/division/observation.py`
- Test: `tests/domain/test_observation.py`, `tests/contracts/test_observation_model.py`

**Interfaces:**
- Consumes: `TaskSpec`, `SceneState`, `Piece` e `Group` (Task 2).
- Produces:
  - `NotebookObservation`: Pydantic estrito, espelho do schema, `extra="forbid"`.
  - `validate_observation(obs) -> list[str]` faz as checagens extras que o schema não cobre e devolve códigos:
    - `BBOX_OUT_OF_BOUNDS` (x+width > 1 ou y+height > 1);
    - `DUPLICATE_GROUP_ID`;
    - `DANGLING_AMBIGUITY_PATH`;
    - `UNCERTAIN_WITHOUT_AMBIGUITY` (grupo `uncertain` sem ambiguidade em `/groups/{i}/count`).
  - `Clarification(field_path: str, value: int, provenance: Literal["learner_report"] = "learner_report")`.
  - `Verification(observation_id, status: Literal["consistent","inconsistent","inconclusive"], facts: dict, issues: tuple[str, ...], reconstruction_allowed: bool)`.
  - `verify_observation(task, quotient: int, obs, clarifications) -> Verification`. O `quotient` vem do conteúdo privado.
    - `facts` traz as chaves do exemplo da Parte II §6.
    - Use `not_represented` somente se todas as contagens forem utilizáveis e o total ≤ dividendo; use `excess_represented` se o total passar do dividendo.
    - `issues` ⊆ {`TOTAL_MISMATCH`, `GROUP_COUNT_MISMATCH`, `GROUPS_UNEQUAL`, `EXCESS_REPRESENTED`, `EXPRESSION_MISMATCH`, `WRITTEN_ANSWER_MISMATCH`}.
    - Contagens fornecidas por clarificação contam para a verificação, mas `facts["learner_reported_groups"]` lista quais vieram do aluno.
  - `build_reconstruction(task, obs, clarifications, *, scene_id, attempt_id, scene_revision) -> SceneState | ReconstructionUnavailable(reason: str)`. É elegível só se as contagens forem utilizáveis, o número de grupos for igual ao divisor e o total for ≤ dividendo. Peças da foto recebem `origin="image"` e `observation_ref=f"{obs_id}/{photo_group_id}"`; as que faltam recebem `task_derived`, com `observation_ref=None`, e ficam disponíveis. Contagens vindas de clarificação recebem `origin="learner_report"`.

- [ ] **Step 1: Testes que falham**

```python
def test_error_fixture_matches_spec_example():
    v = verify_observation(T24_4, 6, load_obs("observacao-5-5-5-5"), [])
    assert v.status == "inconsistent" and v.reconstruction_allowed
    assert v.facts == {"task_total": 24, "task_groups": 4, "observed_group_counts": [5,5,5,5],
                       "represented_total": 20, "groups_equal": True, "not_represented": 4, "written_answer": 5}
    assert set(v.issues) == {"TOTAL_MISMATCH", "WRITTEN_ANSWER_MISMATCH"}
    assert 6 not in v.facts.values()   # quociente privado não vaza para os fatos

def test_reconstruction_equals_fixture_scene():
    s = build_reconstruction(T24_4, load_obs("observacao-5-5-5-5"), [], scene_id="scene-guided-001",
                             attempt_id="attempt-guided-001", scene_revision=9)
    assert s == SceneState.model_validate_json(Path("tests/fixtures/cena-foto-5-5-5-5.json").read_text())

def test_ambiguous_is_inconclusive_and_not_reconstructable():
    v = verify_observation(T24_4, 6, load_obs("observacao-ambigua"), [])
    assert v.status == "inconclusive" and not v.reconstruction_allowed and "not_represented" not in v.facts
    assert isinstance(build_reconstruction(T24_4, load_obs("observacao-ambigua"), [], **ids), ReconstructionUnavailable)

def test_clarified_count_is_learner_report():  # AC-18 (domínio)
    c = [Clarification(field_path="/groups/2/count", value=5)]
    s = build_reconstruction(T24_4, load_obs("observacao-ambigua"), c, **ids)
    assert {p.origin for p in _pieces(s, "group-3")} == {"learner_report"}
    assert {p.origin for p in _pieces(s, "group-1")} == {"image"}

def test_corrected_is_consistent(): ...      # observacao-corrigida → consistent, issues == ()
def test_excess_drawn():  # Review Focus 4: [7,7,7,7] → excess_represented 4, sem not_represented, reconstruction False
    ...
def test_expression_only(): ...              # groups=[] → reconstruction False; status por expressão; nunca "0 desenhados"
def test_extra_checks(): ...                 # cada código de validate_observation dispara no caso mínimo
def test_float_count_rejected_by_model(): ...   # count 5.0 → ValidationError (o schema aceitava)
```

- [ ] **Step 2:** Rode `uv run pytest tests/domain/test_observation.py tests/contracts -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente `observation.py`.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e o `orchestrator`; depois `git commit -m "feat(domain): observação estrita, verificação e reconstrução"`.

---

### Task 6: Registro de ajuda e classificação da tentativa

**Files:**
- Create: `services/backend/app/domain/division/assistance.py`, `services/backend/app/domain/division/classification.py`
- Test: `tests/domain/test_assistance.py`, `tests/domain/test_classification.py`

**Interfaces:**
- Consumes: `Verification` (Task 5).
- Produces:
  - `AssistanceLevel = Literal["none","prompted","demonstrated"]`; `SupportResource = Literal["paper","virtual_objects","reference_model","counting_aid","text_rephrase"]`.
  - `AssistanceLedger(level: AssistanceLevel = "none", resources: frozenset[SupportResource] = frozenset(), reasons: tuple[str, ...] = ())`.
  - `HelpKind = Literal["prompt","visual_hint","worked_step","alternate_strategy","virtual_objects","reference_model","procedural","accessibility"]` (D3).
  - `apply_help_effect(ledger, kind, reason) -> AssistanceLedger`:
    - `prompt` e `visual_hint` → `prompted`;
    - `worked_step` e `alternate_strategy` → `demonstrated`;
    - `virtual_objects` e `reference_model` → adicionam o recurso;
    - `procedural` e `accessibility` → sem mudança.
    
    O nível nunca diminui.
  - `ExplanationResult(rating: Literal["sufficient","partial","unclear"], modality: Literal["text","voice_transcript","artifact"], evidence: str)`.
  - `ExplanationEvaluator` (Protocol): `evaluate(item_id: str, text: str) -> ExplanationResult`.
  - `evaluate_artifact_explanation(task, verification) -> ExplanationResult`: `sufficient` se `status == "consistent"` com grupos = divisor e `groups_equal`; `partial` se só a expressão estiver consistente; `unclear` nos demais casos.
  - `AttemptOutcome = Literal["applied_without_item_help","applied_with_support","answer_correct_evidence_partial","needs_review","inconclusive","not_attempted"]`.
  - `classify_attempt(answer_correct: bool | None, explanation: ExplanationResult | None, ledger: AssistanceLedger, *, evidence_disputed: bool = False) -> AttemptOutcome`. `None` em `answer_correct` significa "não respondeu". Recursos conceituais = `resources - {"paper","text_rephrase"}`.

- [ ] **Step 1: Testes que falham**

```python
def test_level_is_monotonic():
    l = apply_help_effect(AssistanceLedger(), "worked_step", "r")
    assert apply_help_effect(l, "prompt", "r").level == "demonstrated"

def test_procedural_and_accessibility_are_not_help():  # AC-24 (parte)
    l = apply_help_effect(apply_help_effect(AssistanceLedger(), "procedural", "onde envio?"), "accessibility", "x")
    assert l.level == "none" and l.resources == frozenset()

S = ExplanationResult(rating="sufficient", modality="text", evidence="5 grupos de 4 = 20")
def test_ac22_applied_without_item_help():
    paper = AssistanceLedger(resources=frozenset({"paper"}))
    assert classify_attempt(True, S, paper) == "applied_without_item_help"

def test_ac23_answer_alone_is_partial_evidence():
    assert classify_attempt(True, None, AssistanceLedger()) == "answer_correct_evidence_partial"

def test_ac24_objects_make_it_supported():
    l = apply_help_effect(AssistanceLedger(), "virtual_objects", "pediu objetos")
    assert classify_attempt(True, S, l) == "applied_with_support"

@pytest.mark.parametrize("args,expected", [
    ((False, S, AssistanceLedger()), "needs_review"),
    ((None, None, AssistanceLedger()), "not_attempted"),
    ((True, S, AssistanceLedger()), "inconclusive"),        # com evidence_disputed=True
])
def test_other_outcomes(args, expected): ...

def test_artifact_explanation_from_verification(): ...  # corrigida(20÷5 análoga) → sufficient; ambígua → unclear
```

- [ ] **Step 2:** Rode `uv run pytest tests/domain/test_assistance.py tests/domain/test_classification.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente os dois módulos.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e o `orchestrator`; depois `git commit -m "feat(domain): registro de ajuda e classificação"`.

---

### Task 7: Envelope e catálogo de comandos (AC-39)

**Files:**
- Create: `services/backend/app/domain/division/commands.py`
- Test: `tests/contracts/test_commands.py`

**Interfaces:**
- Consumes: `HelpKind` (Task 6) e `DomainError` (Task 1).
- Produces:
  - `Actor = Literal["learner","tutor","system","vision_worker"]`.
  - `CommandEnvelope`: campos comuns da Parte II §2, `extra="forbid"`, `strict=True`.
  - Um modelo `<Type>Payload` por linha do catálogo da Parte II §3, e `Command` como união discriminada por `type`. São 30 tipos, todos com payload estrito. `request_help.kind` usa `HelpKind` sem `procedural`/`accessibility`, que só o tutor registra.
  - `ALLOWED_ACTORS: dict[str, frozenset[Actor]]`, copiado das colunas L/T/S (L=learner, T=tutor, S=system).
  - `parse_command(raw: bytes | str | dict, actor: Actor) -> Command`. Erros: JSON ou schema inválido → `DomainError("INVALID_PAYLOAD")`; ator fora de `ALLOWED_ACTORS` → `DomainError("ACTION_NOT_ALLOWED")`; `actor` presente no JSON → `INVALID_PAYLOAD`. Valida `turn_id`/`turn_epoch` (obrigatórios para tutor, proibidos para learner) e `expected_scene_revision` (obrigatório nos comandos de cena: `move_piece`, `undo_move`, `highlight_group`, `highlight_available`, `set_projection`, `run_demo_step`, `apply_help`, `request_reconstruction`).

- [ ] **Step 1: Testes que falham**

```python
BASE = {"schema_version": "1.0", "command_id": "c1", "session_id": "s1", "attempt_id": "a1",
        "expected_revision": 3, "type": "check_distribution", "payload": {}}

@pytest.mark.parametrize("bad", [
    "{not json", {**BASE, "extra": 1}, {**BASE, "actor": "tutor"},
    {**BASE, "expected_revision": 3.0}, {**BASE, "expected_revision": True},         # Review Focus 1
    {**BASE, "type": "submit_answer", "payload": {"answer": True, "explanation": None}},
    {**BASE, "type": "submit_answer", "payload": {"answer": float("nan"), "explanation": None}},
    {**BASE, "type": "set_phase", "payload": {"phase": "summary"}},                  # nada de set_phase
    {**BASE, "type": "move_piece", "payload": {"piece_id": "p", "from_location": "available", "to_location": "group-1"}},  # sem expected_scene_revision
    {**BASE, "type": "run_demo_step", "payload": {"step_id": "r1-g1", "js": "alert(1)"}},
])
def test_ac39_rejects(bad):
    with pytest.raises(DomainError) as e: parse_command(bad, "learner")
    assert e.value.code in {"INVALID_PAYLOAD", "ACTION_NOT_ALLOWED"}

def test_actor_gate():
    with pytest.raises(DomainError) as e: parse_command({**BASE, "type": "highlight_group", "expected_scene_revision": 1, "payload": {"group_id": "group-1"}}, "learner")
    assert e.value.code == "ACTION_NOT_ALLOWED"

def test_catalog_complete():
    assert len(ALLOWED_ACTORS) == 30 and set(ALLOWED_ACTORS) == set(get_args(CommandType))
```

- [ ] **Step 2:** Rode `uv run pytest tests/contracts/test_commands.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente `commands.py`. Use `json.loads(..., parse_constant=_reject)` para barrar NaN/Infinity e `ConfigDict(strict=True, extra="forbid")` em todos os modelos.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e o `orchestrator`; depois `git commit -m "feat(domain): catálogo de comandos estrito"`.

---

### Task 8: Sessão, transições e `apply_command`

**Files:**
- Create: `services/backend/app/domain/division/transitions.py`, `services/backend/app/domain/division/session.py`
- Test: `tests/domain/test_transitions.py`, `tests/domain/test_session.py`

**Interfaces:**
- Consumes: tudo dos Tasks 1–7.
- Produces:
  - `Phase = Literal["source_capture","source_review","demonstration","practice","notebook","notebook_capture","notebook_review","correction","explanation","transfer","summary"]`.
  - `TRANSITIONS: dict[str, tuple[frozenset[Phase], Phase | None]]`. A chave é o tipo do comando; o valor é (fases permitidas, próxima fase), em que `None` mantém a fase atual. Fases que dependem do resultado ficam como função em `_NEXT_PHASE_RULES`, para `enter_notebook`, `return_to_activity`, `submit_answer` e `continue_after_explanation`.
  - `Attempt(attempt_id, kind: Literal["demonstration","guided","transfer"], item_id, status: Literal["active","closed"], ledger: AssistanceLedger, answer: int | None, explanation: ExplanationResult | None, demo_partial: bool)`.
  - `SessionState(session_id, content_version, phase, session_status: Literal["active","paused","closed"], interaction_mode: Literal["ready","thinking","writing"], revision: int, scene_revision: int, turn_epoch: int, active_attempt_id: str | None, attempts: tuple[Attempt, ...], scene: SceneState | None, last_event_seq: int)`, `frozen`.
  - `new_session(session_id: str) -> SessionState`: fase `source_capture`, revisões em 0, sem tentativa.
  - `DomainEvent(type: str, attempt_id: str | None, data: dict)`, com tipos da lista da Parte II §9.
  - `CommandResult(session: SessionState, events: tuple[DomainEvent, ...], scene_changed: bool)`.
  - `apply_command(session, command, actor, *, content: ContentPackage, explanation_evaluator: ExplanationEvaluator) -> CommandResult`, que pode levantar `DomainError`.
    - Ordem de guardas: (1) sessão fechada → `ACTION_NOT_ALLOWED`; (2) `attempt_id` diferente do ativo → `ATTEMPT_CHANGED`; (3) `expected_revision` diferente → `STALE_REVISION`; (4) comando de cena com `expected_scene_revision` diferente → `STALE_SCENE`; (5) fase fora de `TRANSITIONS` → `INVALID_TRANSITION`; (6) regra do handler.
    - Exceção da Parte II §2: `pause_session`, `interrupt_turn` e `close_session(learner_stopped)` pulam (3) e (4).
    - Sucesso: `revision + 1`, mais `scene_revision + 1` se a cena mudou.
  - Handlers executáveis no incremento 1: `choose_reference_activity`, `run_demo_step`, `finish_demonstration`, `move_piece`, `check_distribution`, `request_help`, `enter_notebook`, `return_to_activity`, `submit_answer`, `submit_explanation`, `continue_after_explanation`, `pause_session`, `close_session`. Os outros: D7.
  - `public_snapshot(session, content) -> dict`: sem `private`/quociente. Na fase `transfer` sem `virtual_objects`/`reference_model` no ledger, `scene` é `None`. `answer_display` só aparece se a regra 4 da Parte II §4 permitir.
  - Atalho de teste: `start_transfer(session, content) -> SessionState`, exposto só para testes como `tests/domain/helpers.py::session_in_transfer` e construído via `continue_after_explanation`.

- [ ] **Step 1: Testes que falham** (`test_transitions.py`: cada comando da Parte I §4 → fase alvo; `test_session.py`):

```python
def test_ac03_demo_flow_reaches_practice_without_answer():
    s = run(new_session("s1"), cmd("choose_reference_activity", content_version="division-sharing-v1"))
    assert s.phase == "demonstration" and s.revision == 1
    for st in demo_steps(T12_4, 3): s = run(s, cmd("run_demo_step", actor="system", step_id=st.step_id))
    s = run(s, cmd("finish_demonstration", actor="system", reason="completed"))
    snap = public_snapshot(s, CONTENT)
    assert s.phase == "practice" and len(snap["scene"]["available_piece_ids"]) == 24
    assert snap["scene"]["answer_display"] is None and "6" not in json.dumps(snap["item"])

def test_ac04_finish_before_first_round_rejected_after_allowed():
    s = _demo_after_steps(3)
    with pytest.raises(DomainError) as e: run(s, cmd("finish_demonstration", reason="learner_requested"))
    assert e.value.code == "INVALID_TRANSITION"
    r = apply(_demo_after_steps(6), cmd("finish_demonstration", reason="learner_requested"))  # Review Focus 3
    demo = attempt(r.session, "demonstration")
    assert demo.demo_partial and r.session.phase == "practice"
    assert any(e.type == "attempt_started" for e in r.events)

def test_finish_by_tutor_not_allowed(): ...      # actor tutor → ACTION_NOT_ALLOWED (catálogo L/S)

def test_ac05_ac06_check_distribution_keeps_phase():
    r = apply(_practice_with_counts([7, 5, 6, 6]), cmd("check_distribution"))
    assert r.session.phase == "practice" and not r.scene_changed
    assert r.events[0].type == "distribution_checked" and r.events[0].data["intervention"] == "compare_groups"

def test_ac21_transfer_starts_clean():
    s = session_in_transfer()
    snap = public_snapshot(s, CONTENT)
    assert snap["scene"] is None and attempt(s, "transfer").ledger == AssistanceLedger()
    assert "quotient" not in json.dumps(snap) and '"4"' not in json.dumps(snap["item"])

def test_ac24_help_recorded_before_resource():
    r = apply(session_in_transfer(), cmd("request_help", kind="virtual_objects", reason="quero peças"))
    assert [e.type for e in r.events] == ["help_granted", "scene_changed"]
    assert public_snapshot(r.session, CONTENT)["scene"] is not None

def test_alternate_strategy_in_transfer_unsupported(): ...   # D4 → UNSUPPORTED_CONTENT

def test_ac22_ac23_via_commands(): ...   # submit_answer(4) + submit_explanation(stub sufficient) → applied_without_item_help no evento attempt_evaluated; só 4 → answer_correct_evidence_partial

@pytest.mark.parametrize("mutation,code", [
    ({"expected_revision": 0}, "STALE_REVISION"),
    ({"attempt_id": "other"}, "ATTEMPT_CHANGED"),
    ({"expected_scene_revision": 0}, "STALE_SCENE"),
    ({"payload": {"piece_id": "piece-01", "from_location": "group-2", "to_location": "group-1"}}, "INVALID_SCENE"),
])
def test_ac27_errors_without_partial_mutation(mutation, code):
    s = _practice_with_counts([1, 0, 0, 0])
    with pytest.raises(DomainError) as e: apply(s, cmd("move_piece", **mutation))
    assert e.value.code == code

def test_pause_with_stale_revision_accepted(): ...   # exceção da Parte II §2; turn_epoch + 1
def test_closed_session_rejects_everything(): ...    # AC-37 (domínio): close → summary; move_piece → ACTION_NOT_ALLOWED
def test_revision_increments_once_per_command(): ... # move_piece: revision+1, scene_revision+1; check_distribution: revision+1, scene igual
```

- [ ] **Step 2:** Rode `uv run pytest tests/domain/test_transitions.py tests/domain/test_session.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente `transitions.py` (tabela completa) e `session.py` (guardas, handlers e `public_snapshot`).
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e o `orchestrator`; depois `git commit -m "feat(domain): sessão, transições e apply_command"`.

---

### Task 9: Rastreabilidade AC × teste e registro de execução

**Files:**
- Create: `tests/acceptance/test_increment_1.py`, `tests/conftest.py`, `docs/EXECUCAO.md`
- Modify: `pyproject.toml` (registra o marcador `ac`)

**Interfaces:**
- Consumes: testes dos Tasks 1–8.
- Produces:
  - Marcador `@pytest.mark.ac("AC-05")`, aplicado também aos testes AC dos tasks anteriores.
  - Hook em `conftest.py` que falha a sessão se algum id de `INCREMENT_1_ACS = {"AC-03","AC-04","AC-05","AC-06","AC-21","AC-22","AC-23","AC-24","AC-27","AC-39"}` ficar sem teste marcado e aprovado.

- [ ] **Step 1:** Em `test_increment_1.py`, escreva um teste por AC que monta a jornada inteira pelo `apply_command`, partindo de `new_session` (sem atalhos), até o ponto que o AC exige.
- [ ] **Step 2:** Rode `uv run pytest -q`. Esperado: FAIL enquanto faltarem marcadores.
- [ ] **Step 3:** Marque os testes e implemente o hook.
- [ ] **Step 4:** Rode `uv run pytest -q -m ac -rA`. Esperado: PASS, com os 10 ACs listados. Registre em `docs/EXECUCAO.md` a versão do app, `content_version`, o ambiente (Python e SO), o comando e o resultado. Escreva também "Escopo: domínio puro; sem HTTP, banco, voz ou visão reais", para atender à Parte III §1: "registra versão do app, conteúdo, prompt/modelo, ambiente".
- [ ] **Step 5:** Rode o preflight e o `orchestrator`; depois `git commit -m "test: rastreabilidade dos ACs do incremento 1"`.

---

## Cobertura e pontos cegos

| AC | Onde | Parte coberta neste incremento |
|---|---|---|
| AC-03 | Tasks 4, 8, 9 | Integral (domínio); a parte de UI fica para o incremento 3 |
| AC-04 | Tasks 4, 8, 9 | Integral |
| AC-05 / AC-06 | Tasks 3, 8, 9 | Detecção e escolha da intervenção; a fala do tutor fica para o incremento 5 |
| AC-21 | Tasks 1, 8, 9 | Projeção pública; "cores de solução" é UI (incremento 3) |
| AC-22 / AC-23 | Tasks 6, 8, 9 | Classificação. A **avaliação** de texto/voz usa stub (D2); o pedido de justificativa pelo tutor fica para o incremento 5 |
| AC-24 | Tasks 6, 8, 9 | Integral (domínio), com D3 |
| AC-27 | Tasks 2, 8, 9 | Revisão, tentativa e origem. `IDEMPOTENCY_CONFLICT` exige o armazenamento de resultados (incremento 2) |
| AC-39 | Tasks 7, 9 | Integral (domínio); a borda HTTP repete o teste no incremento 2 |

O que este incremento **não** prova, para não constar como pronto na demo:
- idempotência por `command_id` e AC-26 (incremento 2);
- qualquer coisa de ACK/fala (incrementos 3 e 5);
- leitura real de foto (incremento 4);
- qualidade da avaliação de explicação em texto livre (D2).

Extras que saem de graça: AC-09 (domínio), AC-13 (reconstrução = fixture), AC-18 (procedência `learner_report`), AC-19 (excesso e só expressão) e AC-37 (sessão fechada). Todos são cobertos no domínio, o que adianta parte do incremento 4.

## Riscos do próprio plano

- **Os 30 modelos de payload (Task 7) são o trabalho mais longo e mais mecânico.** Se o tempo apertar, mantenha a união completa, porque o AC-39 exige rejeitar tipos fora do catálogo, e reduza os payloads não executados a `{}` estrito somente onde o catálogo diz `{}`.
- **A tabela de transições (D7) muda o Spec na prática.** Ao aprovar este plano, atualize o `Spec.md` Parte I §4 com as arestas novas (`request_reconstruction` → `correction`; `return_to_activity` saindo de `explanation`), conforme a regra de governança do PRD §14.
- **Ordem de execução:** os Tasks 2–6 são independentes entre si depois do Task 1; o 7 depende só do 6 (`HelpKind`); o 8 depende de todos. Em subagentes, dá para rodar 2–5 em paralelo.
