# Incremento 2: sessão persistida, comandos autorizados, idempotência e retomada · Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pôr o domínio puro do incremento 1 atrás de uma camada `sessions/` transacional (SQLAlchemy Core, Postgres e SQLite) e de rotas FastAPI `/v1`. A entrega prova AC-26, 27, 33, 36, 37, 38 e 40 com testes de integração nos dois bancos.

**Architecture:**
- A linha `sessions.state` guarda o `SessionState` inteiro em JSON e é a fonte da verdade. Não é event sourcing.
- `session_events` é o log durável, gravado na mesma transação. `attempts` é um modelo de leitura derivado.
- `SessionService` aplica a ordem da Spec Parte II §2: autorizar → chave idempotente → hash do corpo → schema e guardas → transação curta (estado + eventos + resultado) → resposta.
- A API é uma casca fina: só traduz cabeçalhos em `ActorContext` e mapeia `ErrorCode` → HTTP. O domínio continua sem I/O.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy 2 (Core), psycopg 3, FastAPI, httpx (TestClient), uvicorn, pytest. Postgres 17 local (`/opt/homebrew/bin`) para o cluster descartável dos testes.

**Spec:** `docs/spec/Spec.md`: Parte I §4 e §8; Parte II §1, §2, §3, §5 (ACK), §8 e §9; Parte III §3 e §4 (AC-26, 27, 33, 36, 37, 38 e 40); Parte IV. Também valem `docs/plans/MVP-ROADMAP.md` (G1–G7) e `docs/DECISOES-INCREMENTO-1.md`.

## Decisões deste plano

A Spec é ambígua nos pontos abaixo, e este plano decide cada um. Cada decisão traz o custo se estiver errada.

- **Decisão P1:** o estado da sessão é persistido como snapshot JSON (`sessions.state`), validado com `SessionState.model_validate` na leitura. Eventos e `attempts` são gravados na mesma transação; não há reconstrução por replay de eventos. **Custo se errado:** migrar para event sourcing exige um replayer, mas o log já existe e está completo.
- **Decisão P2:** a credencial da demo é um token opaco de sessão. Não há provedor de auth.
  - `POST /v1/sessions` é anônimo e devolve `session_token`, calculado como `base64url(HMAC-SHA256(SESSION_TOKEN_SECRET, "session-token:" + request_id))`. No banco fica só o `sha256` do token, em `session_credentials`.
  - O `request_id` tem de ser de alta entropia: regex `^[A-Za-z0-9_-]{22,128}$`. Por isso o replay do `POST` devolve o mesmo token sem guardá-lo em claro.
  - Tutor, sistema e worker usam tokens de serviço por ator, vindos de variáveis de ambiente.
  - **Custo se errado:** o `request_id` vira segredo equivalente ao token. Trocar por auth Supabase muda só `app/sessions/credentials.py` e `app/api/deps.py`.
- **Decisão P3:** o controlador ativo (Parte II §1, `connection_generation`) é identificado pelo cabeçalho `X-Controller-Id`.
  - O valor é o `request_id` que criou a sessão ou que fez o último `claim-control`.
  - Toda escrita do aluno (comandos e `render-receipts`) exige o controlador vigente; senão a resposta é 403 `CONTROL_LOST`.
  - Essa checagem faz parte da autorização, então vem antes da deduplicação. Leituras (`GET`) não exigem o cabeçalho.
  - **Custo se errado:** o envelope teria de ganhar `connection_generation`, o que é uma mudança de schema 1.0.
- **Decisão P4:** `claim-control` é uma mutação da camada `sessions`, não um comando do catálogo.
  - Exige `expected_revision` e faz `connection_generation += 1`, `turn_epoch += 1` e `revision += 1`.
  - Grava o evento `control_claimed`. É uma extensão da lista da Parte II §9, como `returned_to_activity` no incremento 1.
  - É idempotente por `request_id`.
  - **Custo se errado:** se a revisão não devesse subir, a correção é tirar um `+1` e ajustar 2 testes.
- **Decisão P5:** só resultados **aceitos** são gravados em `command_results`. Uma rejeição (409/422/403) não ocupa o `command_id`, e reenviar o mesmo id reavalia o comando.
  - O hash idempotente é `sha256` do JSON canônico de `{"actor": actor, "body": corpo}`, com `sort_keys`, `separators=(",", ":")` e `ensure_ascii=False`.
  - O mesmo corpo vindo de outro ator dá `IDEMPOTENCY_CONFLICT`.
  - **Custo se errado:** guardar rejeições exige uma coluna `http_status` (que já existe) e um ramo a mais.
- **Decisão P6:** AC-33 entra no incremento 2 pelo caminho domínio + caso de uso, sem rotas de upload e de análise (que ficam no incremento 4).
  - O domínio ganha `open_notebook_capture`, `cancel_capture` e `retake_notebook_photo`, mais duas operações internas fora do catálogo: `submit_artifact` e `apply_analysis_result`.
  - `SessionState` ganha `active_artifact`, `observation` e `verification`.
  - O worker é um stub que chama `SessionService.complete_analysis`.
  - **Custo se errado:** o incremento 4 refaz a assinatura de 2 funções. O domínio já fica pronto para as rotas.
- **Decisão P7:** resultado de análise obsoleto (`superseded`) só muda o status do job. Não muda a sessão nem gera evento de sessão: o `analysis_superseded` já foi emitido pelo `retake_notebook_photo` que causou a troca.
  - Resultado que chega com a sessão em pausa fica `ready` e não aplicado (`applied=false`). O `resume_session` aplica esse resultado **na mesma transação** e com **uma só** revisão, via `bump_revision=False`.
  - Resultado que chega com a sessão fechada é guardado como `ready` e nunca aplicado.
  - **Custo se errado:** a reconciliação em transação separada gera uma revisão a mais, que o cliente veria como `STALE_REVISION`.
- **Decisão P8:** a projeção para o aluno é uma lista de campos permitidos por tipo de evento; o padrão é negar.
  - Nunca saem para o aluno: `answer`, `correct`, `outcome`, `rating`, `evidence`, `issues`, `quotient` e `private`.
  - `attempt_evaluated` aparece só com o envelope e `data: {}`. Assim a sequência continua contínua, sem revelar o resultado.
  - É criada a rota extra `GET /v1/sessions/{id}/events?after_seq=` para a retomada incremental. A Spec §8 não a lista.
  - Os atores de serviço recebem o `data` completo.
  - **Custo se errado:** liberar um campo é mudar uma linha da lista de permitidos.
- **Decisão P9:** o avaliador de explicação de produção, no incremento 2, é o `UnavailableEvaluator`. Ele levanta `DomainError("PROVIDER_UNAVAILABLE")` e a API responde 503. Os testes injetam o `StubEvaluator`, e o LLM entra no incremento 5 (G4/G5: sem fingir avaliação).
  - **Custo se errado:** a demo do incremento 3 não consegue fechar a explicação por texto até o incremento 5. Um stub configurável resolve isso em 10 linhas.
- **Decisão P10:** o schema tem uma fonte para cada banco.
  - Postgres usa os arquivos SQL de `supabase/migrations/`. SQLite usa `metadata.create_all` de `app/db/schema.py`.
  - Um teste reflete o Postgres migrado e o compara com `metadata`: tabelas, colunas, nulabilidade e índices únicos.
  - Todas as tabelas têm RLS habilitado e nenhuma policy, porque só o backend acessa.
  - **Custo se errado:** drift entre os dois bancos. O teste de comparação existe para pegá-lo.
- **Decisão P11:** a sessão demo expira em 24 h (Parte I §9). Uma sessão expirada responde 404 `NOT_FOUND` em todas as rotas. A limpeza dos dados (AC-46) fica para o incremento 4.
  - **Custo se errado:** o cliente pode precisar de um código específico para expiração. Seria trocar o código em 1 ponto.
- **Decisão P12:** `session_id` divergente é tratado em duas camadas.
  - No domínio: `apply_command` rejeita com `INVALID_PAYLOAD` (fecha a pendência do incremento 1).
  - Na API: id da URL diferente do id do corpo dá 400 `INVALID_PAYLOAD`. Credencial de outra sessão dá 404 `NOT_FOUND`, sem revelar se a sessão existe (AC-40).
  - `_Revision` ganha teto `le=2_147_483_647` (INTEGER do Postgres).
  - **Custo se errado:** trocar 1 código de erro.

## Global Constraints

- `schema_version="1.0"`; `content_version="division-sharing-v1"`; base HTTP `/v1`.
- `revision` e `scene_revision` começam em 0. Cada transação aceita soma exatamente +1 em `revision`. Polling, ACK e resultado obsoleto não incrementam a revisão (Parte II §1).
- Idempotência por `(session_id, command_id)`, imposta por restrição única. O reenvio do mesmo corpo devolve o resultado original "mesmo se revisão avançou", com o cabeçalho `Idempotent-Replay: true`. O mesmo id com outro corpo dá `IDEMPOTENCY_CONFLICT` (409).
- Ordem obrigatória: autenticar/autorizar → procurar chave → validar hash → schema e guardas → transação (estado + eventos + resultado) → resposta.
- `actor` vem da credencial e nunca do JSON. Um corpo com `actor` dá `INVALID_PAYLOAD`.
- O envelope de erro é `{"command_id"?: str, "error": {"code", "retryable", "current_revision"?, "current_scene_revision"?}}`.
- Mapeamento HTTP da Parte II §8:

  | HTTP | Códigos |
  |---|---|
  | 400 | `INVALID_PAYLOAD` |
  | 401 | `UNAUTHENTICATED` |
  | 403 | `ACTION_NOT_ALLOWED`, `CONTROL_LOST` |
  | 404 | `NOT_FOUND` |
  | 409 | `STALE_REVISION`, `STALE_SCENE`, `ATTEMPT_CHANGED`, `IDEMPOTENCY_CONFLICT`, `INVALID_TRANSITION` |
  | 413 | `IMAGE_TOO_LARGE` |
  | 415 | `UNSUPPORTED_IMAGE` |
  | 422 | `INVALID_SCENE`, `NO_OP`, `UNSUPPORTED_CONTENT` |
  | 429 | `SESSION_LIMIT` |
  | 503 | `PROVIDER_UNAVAILABLE` |

- `retryable` é `true` só para `STALE_REVISION`, `STALE_SCENE`, `ATTEMPT_CHANGED`, `INVALID_TRANSITION` e `PROVIDER_UNAVAILABLE`.
- Eventos nunca copiam binário, fala integral, URL assinada ou texto livre da criança (Parte II §9; AC-45).
- Testes rodam em SQLite **e** em um Postgres descartável, criado sob `tmp_path_factory`. Nunca em `/tmp`.
- Segredos (G7): `op://Personal/prof-em-casa/<VAR>`. O repositório recebe `.env.tmpl`; nunca `.env`.
- Dependências entram com `uv add` (o lockfile é `uv.lock`).
- Commits seguem R1 de `docs/DECISOES-INCREMENTO-1.md`: o implementador roda `scripts/preflight-git.sh` e commita; o agente `orchestrator` entra antes do PR e do merge.
- O domínio (`app/domain/`) não importa nada de `sqlalchemy`, `fastapi` nem `app.sessions`.

## Review Focus

1. **Duplicatas concorrentes do mesmo comando**, por duas abas ou por um retry que corre em paralelo com o original. Espera-se exatamente um efeito: o perdedor recebe o replay do vencedor, sem 500 por `IntegrityError`. Teste no Task 4 (threads, nos dois bancos).
2. **Corpo igual em JSON, mas com outra ordem de chaves ou outro espaçamento.** Espera-se replay, não `IDEMPOTENCY_CONFLICT`. Teste no Task 4.
3. **Reinício do servidor entre comandos** (engine e serviço novos sobre o mesmo banco). Espera-se o mesmo snapshot e o mesmo `ledger.resources` (frozenset), a mesma cena e o mesmo `return_phase`. Teste no Task 1 (round trip) e no Task 4.
4. **Token da sessão A com a URL da sessão B e um `command_id` conhecido de B.** Espera-se 404 com corpo idêntico ao de uma sessão inexistente, e nenhum dado de B. Teste no Task 7.
5. **Ex-controlador envia `pause_session` (controle imediato) depois de perder o controle.** Espera-se 403 `CONTROL_LOST`: a exceção de revisão antiga vale só para o controlador vigente (Parte II §2). Teste no Task 5.

---

## Estrutura de arquivos

```text
pyproject.toml                         # + fastapi, sqlalchemy, psycopg[binary], uvicorn; dev: httpx
.env.tmpl                              # DATABASE_URL, SESSION_TOKEN_SECRET, SERVICE_TOKEN_* (op://)
.github/workflows/ci.yml               # instala postgresql e exporta TUTOR_REQUIRE_PG=1
supabase/migrations/20261105120000_incremento_2_sessoes.sql
services/backend/app/db/
  schema.py        # metadata + tabelas (fonte do SQLite; comparada com o Postgres)
  engine.py        # make_engine, create_schema (sqlite: create_all + BEGIN IMMEDIATE)
  migrate.py       # apply_migrations (Postgres local/teste)
services/backend/app/domain/division/
  analysis.py      # NOVO: ActiveArtifact, AnalysisResult, submit_artifact, apply_analysis_result
  state.py, session.py, handlers.py, commands.py   # modificados (Task 2)
services/backend/app/sessions/
  context.py       # ActorContext, Clock, IdFactory
  errors.py        # SessionError
  credentials.py   # derive_session_token, hash_token
  repository.py    # leitura/escrita Core (sessão, eventos, resultados, attempts, jobs)
  projection.py    # project_event, session_view
  service.py       # SessionService (casos de uso)
  evaluator.py     # UnavailableEvaluator
services/backend/app/settings.py      # Settings.from_env()
services/backend/app/api/
  app.py           # create_app
  deps.py          # authenticate(headers) -> ActorContext
  errors.py        # HTTP_STATUS, RETRYABLE, error_response
  routes.py        # rotas /v1
  schemas.py       # modelos de resposta (OpenAPI)
scripts/export_openapi.py              # escreve contracts/openapi.json
contracts/openapi.json                 # gerado e commitado; teste de drift
tests/integration/conftest.py          # cluster Postgres descartável + fixture db_url parametrizada
tests/integration/test_*.py
tests/acceptance/test_increment_2.py
tests/ac_traceability.py               # + INCREMENT_2_ACS
docs/EXECUCAO.md, docs/DECISOES-INCREMENTO-2.md
```

---

### Task 1: Dependências, schema, migration e bancos de teste

**Files:**
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`
- Create: `services/backend/app/db/{__init__,schema,engine,migrate}.py`, `supabase/migrations/20261105120000_incremento_2_sessoes.sql`, `tests/integration/conftest.py`
- Test: `tests/integration/test_db_schema.py`

**Interfaces:**
- Produces:
  - `metadata: sqlalchemy.MetaData` com as tabelas abaixo. Colunas JSON usam `JSON().with_variant(JSONB, "postgresql")`; timestamps usam `DateTime(timezone=True)` e são sempre gravados e lidos em UTC.
    - `sessions`: `session_id` text PK, `content_version`, `create_request_id` UNIQUE, `state` JSON, `revision`, `scene_revision`, `phase`, `session_status`, `turn_epoch`, `last_event_seq`, `active_attempt_id` (nulo), `connection_generation` (int, ≥1), `controller_id`, `created_at`, `updated_at`, `expires_at`. Tem CHECK `revision >= 0`.
    - `session_credentials`: `token_hash` PK, `session_id` FK, `actor` CHECK `= 'learner'`, `created_at`.
    - `attempts`: PK `(session_id, attempt_id)`, `kind`, `item_id`, `status`, `assistance_level`, `support_resources` JSON, `updated_revision`.
    - `session_events`: `event_id` PK, `session_id` FK, `event_seq`, `revision`, `type`, `actor`, `command_id` (nulo), `attempt_id` (nulo), `occurred_at`, `data` JSON. UNIQUE `(session_id, event_seq)`.
    - `command_results`: PK `(session_id, command_id)`, `kind` CHECK em `('command','claim_control')`, `body_hash`, `actor`, `principal_id`, `http_status`, `response` JSON, `revision`, `created_at`.
    - `render_receipts`: PK `(session_id, receipt_id)`, `effect_id`, `command_id`, `scene_revision`, `connection_generation`, `status`, `outcome` CHECK em `('accepted','stale')`, `received_at`.
    - `artifacts`: `artifact_id` PK, `session_id` FK, `attempt_id`, `purpose` CHECK em `('source','notebook')`, `version` (≥1), `content_hash` (nulo), `object_key` (nulo), `created_at`, `expires_at`. UNIQUE `(session_id, attempt_id, purpose, version)`.
    - `analysis_jobs`: `job_id` PK, `session_id` FK, `artifact_id` FK, `request_id`, `status` CHECK em `('queued','running','ready','needs_clarification','failed','superseded')`, `executions` (padrão 0), `applied` bool (padrão false), `error_code` (nulo), `created_at`, `updated_at`. UNIQUE `(session_id, request_id)`.
    - `observations`: `observation_id` PK, `job_id` FK UNIQUE, `session_id`, `attempt_id`, `artifact_id`, `document` JSON, `created_at`.
  - `make_engine(url: str) -> Engine`. Em `sqlite`: `PRAGMA foreign_keys=ON`; `StaticPool` quando a URL é em memória; desliga o BEGIN do pysqlite e emite `BEGIN IMMEDIATE` no evento `begin` (receita oficial do SQLAlchemy), para serializar os escritores. Em `postgresql+psycopg`: pool padrão.
  - `create_schema(engine: Engine) -> None`: em SQLite, `metadata.create_all`; em Postgres, `apply_migrations`.
  - `apply_migrations(engine: Engine, directory: Path = MIGRATIONS_DIR) -> list[str]`: aplica, em ordem, os `*.sql` ainda ausentes de `schema_migrations(version text primary key, applied_at timestamptz)` e devolve as versões aplicadas. Pode rodar de novo sem efeito.
  - Fixtures em `tests/integration/conftest.py`:
    - `pg_cluster` (escopo de sessão): `initdb -U postgres --auth=trust -E UTF8 --locale=C` em `tmp_path_factory.mktemp("pg")`. Sobe com `pg_ctl -w -o "-c listen_addresses=127.0.0.1 -c port=<livre> -c unix_socket_directories=''" start`; para com `stop -m fast` no teardown. Cria o banco `template_tutor` já migrado.
    - Binários: `PG_BIN` → `shutil.which("initdb")` → `/opt/homebrew/bin`. Sem binários, `skip`; com `TUTOR_REQUIRE_PG=1`, `fail`.
    - `db_url` (parametrizado `["sqlite", "postgres"]`, escopo de função): SQLite em arquivo dentro de `tmp_path`; Postgres com `CREATE DATABASE t_<uuid12> TEMPLATE template_tutor` e `DROP DATABASE ... WITH (FORCE)` no fim.
    - `engine(db_url) -> Engine` já com schema.

- [ ] **Step 1:** Rode `uv add fastapi sqlalchemy "psycopg[binary]" uvicorn` e `uv add --dev httpx`. Confirme que `uv run pytest -q` continua com 505 passed.
- [ ] **Step 2: Testes que falham** em `tests/integration/test_db_schema.py`

```python
def test_postgres_schema_matches_metadata(pg_engine):          # P10
    reflected = MetaData(); reflected.reflect(pg_engine)
    for name, table in metadata.tables.items():
        got = reflected.tables[name]
        assert {c.name: c.nullable for c in got.columns} == {c.name: c.nullable for c in table.columns}
        assert _unique_sets(got) == _unique_sets(table)      # PK + UNIQUE como frozensets de colunas
    assert set(reflected.tables) - {"schema_migrations"} == set(metadata.tables)

def test_migrations_are_idempotent(pg_engine):
    assert apply_migrations(pg_engine) == []

def test_rls_enabled_on_every_table(pg_engine):
    rows = pg_engine.connect().execute(text(
        "select relname from pg_class where relkind='r' and relnamespace='public'::regnamespace "
        "and not relrowsecurity")).scalars().all()
    assert set(rows) <= {"schema_migrations"}

def test_unique_event_seq_per_session(engine): ...   # 2º insert (s1, seq 1) → IntegrityError; (s2, seq 1) passa

@pytest.mark.parametrize("journey", ALL_DOMAIN_JOURNEYS)  # demo completa, prática [7,5,6,6], caderno, transfer com ajuda
def test_session_state_json_round_trip(journey):           # Review Focus 3
    for state in journey():
        dumped = json.loads(json.dumps(state.model_dump(mode="json")))
        assert SessionState.model_validate(dumped) == state
```

`ALL_DOMAIN_JOURNEYS` é uma lista de geradores de estados, montados com `tests/domain/helpers.py` (`run`, `cmd`, `session_in_transfer`).

- [ ] **Step 3:** Rode `uv run pytest tests/integration/test_db_schema.py -v`. Esperado: FAIL (`ModuleNotFoundError: app.db`).
- [ ] **Step 4:** Implemente `schema.py`, `engine.py`, `migrate.py`, a migration SQL e o `conftest.py`.
  - A migration começa por `create table` em `public` e termina com `alter table <t> enable row level security;` para cada tabela.
  - No `ci.yml`, acrescente `sudo apt-get install -y postgresql` e `PG_BIN=$(ls -d /usr/lib/postgresql/*/bin)`, e exporte `TUTOR_REQUIRE_PG=1`.
- [ ] **Step 5:** Rode `uv run pytest tests/integration -v`. Esperado: PASS nas duas variantes de `db_url`, sem nenhum `skip` de Postgres nesta máquina.
- [ ] **Step 6:** Rode `scripts/preflight-git.sh` e depois `git commit -m "feat(db): schema, migration supabase e bancos de teste sqlite/postgres"`.

---

### Task 2: Pendências do domínio e fluxo de captura do caderno

**Files:**
- Create: `services/backend/app/domain/division/analysis.py`
- Modify: `commands.py` (`MAX_REVISION`; `load_json_object` público), `session.py` (guarda de `session_id`), `state.py` (campos novos), `handlers.py` (3 handlers)
- Test: `tests/domain/test_analysis.py`, `tests/domain/test_session.py` (acréscimos), `tests/contracts/test_commands.py` (acréscimos)

**Interfaces:**
- Consumes: `apply_command`, `verify_observation`, `NotebookObservation` e `Verification` (incremento 1).
- Produces:
  - `MAX_REVISION = 2_147_483_647`, com `_Revision = Annotated[StrictInt, Field(ge=0, le=MAX_REVISION)]`.
  - `load_json_object(raw: bytes | str | dict) -> dict[str, Any]`: é o atual `_load` renomeado (o nome antigo fica como alias). A camada `sessions` usa essa função para ler `command_id` antes do `parse_command`.
  - `apply_command`: logo depois da checagem de ator, `command.session_id != session.session_id` → `DomainError("INVALID_PAYLOAD", "session_id mismatch")`.
  - Em `state.py`:
    - `ActiveArtifact(artifact_id: str, artifact_version: int (≥1), job_id: str)`, frozen.
    - `SessionState` ganha `active_artifact: ActiveArtifact | None = None`, `observation: NotebookObservation | None = None` e `verification: Verification | None = None`.
    - `public_snapshot` ganha `"analysis": None | {"artifact_id", "artifact_version", "status": "pending"|"available"}`, sem `verification.issues` nem `facts`.
  - Handlers novos (as fases já estão em `TRANSITIONS`):
    - `open_notebook_capture`: `notebook` → `notebook_capture`, sem evento.
    - `cancel_capture`: `notebook_capture` → `notebook`, sem evento.
    - `retake_notebook_photo`: `notebook_review` → `notebook_capture`. Emite `analysis_superseded {artifact_id, job_id, reason: "retake"}` quando há `active_artifact`, e zera `active_artifact`, `observation` e `verification`.
  - Em `analysis.py`:
    - `AnalysisResult(job_id: str, artifact_id: str, artifact_version: int, attempt_id: str, observation: NotebookObservation)`, frozen.
    - `Disposition = Literal["applied", "superseded", "deferred", "discarded"]`.
    - `AnalysisApplication(disposition: Disposition, result: CommandResult | None)`.
    - `submit_artifact(session: SessionState, *, attempt_id: str, artifact_id: str, artifact_version: int, job_id: str) -> CommandResult`.
      - Exige a fase `notebook_capture` (senão `INVALID_TRANSITION`), `attempt_id == active_attempt_id` (senão `ATTEMPT_CHANGED`) e sessão não fechada (senão `ACTION_NOT_ALLOWED`).
      - Leva a `notebook_review`, define `active_artifact` e emite `artifact_submitted {artifact_id, artifact_version, job_id}`.
      - Soma +1 em `revision`.
    - `apply_analysis_result(session, result: AnalysisResult, *, content: ContentPackage, bump_revision: bool = True) -> AnalysisApplication`. Regras, nesta ordem:
      1. Sessão `closed` → `discarded`.
      2. `result.attempt_id != active_attempt_id`, `active_artifact is None`, ou `artifact_id`, `job_id` ou `artifact_version` diferentes de `active_artifact` → `superseded`.
      3. Sessão `paused` → `deferred`.
      4. Senão, `applied`: `verification = verify_observation(item.task, item.private.quotient, obs, [])`. Grava `observation` e `verification` e emite `analysis_completed {job_id, artifact_id, artifact_version, observation_id, verification_status, issues, reconstruction_allowed}`. A fase continua `notebook_review`, e `revision` soma +1 só se `bump_revision`.

      Nos casos 1 a 3, `result is None` e o estado não muda.

- [ ] **Step 1: Testes que falham**

```python
def test_session_id_mismatch_rejected():                       # P12
    s = session_in_practice()
    with pytest.raises(DomainError) as e: apply(s, cmd("check_distribution", session_id="other"))
    assert e.value.code == "INVALID_PAYLOAD"

def test_revision_upper_bound():
    raw = {**valid_envelope("check_distribution"), "expected_revision": 2**31}
    with pytest.raises(DomainError) as e: parse_command(raw, "learner")
    assert e.value.code == "INVALID_PAYLOAD"

def test_capture_flow_reaches_review():                        # tests/domain/test_analysis.py
    s = in_notebook_capture()        # prática → enter_notebook(record_solution) → open_notebook_capture
    r = submit_artifact(s, attempt_id=s.active_attempt_id, artifact_id="art-1", artifact_version=1, job_id="job-1")
    assert r.session.phase == "notebook_review" and r.session.revision == s.revision + 1
    assert [e.type for e in r.events] == ["artifact_submitted"]

def test_ac33_v1_result_after_v2_submitted_is_superseded():
    v2 = with_v2_submitted()         # v1 enviado → retake_notebook_photo → v2 enviado
    app = apply_analysis_result(v2, result_for("job-1", "art-1", 1), content=CONTENT)
    assert app.disposition == "superseded" and app.result is None

def test_ac33_result_for_changed_attempt_is_superseded(): ...  # attempt_id da guiada, sessão já em transfer
def test_paused_result_is_deferred(): ...                      # disposition == "deferred", estado igual
def test_closed_result_is_discarded(): ...
def test_applied_result_records_verification_without_quotient():
    app = apply_analysis_result(in_review(), result_for(..., obs=load_obs("observacao-5-5-5-5")), content=CONTENT)
    assert app.disposition == "applied" and app.result.session.verification.status == "inconsistent"
    assert "quotient" not in json.dumps(public_snapshot(app.result.session, CONTENT))
    assert public_snapshot(app.result.session, CONTENT)["analysis"]["status"] == "available"

def test_bump_revision_false_keeps_revision(): ...
def test_retake_supersedes_and_clears_observation(): ...
def test_domain_has_no_io_imports():                           # Global Constraint
    src = "\n".join(p.read_text() for p in DOMAIN_DIR.rglob("*.py"))
    assert not re.search(r"^\s*(from|import) (sqlalchemy|fastapi|app\.sessions)", src, re.M)
```

- [ ] **Step 2:** Rode `uv run pytest tests/domain tests/contracts -q`. Esperado: FAIL nos testes novos.
- [ ] **Step 3:** Implemente as mudanças. Remova `open_notebook_capture`, `cancel_capture` e `retake_notebook_photo` do conjunto `not_in_increment_1`, e atualize os testes do incremento 1 que esperavam esse detalhe para esses três comandos.
- [ ] **Step 4:** Rode `uv run pytest -q`. Esperado: PASS (505 + novos).
- [ ] **Step 5:** Rode o preflight e depois `git commit -m "feat(domain): session_id, teto de revisão e fluxo de captura com análise"`.

---

### Task 3: Projeção pública de eventos e snapshot

**Files:**
- Create: `services/backend/app/sessions/{__init__,projection}.py`
- Test: `tests/domain/test_projection.py` (puro, sem banco)

**Interfaces:**
- Consumes: `EventType` e `public_snapshot` (Task 2).
- Produces:
  - `Audience = Literal["learner", "service"]`.
  - `EventRecord(event_id: str, session_id: str, event_seq: int, revision: int, type: str, actor: str, command_id: str | None, attempt_id: str | None, occurred_at: datetime, data: dict)`, frozen dataclass.
  - `LEARNER_EVENT_FIELDS: dict[str, frozenset[str]]`: a lista de permitidos (P8). Ela cobre todos os `EventType` mais `control_claimed`; um tipo ausente da lista recebe `data: {}`. Valores fixados:
    - `answer_submitted`: `{}`;
    - `attempt_evaluated`: `{}`;
    - `explanation_evaluated`: `{"modality"}`;
    - `analysis_completed`: `{"artifact_id", "artifact_version", "observation_id"}`;
    - `help_granted`: `{"kind", "assistance_level", "support_resources"}`;
    - `distribution_checked`: todos os campos atuais. São fatos da cena que a criança já vê.
    - Os demais tipos: o implementador lista as chaves que o handler emite, sem nenhuma de `FORBIDDEN_LEARNER_KEYS`.
  - `FORBIDDEN_LEARNER_KEYS = frozenset({"answer", "correct", "outcome", "rating", "evidence", "issues", "quotient", "private", "reason_text"})`.
  - `project_event(event: EventRecord, audience: Audience) -> dict`: devolve `{"event_id", "event_seq", "revision", "type", "attempt_id", "occurred_at", "data"}` (sem `actor` nem `command_id` para o aluno). Para `service`, devolve o `data` completo e também `actor` e `command_id`.
  - `session_view(state: SessionState, content: ContentPackage, *, connection_generation: int) -> dict`: devolve `public_snapshot(...) | {"connection_generation": connection_generation}`.

- [ ] **Step 1: Testes que falham**

```python
@pytest.mark.parametrize("journey", ALL_DOMAIN_JOURNEYS + [transfer_correct, transfer_wrong])
def test_learner_projection_never_contains_forbidden_keys(journey):
    for event in events_of(journey):                       # DomainEvent → EventRecord sintético
        assert not (_all_keys(project_event(event, "learner")) & FORBIDDEN_LEARNER_KEYS)

def test_correct_and_wrong_answers_project_identically():
    right = project_event(answer_event(answer=4, correct=True), "learner")
    wrong = project_event(answer_event(answer=3, correct=False), "learner")
    assert strip_ids(right) == strip_ids(wrong)

def test_every_event_type_has_an_explicit_rule():
    assert set(get_args(EventType)) | {"control_claimed"} == set(LEARNER_EVENT_FIELDS)

def test_service_audience_keeps_full_data(): ...
def test_unknown_event_type_projects_empty_data(): ...
```

- [ ] **Step 2:** Rode `uv run pytest tests/domain/test_projection.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente `projection.py`.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e depois `git commit -m "feat(sessions): projeção pública de eventos sem correção nem resposta"`.

---

### Task 4: `SessionService`: criação, comando transacional e idempotência

**Files:**
- Create: `services/backend/app/sessions/{context,errors,credentials,repository,service,evaluator}.py`
- Test: `tests/integration/test_session_commands.py`

**Interfaces:**
- Consumes: Task 1 (`metadata`, `make_engine`), Task 2 (`load_json_object`, `apply_command`), Task 3 (`EventRecord`, `session_view`).
- Produces:
  - `Clock = Callable[[], datetime]` (UTC) e `IdFactory = Callable[[str], str]`. O padrão de `IdFactory` é `prefix + "_" + secrets.token_urlsafe(12)`.
  - `ActorContext(actor: Actor, principal_id: str, session_id: str | None, controller_id: str | None)`, frozen. Atores de serviço têm `session_id=None`.
  - `SessionError(code: ErrorCode, detail: str | None = None, *, current_revision: int | None = None, current_scene_revision: int | None = None, command_id: str | None = None)`.
  - `derive_session_token(secret: bytes, request_id: str) -> str` e `hash_token(token: str) -> str` (sha256 hex).
  - `CreatedSession(session_id: str, session_token: str, controller_id: str, connection_generation: int, snapshot: dict, replay: bool)`.
  - `CommandOutcome(status_code: int, body: dict, replay: bool)`.
  - Classe `SessionService(engine, content, evaluator, *, token_secret: bytes, clock: Clock, ids: IdFactory, session_ttl: timedelta = timedelta(hours=24))`, com os métodos:
    - `create_session(request_id: str, content_version: str) -> CreatedSession`. Se `content_version` não for a vigente: `UNSUPPORTED_CONTENT`. Se o `request_id` não seguir a regex P2: `INVALID_PAYLOAD`. O replay do mesmo `request_id` devolve a mesma sessão com `replay=True`. `controller_id = request_id`, `connection_generation = 1`.
    - `get_snapshot(ctx: ActorContext, session_id: str) -> dict`.
    - `execute_command(ctx: ActorContext, session_id: str, raw_body: bytes) -> CommandOutcome`, cujo corpo é o de sucesso da Parte II §2: `{"command_id", "status": "accepted", "revision", "scene_revision", "event_seq", "scene_effect"}`. `scene_effect` é `{"effect_id": f"effect-{scene_revision}", "requires_ack": "render_applied"}` quando a cena mudou; senão, `null`.
  - Funções de `repository.py` (todas recebem `Connection`):
    - `load_session(conn, session_id, *, for_update: bool) -> SessionRow | None`, com `SessionRow(state, connection_generation, controller_id, expires_at)`. `for_update` aplica `with_for_update()` no Postgres.
    - `save_session(conn, *, expected_revision: int, row: SessionRow, now) -> None`: faz `UPDATE ... WHERE session_id=:id AND revision=:expected`. Se `rowcount != 1`, levanta `SessionError("STALE_REVISION")`.
    - `append_events(conn, session_id, events, *, first_seq, revision, actor, command_id, now) -> list[EventRecord]`.
    - `upsert_attempts(conn, state) -> None`.
    - `find_result(conn, session_id, command_id)` e `insert_result(conn, ...)`.
  - O algoritmo de `execute_command` segue a ordem da Global Constraint:
    1. Autorização: `NOT_FOUND` se a sessão não existe, expirou, ou se `ctx.session_id` não é `None` e é diferente da URL. `CONTROL_LOST` se o ator é `learner` e `ctx.controller_id != row.controller_id`.
    2. `load_json_object` e extração de `command_id`. Se o `session_id` do corpo difere da URL: `INVALID_PAYLOAD`.
    3. Hash (P5).
    4. `find_result`: com hash igual, faz replay (mesmo `status_code` e `body`, `replay=True`); com hash diferente, `IDEMPOTENCY_CONFLICT`.
    5. `parse_command`.
    6. `with engine.begin()`: lê a sessão `for_update` e repete o `find_result`. Roda `apply_command` (um `DomainError` vira `SessionError` com as revisões atuais, e nada é gravado), `save_session`, `append_events`, `upsert_attempts` e `insert_result`.
    7. Se a transação falha com `IntegrityError` em `command_results`, volta ao passo 4 **uma** vez.

- [ ] **Step 1: Testes que falham** (todos parametrizados por `db_url`; o serviço é criado com `StubEvaluator`, relógio fixo e ids sequenciais)

```python
@pytest.mark.ac("AC-26")
def test_ac26_same_command_twice_one_effect(svc, learner_in_practice):
    ctx, sid = learner_in_practice
    body = move_body(sid, rev=R, scene_rev=S, cmd_id="c-move-1")
    first = svc.execute_command(ctx, sid, body); again = svc.execute_command(ctx, sid, body)
    assert again.replay and again.body == first.body and first.body["revision"] == R + 1
    snap = svc.get_snapshot(ctx, sid)
    assert snap["revision"] == R + 1 and count_events(svc, sid, "scene_changed", after=R) == 1
    assert pieces_in(snap, "group-1") == ["piece-01"]

def test_replay_after_revision_advanced_returns_original(...): ...   # AC-36 (serviço)
def test_key_order_and_whitespace_do_not_change_hash(...): ...       # Review Focus 2

@pytest.mark.ac("AC-27")
@pytest.mark.parametrize("variant,code", [
    ("same_id_other_body", "IDEMPOTENCY_CONFLICT"), ("stale_revision", "STALE_REVISION"),
    ("other_attempt", "ATTEMPT_CHANGED"), ("wrong_origin", "INVALID_SCENE")])
def test_ac27_errors_leave_no_partial_mutation(svc, learner_in_practice, variant, code):
    before = dump_tables(svc.engine, sid)               # sessions, session_events, command_results, attempts
    with pytest.raises(SessionError) as e: svc.execute_command(ctx, sid, variant_body(variant))
    assert e.value.code == code and dump_tables(svc.engine, sid) == before
    if code == "STALE_REVISION": assert e.value.current_revision == R

def test_rejected_command_id_is_not_reserved(...): ...  # STALE com c-9; depois c-9 com a revisão certa → accepted (P5)
def test_same_body_from_other_actor_conflicts(...): ... # P5
def test_url_body_session_mismatch_invalid_payload(...): ...
def test_concurrent_duplicates_single_effect(...):      # Review Focus 1: 8 threads, mesmo corpo
    results = run_parallel(8, lambda: svc.execute_command(ctx, sid, body))
    assert len({json.dumps(r.body, sort_keys=True) for r in results}) == 1
    assert sum(not r.replay for r in results) == 1
def test_concurrent_distinct_commands_same_revision_one_wins(...): ...  # 1 accepted, demais STALE_REVISION
def test_restart_reloads_identical_state(...): ...      # Review Focus 3: SessionService novo sobre o mesmo db_url
def test_create_session_replay_returns_same_token(...): ...
def test_unavailable_evaluator_maps_to_provider_unavailable(...): ...   # P9
```

- [ ] **Step 2:** Rode `uv run pytest tests/integration/test_session_commands.py -v`. Esperado: FAIL (`ImportError`).
- [ ] **Step 3:** Implemente os módulos. `UnavailableEvaluator.evaluate` levanta `DomainError("PROVIDER_UNAVAILABLE", "explanation evaluator not configured")`.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS nos dois bancos.
- [ ] **Step 5:** Rode o preflight e depois `git commit -m "feat(sessions): comando transacional com idempotência e guarda de revisão"`.

---

### Task 5: Autenticação, controle, ACK e retomada por eventos

**Files:**
- Modify: `services/backend/app/sessions/{service,repository,credentials}.py`
- Create: `services/backend/app/settings.py`
- Test: `tests/integration/test_session_access.py`

**Interfaces:**
- Consumes: Task 4.
- Produces:
  - `Settings(database_url: str, session_token_secret: bytes, service_token_hashes: dict[str, Actor])`, com `Settings.from_env()`. Lê `DATABASE_URL`, `SESSION_TOKEN_SECRET` e `SERVICE_TOKEN_TUTOR|SYSTEM|VISION_WORKER`. Um token de serviço ausente desliga aquele ator.
  - `SessionService.authenticate(bearer: str | None, controller_id: str | None) -> ActorContext`:
    - Token ausente ou desconhecido dá `UNAUTHENTICATED`.
    - Hash em `service_token_hashes` dá um ator de serviço com `session_id=None`.
    - Hash em `session_credentials` dá `learner`, com `session_id` e `controller_id` vindos do cabeçalho.
  - `claim_control(ctx, session_id, request_id: str, expected_revision: int) -> dict`. Devolve `{"controller_id": request_id, "connection_generation", "revision", "turn_epoch"}`. Regras P4: `STALE_REVISION` se a revisão não confere; `ACTION_NOT_ALLOWED` se a sessão está `closed`. É idempotente por `(session_id, request_id)` em `command_results` com `kind='claim_control'`. Não exige ser o controlador atual, porque assumir o controle é justamente o caso da segunda aba.
  - `record_render_receipt(ctx, session_id, receipt: RenderReceipt) -> dict`. Devolve `{"receipt_id", "outcome": "accepted"|"duplicate"|"stale"}` e nunca muda a revisão.
    - `RenderReceipt` é o modelo estrito do ACK da Parte II §5: `extra="forbid"`; `status` em `render_applied|animation_completed|settled_by_interruption|render_failed`.
    - `stale` quando `connection_generation` difere da vigente ou `scene_revision` é maior que a atual. `duplicate` quando o `receipt_id` já existe.
  - `list_events(ctx, session_id, after_seq: int = 0, limit: int = 200) -> list[dict]`: `project_event` com `audience = "learner" if ctx.actor == "learner" else "service"`.

- [ ] **Step 1: Testes que falham** (parametrizados por `db_url`)

```python
@pytest.mark.ac("AC-38")
def test_ac38_second_tab_takes_control(svc, two_tabs):
    tab_a, tab_b, sid = two_tabs                        # mesmo token, controller ids diferentes
    out = svc.claim_control(tab_b, sid, request_id=RID_B, expected_revision=R)
    assert out["connection_generation"] == 2 and out["turn_epoch"] == E + 1 and out["revision"] == R + 1
    with pytest.raises(SessionError) as e: svc.execute_command(tab_a, sid, move_body(sid, rev=R + 1, ...))
    assert e.value.code == "CONTROL_LOST"
    assert svc.record_render_receipt(tab_b_receipt_ctx, sid, receipt(generation=1))["outcome"] == "stale"
    assert svc.get_snapshot(tab_a, sid)["revision"] == R + 1   # sem bifurcação: uma linha de revisão

def test_old_controller_cannot_pause(...): ...           # Review Focus 5: CONTROL_LOST
def test_claim_control_replay_is_idempotent(...): ...
def test_claim_control_with_stale_revision(...): ...
def test_receipt_duplicate_and_no_revision_change(...): ...
def test_events_after_seq_projected_for_learner(...):   # retomada incremental; sem chaves proibidas
    evs = svc.list_events(learner, sid, after_seq=3)
    assert [e["event_seq"] for e in evs] == list(range(4, last + 1))

@pytest.mark.ac("AC-40")
def test_ac40_service_level_cross_session(...): ...      # contexto de A em B: get, command, claim, receipt, events → NOT_FOUND
def test_expired_session_is_not_found(...): ...          # P11, relógio + 24 h + 1 s
def test_unknown_and_missing_token_unauthenticated(...): ...
def test_tutor_service_token_runs_tutor_command(...): ...  # highlight_group com turn_id/turn_epoch
```

- [ ] **Step 2:** Rode `uv run pytest tests/integration/test_session_access.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente. `claim_control` grava o evento `control_claimed {connection_generation, turn_epoch}`. Ele atualiza `state.turn_epoch` e `revision` pelo `SessionState.with_changes`, porque o domínio não tem comando para isso.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e depois `git commit -m "feat(sessions): auth por token, claim-control, ACK e eventos projetados"`.

---

### Task 6: Casos de uso de artefato e análise (AC-33, AC-37)

**Files:**
- Modify: `services/backend/app/sessions/{service,repository}.py`
- Test: `tests/integration/test_session_analysis.py`

**Interfaces:**
- Consumes: Task 2 (`submit_artifact`, `apply_analysis_result`, `AnalysisResult`) e Task 4.
- Produces:
  - `submit_notebook_artifact(ctx, session_id, *, request_id: str, expected_revision: int, attempt_id: str) -> dict`. Devolve `{"artifact_id", "artifact_version", "job_id", "revision"}`.
    - Só o ator `learner` e o controlador vigente.
    - `artifact_version = 1 + max(version)` por `(session_id, attempt_id, 'notebook')`.
    - Cria o artefato (`object_key=None` no incremento 2) e o job `queued` na mesma transação da mudança de fase (outbox implícito: Parte II §8).
    - Replay por `(session_id, request_id)` devolve o mesmo dicionário.
  - `complete_analysis(ctx, job_id: str, observation: NotebookObservation) -> Disposition`.
    - Só o ator `vision_worker`; outro ator dá `ACTION_NOT_ALLOWED`.
    - Numa transação: trava a sessão, grava `observations` e chama `apply_analysis_result`.
    - Status do job por disposição: `applied` → `ready` ou `needs_clarification` (conforme `observation.status`) e `applied=true`; `deferred` → o mesmo status com `applied=false`; `discarded` → `ready` com `applied=false`; `superseded` → `superseded`.
    - Um job já terminal devolve a disposição anterior, sem efeito.
  - Reconciliação: dentro de `execute_command`, quando o comando aceito é `resume_session`, procure um job com `applied=false`, status `ready|needs_clarification` e `job_id == state.active_artifact.job_id`. Se houver, aplique-o com `bump_revision=False` na mesma transação (P7) e anexe os eventos depois de `session_resumed`.
  - `retake_notebook_photo` aceito também marca como `superseded` o job do artefato anterior, na mesma transação.

- [ ] **Step 1: Testes que falham** (parametrizados por `db_url`; jornadas montadas por `execute_command`, sem atalho de estado)

```python
@pytest.mark.ac("AC-33")
def test_ac33_slow_v1_does_not_overwrite_v2(svc, learner_in_capture, worker):
    v1 = svc.submit_notebook_artifact(learner, sid, request_id="up-1", expected_revision=R, attempt_id=A)
    v2 = retake_and_submit_v2(...)                              # retake_notebook_photo (→ notebook_capture) → submit v2
    assert svc.complete_analysis(worker, v1["job_id"], obs_for(v1)) == "superseded"
    snap = svc.get_snapshot(learner, sid)
    assert snap["analysis"]["artifact_id"] == v2["artifact_id"] and snap["analysis"]["status"] == "pending"
    assert job_status(svc, v1["job_id"]) == "superseded"
    assert svc.complete_analysis(worker, v2["job_id"], obs_for(v2)) == "applied"

@pytest.mark.ac("AC-33")
def test_ac33_result_after_attempt_changed_is_superseded(...): ...   # retake → cancel → return → submit_answer(6) → continue → transfer

@pytest.mark.ac("AC-37")
def test_ac37_paused_keeps_result_until_resume(svc, ...):
    pause(...); assert svc.complete_analysis(worker, job, obs) == "deferred"
    assert svc.get_snapshot(learner, sid)["revision"] == R_paused       # sem mudança nem evento
    out = resume(...)
    assert out.body["revision"] == R_paused + 1                          # uma revisão (P7)
    assert last_event_types(svc, sid, 2) == ["session_resumed", "analysis_completed"]

@pytest.mark.ac("AC-37")
def test_ac37_closed_session_ignores_late_result(...): ...   # discarded; revisão e eventos iguais
@pytest.mark.ac("AC-37")
def test_ac37_tutor_command_rejected_while_paused_or_closed(...): ...   # highlight_group → ACTION_NOT_ALLOWED; tabelas iguais
def test_submit_artifact_replay_same_job(...): ...
def test_complete_analysis_twice_is_idempotent(...): ...
def test_only_vision_worker_completes(...): ...
```

- [ ] **Step 2:** Rode `uv run pytest tests/integration/test_session_analysis.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS.
- [ ] **Step 5:** Rode o preflight e depois `git commit -m "feat(sessions): artefato, análise com supersessão e reconciliação na retomada"`.

---

### Task 7: Rotas FastAPI, erros HTTP e OpenAPI

**Files:**
- Create: `services/backend/app/api/{__init__,app,deps,errors,routes,schemas}.py`, `scripts/export_openapi.py`, `contracts/openapi.json`, `.env.tmpl`
- Test: `tests/integration/test_http_api.py`, `tests/contracts/test_openapi.py`

**Interfaces:**
- Consumes: Tasks 4–6 (`SessionService`, `SessionError`, `Settings`).
- Produces:
  - `create_app(service: SessionService) -> FastAPI` e `app = create_app(build_service(Settings.from_env()))`, montado sob demanda por `get_app()` para não ler o ambiente no import.
  - `HTTP_STATUS: dict[ErrorCode, int]` e `RETRYABLE: frozenset[ErrorCode]` (Global Constraints). `error_response(err: SessionError | DomainError) -> JSONResponse`.
  - Um handler de `RequestValidationError` e de JSON inválido responde 400 `INVALID_PAYLOAD` no envelope comum. Nenhuma rota responde o 422 padrão do FastAPI.
  - Rotas:

    | Rota | Corpo | Resposta |
    |---|---|---|
    | `POST /v1/sessions` | `{"request_id", "content_version"}` estrito | 201 `CreatedSession` sem `replay`; o replay leva `Idempotent-Replay: true` |
    | `GET /v1/sessions/{session_id}` | — | 200 `session_view` |
    | `POST /v1/sessions/{session_id}/commands` | corpo cru | 200 `CommandAccepted`; o replay leva `Idempotent-Replay: true` |
    | `POST /v1/sessions/{session_id}/claim-control` | `{"request_id", "expected_revision"}` | 200 |
    | `POST /v1/sessions/{session_id}/render-receipts` | `RenderReceipt` | 200 `{"receipt_id", "outcome"}` |
    | `GET /v1/sessions/{session_id}/events?after_seq=` | — | 200 `{"events": [...]}` |

    A rota de comandos lê `await request.body()` e entrega os bytes ao serviço, preservando a rejeição de chave duplicada e NaN. Ela documenta o corpo com `openapi_extra={"requestBody": {"content": {"application/json": {"schema": TypeAdapter(Command).json_schema(ref_template=...)}}}}`.
  - Cabeçalhos: `Authorization: Bearer <token>` e `X-Controller-Id` (P3).
  - `scripts/export_openapi.py` escreve `contracts/openapi.json` (indentação 2, `sort_keys`). O teste compara esse arquivo com `app.openapi()`.
  - `.env.tmpl`: `DATABASE_URL=op://Personal/prof-em-casa/DATABASE_URL`, `SESSION_TOKEN_SECRET=op://Personal/prof-em-casa/SESSION_TOKEN_SECRET` e `SERVICE_TOKEN_{TUTOR,SYSTEM,VISION_WORKER}=op://Personal/prof-em-casa/SERVICE_TOKEN_<ATOR>`.

- [ ] **Step 1: Testes que falham** (`TestClient(create_app(svc))`, parametrizados por `db_url`)

```python
@pytest.mark.ac("AC-26")
def test_http_replay_header_and_single_effect(client, practice): ...   # 2× POST: 200/200, 2º com Idempotent-Replay: true

@pytest.mark.ac("AC-27")
@pytest.mark.parametrize("variant,status,code", [
    ("same_id_other_body", 409, "IDEMPOTENCY_CONFLICT"), ("stale_revision", 409, "STALE_REVISION"),
    ("other_attempt", 409, "ATTEMPT_CHANGED"), ("wrong_origin", 422, "INVALID_SCENE")])
def test_ac27_http_codes(client, practice, variant, status, code):
    r = client.post(cmd_url, content=variant_body(variant), headers=h)
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert client.get(sess_url, headers=h).json()["revision"] == R

@pytest.mark.ac("AC-39")
@pytest.mark.parametrize("raw", [b"{", b'{"a":1,"a":2}', NAN_BODY, EXTRA_FIELD_BODY, ACTOR_IN_BODY, UNKNOWN_TYPE_BODY])
def test_ac39_http_edge_rejects_without_mutation(client, practice, raw):
    r = client.post(cmd_url, content=raw, headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PAYLOAD"

@pytest.mark.ac("AC-40")
@pytest.mark.parametrize("method,path", ALL_SESSION_ROUTES)   # GET, commands, claim-control, render-receipts, events
def test_ac40_token_a_on_session_b(client, two_sessions, method, path):
    r = call(client, method, path.format(id=B.id), token=A.token, body=b_known_command(B))
    ghost = call(client, method, path.format(id="ses_doesnotexist"), token=A.token, body=...)
    assert r.status_code == ghost.status_code == 404 and r.json() == ghost.json()   # Review Focus 4
    assert B.id not in r.text

def test_missing_token_401(...): ...
def test_url_body_session_mismatch_400(...): ...
def test_fastapi_validation_mapped_to_invalid_payload(...): ...   # POST /v1/sessions com campo extra → 400
def test_provider_unavailable_503(...): ...                     # submit_explanation com UnavailableEvaluator
```

```python
# tests/contracts/test_openapi.py
def test_openapi_committed_matches_app():
    assert json.loads(Path("contracts/openapi.json").read_text()) == create_app(fake_service()).openapi()
def test_openapi_has_routes_and_command_union():
    spec = create_app(fake_service()).openapi()
    assert {"/v1/sessions", "/v1/sessions/{session_id}/commands", "/v1/sessions/{session_id}/claim-control",
            "/v1/sessions/{session_id}/render-receipts", "/v1/sessions/{session_id}/events"} <= set(spec["paths"])
    assert len(command_schema(spec)["oneOf"]) == 30
```

- [ ] **Step 2:** Rode `uv run pytest tests/integration/test_http_api.py tests/contracts/test_openapi.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente. Gere o contrato com `uv run python scripts/export_openapi.py`.
- [ ] **Step 4:** Rode o mesmo comando. Esperado: PASS. Teste também à mão, com `SESSION_TOKEN_SECRET=dev DATABASE_URL=sqlite:///<job tmp>/dev.db uv run uvicorn app.api.app:get_app --factory --app-dir services/backend`: `curl -X POST localhost:8000/v1/sessions` responde 201.
- [ ] **Step 5:** Rode o preflight e depois `git commit -m "feat(api): rotas /v1, envelope de erro e contrato OpenAPI"`.

---

### Task 8: Aceite ponta a ponta, rastreabilidade e registro de execução

**Files:**
- Create: `tests/acceptance/test_increment_2.py`, `docs/DECISOES-INCREMENTO-2.md`
- Modify: `tests/ac_traceability.py`, `tests/test_ac_traceability.py`, `docs/EXECUCAO.md`, `README.md` (seção "Rodar a API")

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces:
  - `INCREMENT_2_ACS = frozenset({"AC-26", "AC-27", "AC-33", "AC-36", "AC-37", "AC-38", "AC-40"})` e `REQUIRED_ACS = INCREMENT_1_ACS | INCREMENT_2_ACS`, que passa a ser o conjunto usado em `missing()`.
  - Um teste de aceite por AC do incremento 2. Cada um percorre a jornada só por HTTP: parte de `POST /v1/sessions` e avança por `choose_reference_activity` → `run_demo_step` (token de serviço `system`) → `finish_demonstration` → prática. Exceção: AC-33 e AC-37 usam `complete_analysis` do worker stub, porque não há rota de análise neste incremento (P6). Todos são parametrizados por `db_url`.
  - O teste de AC-36 simula a resposta perdida: envia um `move_piece`, descarta a resposta e envia o mesmo corpo de novo. Espera replay, com a peça movida uma vez só. Em seguida, `GET` do snapshot e `GET /events?after_seq=` devolvem o estado confirmado.

- [ ] **Step 1:** Escreva `test_increment_2.py` com os 7 testes marcados `@pytest.mark.ac(...)` e `@pytest.mark.acceptance`. Acrescente em `test_ac_traceability.py` um caso de pytester: sem teste aprovado para AC-38, a execução completa falha e lista `AC-38`.
- [ ] **Step 2:** Rode `uv run pytest -q`. Esperado: FAIL até `REQUIRED_ACS` incluir o incremento 2 e todos os marcadores existirem.
- [ ] **Step 3:** Atualize o hook. Em `docs/EXECUCAO.md`, acrescente a seção "Incremento 2" no mesmo formato:
  - Identificação: commit, Python, SO, Postgres 17.11, SQLite (`sqlite3.sqlite_version`).
  - Comandos e resultados.
  - Cobertura por AC: qual teste e qual parte foi comprovada.
  - "Não comprovado neste incremento": rotas de upload, análise e voice-token; prévia de gesto descartada na UI (AC-36, parte de UI, incremento 3); ACK e fala (AC-28–32); limpeza de 24 h (AC-46).

  Registre em `docs/DECISOES-INCREMENTO-2.md` as P1–P12 e as decisões tomadas durante a execução, no formato R<n> do incremento 1.
- [ ] **Step 4:** Rode `uv run pytest -q -m ac -rA` e `TUTOR_REQUIRE_PG=1 uv run pytest -q`. Esperado: PASS, com os 17 ACs listados e nenhum `skip` de Postgres. Rode também `uv run ruff check .`. Copie as contagens para o `EXECUCAO.md`.
- [ ] **Step 5:** Rode o preflight e depois `git commit -m "test: aceite e rastreabilidade do incremento 2; EXECUCAO atualizado"`. O PR para `develop` passa antes pelo `orchestrator`.

---

## Cobertura por AC

| AC | Tasks | Parte coberta neste incremento |
|---|---|---|
| AC-26 | 4, 7, 8 | Integral (serviço e HTTP, dois bancos, concorrência) |
| AC-27 | 2, 4, 7, 8 | Integral, inclusive `IDEMPOTENCY_CONFLICT`, que faltava no incremento 1 |
| AC-33 | 2, 6, 8 | Domínio e worker stub: v1 obsoleto e tentativa trocada. A rota `/analyses` e o worker real ficam no incremento 4 |
| AC-36 | 4, 5, 8 | Servidor: replay sem duplicar e snapshot ou eventos para reconciliar. O descarte da prévia na tela é do incremento 3 |
| AC-37 | 2, 6, 8 | Pausa (adiada até a retomada), sessão fechada (descartado) e tutor rejeitado |
| AC-38 | 5, 7, 8 | Geração, perda de escrita e de ACK, sem bifurcação. A UI de leitura da 2ª aba é do incremento 3 |
| AC-40 | 5, 7, 8 | Sessão, comandos, controle, ACK e eventos. Upload, análise e voice-token entram nos incrementos 4 e 5, com o mesmo `authenticate` |

## Análise crítica

**Problemas**

- **A fase revela a correção.** A Parte I §4 manda `submit_answer` → `explanation` quando a resposta está correta e manter `transfer` quando está errada. A mudança de fase no snapshot conta para a criança se ela acertou, antes de qualquer feedback autorizado. Pela Parte I §7, feedback corretivo após erro na questão nova marca apoio.
  - A projeção (P8) esconde os campos, mas não esconde a fase.
  - Este plano **não** resolve isso, porque é comportamento normativo da Spec. Fica sinalizado como conflito para decisão do usuário. A saída mais barata seria uma fase `answer_pending` que não muda no erro.
- **AC-33 e AC-37 forçam parte do incremento 4 para dentro do incremento 2:** o fluxo de captura, a supersessão e a reconciliação. O risco é a assinatura de `submit_artifact` mudar quando entrarem o upload real e o hash do objeto. Isso foi mitigado deixando `content_hash` e `object_key` nulos e recebendo `request_id` desde já.
- **O snapshot JSON (P1) acopla o banco ao formato Pydantic.** Renomear um campo de `SessionState` quebra sessões já gravadas. Para a demo (TTL de 24 h) isso é aceitável; para o piloto, exigiria um `state_version` e migração de dados.
- **Tokens de serviço globais.** Um processo de tutor com token válido age em qualquer sessão. Isso é aceitável até o incremento 5, quando o token de voz restrito à sala (`voice-token`) deve vincular o tutor a uma sessão.
- **SQLite não reproduz o Postgres:** bloqueio por linha, timezone e JSONB. Por isso o Postgres descartável é obrigatório na máquina local e no CI (`TUTOR_REQUIRE_PG=1`). Rodar só em SQLite esconderia bugs de `FOR UPDATE`.

**Oportunidades**

- `contracts/openapi.json`, commitado e com teste de drift, permite ao incremento 3 gerar `apps/web/src/api/generated` com `openapi-typescript`, sem escrever tipos à mão (Parte IV, "Fronteiras").
- `GET /events?after_seq=` deixa a retomada barata, sem baixar o snapshot inteiro a cada polling de 2 s. Também serve de base para o tutor do incremento 5 montar o contexto do turno.
- O teste de concorrência do Task 4 pode virar o ensaio de "dez sessões simultâneas" da Parte III §6, mudando só o número de threads.
- `session_events` sem texto livre já adianta parte do AC-45 (inspeção automatizada de logs). Basta um teste que varra `data` procurando campos proibidos.

## Conflitos com a Spec encontrados

1. **A fase revela a correção na questão nova** (Parte I §4 × Parte I §7 e Parte II §8 "sem resposta oculta"). Ver a Análise crítica.
2. **`claim-control` exige `expected_revision`,** mas a Parte II §1 diz que a revisão só sobe por mutação do domínio. P4 decide que a revisão sobe.
3. **`POST /sessions` anônimo e idempotente por `request_id`** contra "outra identidade sem vínculo não pode recuperá-lo" (Parte II §2): antes da criação não existe identidade. P2 transforma o `request_id` em segredo.
4. **O envelope de comando não tem campo de controlador ou geração,** mas o AC-38 exige que o primeiro controlador perca a escrita. P3 usa um cabeçalho.
5. **Retomar com análise pendente produz dois fatos** (`session_resumed` e `analysis_completed`), enquanto a Parte II §1 pede "incremento único por transação". P7 aplica os dois numa única revisão.
6. **A lista de eventos da Parte II §9 não tem evento de controle.** O plano acrescenta `control_claimed`, como o incremento 1 fez com `returned_to_activity`. As duas extensões precisam entrar no `Spec.md`, junto com D3 e R16.
