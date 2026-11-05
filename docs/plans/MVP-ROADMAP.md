# Roteiro do MVP (incrementos 2–6)

Meta: jornada completa funcionando em celular e tablet (Spec Parte IV, "Definição de pronto"). Cada incremento tem plano próprio em `docs/plans/`, branch empilhada (`feat/incremento-N-*`) e PR para `develop`.

## Análise crítica

Problemas:
- A Spec pede adapters reais (visão, voz) na homologação. Visão e tutor dependem de chave de API, e voz (LiveKit) depende de conta. Nenhuma das duas existe no cofre para este projeto. Os incrementos 2 e 3 não dependem delas e vão primeiro.
- O risco maior é a leitura da foto do caderno, que é a mais difícil de acertar. O conjunto de avaliação de visão precisa de fotos reais de caderno feitas pelo autor, e fixtures sintéticas não comprovam a leitura.
- O prazo é 30/11. A cena 3D no celular é o item de UI mais caro, por isso existe o modo 2D (SVG) como caminho garantido.

Oportunidades:
- O domínio já está pronto e testado (505 testes), então a API é uma casca fina sobre `apply_command`.
- A rubrica e a cena são determinísticas, o que permite testar a jornada de ponta a ponta sem modelo, com os adapters de stub.

## Decisões globais (valem para todos os incrementos)

- G1 Frontend: `apps/web`, Vite + React + TypeScript, React Three Fiber para o 3D e SVG para o 2D, pnpm. Mobile primeiro.
- G2 API: FastAPI em `services/backend/app/api`, que só chama os casos de uso de `sessions/`. O domínio continua puro.
- G3 Persistência: SQLAlchemy Core.
  - Postgres no deploy (Supabase); migrations em SQL em `supabase/migrations/`.
  - Os testes rodam em SQLite e também em um Postgres local temporário, criado com `initdb` dentro do diretório de trabalho do job, nunca em /tmp.
  - Idempotência por restrição única.
- G4 Visão: adapter atrás de um Protocol.
  - O real usa a API da Anthropic com saída forçada no schema `NotebookObservation`; o stub é determinístico.
  - Sem chave, a análise real fica indisponível e o produto mostra isso, sem fingir leitura.
- G5 Tutor: texto primeiro, com ferramentas tipadas por etapa e falas validadas.
  - Voz no navegador (Web Speech API) como canal inicial.
  - O adapter LiveKit entra quando houver conta.
- G6 Deploy: frontend na Vercel. O backend tem o destino decidido no incremento 6, conforme custo e latência.
- G7 Segredos em `op://Personal/prof-em-casa/<VAR>`. `.env` gerado por `op inject` e nunca commitado.

## Ordem

| Inc. | Entrega | Dependência externa |
|---|---|---|
| 2 | Sessão persistida, API HTTP, idempotência, retomada (AC-26–27, 33, 36–38, 40) | nenhuma |
| 3 | Frontend + cena 3D/2D, gestos, demonstração, ACK (AC-07–10, 13–15, 28–32, 43–44) | nenhuma |
| 4 | Captura, armazenamento privado, fila, visão real (AC-01–02, 12, 16–20, 33–35, 41, 46–47) | chave Anthropic, fotos reais |
| 5 | Tutor contextual, voz/texto, modo caderno (AC-08, 11–12, 23–24, 28–32, 42) | chave Anthropic (LiveKit opcional) |
| 6 | Questão nova, resumo, integração, deploy, avaliação real (AC-21–25, 45, 48) | Vercel + backend hospedado |
