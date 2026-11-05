# Prof em Casa

Tutor de estudo para alunos do 4º e 5º ano que transforma uma atividade da apostila em uma aula interativa, começando por divisão exata por partilha. Projeto inscrito no Hack Brasil 2026 (trilha Acesso à educação).

> Em desenvolvimento. Nada aqui foi testado com crianças, e nenhum ganho de aprendizagem foi medido. Todos os dados de exemplo são sintéticos.

## O problema

Muitas crianças não conseguem fazer a lição de casa sem um adulto ao lado: não entendem o conteúdo da apostila e não sabem por onde começar. O tutor quer ajudá-las a resolver sozinhas, com pistas graduais em vez de respostas prontas.

## A jornada (primeiro recorte: divisão exata por partilha)

1. **Demonstração**: o tutor mostra 12 ÷ 4 distribuindo objetos em quatro grupos.
2. **Prática guiada**: a criança distribui 24 objetos em 4 grupos numa cena 3D/2D e recebe ajuda conforme a tentativa.
3. **Caderno**: a montagem vira um esquema para desenhar no papel.
4. **Foto do caderno**: o tutor lê a foto, pede esclarecimento quando a imagem é duvidosa e aponta onde revisar, sem dar a resposta.
5. **Questão nova** (20 ÷ 5) com menos apoio, e um resumo do que a criança fez sozinha e com ajuda.

## Estado atual

| Incremento | Conteúdo | Estado |
|---|---|---|
| 1 | Conteúdo, tipos e regras pedagógicas (domínio puro) | pronto, 505 testes |
| 2 | Sessão persistida, comandos autorizados, retomada | pronto no backend, 1152 testes na suíte completa; aguarda revisão |
| 3 | Cena 3D/2D, gestos, demonstração | planejado |
| 4 | Captura e análise real da foto do caderno | planejado |
| 5 | Tutor por voz/texto | planejado |
| 6 | Questão nova, resumo, integração completa | planejado |

Detalhes do que foi verificado: [docs/EXECUCAO.md](docs/EXECUCAO.md). Decisões: [incremento 1](docs/DECISOES-INCREMENTO-1.md) e [incremento 2](docs/DECISOES-INCREMENTO-2.md). Especificação: [docs/spec](docs/spec).

## Como rodar

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12 (versões em `mise.toml`).

```bash
uv sync
uv run pytest -q          # todos os testes
uv run pytest -q -m ac    # só os testes ligados a casos de aceite da Spec
uv run ruff check .
```

## Rodar a API

A API (`/v1`, FastAPI) precisa de banco e de segredos. Os segredos moram no 1Password (cofre `Personal`, item `prof-em-casa`) e o `.env` é gerado, nunca editado à mão nem commitado:

```bash
op inject -i .env.tmpl -o .env
```

Variáveis lidas do ambiente (o modelo está em `.env.tmpl`):

- `DATABASE_URL`: Postgres (`postgresql+psycopg://...`) ou, só para desenvolvimento local, SQLite (`sqlite:///dev.db`, que cria o schema na partida). No Postgres, aplique antes as migrations de `supabase/migrations/`. Sem ela a API não sobe.
- `SESSION_TOKEN_SECRET`: chave do token de sessão, com **32 caracteres ou mais**. Um valor curto como `dev` é recusado na partida.
- `SERVICE_TOKEN_TUTOR`, `SERVICE_TOKEN_SYSTEM`, `SERVICE_TOKEN_VISION_WORKER`: tokens dos atores de serviço, 32+ caracteres e distintos entre si. Um token ausente desliga o ator correspondente.
- `OPENROUTER_API_KEY`: reservada para o avaliador e o tutor (incremento 5); a API do incremento 2 não a usa.

Com o ambiente carregado (por exemplo `set -a; source .env; set +a`), suba o servidor:

```bash
uv run uvicorn app.api.app:get_app --factory --app-dir services/backend
```

Uma sessão expira em 24 h; repetir `POST /v1/sessions` com o mesmo `request_id` depois disso responde 404, então o cliente usa um `request_id` novo para abrir outra sessão. Os comandos exigem `Content-Type: application/json` (415 caso contrário).

O contrato fica em `contracts/openapi.json`, e o servidor também o serve em `/docs`. O avaliador de explicação por texto ainda não existe: o comando `submit_explanation` responde 503 (`PROVIDER_UNAVAILABLE`) até o incremento 5.

## Organização

- `services/backend/app/domain/division/`: regras da divisão, cena, observação do caderno, ajuda e classificação da tentativa.
- `services/backend/app/content/`: carregamento do pacote de conteúdo versionado.
- `content/division-sharing-v1/`: itens, demonstração e textos (atividade própria, sem página comercial).
- `services/backend/app/sessions/`: serviço de sessão (comandos transacionais, idempotência, controle, eventos, análise).
- `services/backend/app/api/`: rotas `/v1`, erros HTTP e contrato OpenAPI.
- `services/backend/app/db/` e `supabase/migrations/`: schema (SQLite nos testes, Postgres por migration).
- `contracts/`: JSON Schema da observação do caderno e `openapi.json`.
- `tests/`: domínio, contratos, integração (SQLite e Postgres descartável) e aceite.

## Elegibilidade

Repositório criado em 05/11/2026, depois da abertura do evento. Não reutiliza código de projetos anteriores dos autores.
