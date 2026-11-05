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
| Código sob teste | branch `feat/incremento-1-dominio`, a partir do commit `2d432ac` (Task 8) |
| Data | 2026-11-05 |

## Comandos e resultado

| Comando | Resultado |
|---|---|
| `uv run pytest -q` | 473 passed |
| `uv run pytest -q -m ac -rA` | 45 passed, 428 deselected; os 10 ACs com teste marcado e aprovado |
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
  exatamente `-m ac`. Rodar um arquivo ou um `-k` isolado não falha por AC de outro arquivo.
  O comportamento do próprio hook é testado em `tests/test_ac_traceability.py` (pytester).

## Cobertura por AC (domínio)

| AC | Teste de aceite | Parte comprovada |
|---|---|---|
| AC-03 | `test_ac03_complete_demonstration` | demonstração de 12 ÷ 4 termina em `[3,3,3,3]`, 0 disponíveis; o item guiado começa sem resposta |
| AC-04 | `test_ac04_advance_request_before_and_after_the_first_round` | pedir para avançar antes da 1ª rodada é recusado; depois, avança como demonstração parcial |
| AC-05 | `test_ac05_unequal_practice_detects_inequality_without_acting` | `[7,5,6,6]`: detecta desigualdade, escolhe `compare_groups`, não move peça nem marca domínio |
| AC-06 | `test_ac06_equal_groups_with_available_pieces_ask_about_the_total` | `[5,5,5,5]` com 4 disponíveis: grupos iguais, total incompleto, `check_total_use`, sem "resto" |
| AC-21 | `test_ac21_new_question_starts_clean` | 20 ÷ 5 sem cena, sem resposta, sem ajuda prévia, projeção pública sem quociente |
| AC-22 | `test_ac22_correct_answer_with_sufficient_explanation_and_paper_is_without_item_help` | `applied_without_item_help`; resumo sem alegar domínio nem retenção |
| AC-23 | `test_ac23_bare_answer_is_partial_evidence_and_never_sufficient_alone` | resposta isolada fica `answer_correct_evidence_partial` |
| AC-24 | `test_ac24_help_is_recorded_before_the_resource_and_marks_support` | ajuda registrada antes da cena; resultado `applied_with_support` |
| AC-27 | `test_ac27_rejected_commands_leave_no_partial_mutation` | revisão velha, tentativa trocada, cena velha, origem da peça incorreta: erro e sessão intacta |
| AC-39 | `test_ac39_invalid_json_extra_fields_and_unauthorized_actions_change_nothing` | JSON inválido, campo extra, tipo fora do catálogo, ator não autorizado: rejeitados, nada executa |

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
