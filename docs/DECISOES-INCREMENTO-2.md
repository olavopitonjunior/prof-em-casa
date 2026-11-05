# Decisões do incremento 2 (sessão persistida, comandos autorizados, idempotência e retomada)

Registro das decisões do incremento 2, tomadas em 05/11/2026 (branch `feat/incremento-2-sessao`, plano `docs/plans/2026-11-05-incremento-2-sessao.md`). Cada linha: o que foi decidido, por quê e o custo se estiver errado. Mesmo formato de [DECISOES-INCREMENTO-1.md](DECISOES-INCREMENTO-1.md).

## Decisões do plano (P1–P12)

A Spec é ambígua nestes pontos, e o plano decidiu cada um. A ledger da execução registra a aceitação delas em R20.

- P1: o estado da sessão é persistido como snapshot JSON (`sessions.state`), validado com `SessionState.model_validate` na leitura. Eventos e `attempts` são gravados na mesma transação; não há reconstrução por replay de eventos. **Custo se errado:** migrar para event sourcing exige um replayer, mas o log já existe e está completo.
- P2: a credencial da demo é um token opaco de sessão. Não há provedor de auth.
  - `POST /v1/sessions` é anônimo e devolve `session_token`, calculado como `base64url(HMAC-SHA256(SESSION_TOKEN_SECRET, "session-token:" + request_id))`. No banco fica só o `sha256` do token, em `session_credentials`.
  - O `request_id` tem de ser de alta entropia: regex `^[A-Za-z0-9_-]{22,128}$`. Por isso o replay do `POST` devolve o mesmo token sem guardá-lo em claro.
  - Tutor, sistema e worker usam tokens de serviço por ator, vindos de variáveis de ambiente.
  - **Custo se errado:** o `request_id` vira segredo equivalente ao token. Trocar por auth Supabase muda só `app/sessions/credentials.py` e `app/api/deps.py`.
- P3: o controlador ativo (Parte II §1, `connection_generation`) é identificado pelo cabeçalho `X-Controller-Id`.
  - O valor é o `request_id` que criou a sessão ou que fez o último `claim-control`.
  - Toda escrita do aluno (comandos e `render-receipts`) exige o controlador vigente; senão a resposta é 403 `CONTROL_LOST`.
  - Essa checagem faz parte da autorização, então vem antes da deduplicação. Leituras (`GET`) não exigem o cabeçalho.
  - **Custo se errado:** o envelope teria de ganhar `connection_generation`, o que é uma mudança de schema 1.0.
- P4: `claim-control` é uma mutação da camada `sessions`, não um comando do catálogo.
  - Exige `expected_revision` e faz `connection_generation += 1`, `turn_epoch += 1` e `revision += 1`.
  - Grava o evento `control_claimed`. É uma extensão da lista da Parte II §9, como `returned_to_activity` no incremento 1.
  - É idempotente por `request_id`.
  - **Custo se errado:** se a revisão não devesse subir, a correção é tirar um `+1` e ajustar 2 testes.
- P5: só resultados **aceitos** são gravados em `command_results`. Uma rejeição (409/422/403) não ocupa o `command_id`, e reenviar o mesmo id reavalia o comando.
  - O hash idempotente é `sha256` do JSON canônico de `{"actor": actor, "body": corpo}`, com `sort_keys`, `separators=(",", ":")` e `ensure_ascii=False`.
  - O mesmo corpo vindo de outro ator dá `IDEMPOTENCY_CONFLICT`.
  - **Custo se errado:** guardar rejeições exige uma coluna `http_status` (que já existe) e um ramo a mais.
- P6: AC-33 entra no incremento 2 pelo caminho domínio + caso de uso, sem rotas de upload e de análise (que ficam no incremento 4).
  - O domínio ganha `open_notebook_capture`, `cancel_capture` e `retake_notebook_photo`, mais duas operações internas fora do catálogo: `submit_artifact` e `apply_analysis_result`.
  - `SessionState` ganha `active_artifact`, `observation` e `verification`.
  - O worker é um stub que chama `SessionService.complete_analysis`.
  - **Custo se errado:** o incremento 4 refaz a assinatura de 2 funções. O domínio já fica pronto para as rotas.
- P7: resultado de análise obsoleto (`superseded`) só muda o status do job. Não muda a sessão nem gera evento de sessão: o `analysis_superseded` já foi emitido pelo `retake_notebook_photo` que causou a troca.
  - Resultado que chega com a sessão em pausa fica `ready` e não aplicado (`applied=false`). O `resume_session` aplica esse resultado **na mesma transação** e com **uma só** revisão, via `bump_revision=False`.
  - Resultado que chega com a sessão fechada é guardado como `ready` e nunca aplicado.
  - **Custo se errado:** a reconciliação em transação separada gera uma revisão a mais, que o cliente veria como `STALE_REVISION`.
- P8: a projeção para o aluno é uma lista de campos permitidos por tipo de evento; o padrão é negar.
  - Nunca saem para o aluno: `answer`, `correct`, `outcome`, `rating`, `evidence`, `issues`, `quotient` e `private`.
  - `attempt_evaluated` aparece só com o envelope e `data: {}`. Assim a sequência continua contínua, sem revelar o resultado.
  - É criada a rota extra `GET /v1/sessions/{id}/events?after_seq=` para a retomada incremental. A Spec §8 não a lista.
  - Os atores de serviço recebem o `data` completo.
  - **Custo se errado:** liberar um campo é mudar uma linha da lista de permitidos.
- P9: o avaliador de explicação de produção, no incremento 2, é o `UnavailableEvaluator`. Ele levanta `DomainError("PROVIDER_UNAVAILABLE")` e a API responde 503. Os testes injetam o `StubEvaluator`, e o LLM entra no incremento 5 (G4/G5: sem fingir avaliação).
  - **Custo se errado:** a demo do incremento 3 não consegue fechar a explicação por texto até o incremento 5. Um stub configurável resolve isso em 10 linhas.
- P10: o schema tem uma fonte para cada banco.
  - Postgres usa os arquivos SQL de `supabase/migrations/`. SQLite usa `metadata.create_all` de `app/db/schema.py`.
  - Um teste reflete o Postgres migrado e o compara com `metadata`: tabelas, colunas, nulabilidade e índices únicos.
  - Todas as tabelas têm RLS habilitado e nenhuma policy, porque só o backend acessa.
  - **Custo se errado:** drift entre os dois bancos. O teste de comparação existe para pegá-lo.
- P11: a sessão demo expira em 24 h (Parte I §9). Uma sessão expirada responde 404 `NOT_FOUND` em todas as rotas. A limpeza dos dados (AC-46) fica para o incremento 4.
  - **Custo se errado:** o cliente pode precisar de um código específico para expiração. Seria trocar o código em 1 ponto.
- P12: `session_id` divergente é tratado em duas camadas.
  - No domínio: `apply_command` rejeita com `INVALID_PAYLOAD` (fecha a pendência do incremento 1).
  - Na API: id da URL diferente do id do corpo dá 400 `INVALID_PAYLOAD`. Credencial de outra sessão dá 404 `NOT_FOUND`, sem revelar se a sessão existe (AC-40).
  - `_Revision` ganha teto `le=2_147_483_647` (INTEGER do Postgres).
  - **Custo se errado:** trocar 1 código de erro.

## Decisões tomadas durante a execução (R19–R31)

Copiadas da ledger da execução (`.superpowers/sdd/2026-11-05-incremento-2-sessao/progress.md`, linhas "Ruling"; a pasta `.superpowers/` está no `.gitignore`, então a ledger existe só na máquina de execução). R19 aparece aqui e de novo na seção seguinte, porque depende de uma decisão do usuário.

- R19: conflito 1 (fase explanation revela correção na transferência) — mantém Spec no domínio; levar ao usuário no relatório; frontend do inc. 3 não exibe acerto — custo se errado: mudar 1 transição no domínio.
- R20: P1–P12 do plano aceitas; conflitos 2–6 seguem as decisões do plano e entram na lista de atualização do Spec.md — custo se errado: ver custo de cada P.
- R21: FKs session_id→sessions ON DELETE CASCADE (+observations.artifact_id→artifacts) — protege purga AC-46 de órfãos com dado do aluno — custo se errado: remover cascade.
- R22: attempts.item_id = task_id da Spec §9; + coluna outcome nullable ("resultado") — custo se errado: renomear coluna.
- R23: abrir nova captura (open_notebook_capture/revise) com active_artifact existente → artefato antigo vira superseded (emite analysis_superseded se job pendente) e observation/verification limpos; resultado tardio do antigo não se aplica — custo se errado: 1 regra a remover.
- R24: apply_analysis_result exige observation.artifact_id/attempt_id iguais aos do resultado e da sessão → senão INVALID_PAYLOAD (fixtures de teste ajustam ids) — custo se errado: mover checagem para camada sessions.
- R25: mudanças extras do implementer aceitas (submit_artifact limpa observation/verification; guided→transfer limpa artefato; submit permitido em pausa; ordem closed→phase) — custo se errado: ajustes locais.
- R26: todo caminho que descarta artefato com análise pendente emite exatamente um analysis_superseded; análise concluída descartada não emite — custo se errado: 1 evento a mais/menos.
- R27: whitelist de aplicação = {notebook_review} (Spec §8); toda saída do fluxo captura/revisão com análise pendente descarta o artefato (analysis_superseded) — sem "pending" fantasma — custo se errado: reabrir whitelist.
- R28: texto livre da criança (request_help.reason) NÃO é persistido nem emitido em eventos (AC-45: sem nomes/transcrição) — help_granted leva só has_reason: bool; texto fica efêmero para o tutor (inc. 4+). Custo se errado: perder contexto do pedido em auditoria.
- R29: erro HTTP para audiência learner leva só code (+ campos estruturais), nunca detail textual do domínio ("explanation is not sufficient" = oráculo de rating) — Task 7. Custo se errado: mensagens de erro menos úteis no front.
- R30: comando de tutor com turn_epoch ≠ state.turn_epoch é rejeitado (código da Spec) — sem isso claim-control não corta turno velho; entra no fix da Task 5. Custo se errado: rejeitar fala legítima após corrida.
- : STALE_TURN é extensão da Spec (sem código próprio) — Task 7 mapeia para 409 e o catálogo de erros em DECISOES-INCREMENTO-2 registra — custo se errado: renomear um código.
- R31: corpo HTTP limitado (64 KiB) antes de ler/parsear → 413 com envelope; nada da entrada do cliente é ecoado sem validar formato — custo se errado: rejeitar payload legítimo grande (não existe no MVP).

## Pendente de decisão do usuário

- R19 (conflito 1 do plano): a transição para a fase `explanation` revela se a criança acertou a questão nova. A Parte I §4 manda `submit_answer` ir para `explanation` quando a resposta está correta e manter `transfer` quando está errada. Quem lê a fase no snapshot sabe o resultado antes de qualquer feedback autorizado, e a Parte I §7 trata feedback corretivo após erro na questão nova como apoio. A projeção (P8) esconde os campos de correção, mas não esconde a fase.
  - Estado atual: o domínio mantém o comportamento da Spec, e o frontend do incremento 3 não deve exibir acerto. Se esta regra estiver errada, o custo é mudar uma transição no domínio.
  - Correção mais barata: uma fase `answer_pending` que não muda no erro. Isso muda uma transição no domínio e a Spec.
  - A decisão é do usuário, não da execução. Nada além do comportamento normativo da Spec foi implementado.

## Parked para a revisão final / próximos incrementos

Itens menores que os revisores levantaram e que a execução adiou de propósito. Copiados da ledger (linhas "Parked").

- Task 1 (menores): drift não compara tipos/defaults/CHECK (CHECKs cobertos por inserts); passthrough postgresql://; lista de migrations não pega arquivo extra no meio — não load-bearing.
- Task 2 (reavaliação): already_applied (disposição extra, aceita por R25); campos de revisão do SessionState sem le=MAX_REVISION (Minor → Task 4/8); P7 reconciliação de retomada não verificada (→ Task 4).
- Task 3 (menores): teste checa chaves não valores de reason; códigos de analysis_superseded sem jornada; listas aninhadas por referência (copiar no projetor se virar problema); forbidden-key só em teste. Note for Task 4: observation_id deve ser opaco (uuid, sem semântica).
- Task 4 (menores): always_race só checa revisão; _is_result_race por substring do constraint; TUTOR_REQUIRE_PG=1 no CI/EXECUCAO (Task 8).
- Task 5: teto de receipts por sessão (Task 8/inc 6).
- Task 6 (menores, para a onda final): analysis_completed reconciliado gravado com actor learner (deveria vision_worker); reconciliação sem guarda DomainError; jobs queued de sessão fechada ficam queued + observação gravada em resultado tardio; bloco save/append/SessionRow triplicado (service.py +320 linhas); request_id do submit sem formato; teste deferred→resume→retake e colisão submit×comando ausentes.
- Task 7: SESSION_LIMIT/throttle de POST /v1/sessions e CORS → incremento de deploy (G7). Contrato comparado parseado (ok).

Resolvido depois: "P7 reconciliação de retomada não verificada" ficou coberto pelo teste de AC-37 da Task 6 (pausa, adiamento e retomada em uma só revisão).

Destaques:

- `SESSION_LIMIT` (429, throttle de `POST /v1/sessions`) e CORS não existem na API do incremento 2. Entram no incremento de deploy (G7). O código `SESSION_LIMIT` está no catálogo e na tabela HTTP, mas nada o emite.
- Os campos de revisão do `SessionState` ainda não têm `le=MAX_REVISION`; só o envelope do comando e as rotas têm o teto.
- O evento `analysis_completed` gravado na reconciliação da retomada leva o ator `learner`; o correto seria `vision_worker`.
- Não há teto de recibos de render (`render_receipts`) por sessão.

## Atualizações pendentes no Spec.md

O `Spec.md` é do usuário e não foi editado. Para ficar coerente com o que foi construído:

1. Conflito 2 do plano (P4): `claim-control` exige `expected_revision`, mas a Parte II §1 diz que a revisão só sobe por mutação do domínio. P4 decide que a revisão sobe.
2. Conflito 3 (P2): `POST /sessions` é anônimo e idempotente por `request_id`, contra "outra identidade sem vínculo não pode recuperá-lo" (Parte II §2). Antes da criação não existe identidade; P2 transforma o `request_id` em segredo (regex `^[A-Za-z0-9_-]{22,128}$`).
3. Conflito 4 (P3): o envelope de comando não tem campo de controlador ou geração, mas o AC-38 exige que o primeiro controlador perca a escrita. P3 usa o cabeçalho `X-Controller-Id`.
4. Conflito 5 (P7): retomar com análise pendente produz dois fatos (`session_resumed` e `analysis_completed`), enquanto a Parte II §1 pede "incremento único por transação". P7 aplica os dois numa única revisão.
5. Conflito 6: a lista de eventos da Parte II §9 não tem evento de controle. O plano acrescenta `control_claimed`, como o incremento 1 fez com `returned_to_activity`. As duas extensões entram no `Spec.md`, junto com D3 e R16 do incremento 1.
6. Códigos de erro acrescentados durante a execução, ausentes do catálogo da Spec:
   - `STALE_TURN` (409, não retentável): comando de tutor com `turn_epoch` diferente do vigente (R30). Extensão sem código próprio na Spec.
   - `PAYLOAD_TOO_LARGE` (413): corpo HTTP acima de 64 KiB (R31). Só existe na borda HTTP.
   - `INTERNAL_ERROR` (500): erro inesperado, devolvido no envelope sem detalhe. Só existe na borda HTTP.
7. Também fora da lista de rotas da Parte II §8: `GET /v1/sessions/{id}/events?after_seq=` (P8), usada na retomada incremental e no AC-36.

O conflito 1 do plano é o R19 acima e depende da decisão do usuário.
