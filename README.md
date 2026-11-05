# tutor-divisao

Tutor de estudo para alunos do 4º e 5º ano que transforma uma atividade da apostila em uma aula interativa. Projeto inscrito no Hack Brasil 2026 (trilha Acesso à educação).

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
| 2 | Sessão persistida, comandos autorizados, retomada | em desenvolvimento |
| 3 | Cena 3D/2D, gestos, demonstração | planejado |
| 4 | Captura e análise real da foto do caderno | planejado |
| 5 | Tutor por voz/texto | planejado |
| 6 | Questão nova, resumo, integração completa | planejado |

Detalhes do que foi verificado: [docs/EXECUCAO.md](docs/EXECUCAO.md). Decisões: [docs/DECISOES-INCREMENTO-1.md](docs/DECISOES-INCREMENTO-1.md). Especificação: [docs/spec](docs/spec).

## Como rodar

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12 (versões em `mise.toml`).

```bash
uv sync
uv run pytest -q          # todos os testes
uv run pytest -q -m ac    # só os testes ligados a casos de aceite da Spec
uv run ruff check .
```

## Organização

- `services/backend/app/domain/division/`: regras da divisão, cena, observação do caderno, ajuda e classificação da tentativa.
- `services/backend/app/content/`: carregamento do pacote de conteúdo versionado.
- `content/division-sharing-v1/`: itens, demonstração e textos (atividade própria, sem página comercial).
- `contracts/`: JSON Schema da observação do caderno.
- `tests/`: domínio, contratos e aceite.

## Elegibilidade

Repositório criado em 05/11/2026, depois da abertura do evento. Não reutiliza código de projetos anteriores dos autores.
