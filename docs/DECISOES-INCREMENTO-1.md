# Decisões do incremento 1 (domínio de divisão)

Registro das decisões tomadas durante a execução por subagentes em 05/11/2026 (branch `feat/incremento-1-dominio`). Cada linha: o que foi decidido, por quê e o custo se estiver errado.

## Decisões aprovadas pelo usuário

- D1: repositório novo em `~/dev/tutor-divisao`.
- D2: nota da explicação chega pré-avaliada; o domínio avalia só a modalidade artefato.
- D3: `request_help.kind` inclui `virtual_objects` e `reference_model` (acrescentam recurso sem subir o nível de assistência).

## Decisões tomadas durante a execução

- R1 commit gate — implementers run scripts/preflight-git.sh and commit themselves; no orchestrator per commit (orchestrator verdict 05/11: per-commit preflight only, orchestrator before PR/merge) — cost if wrong: extra commits without judgment review; task review still gates.
- R2 DomainError subclasses Exception, NOT ValueError, so it propagates out of Pydantic validators unwrapped — cost if wrong: tests expecting DomainError get ValidationError.
- R4 no GitHub remote/push in this run (D1 named a public GitHub repo; publishing is outward-facing, needs user go) — cost if wrong: user creates remote later, one command.
- R5 TaskSpec lives in services/backend/app/domain/division/task.py, created in Task 1 with errors.py — cost if wrong: one import path move.
- R6 implementers run ruff format only on services/ tests/ (T1 implementer's ruff format reformatted docs/plans .md; restored via checkout) — cost if wrong: none
- R7: demo_steps rejeita rounds fora de 1..quotient com INVALID_PAYLOAD — demo nunca deve passar do quociente; custo se errado: relaxar 1 guarda.
- R8: obs.status!=usable só gera inconclusive se restar ambiguidade não clarificada — senão AC-18 (clarificar) nunca resolve — custo se errado: 1 condição.
- R9: só-expressão (groups=[]): inconsistent se issue de expressão/resposta; consistent se resposta confere; inconclusive se sem resposta legível; reconstrução indisponível — custo se errado: tabela de status de 3 linhas.
- R10: clarificação duplicada/para caminho não ambíguo → INVALID_PAYLOAD — custo se errado: trocar por "última vence".
- R11: WRITTEN_ANSWER_MISMATCH compara com quociente da tarefa (pode coexistir com EXPRESSION_MISMATCH) — custo se errado: intervenção duplicada no incremento 2.
- R12: ambiguidade não clarificada em /expression/* também bloqueia reconstrução (inconclusive ⇒ ¬reconstrução) — conservador: clarificar antes de reconstruir — custo se errado: separar status do desenho e da expressão.
- R13: classify_attempt — explicação parcial/ausente → answer_correct_evidence_partial ANTES de checar ajuda (Spec Parte I 'Classificação final': with_support exige explicação suficiente). Corrige minha ordem do dispatch — custo se errado: troca de 2 linhas.
- R14: request_help.kind = HelpKind − {procedural, accessibility} (6 valores) — D3 aprovada pelo usuário prevalece sobre a tabela da Spec §3 — custo se errado: nenhum (D3 explícita). Spec.md precisa ser atualizada (junto com D7).
- R15: turn_id/turn_epoch opcionais em par para system/vision_worker (Spec §2 omissa) — custo se errado: tornar obrigatório.
- R16: arestas D7 além da Spec aceitas (submit_answer correto practice→explanation; return_to_activity explanation→practice/transfer; request_reconstruction notebook_review→correction; request_help em notebook; transfer→summary com sessão ativa até close_session; evento returned_to_activity) — custo se errado: ajuste na tabela TRANSITIONS; Spec.md precisa ser atualizada pelo usuário.
- R17: turn_epoch do tutor não validado no incremento 1 (sem handlers de tutor executáveis) — custo se errado: 1 guarda no incremento 5.
- R18: ambiguidade em /expression/* não é clarificável no incremento 1 (Clarification só aceita /groups/{i}/count) → fica inconclusive — conservador — custo se errado: ampliar Clarification no incremento 4.

## Pendências para incrementos seguintes

- Spec.md precisa ser atualizada pelo usuário: D3 (tipos de ajuda) e arestas extras de transição (R16).
- Avaliador de explicação que lança exceção escapa sem `DomainError` (fronteira do avaliador real, incremento 3+).
- `answer_submitted` carrega correct/answer (projeção de eventos no incremento 2); `_Revision` sem limite superior; `session_id` não conferido.
- Textos em pt-BR precisam de leitura pedagógica do usuário.
