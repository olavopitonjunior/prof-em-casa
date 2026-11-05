# Registro de execução: incremento 1 (domínio da divisão por partilha)

Escopo: domínio puro; sem HTTP, banco, voz ou visão reais

Este registro atende à Spec, Parte III §1 ("registra versão do app, conteúdo, prompt/modelo,
ambiente e resultado"). Todas as fixtures são sintéticas (`model_ref` =
`synthetic-fixture-not-a-model-run`). Nenhuma criança participou de qualquer teste, e este
documento não afirma ganho de aprendizagem.

## Identificação

| Item | Valor |
|---|---|
| Versão do app (`pyproject.toml`) | 0.1.0 |
| `content_version` | `division-sharing-v1` (itens `demo-12-4`, `guided-24-4`, `transfer-20-5`) |
| `schema_version` dos comandos | 1.0 |
| Prompt / modelo | nenhum; a avaliação da explicação usa um stub determinístico (D2) |
| Python | 3.12.14 (`uv run python -V`) |
| Sistema operacional | macOS 26.6.2 (build 25G83), arm64 |
| Ferramentas | uv 0.12.5, pytest 9.2.0 |
| Código sob teste | branch `feat/incremento-1-dominio`, commit de código `fa34945` (base `457cb8c`); o commit seguinte altera só este registro |
| Data | 2026-11-05 |

## Comandos e resultado

| Comando | Resultado |
|---|---|
| `uv run pytest -q` | 505 passed |
| `uv run pytest -q -m ac -rA` | 45 passed, 460 deselected; os 10 ACs com teste marcado e aprovado |
| `uv run ruff check .` | All checks passed |

## Como a rastreabilidade funciona

- Cada AC do incremento 1 (AC-03, 04, 05, 06, 21, 22, 23, 24, 27 e 39) tem testes marcados com
  `@pytest.mark.ac("AC-xx")`. Há um teste de aceite por AC em
  `tests/acceptance/test_increment_1.py`: a jornada parte de `new_session` e avança só por
  comandos (`apply_command`), sem atalho de estado. Os testes unitários dos Tasks 1 a 8 que
  cobrem o mesmo AC também levam o marcador.
- O hook está em `tests/ac_traceability.py` (registrado por `tests/conftest.py`). Ao final da
  sessão, se algum id de `INCREMENT_1_ACS` não tiver ao menos um teste marcado que tenha passado
  nesta execução, a sessão termina com falha e imprime os ids ausentes.
- Quando o hook vale: só em execução completa, ou seja, sem `-k`, `--deselect`, `--lf`, `--ff`,
  `--sw` ou `--co`, sem arquivo, diretório ou nodeid fora de `testpaths`, e com `-m` vazio ou
  exatamente `-m ac`. `-p no:ac-traceability` desliga o hook de forma explícita. Rodar um arquivo ou um `-k` isolado não falha por AC de outro arquivo.
  O comportamento do próprio hook é testado em `tests/test_ac_traceability.py` (pytester).

## Cobertura por AC (domínio)

| AC | Teste de aceite | Parte comprovada |
|---|---|---|
| AC-03 | `test_ac03_complete_demonstration` | demonstração de 12 ÷ 4 termina em `[3,3,3,3]`, 0 disponíveis; o item guiado começa sem resposta |
| AC-04 | `test_ac04_advance_request_before_and_after_the_first_round` | pedir para avançar antes da 1ª rodada é recusado; depois, avança como demonstração parcial, com o pedido registrado (`demo_finish_reason`, `requested_by`) |
| AC-05 | `test_ac05_unequal_practice_detects_inequality_without_acting` | `[7,5,6,6]`: detecta desigualdade, escolhe `compare_groups`, não move peça nem marca domínio |
| AC-06 | `test_ac06_equal_groups_with_available_pieces_ask_about_the_total` | `[5,5,5,5]` com 4 disponíveis: grupos iguais, total incompleto, `check_total_use`, sem "resto" |
| AC-21 | `test_ac21_new_question_starts_clean` | 20 ÷ 5 sem cena, sem resposta, sem ajuda prévia, projeção pública sem quociente |
| AC-22 | `test_ac22_correct_answer_with_sufficient_explanation_and_paper_is_without_item_help` | `applied_without_item_help` com recurso `paper` no registro e nível `none`. Não comprovado aqui: o resumo "sem alegar domínio nem retenção", pois este incremento ainda não tem resumo |
| AC-23 | `test_ac23_bare_answer_is_partial_evidence_and_never_sufficient_alone` | resposta isolada fica `answer_correct_evidence_partial` |
| AC-24 | `test_ac24_help_is_recorded_before_the_resource_and_marks_support` | ajuda registrada antes da cena; resultado `applied_with_support` |
| AC-27 | `test_ac27_rejected_commands_leave_no_partial_mutation` | revisão velha, tentativa trocada, cena velha, origem da peça incorreta: erro e sessão intacta |
| AC-39 | `test_ac39_invalid_json_extra_fields_and_unauthorized_actions_change_nothing` | JSON inválido, campo extra, tipo fora do catálogo, ator não autorizado: rejeitados, nada executa |

## Onda final (correções da revisão)

Itens F1 a F9 da revisão final, com teste vermelho antes de cada correção de comportamento: validação do ACK de render (R32), repetição de `POST /v1/sessions` após a expiração (R33), `claim-control` repetido sem ser mais o controlador (R34), 405/415 e `after_seq` limitado no envelope (R35), `evidence` não persistido (R36), jobs encerrados ao fechar/expirar, ator `vision_worker` e guarda `DomainError` na reconciliação, helper único de gravação (R37). No aceite, o AC-33 ganhou o caso que isola a guarda de tentativa e o AC-37 um controle positivo. O hash do commit de código desta onda está no `git log` (mensagem "onda final"); o registro de hash foi feito num commit de documentação seguinte.

## Não comprovado neste incremento

Não conta como pronto na demonstração:

- Idempotência por `command_id` e AC-26 (incremento 2). Em AC-27 falta o `IDEMPOTENCY_CONFLICT`,
  que exige o armazenamento de resultados.
- Qualquer coisa de ACK ou fala do tutor (incrementos 3 e 5). Em AC-05, AC-06, AC-22 e AC-23
  provamos a detecção e a escolha da intervenção; a fala e o pedido de justificativa pelo tutor
  ficam para o incremento 5.
- Leitura real de foto do caderno (incremento 4). As observações usadas são fixtures sintéticas.
- Qualidade da avaliação de explicação em texto livre ou voz (D2): o avaliador é um stub, então o
  teste só prova o que o domínio faz com a nota recebida.
- Interface: o que o AC-03 e o AC-21 pedem da tela (por exemplo, cores de solução) fica para o
  incremento 3. A borda HTTP repete o teste do AC-39 no incremento 2.
- Ajuda procedimental (instrução de upload) só entra pelo tutor via `apply_help`, que ainda não
  tem handler. Que ela não conta como ajuda conceitual está provado só nos testes unitários de
  `assistance` e `classification`, não em jornada completa.
- Nenhum teste com crianças, e nenhuma afirmação sobre ganho de aprendizagem ou retenção.

---

# Registro de execução: incremento 2 (sessão persistida, comandos autorizados, idempotência e retomada)

Escopo: camada `sessions/` sobre o domínio, banco (SQLite e Postgres) e rotas `/v1`; sem interface, voz, upload nem visão real

Este registro atende à Spec, Parte III §1, para o incremento 2. Todas as fixtures são sintéticas
(`model_ref` = `synthetic-fixture-not-a-model-run`; observações do caderno vindas de arquivos de
`tests/fixtures`). Nenhuma criança participou de qualquer teste, e este documento não afirma ganho
de aprendizagem.

## Identificação (incremento 2)

| Item | Valor |
|---|---|
| Versão do app (`pyproject.toml`) | 0.1.0 (a API declara `API_VERSION` 0.2.0) |
| `content_version` | `division-sharing-v1` |
| `schema_version` dos comandos | 1.0 |
| Prompt / modelo | nenhum; o avaliador de explicação é o stub dos testes (D2). O de produção é o `UnavailableEvaluator` (P9), que responde 503 |
| Python | 3.12.14 (`uv run python -V`) |
| Sistema operacional | macOS 26.6.2 (build 25G83), arm64 |
| Ferramentas | uv 0.12.5, pytest 9.2.0 |
| Postgres (cluster descartável dos testes) | 17.11 (Homebrew), `initdb`/`pg_ctl` sob `tmp_path_factory`, porta livre em 127.0.0.1, parado no teardown |
| SQLite (`sqlite3.sqlite_version`) | 3.53.1 |
| Código sob teste | branch `feat/incremento-2-sessao`, base `09bcdc8`; último commit de código da Task 7 `0f938e5`; testes de aceite e rastreabilidade (Task 8) em `9f1d5f1`; onda final de correções (ACK, expiração, envelope 405/415, `after_seq`, controle, evidence, jobs encerrados, AC-33/AC-37) no commit descrito em "Onda final" abaixo |
| Data | 2026-11-05 |

## Comandos e resultado (incremento 2)

| Comando | Resultado |
|---|---|
| `uv run pytest -q` | 1152 passed, 0 skipped |
| `uv run pytest -q -m ac -rA` | 130 passed, 1022 deselected; 17 ids com teste marcado e aprovado: os 16 exigidos (10 do incremento 1 e 7 do 2, com AC-27 nos dois) e AC-45, marcado a mais |
| `TUTOR_REQUIRE_PG=1 uv run pytest -q -rs` | 1152 passed, 0 skipped (nenhum skip de Postgres) |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check services tests` | 68 files already formatted |

Com `TUTOR_REQUIRE_PG=1`, a falta dos binários do Postgres falha o teste em vez de pulá-lo
(`pg_cluster` em `tests/integration/conftest.py`). Sem a variável e sem Postgres, os testes
parametrizados por `db_url` pulam a metade `postgres`; por isso esta execução com a variável é a
que vale como evidência. O conjunto passou de 505 testes (incremento 1) para 1152. `ruff format --check .` na raiz acusa dois arquivos de `docs/plans/*.md` que já estavam sem formatar; a verificação vale para `services` e `tests`.

Em 05/11/2026 a execução emitiu um aviso (`StarletteDeprecationWarning`: o `TestClient` do
Starlette prefere `httpx2` a `httpx`). Não afeta resultado.

## Como a rastreabilidade funciona (incremento 2)

- `tests/ac_traceability.py` agora exige `REQUIRED_ACS = INCREMENT_1_ACS | INCREMENT_2_ACS`.
  `INCREMENT_2_ACS` = AC-26, 27, 33, 36, 37, 38 e 40. AC-27 está nos dois incrementos, então a
  união tem 16 ids, não 17. O 17º id da lista de `-m ac` é AC-45, que tem teste marcado mas não é
  exigido.
- Há um teste de aceite por AC em `tests/acceptance/test_increment_2.py`, rodado em SQLite e em
  Postgres (14 execuções). Cada jornada parte de `POST /v1/sessions` e avança só por HTTP:
  `choose_reference_activity` (aluno), `run_demo_step` e `finish_demonstration` (token de serviço
  `system`) e a prática. Exceção (P6): AC-33 e AC-37 chamam `SessionService.complete_analysis`
  com o ator `vision_worker`, porque não há rota de análise neste incremento. A submissão do
  artefato também vai direto ao serviço (`submit_notebook_artifact`), pelo mesmo motivo.
- Os fixtures de banco (`db_url`, cluster Postgres descartável, `make_service`) são os de
  `tests/integration/conftest.py`, reexportados por `tests/acceptance/conftest.py`. Quando a suíte
  inteira roda, o cluster sobe uma vez para a integração e outra para o aceite.
- Em `tests/test_ac_traceability.py`, um caso de pytester prova que, sem teste aprovado para
  AC-38, a execução completa falha e lista `AC-38`.
- O passo "esperar FAIL até `REQUIRED_ACS` incluir o incremento 2" do plano teve pouco efeito
  prático: as Tasks 4 a 7 já tinham marcado os sete ids em seus testes de integração. O que ficou
  vermelho primeiro foi o teste do próprio hook (`INCREMENT_2_ACS` inexistente).

## Cobertura por AC (incremento 2)

| AC | Teste de aceite (HTTP) | Parte comprovada | Outros testes marcados |
|---|---|---|---|
| AC-26 | `test_ac26_same_body_twice_has_one_effect` | mesmo corpo duas vezes: 200 nas duas, `Idempotent-Replay: true` na segunda, mesma resposta, uma revisão a mais, peça movida uma vez, um `scene_changed` | `test_http_replay_header_and_single_effect`; `test_ac26_same_command_twice_one_effect`; concorrência de duplicatas em `test_concurrent_duplicates_single_effect` (serviço, threads) |
| AC-27 | `test_ac27_rejections_name_the_code_and_leave_no_trace` | `IDEMPOTENCY_CONFLICT` (409), `STALE_REVISION` (409), `ATTEMPT_CHANGED` (409), `INVALID_SCENE` (422); snapshot idêntico e nenhum evento novo após cada rejeição; a rejeição não ocupa o `command_id` (P5) | `test_ac27_http_codes`; `test_ac27_errors_leave_no_partial_mutation` (serviço) |
| AC-33 | `test_ac33_slow_v1_does_not_overwrite_v2` | v1 chega depois da v2 e fica `superseded`, sem sobrescrever; v2 é aplicada; resultado de uma foto de tentativa antiga fica `superseded` e a questão nova não herda a análise. Na jornada normal toda saída da captura já supersede o job; por isso um segundo caso reabre o job à força (`queued`) e prova que o resultado da tentativa antiga ainda é recusado (guarda de vigência/tentativa), sem alterar o snapshot | `test_ac33_slow_v1_does_not_overwrite_v2` e `test_ac33_result_after_attempt_changed_is_superseded` em `test_session_analysis.py` (serviço) |
| AC-36 | `test_ac36_lost_response_is_replayed_and_state_is_reconcilable` | resposta perdida e corpo reenviado: replay, peça movida uma vez; `GET` do snapshot e `GET /events?after_seq=` concordam sobre o estado confirmado | `test_replay_after_revision_advanced_returns_original` |
| AC-37 | `test_ac37_pause_defers_and_closed_session_discards` | pausa: resultado fica `deferred`, sem mudança nem evento, e a retomada o aplica numa só revisão (`session_resumed` + `analysis_completed`); controle positivo (sessão ativa: o mesmo resultado é aplicado); sessão fechada: resultado tardio descartado e job encerrado, nada muda; tutor recusado em sessão pausada e em fechada (403 `ACTION_NOT_ALLOWED`) | `test_ac37_*` em `test_session_analysis.py` |
| AC-38 | `test_ac38_second_tab_takes_control_without_forking_state` | `claim-control` sobe a geração para 2; a aba A perde escrita e ACK (403 `CONTROL_LOST`); as duas abas leem o mesmo estado; a aba B continua escrevendo | `test_ac38_second_tab_takes_control`; `test_concurrent_claims_have_one_winner` |
| AC-40 | `test_ac40_credential_of_a_sees_nothing_of_b` | token da sessão A nas cinco rotas da sessão B (snapshot, comandos com `command_id` conhecido de B, `claim-control`, ACK, eventos): 404 idêntico byte a byte ao de sessão inexistente, sem o id de B; B não muda | `test_ac40_token_a_on_session_b`; `test_ac40_service_token_on_missing_session_is_the_same_404`; `test_ac40_service_level_cross_session` (serviço) |

## Não comprovado neste incremento

Não conta como pronto na demonstração:

- Rotas de upload, de análise e `voice-token`. AC-33 e AC-37 provam o domínio e o caso de uso com
  o worker stub; a rota `/analyses` e o worker real ficam no incremento 4, e o token de voz
  restrito à sala no incremento 5. AC-40 cobre sessão, comandos, controle, ACK e eventos; upload,
  análise e `voice-token` entram depois, com o mesmo `authenticate`.
- A parte de interface do AC-36: o descarte da prévia de gesto na tela (incremento 3). Aqui só se
  prova o servidor (replay sem duplicar; snapshot e eventos para reconciliar).
- A interface de leitura da segunda aba (AC-38, incremento 3).
- ACK com efeito e fala do tutor (AC-28 a AC-32): o ACK é gravado e validado, mas nada espera por
  ele nem fala.
- Limpeza dos dados em 24 h (AC-46). A sessão expira em 24 h (P11) e responde 404, mas nenhum
  processo apaga as linhas.
- Throttle de criação de sessão (`SESSION_LIMIT`) e CORS: o código existe no catálogo, nada o
  emite (incremento de deploy, G7).
- O Postgres dos testes é um cluster local descartável com `fsync` desligado; não é o Supabase
  real. A migration SQL é comparada com o schema do código por teste, mas nunca foi aplicada num
  projeto Supabase.
- R19: a fase `explanation` revela a correção da questão nova (ver DECISOES-INCREMENTO-2). A
  decisão é do usuário.
- Nenhum teste com crianças, e nenhuma afirmação sobre ganho de aprendizagem ou retenção.
