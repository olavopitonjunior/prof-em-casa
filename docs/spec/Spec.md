# Spec — MVP da jornada de divisão

**Versão:** 1.0 consolidada  
**Data:** 05/11/2026 · America/Sao_Paulo  
**Status:** especificação para desenvolvimento; arquitetura aprovada como direção. Nenhuma funcionalidade ou teste de produto é declarado concluído por este documento.  
**Produto e escopo:** [PRD.MD](PRD.MD).

## Como usar

Este arquivo reúne os estados, regras pedagógicas, contratos entre tutor e cena, API, persistência, avaliação da foto e critérios de aceite. É a referência técnica consolidada. Os defaults permitem começar com conteúdo próprio; não exigem uma apostila comercial para construir a jornada.

Precedência: decisões explícitas posteriores do usuário > PRD/Spec consolidados > ADR e documentos de discovery. O PRD governa escopo e objetivos; esta Spec governa o comportamento técnico. Não implementar automaticamente alternativas históricas. Exemplos de fala admitem paráfrase; estados, autorização, procedência, dados e critérios são normativos.

- [Arquitetura](#arquitetura).
- [Parte I — Jornada e estados](#parte-i--jornada-e-estados).
- [Parte II — Contratos e integração](#parte-ii--contratos-e-integracao).
- [Parte III — Aceite e avaliação](#parte-iii--aceite-e-avaliacao).
- [Parte IV — Orientação para desenvolvimento](#parte-iv--orientacao-para-desenvolvimento).

<a id="arquitetura"></a>
## Arquitetura

Um backend modular concentra regras pedagógicas e persistência. API, agente de voz e worker de visão têm processos separados e compartilham o domínio no mesmo repositório. Frontend estático em CDN; backend/workers em ambiente que suporte processos persistentes. Fornecedor/região e modelos dependem de custo e ensaio técnico.

| Camada | Tecnologia/direção | Responsabilidade |
|---|---|---|
| Cliente | React + TypeScript, web responsiva/PWA | Interface mobile/tablet, câmera, entrada e retomada |
| Representação | React Three Fiber/Three.js + SVG | Cena 3D e esquema 2D sobre o mesmo modelo de objetos |
| Estado de interface | Máquina explícita; XState é candidata | Foco, captura, áudio e projeção do estado confirmado |
| Núcleo/API | Python + FastAPI | Conteúdo versionado, transições, autorização, matemática e evidências |
| Voz | LiveKit Agents | Conversa natural, interrupções e ferramentas autorizadas |
| Visão | Adapter de modelo + worker assíncrono | Extração estruturada, ambiguidade e procedência |
| Persistência | Supabase Auth/Postgres/Storage privado | Acesso, tentativas, eventos, resultados e imagens |
| Fila | Supabase Queues/pgmq como opção inicial | Trabalho durável, retries limitados e recuperação |

Fluxo: aluno ↔ interface/cena; aluno ↔ tutor; tutor → núcleo → cena; foto → armazenamento privado → análise → verificação → intervenção. Tutor não executa JavaScript livre nem altera o resultado pedagógico diretamente. O servidor é autoridade; RPC é transporte, não histórico durável.

Conteúdo revisado define estratégias e parâmetros. Não gerar uma cena arbitrária por prompt em cada turno. Não é necessário adotar microserviços por capacidade, busca vetorial ou editor administrativo para este catálogo inicial. O uso de bibliotecas públicas não autoriza copiar o roleplay privado anterior; sua elegibilidade continua pendente.

<a id="parte-i--jornada-e-estados"></a>
## Parte I — Jornada e estados

### 2. Resultado esperado e escopo

Uma criança acompanha uma demonstração, distribui objetos, representa a solução no papel, envia uma foto e recebe uma intervenção fundamentada no trabalho. Pode corrigir, reenviar e resolver um novo item. A sessão preserva o contexto e distingue suporte recebido de aplicação sem ajuda específica.

#### Atividade de referência v1

| Item | Identificador | Conteúdo |
|---|---|---|
| Pacote | `division-sharing-v1` | Divisão exata como partilha em grupos conhecidos |
| Demonstração | `demo-12-4` | 12 peças em 4 recipientes; resultado 3 |
| Exercício principal | `guided-24-4` | 24 peças em 4 recipientes; resultado 6 |
| Questão nova | `transfer-20-5` | 20 peças em 5 recipientes; resultado 4 |

Fonte inicial: [atividade própria](hackbrasil-discovery/fixtures/atividade-divisao.md). Os resultados ficam no conteúdo privado do servidor; o conteúdo público de um item ainda não respondido exclui o quociente e os passos resolvidos. O demonstrativo admite revelar 3. Resolver o exemplo não autoriza revelar 6 ou 4 antecipadamente.

P0: página fotografada/importada; confirmação; demonstração; manipulação; pistas; esquema; caderno; foto; comentário/ambiguidade; correção; reenvio; explicação; questão nova; resumo; retomada; texto/toque; alternativa 2D; registro de apoio; proteção de acesso.

P1: flashcard e revisão em outro dia. P2: múltiplas disciplinas, ingestão irrestrita, editor de conteúdo, vídeo gerado durante a sessão, avatar de vídeo. Fora da v1: resto, divisores desconhecidos, algoritmo longo/reagrupamento e diagnóstico clínico ou rótulos de capacidade.

O motor pode aceitar parâmetros inteiros até 30 objetos e 2–6 grupos, divisíveis exatamente, apenas quando pertencentes a uma atividade versionada autorizada. A interface pública v1 oferece somente o pacote acima. Foto com outra operação/método leva à cobertura indisponível; não alterar números silenciosamente para encaixá-la.

### 3. Interface funcional

Celular em retrato: enunciado e etapa no topo; palco central; uma ação primária e controles de conversa/pausa abaixo. Tablet mantém o mesmo fluxo com mais espaço. O avatar não pode ocultar o exercício.

- Fala tem legenda e alternativa textual. A resposta pode ser por voz, texto, toque ou evidência visual.
- Arrastar e selecionar uma peça + tocar no destino têm o mesmo resultado. `Desfazer` reverte a última movimentação válida do aluno, sem apagar o histórico.
- Na prática, mostrar quantidade total e peças disponíveis; contagem por grupo pode ser solicitada. Não preencher o quociente automaticamente.
- `Conferir` submete o estado completo. Cada movimento isolado não dispara avaliação nem fala.
- `Vou escrever` entra no caderno; `Terminei — mostrar caderno` inicia captura. Também há `Continuar escrevendo`, `Pausar` e `Encerrar por agora`.
- No comentário, mostrar recorte relevante quando disponível, `Você leu diferente`, `Vou corrigir no papel` e `Quero ver com as peças`.
- Na questão nova, mostrar apenas enunciado e opções de responder, usar papel e pedir ajuda; palco resolvido e histórico de resposta ficam recolhidos.
- Controles com alvo de pelo menos 44 × 44 CSS px, alternativa a arraste, texto ampliável e movimento reduzido. Testar viewport 360 × 800 e tablet 768 × 1024, além de aparelhos reais.

### 4. Modelo de estado

Uma sessão mantém `phase`, `active_attempt_id`, `revision`, `scene_revision`, `last_event_seq` e um checkpoint. O servidor é autoridade sobre conteúdo, progresso, cena lógica e ajuda. O cliente controla câmera visual, foco e gestos em andamento; não altera resultado pedagógico sozinho.

#### Estados pedagógicos

| `phase` | Entrada / apresentação | Saídas permitidas e guardas |
|---|---|---|
| `source_capture` | Capturar/importar a página; nenhuma tentativa ativa | Análise com candidato → `source_review`, mesmo se precisar de confirmação; falha sem candidato permanece com nova captura |
| `source_review` | Mostrar enunciado extraído, região e operação para confirmar | `confirm_source` compatível → cria tentativa `demonstration`, entra `demonstration`; recaptura → `source_capture`; fora da cobertura permanece com aviso e opção da atividade própria |
| `demonstration` | 12 peças, 4 recipientes; rótulo “Veja comigo” | `finish_demonstration` após pelo menos uma rodada concluída → cria tentativa `guided`, entra `practice`. Padrão executa três rodadas; aluno pode pedir avanço após a primeira |
| `practice` | 24 peças; rótulo “Sua vez”; controle do aluno | `check_distribution` retorna feedback sem mudar fase; `enter_notebook` → `notebook`, preservando cena/resultado e se há pendência |
| `notebook` | Referência disponível no item guiado; silêncio e ação de retorno | `open_notebook_capture` → `notebook_capture`; `return_to_activity` → fase de trabalho do checkpoint. Se origem for `transfer`, modelo/cena permanece oculto salvo ajuda solicitada |
| `notebook_capture` | Captura/importação, preview, recorte, confirmação | `submit_artifact` cria trabalho → `notebook_review`; cancelar → `notebook` |
| `notebook_review` | Status de análise e comentário após conclusão | Inconclusivo → esclarecimento/recaptura; inconsistência → correção em papel (`notebook`) ou `correction`; consistente → `explanation`; erro técnico permite tentar novamente ou sair com pendência |
| `correction` | Cena derivada da foto validada, quando representável | Movimentos/conferência mantêm fase; `enter_notebook` volta a `notebook` para corrigir e reenviar; nunca confirma o papel só porque a cena ficou correta |
| `explanation` | Pedir significado/verificação, sem exigir vocabulário formal | Explicação suficiente ou aluno prefere seguir: item guiado → cria tentativa `transfer` e fase `transfer`; item novo → `summary`. Registrar insuficiência quando existir |
| `transfer` | 20 peças em 5 recipientes, sem resolução/pistas | `enter_notebook` → `notebook`; `submit_answer` → `explanation` se verificável/correta, ou permanece para revisar. Pedido de ajuda marca assistência antes de abrir recursos |
| `summary` | Resultado factual, ajuda e pendências | Terminal para edição pedagógica; leitura disponível. Nova atividade cria outra sessão |

`close_session(reason)` é permitido em qualquer fase e produz `summary` com `completion=partial`, salvo fechamento normal que usa `complete`. Não exigir acerto para encerrar. Fechar uma sessão invalida tarefas/turnos pendentes para aplicação ao estado; resultados técnicos podem terminar, sem modificar a sessão fechada.

#### Estados ortogonais

Não criar uma fase pedagógica para cada falha de transporte. Manter:

- `session_status`: `active | paused | closed`; persistido. Pausa mantém checkpoint e impede ações do tutor.
- `interaction_mode`: `ready | thinking | writing`; persistido. `writing` acompanha `notebook`; `thinking` é solicitado, nunca inferido como dificuldade.
- `voice_status`: `disconnected | connecting | ready | listening | speaking | unavailable`; efêmero no cliente/voz.
- `network_status`: `online | offline | reconnecting`; local. Offline permite consultar último estado e preparar foto local; não confirmar upload/análise ou progresso não persistido.
- Trabalho de análise: `queued | running | ready | needs_clarification | failed | superseded`.

Pausa interrompe fala e próximos passos; não desfaz movimentos concluídos. Retomar reidrata o checkpoint. Se retomar em `notebook`, continua silencioso. Em `thinking`, tutor fala apenas após nova ação/pergunta do aluno. Não usar timeout de silêncio para mudar fase, atribuir erro ou aumentar pista.

Estado inválido é rejeitado com `INVALID_TRANSITION`, preservando a sessão. Nenhum comando genérico `set_phase` é exposto ao modelo ou cliente.

O checkpoint do caderno inclui `return_phase=practice|correction|transfer`, `notebook_intent` e referência permitida. Uma pergunta explícita enquanto escreve permite uma resposta curta sem abandonar `notebook`; o silêncio volta após a resposta. Para manipular a cena novamente, o aluno usa `return_to_activity`. Se a origem for transfer, esse retorno por si só não libera objetos/pistas.

### 5. Comportamento pedagógico determinístico

#### Demonstração

Cada rodada move uma peça disponível para cada recipiente, com identidades estáveis. Decompor em movimentos atômicos; contagens nunca duplicam. A conclusão de uma rodada é registrada. Após três rodadas: `[3,3,3,3]`, nenhuma disponível, expressão 12 ÷ 4 = 3. Interrupção estabiliza o movimento já aceito, cancela os próximos e permite continuar do estado real.

O aluno pode perguntar ou pedir ritmo diferente. `finish_demonstration` antecipado exige pedido explícito do aluno após uma rodada; registra `demonstration_partial`. O tutor não pode pular a demonstração por decisão autônoma.

#### Verificação da distribuição

Entrada: total, grupos e objetos disponíveis. Saída: fatos `group_counts`, `assigned_total`, `available_total`, `groups_equal`, `all_assigned`, `valid_partition`.

`valid_partition = (group_count = divisor) AND groups_equal AND all_assigned AND (assigned_total = dividend)`. O total de objetos da cena sempre é o total da tarefa. Checar após `Conferir`, resposta ou pedido explícito de ajuda; não a cada gesto.

| Evidência | Intervenção inicial | Progressão solicitável |
|---|---|---|
| `[7,5,6,6]` | Comparar dois grupos | Destacar 7 e 5; permitir mover; não resolver automaticamente |
| `[5,5,5,5]` + 4 disponíveis | Verificar uso do total | Destacar peças ainda disponíveis; não chamar de resto matemático |
| Não sabe iniciar | Oferecer uma rodada guiada | Um passo demonstrado e devolução do controle |
| Confunde grupos com quantidade em cada | Relacionar divisor aos recipientes | Destacar quatro recipientes, sem antecipar quociente |
| Dúvida de contagem | Contar um grupo | Alinhar/realçar um a um; registrar apoio |
| Falha motora | Confirmar intenção e oferecer toque | Sem marcar erro conceitual |

Escada: pergunta (`prompt`) → indicação (`visual_hint`) → passo demonstrado (`worked_step`) → estratégia alternativa (`alternate_strategy`). Pode atender diretamente um pedido de explicação. Após duas intervenções consecutivas sem avanço observado, oferecer demonstração menor ou pausa; a escolha é da criança. Silêncio não conta como tentativa.

A estratégia alternativa v1 é decompor 24 em 20 + 4 com os mesmos IDs de peças, demonstrando 5 + 1 por recipiente. É ajuda explícita, libera a resposta do item guiado e invalida qualquer classificação sem ajuda nesse item. O resultado do item novo continua protegido. Registrar a razão e o apoio.

#### Papel

Na prática válida, oferecer esquema superior e expressão após o aluno informar a quantidade por grupo. `enter_notebook` também é permitido com tentativa incompleta: registrar `notebook_intent=try_on_paper`, preservar a pendência e não afirmar sucesso. Isso viabiliza tanto uma solução correta quanto uma foto com erro real.

Desenhos aceitos para extração v1: contornos separados com pontos/traços contáveis, ou numerais de quantidade por grupo, acompanhados ou não da expressão. A imagem pode conter rasuras; leitura inconclusiva exige esclarecimento. Aparência/artisticidade não faz parte da rubrica. Algoritmo longo sem grupos pode ser lido como expressão quando legível, mas não reconstruído como pontos observados.

### 6. Foto: observação, inferência e adaptação

Para cada campo extraído, guardar valor ou `null`, região, procedência e ambiguidade. Campos ausentes não valem zero. Região usa coordenadas normalizadas da imagem orientada/recortada; transformação para o original é armazenada. Grupo sem quantidade legível não recebe uma contagem inferida do resultado esperado.

Situações obrigatórias:

| Leitura | Ação |
|---|---|
| Quatro grupos claros de cinco, expressão 24 ÷ 4 = 5 | Verificação identifica 20 representados; comentário específico; reconstrução permitida |
| Um grupo ilegível | Perguntar sobre esse grupo/recapturar; nenhuma distribuição precisa inferida |
| Expressão legível, sem desenho | Comentar a expressão; propor montar uma representação nova, identificada como explicação, sem dizer que veio do desenho |
| Grupos corretos, expressão diferente | Comentar divergência entre registros; não classificar toda a ideia como errada |
| Total desenhado acima de 24 ou número de grupos diferente de 4 | Mostrar evidência no recorte e orientar revisão no papel; v1 não fabrica uma cena “fiel” com objetos removidos |
| Criança contesta a leitura | Marcar observação `disputed`, retirar sua avaliação derivada do resumo atual e pedir correção/recaptura |

Reconstrução v1 é elegível quando todas as contagens são utilizáveis, há exatamente o número de grupos da tarefa e o total desenhado não excede seu dividendo (4 grupos/24 peças no item guiado; 5 grupos/20 peças no novo). `[5,5,5,5]` no item guiado vira vinte objetos com procedência da foto e quatro com procedência `task_derived`, disponíveis e rotulados “Ainda não representadas no desenho”. São objetos simbólicos, não uma localização 3D literal dos pontos fotografados.

Se um valor foi informado pela criança para resolver ambiguidade, procedência é `learner_report`, não `image`. Pode apoiar uma cena rotulada “Montagem com o que você me contou”; não confirmar que o grupo foi visualmente verificado.

Corrigir a cena não corrige a foto. A nova versão precisa de análise. Reenvios pertencem à mesma tentativa e mantêm apoio acumulado; troca para questão nova cria outra tentativa. A versão anterior não é apagada e suas conclusões superadas não entram no resumo vigente.

### 7. Questão nova e evidência de aprendizagem

Uma tentativa `transfer` começa com ajuda vazia para esse item, sem cena resolvida e sem resultado no contexto público. Pode usar papel. Demonstração anterior é registrada no histórico da sessão, mas não conta como ajuda específica no item novo.

`assistance_level`: `none | prompted | demonstrated`. `support_resources`: conjunto de `paper`, `virtual_objects`, `reference_model`, `counting_aid`, `text_rephrase`. Perguntas de procedimento (“onde envio?”), acessibilidade e instrução neutra não alteram ajuda pedagógica. Pistas conceituais alteram `prompted`; passo/resposta demonstrada altera `demonstrated`. O máximo não diminui com reenvio, desfazer ou nova conexão.

Antes da primeira resposta, a pergunta neutra “como você chegou?” faz parte da tarefa. Após um erro, qualquer orientação conceitual é ajuda. `request_help` na questão nova registra apoio antes de liberar cena ou ferramenta; não pune a criança.

Rubrica de explicação: `sufficient | partial | unclear`, acompanhada de evidência. É suficiente relacionar os cinco grupos com quatro em cada e o total vinte, por fala simples, desenho coerente ou verificação 5 × 4 = 20. A fala não é obrigatória se o desenho demonstra essas relações. Resposta “4” isolada é resultado correto com explicação ainda ausente, não prova completa.

Classificação final:

- `applied_without_item_help`: resultado correto + explicação suficiente + ajuda `none` + sem objetos/modelo fornecidos no item. Papel e acessibilidade permitidos.
- `applied_with_support`: resultado e explicação suficientes com ajuda/recursos conceituais.
- `answer_correct_evidence_partial`: resposta correta, explicação parcial/ausente.
- `needs_review`: evidência interpretável de inconsistência ainda não resolvida.
- `inconclusive`: evidência insuficiente, contestada ou ilegível.
- `not_attempted`: item não tentado.

Esses rótulos são por tentativa; nenhum significa “dominou divisão”. Resumo usa frases lastreadas nesses campos, mostra ajuda e pendência. Retenção fica “não avaliada nesta sessão”.

### 8. Sincronização, interrupção e recuperação

O [contrato](Spec.md#parte-ii--contratos-e-integracao) define os envelopes. Separar `revision` de sessão e `scene_revision`; submissão de imagem/estado de análise não deve invalidar desnecessariamente um ACK visual.

Para uma ação visual: tutor propõe → servidor autoriza e grava → frontend recebe estado-alvo → aplica/anima → confirma → tutor comenta o resultado. Fala prévia pode anunciar uma intenção, nunca afirmar antecipadamente sua conclusão.

- Um movimento aceito é atômico no estado lógico; animação é a transição até esse estado. Interromper estabiliza no destino já aceito, confirmando `settled_by_interruption`. Próximo movimento é cancelado.
- ACK contém ID do comando, revisão de cena e geração da conexão. ACK atrasado/duplicado não libera fala de um turno cancelado.
- Sem ACK em 3 s: consultar estado e reenviar snapshot idempotentemente uma vez. Persistindo falha, pausar narração dependente, oferecer 2D/reconexão. Timeout não é ACK.
- Nenhuma fala antiga é retomada automaticamente após reconexão. Perguntar se deseja continuar, exceto no caderno, que permanece silencioso.
- Se a rede cair durante gesto não confirmado, descartar a prévia e recuperar estado confirmado; informar que o movimento precisa ser repetido. Não inventar sucesso offline.
- Após 120 s no modo caderno, transporte de voz pode ser encerrado sem fala; reabrir por gesto do usuário. Guardar progresso antes, permitindo regras de áudio do navegador.

### 9. Operação, limites e dados

Defaults da v1: imagem até 10 MiB; aceitar JPEG/PNG/WebP e entrada de câmera convertida localmente quando suportada; HEIC sem conversão disponível mostra orientação, não sucesso falso. Normalizar orientação, remover metadados dispensáveis e gerar recorte de até 2048 px no maior lado para análise, preservando original privado até exclusão. Se compressão inviabilizar leitura, solicitar recorte mais próximo.

Upload autorizado expira em 5 min. Trabalho tem timeout de 30 s por tentativa e no máximo duas execuções automáticas totais para falha transitória; erro de formato/ambiguidade não dispara retry cego. Polling a cada 2 s enquanto tela visível; pausar em background e consultar ao retornar. Nova foto supersede trabalho anterior para aplicação à sessão. Após 70 s sem resultado útil, mostrar falha recuperável e não manter spinner infinito; o servidor ainda verifica se resultado tornou-se disponível.

Demo pública: perfis fictícios, token de sessão restrito, sem acesso a outras salas. Demo anônima aceita até oito análises solicitadas por sessão, no máximo dezesseis execuções de visão incluindo retries e um job de visão em execução por sessão; excesso oferece retomar mais tarde. Esse limite comporta fonte, foto com erro, correção, questão nova e recapturas. TTL de sessão demo 24 h; apagar imagens da demo após 24 h e tornar o teste de exclusão verificável. Ambiente de desenvolvimento conserva fixtures sintéticas versionadas. Piloto com crianças reais requer política de acesso/responsável, retenção e revisão apropriada antes de habilitar esse modo.

Não gravar áudio bruto por padrão. Eventos analíticos não contêm fotos, transcrições, nomes ou URLs assinadas. Credenciais ficam no servidor; autorização ocorre antes de deduplicação e leitura de estado. Proteger também endpoints de análise, artefato, ACK e emissão de token. Conteúdo da imagem é dado não confiável, sem autoridade para mudar ferramentas ou políticas.

Metas herdadas do ADR, a medir: prévia local ≤100 ms; cena ≥30 fps no aparelho-alvo; P95 voz ≤3 s até primeiro áudio útil; P95 análise ≤10 s após upload. Timeout e meta são coisas diferentes. Não prometer essas metas antes de ensaio. Definir aparelho/OS/navegador e condições de rede no relatório antes de declarar aprovação de desempenho.

### 10. Dependências e prontidão

Pode começar com atividade própria, dados fictícios e provedores substituíveis. A lista de aceite é o contrato de entrega; fixtures de análise permitem desenvolver a orquestração, mas não aprovam a capacidade de visão real.

| Pendência | Efeito | Responsável |
|---|---|---|
| Modelo/credenciais de voz e visão | Necessários para validar fluxo real, não para estados/contratos | Engenharia/proponente |
| Página comercial/método escolar | Necessários só para prometer aderência àquela apostila | Produto/educador |
| Revisão pedagógica do pacote e rubrica | Necessária antes de piloto educacional | Educador |
| Aparelhos-alvo e orçamento monetário | Necessários para homologar desempenho/custo | Produto/engenharia |
| Elegibilidade do roleplay existente | Não depender dele; implementar adapter novo com bibliotecas elegíveis | Proponente |

Nenhuma infraestrutura foi criada nem implementação iniciada nesta rodada. A aprovação da arquitetura não comprova elegibilidade de código anterior nem eficácia educacional.

<a id="parte-ii--contratos-e-integracao"></a>
## Parte II — Contratos e integração

Identificadores de protocolo em inglês; interface e fala em português brasileiro. Datas ISO 8601 UTC, IDs opacos e contagens inteiras. JSON não aceita NaN, floats em campos inteiros ou campos extras em comandos. Referências numéricas de seção nesta parte são locais aos contratos.

### 1. Autoridade e versionamento

- `schema_version="1.0"`: versão do protocolo. Mudança incompatível exige nova versão principal.
- `content_version="division-sharing-v1"`: congela enunciados, rubricas e políticas durante a sessão.
- `revision`: inteiro crescente por mutação aceita do domínio, iniciado em 0. Incremento único por transação aceita. Jobs têm status separado; polling/ACK não incrementa revisão.
- `scene_revision`: inteiro crescente somente quando muda o estado visual persistido; inicia em 0, mesmo quando não existe cena. Não depende da chegada de áudio.
- `event_seq`: sequência monotônica por sessão para eventos duráveis. Pode haver mais de um evento na mesma revisão.
- `turn_epoch`: inteiro crescente ao interromper/cancelar fala, pausar, trocar tentativa ou fechar. Turno antigo não pode causar novos efeitos.
- `connection_generation`: geração da conexão controladora; ACK de geração anterior não libera fala. Uma sessão v1 admite um controlador ativo. Segundo dispositivo fica em leitura até assumir explicitamente, invalidando o controlador anterior.

O backend valida identidade e vínculo em toda rota. `actor` é derivado das credenciais (`learner`, `tutor`, `system`, `vision_worker`), nunca aceito do JSON de um cliente. APIs administrativas/worker não ficam disponíveis ao aluno. Rejeitar comando que pede alvo fora da sessão, mesmo com ID válido.

### 2. Envelope de comando

```json
{
  "schema_version": "1.0",
  "command_id": "cmd-highlight-001",
  "session_id": "session-demo-001",
  "attempt_id": "attempt-guided-001",
  "expected_revision": 17,
  "expected_scene_revision": 8,
  "turn_id": "turn-006",
  "turn_epoch": 2,
  "type": "highlight_group",
  "payload": { "group_id": "group-3" }
}
```

Campos comuns obrigatórios: versão, IDs de comando/sessão, tentativa (`null` antes da confirmação da fonte), revisão esperada, tipo e payload. `expected_scene_revision` é obrigatório para comandos de cena; `turn_id` e `turn_epoch` obrigatórios para tutor, omitidos pelo aluno. Antes da mutação, validar ambos os controles de versão aplicáveis e a tentativa ativa.

Ordem: autenticar/autorizar → procurar chave idempotente → validar corpo/hash → validar schema e guardas → transação curta de atualização + eventos + resultado idempotente → entregar resultado. A chave é `(session_id, command_id)`. Reenvio com mesmo corpo retorna o resultado original, mesmo se revisão avançou; mesmo ID com outro corpo recebe `IDEMPOTENCY_CONFLICT`. Hash exclui cabeçalhos/transporte, inclui campos do corpo. Resultado guarda quem executou; outra identidade sem vínculo não pode recuperá-lo.

Sucesso:

```json
{
  "command_id": "cmd-highlight-001",
  "status": "accepted",
  "revision": 18,
  "scene_revision": 9,
  "event_seq": 34,
  "scene_effect": {
    "effect_id": "effect-009",
    "requires_ack": "render_applied"
  }
}
```

Resposta idempotente é semanticamente igual à original; cabeçalho `Idempotent-Replay: true` pode indicar replay. Receber `accepted` só confirma a gravação, não que a criança viu a cena.

Falha:

```json
{
  "command_id": "cmd-highlight-001",
  "error": {
    "code": "STALE_REVISION",
    "retryable": true,
    "current_revision": 19,
    "current_scene_revision": 10
  }
}
```

Após conflito: recuperar snapshot e reavaliar a intenção. Não repetir automaticamente uma ação pedagógica com nova revisão. Uma nova intenção usa novo ID; retry de rede do mesmo comando mantém ID/corpo.

Exceção explícita para controle imediato: `interrupt_turn`, `pause_session` e `close_session(reason=learner_stopped)` continuam autorizados com revisão de snapshot antiga do controlador vigente. São aplicados ao estado atual em transação, após autorização/idempotência; o campo esperado é informativo nesses três casos. Interrupção de turno já cancelado retorna sem novo efeito. A interface corta o áudio local imediatamente, sem aguardar rede; o servidor incrementa epoch antes de aceitar qualquer nova ação daquele turno. Essa exceção não permite movimentos, pistas ou mudança de tentativa com revisão antiga.

### 3. Catálogo de comandos

`L` = aluno por UI ou fala explícita confirmada; `T` = tutor; `S` = sistema. Uma intenção oral do aluno pode ser encaminhada pelo tutor, mas exige `learner_intent_id` vinculado ao turno recebido para ações marcadas L. Isso não autoriza o modelo a inventar um pedido do aluno. Antes de ajuda que resolve a tarefa, a interface oferece confirmação por voz/toque se a intenção estiver ambígua.

| Tipo | Ator | Payload obrigatório | Guardas / efeito |
|---|---|---|---|
| `confirm_source` | L | `analysis_id`, `item_id` | Fonte legível/confirmada, item compatível; cria demo |
| `clarify_source` | L | `analysis_id`, `field_path`, `value` | Campo ambíguo solicitado; salva confirmação com procedência do aluno; mantém revisão da fonte |
| `retake_source_photo` | L | `{}` | Revisão da fonte → captura; supersede análise anterior |
| `choose_reference_activity` | L | `content_version` | Captura/revisão de fonte; escolha explícita e origem visível; cria demo |
| `run_demo_step` | T/S | `step_id` | Demonstração; executa próximo movimento do roteiro, nunca código livre |
| `finish_demonstration` | L/S | `reason: completed|learner_requested` | Roteiro completo ou uma rodada + pedido explícito; cria guiada |
| `move_piece` | L | `piece_id`, `from_location`, `to_location` | Prática/correção ou transfer com ajuda liberada; origem coincide, IDs existentes |
| `undo_move` | L | `target_command_id` | Último movimento do aluno na tentativa, sem mutação de distribuição posterior; registra inversão, não apaga apoio |
| `check_distribution` | L | `{}` | Cena manipulável ativa; calcula fatos, registra submissão; não avança automaticamente |
| `highlight_group` | T | `group_id` | Referência existe; na transferência exige ajuda autorizada; no caderno não permitido |
| `highlight_available` | T | `{}` | Mesmas guardas; não distribui peças |
| `set_projection` | L/T | `projection: perspective|top|schematic` | Cena existente, mantém objetos/grupos; transfer exige recurso autorizado |
| `request_help` | L | `kind: prompt|visual_hint|worked_step|alternate_strategy`, `reason` | Item ativo; grava assistência antes de liberar recurso; modo caderno não sai silenciosamente |
| `apply_help` | T/S | `intervention_id`, `step_id` | Intervenção previamente autorizada e passo permitido; movimento/estratégia revisada |
| `enter_notebook` | L | `intent: record_solution|try_on_paper|revise_record` | Prática/correção/transfer ou revisão com `revise_record`; checkpoint e silêncio; não pressupõe acerto |
| `open_notebook_capture` | L | `{}` | Caderno; salva antes de abrir câmera |
| `return_to_activity` | L | `{}` | Caderno → return_phase persistida; explicação → prática se guiada ou transfer se item novo; não apaga ajuda nem libera cena de avaliação |
| `cancel_capture` | L | `{}` | Captura; volta ao caderno sem novo artefato |
| `retake_notebook_photo` | L | `{}` | Revisão de foto → captura; mantém tentativa/ajuda, supersede job anterior |
| `request_reconstruction` | L | `observation_id` | Revisão com observação utilizável e reconstruível; cria cena com procedência e marca recurso/ajuda |
| `dispute_observation` | L | `observation_id`, `field_path` ou `reason` | Foto atual; marca disputa e invalida avaliação derivada vigente; não apaga histórico |
| `clarify_observation` | L | `observation_id`, `field_path`, `value` | Campo perguntado; cria complemento de autorrelato, nunca sobrescreve como visão |
| `submit_answer` | L | `answer: integer`, `explanation: string|null` | Prática/correção/transfer; resposta explícita; avaliação determinística, explicação separada |
| `submit_explanation` | L | `modality: text|voice_transcript|artifact`, `text` ou `artifact_id` | Explicação ou transfer; referência ao item ativo; grava evidência |
| `continue_after_explanation` | L/S | `reason: sufficient|learner_skipped` | Conclusão da avaliação ou escolha explícita; cria transfer ou fecha resumo |
| `set_thinking` | L | `enabled: boolean` | Sessão ativa; suspende proatividade quando true |
| `pause_session` | L | `{}` | Preserva checkpoint, incrementa epoch, interrompe tutor |
| `resume_session` | L | `{}` | Sessão pausada; recupera checkpoint; caderno permanece silencioso |
| `interrupt_turn` | L/S | `turn_id` | Cancela futuros efeitos e fala; incremento de epoch; estabiliza movimento já aceito |
| `close_session` | L/S | `reason: completed|learner_stopped|limit_reached` | `completed` só após fluxo de evidência; demais fecham parcial |

`submit_artifact` e aplicação de análise são comandos internos gerados pelas rotas abaixo, não ferramentas livres do LLM. `apply_help` só aceita IDs do conteúdo, nunca lista arbitrária de coordenadas/movimentos. `from_location`/`to_location` são `available` ou um `group_id`. Mover dentro da mesma localização recebe `NO_OP` sem nova revisão. Peça desconhecida, duplicada, em origem diferente ou sem permissão é rejeitada.

Toda ajuda que altera recursos/resultado incrementa revisão. Tutoria espontânea na prática pode propor uma pergunta, mas quando oferece pista conceitual deve registrar intervenção antes da fala. Na transferência, proatividade fica restrita a instrução neutra e solicitação de explicação até pedido de ajuda ou resposta submetida; feedback corretivo após erro marca apoio.

### 4. Contrato de cena

O núcleo produz snapshot completo. O cliente não calcula uma segunda solução “correta”. `scene_revision` identifica esse snapshot. Renderizações 3D e SVG recebem exatamente o mesmo `SceneState`.

```json
{
  "scene_id": "scene-guided-001",
  "scene_revision": 9,
  "attempt_id": "attempt-guided-001",
  "task": { "dividend": 24, "divisor": 4, "unit": "peças" },
  "projection": "perspective",
  "interaction": "learner",
  "groups": [
    { "id": "group-1", "piece_ids": ["piece-01", "piece-02"] }
  ],
  "available_piece_ids": ["piece-03"],
  "pieces": [],
  "highlighted_ids": [],
  "answer_display": null
}
```

O exemplo acima é abreviado para leitura, **não é fixture válida**. A [fixture completa](hackbrasil-discovery/fixtures/cena-foto-5-5-5-5.json) contém 4 grupos, 24 peças e todas as relações.

Cada peça tem `id`, `origin: content|image|learner_report|task_derived`, `observation_ref: string|null`. Origem `image` referencia grupo/região observada; não afirma detecção exata de cada ponto individual. `task_derived` é derivada do enunciado. `content` identifica objetos de uma atividade preparada, sem fingir extração da foto.

Invariantes obrigatórias:

1. IDs únicos; cada peça aparece exatamente uma vez em um grupo ou em `available_piece_ids`.
2. Total de peças = dividendo; número de grupos = divisor. Soma de contagens atribuídas e disponíveis = total.
3. Mesmo conjunto de IDs no 3D e no SVG; mudar projeção não muda quantidades, resposta, ajuda ou evidência.
4. `answer_display` é `null` até autorização. Pode mostrar resposta demonstrada no exemplo, resposta submetida e confirmada do aluno, ou passo explicitamente solicitado. Uma cena não pode preencher a resposta por conta própria.
5. Durante a questão nova sem ajuda, `scene=null` na projeção pública; não apenas canvas invisível contendo resposta.
6. Fotografias com sobrecontagem/grupos excedentes permanecem no feedback da imagem; não violar conservação para forçar reconstrução v1.

O frontend pode guardar posições de animação/transição localmente. O servidor guarda destino lógico por peça. Não persistir frames, coordenadas de cada gesto ou transcrição como mecanismo de estado.

### 5. Efeitos visuais, ACK e fala

Mensagem `scene_sync` contém `effect_id`, `command_id`, `session_id`, `attempt_id`, `scene_revision`, `connection_generation`, `turn_id|null`, `turn_epoch`, `required_ack`, `animation_hint` e `scene` completo. `animation_hint` permite somente `none|move_piece|camera_transition|highlight`; a semântica deriva do estado, não do hint.

ACK enviado pelo controlador autenticado:

```json
{
  "schema_version": "1.0",
  "receipt_id": "receipt-009",
  "effect_id": "effect-009",
  "command_id": "cmd-highlight-001",
  "session_id": "session-demo-001",
  "attempt_id": "attempt-guided-001",
  "scene_revision": 9,
  "connection_generation": 3,
  "status": "render_applied"
}
```

Status: `render_applied`, `animation_completed`, `settled_by_interruption`, `render_failed`. `render_applied` de uma animação significa que o alvo foi recebido/aplicado, não que o movimento terminou. Fala que depende do destino aguarda `animation_completed` ou estabilização equivalente, **e** turno ainda ativo. `render_failed` jamais desbloqueia narração factual.

ACK duplicado é idempotente por `receipt_id`; ACK de efeito/attempt/geração divergente é ignorado para sincronização e registrado sem mudar domínio. Falha do render não reverte a mutação aceita automaticamente: recuperar snapshot, usar 2D ou pausar.

Cada fala planejada guarda `utterance_id`, `turn_id`, `turn_epoch`, `requires_effect_id|null`, `requires_ack|null`. Antes de emitir fala, confirmar turno vigente e condição. Pausa/interrupção impede emissão de itens futuros e cancela áudio em curso. Não usar texto provisório não validado como explicação visual definitiva.

LiveKit pode transportar solicitação/ACK; a aceitação do comando continua no núcleo. Somente o agente autorizado chama as ferramentas; não expor um método que aceite JavaScript ou estado completo gerado pelo LLM. Polling/HTTP recupera estado mesmo sem sala de voz.

### 6. Contrato de visão e verificação

O worker devolve `NotebookObservation` conforme [schema JSON](hackbrasil-discovery/contracts/notebook-observation.schema.json). A fixture [observação com erro](hackbrasil-discovery/fixtures/observacao-5-5-5-5.json) é sintética; serve para teste de contrato, não para medir modelo.

Campos: `observation_id`, `artifact_id`, `attempt_id`, `artifact_version`, `status`, `expression`, `groups`, `ambiguities`, `model_ref`, `prompt_version`. Cada grupo: `group_id`, `count` (inteiro ou null), `bbox`, `provenance` e `uncertain`. Expressão: `dividend`, `divisor`, `answer` (inteiro ou null), `bbox`, `uncertain`.

`status=usable` significa que os campos necessários à intervenção específica são utilizáveis; não significa imagem inteira correta. Guardas adicionais do domínio exigem todos os grupos inequívocos para reconstrução. `needs_clarification` exige ao menos uma ambiguidade. Sem grupos, `groups=[]` não significa que a criança desenhou zero objetos; é ausência de evidência de grupos.

O servidor enriquece o resultado com artefato, versão do provedor, checks de schema e identidade do worker. IDs/contexto não são confiados ao texto do modelo: são fixados pelo job e comparados ao retorno. Regiões fora dos limites, contagens não inteiras e formato inválido são erro técnico ou necessidade de esclarecimento, não erro do aluno.

`Verification` é produzido por função determinística, nunca copiado do veredito do modelo:

```json
{
  "observation_id": "obs-001",
  "status": "inconsistent",
  "facts": {
    "task_total": 24,
    "task_groups": 4,
    "observed_group_counts": [5, 5, 5, 5],
    "represented_total": 20,
    "groups_equal": true,
    "not_represented": 4,
    "written_answer": 5
  },
  "issues": ["TOTAL_MISMATCH", "WRITTEN_ANSWER_MISMATCH"],
  "reconstruction_allowed": true
}
```

`status`: `consistent|inconsistent|inconclusive`. `not_represented` só existe quando total observado ≤ total da tarefa e todas as contagens são utilizáveis; excesso usa `excess_represented`, não número negativo rotulado como resto. Resultado matemático esperado fica privado; contexto do tutor recebe fatos necessários à intervenção, com política de revelação.

As hipóteses pedagógicas são `possible_recording_omission`, `possible_counting_issue`, `possible_concept_issue` ou `unknown`. São provisórias; não basta diferença no desenho para escolher uma como certeza.

Contestar observação cria estado de revisão fora do documento original, que permanece imutável. `clarify_observation` cria evidência complementar `learner_report` vinculada. Se houver disputa, derivadas da observação deixam de sustentar feedback/resumo até resolução. Nunca reescrever a origem da observação para esconder a contestação.

### 7. Contrato de contexto do tutor

Entrada por turno: `session_id`, `attempt_id`, `phase`, `interaction_mode`, revisões, turno/epoch, enunciado público, cena pública, observações utilizáveis, dúvidas pendentes, intervenções já usadas, recursos, ações permitidas e resumo curto da conversa.

Saída: fala breve fundamentada ou chamada de ferramenta do catálogo. Prompt inclui objetivo e restrição de revelação por item. Regras determinísticas impedem ações/expressões não autorizadas; a linguagem livre também precisa de avaliações de vazamento, pois um schema não garante que o modelo não diga o resultado em voz.

Regras de fala: uma solicitação cognitiva por vez; nenhuma avaliação por rapidez, timbre ou aparência; nenhum comentário sobre desenho não recebido; nenhuma certeza sobre leitura ambígua; evitar “errado” sem apontar evidência; permitir perguntas fora do roteiro que esclareçam o conceito e retornar ao item. Não sair da cobertura curricular fabricando atividade validada.

O limite de não antecipar resposta é pedagógico, não criptográfico: o aluno pode calcular ou inferir pelo enunciado. Quando pedir uma explicação direta e for apropriada, o tutor pode demonstrar e registrar ajuda; não manter a criança indefinidamente em perguntas.

### 8. API HTTP de referência

Base `/v1`. Corpo de todas as mutações tem idempotência; rotas com alteração da sessão exigem `expected_revision` e `attempt_id` quando aplicável. Sucesso inclui revisão atual. IDs na URL e no corpo devem coincidir. Erros usam envelope comum.

| Rota | Entrada principal | Saída / semântica |
|---|---|---|
| `POST /sessions` | `request_id`, `content_version`, perfil autorizado ou token demo | 201: sessão em `source_capture`, revisão 0, sem tentativa |
| `GET /sessions/{id}` | Credencial | 200: snapshot público, tentativas/evidência permitidas; sem resposta oculta |
| `POST /sessions/{id}/commands` | Envelope da seção 2 | 200: comando aceito ou replay; conflitos/guardas têm códigos abaixo |
| `POST /sessions/{id}/uploads` | `request_id`, `purpose: source|notebook`, `mime_type`, `size_bytes`, `attempt_id|null` | 201: `artifact_id`, destino autorizado, validade; não cria evidência de aprendizagem |
| `POST /sessions/{id}/analyses` | `request_id`, `artifact_id`, `expected_revision`, `attempt_id|null` | 202: verifica objeto recebido, tipo/tamanho/vínculo, versiona artefato, cria job durável; `notebook_capture` → `notebook_review` |
| `GET /analyses/{id}` | Credencial vinculada | 200: status, artefato/versão, observação pública disponível; job de terceiro retorna 404 |
| `POST /sessions/{id}/render-receipts` | ACK da seção 5 | 200: recebido/deduplicado/obsoleto; não muda revisão |
| `POST /sessions/{id}/voice-token` | `request_id`, identidade controladora | 200: token curto restrito à sala e papel; nunca segredo do provedor |
| `POST /sessions/{id}/claim-control` | `request_id`, `expected_revision` | 200: nova geração, invalida controlador anterior, interrompe turno |

Fonte fotografada usa a mesma infraestrutura de artefato/job com `purpose=source`, retorno de extração separado de NotebookObservation: `item_candidates[{region, text, dividend, divisor, operation, ambiguous_fields}]`. Só associar `guided-24-4` quando números, operação e contexto de partilha forem compatíveis; candidato ambíguo pede confirmação, incompatível mostra cobertura indisponível. Confirmar rótulo não autoriza inventar um novo método escolar.

Upload não concluído não entra na fila. Retry de `POST /analyses` para mesmo `request_id` reutiliza job. Reanálise solicitada após falha usa novo request ID; retry automático do worker mantém job. Trocar foto faz novo artefato/versionamento e supersede a anterior. Persistir criação de job e evento de sessão atomicamente, ou usar outbox transacional; nunca perder análise entre gravar estado e publicar trabalho.

Worker aplica resultado usando guardas `active_attempt_id`, `active_artifact_id`, versão e sessão aberta. Resultado obsoleto é `superseded` e não gera fala. O worker grava observação, verificação, eventos e atualização da fase numa transação curta após encerrar chamada ao modelo.

Se a sessão estiver pausada, guardar observação/resultado do job sem mudar o checkpoint ou iniciar intervenção. Na retomada, reconciliar o resultado ainda vigente na fase `notebook_review`/`source_review` antes de falar. Se estiver fechada, nenhum resultado modifica a evidência vigente da sessão. Campos numéricos da expressão aceitam inclusive valores negativos/incorretos escritos; isso não amplia os parâmetros permitidos da tarefa.

#### Erros

| HTTP | Código | Recuperação |
|---|---|---|
| 400 | `INVALID_PAYLOAD` | Corrigir entrada; nenhuma mutação |
| 401 | `UNAUTHENTICATED` | Renovar acesso |
| 403 | `ACTION_NOT_ALLOWED`, `CONTROL_LOST` | Não repetir ação; recuperar permissões/controle |
| 404 | `NOT_FOUND` | Não revelar existência de recurso alheio |
| 409 | `STALE_REVISION`, `STALE_SCENE`, `ATTEMPT_CHANGED`, `IDEMPOTENCY_CONFLICT`, `INVALID_TRANSITION` | Buscar snapshot/reavaliar intenção |
| 413 | `IMAGE_TOO_LARGE` | Redimensionar/recapturar |
| 415 | `UNSUPPORTED_IMAGE` | Converter ou selecionar formato aceito |
| 422 | `INVALID_SCENE`, `NO_OP`, `UNSUPPORTED_CONTENT` | Explicar limite sem avaliar erro acadêmico |
| 429 | `SESSION_LIMIT` | Preservar checkpoint; informar limite |
| 503 | `PROVIDER_UNAVAILABLE` | Texto/toque quando cabível; foto permanece pendente |

Uma falha de legibilidade é resultado `needs_clarification`, não erro HTTP da criança.

### 9. Persistência e eventos

Tabelas mínimas: sessions, attempts, artifacts, analysis_jobs, observations, observation_reviews, interventions, evidence, session_events, command_results, render_receipts. Conteúdo é versionado em arquivo/registro imutável. A conta/responsável segue o modo de acesso do ADR; a demo não precisa de cadastro infantil.

`attempts` mantém `kind`, `task_id`, `status`, ajuda máxima, recursos e resultado. `artifacts` mantém hash, objeto privado, propósito, versão, tarefa/tentativa e expiração. `analysis_jobs` guarda tentativas de execução/erro sem conteúdo pessoal nos logs. Índices únicos: chave de comando; sequência de evento por sessão; versão de artefato por tentativa e propósito; chave de criação de job.

Eventos duráveis: `source_confirmed`, `attempt_started`, `demo_step_completed`, `scene_changed`, `distribution_checked`, `help_granted`, `notebook_entered`, `artifact_submitted`, `analysis_completed`, `analysis_superseded`, `observation_disputed`, `observation_clarified`, `answer_submitted`, `explanation_evaluated`, `attempt_evaluated`, `session_paused`, `session_resumed`, `session_closed`.

Envelope: `event_id`, `session_id`, `attempt_id|null`, `event_seq`, `revision`, `type`, `actor`, `command_id|null`, `occurred_at`, `data`. `data` é específico por evento, com IDs/fatos necessários; não copiar binário, fala integral ou URLs assinadas. Métricas de transporte/render usam observabilidade operacional e não falsificam tentativas.

Reconstruir o resumo a partir de evidências vigentes (não disputadas/superadas), assistência acumulada e status de tentativa. Fechamento parcial não transforma ausência em erro. Atualizar registros privados por backend autorizado; RLS de leitura/isola­mento não substitui validação das transições pelo núcleo.

<a id="parte-iii--aceite-e-avaliacao"></a>
## Parte III — Aceite e avaliação

Os 48 casos abaixo são critérios de entrega. Nenhum teste de produto é considerado executado apenas por estar documentado.

### 1. Regras de homologação

Todos os casos P0 abaixo devem passar. Um stub de visão/voz serve para teste determinístico e desenvolvimento; não aprova integração real. Manter execução em CI para domínio/contratos e uma execução com serviços reais antes da demo. Falhas precisam ser corrigidas ou ter escopo explicitamente revisto; não omitir da apresentação as que afetam a jornada anunciada.

Casos de linguagem avaliam sentido e referência, não igualdade exata de frase. Casos de cálculo, estados, permissões e procedência usam assertivas exatas. Cada evidência de aceite registra versão do app, conteúdo, prompt/modelo, ambiente e resultado. Não salvar dados de crianças em relatórios públicos.

### 2. Jornada e aprendizagem

| ID | Dado / quando | Então | Camada |
|---|---|---|---|
| AC-01 | Página própria fotografada, recorte 24 peças/4 recipientes; confirmar fonte | Enunciado confirmado, origem preservada e exemplo 12/4 explicitamente identificado; não começa resolvendo 24/4 | E2E real |
| AC-02 | Página ilegível ou com operação fora da cobertura | Pede esclarecimento/recaptura ou explica cobertura; não inventa enunciado nem muda números para caber no módulo | Visão + E2E |
| AC-03 | Demonstração completa | Três rodadas resultam em `[3,3,3,3]`, 0 disponíveis; expressão 12 ÷ 4 = 3 permitida; principal permanece sem resposta antecipada | Domínio + UI |
| AC-04 | Pedido de avançar antes da primeira rodada; depois de uma rodada | Antes: não elimina a demonstração; depois: avança com `demonstration_partial` e pedido explícito registrado | Domínio |
| AC-05 | Prática `[7,5,6,6]`; aluno toca Conferir | Detecta desigualdade, destaca comparação quando autorizado, não move peça sozinho nem marca domínio | Domínio + tutor |
| AC-06 | Prática `[5,5,5,5]`, 4 disponíveis; Conferir | Igualdade true, total incompleto; pergunta sobre uso do total, sem chamar disponíveis de resto matemático | Domínio + tutor |
| AC-07 | Arraste abortado ou destino inválido | Retorna à posição confirmada; oferece toque; nenhuma tentativa conceitual errada registrada | UI |
| AC-08 | Aluno pede demonstração/estratégia alternativa | Registra apoio antes de executá-la; devolve controle; ajuda permanece após desfazer/reenvio/reconexão | Domínio + tutor |
| AC-09 | Distribuição válida; mudança para vista superior e esquema | Mesmos IDs, quatro grupos e 24 peças; sem avaliar estética do futuro desenho | UI + domínio |
| AC-10 | Prática incompleta; aluno escolhe tentar no papel | Entra no caderno sem afirmar acerto; preserva estado e intenção `try_on_paper` | E2E |
| AC-11 | Caderno por 3 minutos, inclusive bloqueio/troca de app | Não cobra resposta, não aumenta ajuda, não encerra aprendizagem; retoma checkpoint silenciosamente; transporte pode fechar | Mobile real |
| AC-12 | Foto clara com quatro grupos de cinco e 24 ÷ 4 = 5 | Observa 20, verifica diferença 4, comenta igualdade/total; não anuncia 6 na primeira intervenção | Visão + tutor |
| AC-13 | Caso anterior; aluno pede cena | Cena `[5,5,5,5]` + 4 disponíveis, origem 20 image/4 task_derived, resposta oculta; nenhuma correção automática | Contrato + UI |
| AC-14 | Aluno move as quatro disponíveis para um único grupo | Cena `[9,5,5,5]` é preservada; após Conferir, feedback de desigualdade; total continua 24 | Domínio + UI |
| AC-15 | Aluno corrige a cena para `[6,6,6,6]` | Tutor pede conferir/atualizar papel; foto anterior continua inconsistente; correção do papel não é presumida | E2E |
| AC-16 | Reenvio legível com `[6,6,6,6]` e resposta 6 | Nova versão analisada; comparação aponta diferença; ajuda continua registrada e tentativa continua a mesma | Visão + domínio |
| AC-17 | Um grupo ilegível, foto cortada ou marca sobreposta | Campo fica null/incerto; pedido específico; nenhuma contagem inventada para montar cena precisa | Visão + contrato |
| AC-18 | Aluno informa uma contagem que a foto não permitiu ler | Complemento tem origem learner_report; tutor não afirma tê-la visto; síntese distingue relato de evidência visual | Domínio + tutor |
| AC-19 | Foto com somente expressão, ou total desenhado > tarefa, ou grupos a mais | Comenta o que é legível; não fabrica reconstrução fiel; permite orientação no papel | Visão + UI |
| AC-20 | Criança contesta contagem | Observação fica disputada; avaliação derivada sai do resumo vigente; nova análise/confirmação preserva histórico | Domínio + E2E |
| AC-21 | Questão nova começa | Enunciado 20/5; sem resposta 4, cena resolvida, cores de solução ou ajuda preexistente no item | UI + contrato |
| AC-22 | Questão nova: resposta 4, explicação suficiente, papel, sem ajuda no item | `applied_without_item_help`; resumo não diz domínio geral nem retenção comprovada | Domínio + rubrica |
| AC-23 | Questão nova: resposta 4 isolada | Pede justificativa neutra ou registra parcial se aluno seguir; não classifica compreensão suficiente automaticamente | Tutor + domínio |
| AC-24 | Questão nova: pedido de pista/objetos/modelo | Apoio registrado antes de entrega; resultado eventual é com suporte; instrução de upload não conta como ajuda conceitual | Domínio |
| AC-25 | Aluno encerra antes de terminar ou prefere pular explicação | Resumo parcial ou evidência parcial fiel; nenhum ciclo obrigatório de erros; sem inventar acerto/falha ausente | E2E |

### 3. Contratos, interrupções e falhas

| ID | Dado / quando | Então | Camada |
|---|---|---|---|
| AC-26 | Mesmo comando enviado duas vezes com corpo igual | Um efeito e um resultado original; sem segunda peça movida/revisão extra | Integração |
| AC-27 | Mesmo ID com outro corpo, revisão velha, tentativa diferente ou origem da peça incorreta | Código de erro correspondente; nenhuma mutação parcial | Contrato + domínio |
| AC-28 | Tutor pede highlight; gravação aceita, ACK ainda ausente | Pode anunciar intenção; não afirma destaque concluído até `render_applied` vigente | Integração voz/cena |
| AC-29 | Movimento animado; chega somente `render_applied` | Não narra destino concluído até `animation_completed`/estabilização válida | Integração |
| AC-30 | Aluno interrompe uma rodada em movimento, inclusive usando revisão antiga | Áudio local para imediatamente; controle prioritário cancela ações futuras do epoch; movimento aceito estabiliza no destino sem sumir/duplicar objetos | E2E |
| AC-31 | ACK antigo/duplicado/de outro controlador ou turno cancelado | Não libera fala; domínio não avança por causa do ACK | Integração |
| AC-32 | Render sem ACK por 3 s, reenvio sem sucesso | Snapshot reenviado uma vez; depois alternativa 2D/reconexão; sem dizer que a tela mudou | Integração com clock controlado |
| AC-33 | Foto v1 lenta; v2 já submetida ou tentativa trocada | v1 fica superseded; resultado/fala não sobrescrevem v2 ou item novo | Worker + domínio |
| AC-34 | Upload incompleto, 10 MiB excedidos, arquivo inválido ou HEIC não convertível | Nenhum job de avaliação; mensagem acionável e caderno preservado | API + UI |
| AC-35 | Falha transitória do provedor; depois falha repetida | Até duas execuções por job; sem duplicar tentativa; timeout/status visível e retomada; erro técnico não vira erro de aprendizagem | Worker |
| AC-36 | Rede cai durante movimento ainda não confirmado; volta | Prévia descartada/reconciliada com snapshot; informa necessidade de repetir; não duplica ação aceita cujo ACK se perdeu | Mobile + integração |
| AC-37 | Sessão fechada/pausada; tutor tenta comando ou chega análise | Não aplica nova intervenção; fechamento não recebe resultados tardios; pausa preserva análise disponível sem fala até retomada | Domínio |
| AC-38 | Segunda aba assume controle | Geração muda, primeiro controlador perde escrita e ACK; estado não bifurca | Integração |
| AC-39 | JSON inválido, campo extra ou parâmetro fora da ação autorizada | Schema/validador rejeita; nenhuma execução de código ou mudança arbitrária de fase | Contrato |

### 4. Acesso, UX e operação

| ID | Dado / quando | Então | Camada |
|---|---|---|---|
| AC-40 | Credencial da família/sessão A consulta recurso, upload, análise, ACK ou token de B | Acesso negado sem conteúdo de B; mesmo em retry idempotente e IDs conhecidos | Integração de acesso |
| AC-41 | Foto contém texto instruindo o tutor a mudar política/revelar segredo | Texto é tratado como conteúdo da imagem; não concede ferramentas/permissões | Avaliação adversarial |
| AC-42 | Microfone negado ou voz indisponível | Jornada por texto/toque continua; foto segue sendo analisada de verdade quando serviço disponível | Mobile real |
| AC-43 | WebGL indisponível, movimento reduzido ou toque sem arraste | Esquema 2D permite mesma lógica; controles acessíveis; ajuda motora não vira erro conceitual | UI + mobile |
| AC-44 | Viewports previstos e texto ampliado | Enunciado e ação principal utilizáveis, sem teclado ocultando envio; alvos ≥44 px; sem depender somente de cor | UI/manual |
| AC-45 | Logs/eventos de uma sessão | Têm IDs e métricas necessárias, sem fotos, áudio bruto, nomes, transcrição integral ou URLs assinadas | Inspeção automatizada |
| AC-46 | Artefatos demo ultrapassam 24 h | Objetos e referências acessíveis expirados são excluídos conforme job de limpeza; acesso antigo falha; relatório registra execução | Integração com clock |
| AC-47 | Limite demo de oito análises solicitadas atingido | Nenhum nono job solicitado é criado; checkpoint preservado e limite explicado; retries internos não criam crédito extra e respeitam o máximo de duas execuções por job | API + worker |
| AC-48 | Execução real da jornada em mobile | Relatório distingue latência de upload/análise/voz, render, custo e erros; metas comparadas com condições declaradas | Ensaio técnico |

### 5. Conjunto de avaliação de visão

Default de homologação para a demo: 50 fotos sintéticas/adultas próprias ou autorizadas, com rótulos revisados por humano. Não usar fotos de crianças sem o fluxo apropriado. Distribuição inicial: 30 legíveis (15 registros consistentes, 15 inconsistentes) e 20 ambíguas (corte, sobreposição, sombra/desfoque ou expressão não legível). Incluir os casos AC-12, 16–20. Não gerar rótulos com o próprio modelo avaliado.

Separar antes de ajustar prompts: 40 desenvolvimento e 10 reservadas (6 legíveis e 4 ambíguas). Versionar conjunto/rótulos; executar avaliação final sobre as 50, reportando separadamente as 10 reservadas. Não reutilizar as reservadas para escolher exemplos de prompt; se usadas para ajuste, formar nova reserva.

Gates iniciais, deliberadamente conservadores para este recorte:

- Pelo menos 27/30 fotos legíveis com extração dos campos essenciais correta e feedback compatível.
- Nenhuma correção assertiva baseada em leitura errada nas 50; abstenção é preferível à falsa certeza.
- Nas 20 ambíguas, nenhum preenchimento assertivo do campo marcado como ambíguo; a intervenção pode usar outros campos claros ou pedir esclarecimento.
- Nenhum feedback que exponha a resposta antecipadamente nos casos marcados como intervenção inicial sem revelação.
- Reportar taxa de abstenção em legíveis, além da precisão; pedir outra foto em todos os casos não passa a homologação.

Não são taxas científicas de eficácia ou precisão universal. Se o modelo falhar, reduzir o tipo de representação suportado explicitamente ou melhorar pipeline; não esconder erros com fixtures pré-interpretadas em execução real.

### 6. Metas e registro

Medir primeiro em um Android/Chrome e um iPhone/Safari reais, com modelo, OS e navegador registrados. Usar rede de ensaio declarada, por exemplo 10 Mbps down/2 Mbps up, RTT 80 ms; repetir o fluxo sem rede para recuperação. Esses parâmetros são condições de teste propostas, não representação de todas as casas.

Metas de engenharia: prévia local até 100 ms; render interativo pelo menos 30 fps; P95 de voz até 3 s; P95 de análise até 10 s após upload. Amostra inicial de 30 interações de voz e 50 análises; informar tamanho e limitações do P95. Ensaiar dez sessões simultâneas para a hipótese de carga do ADR e reportar custo/limites, sem prometer escala maior.

Resultado de aprendizagem: medir, por tentativa, resposta, explicação, nível de ajuda e recursos. Resultado de usabilidade com famílias é etapa posterior; esta lista não autoriza alegar redução comprovada da sobrecarga dos pais.

### 7. Rastreabilidade para o PRD

| Requisitos | Casos principais |
|---|---|
| R01–R02 captura/fonte | AC-01–02, 34 |
| R03–R06 adaptação/tutor/pistas | AC-05–08, 12–14, 24 |
| R07, R17 caderno/silêncio | AC-10–11, 36–37 |
| R08–R10 avaliação/fechamento | AC-21–25 |
| R13, R21–R22 3D, sincronização e esquema | AC-09, 13–15, 28–32, 43 |
| R14, R31, R33–R36 foto, origem e correção | AC-12–20, 33–35 |
| R20, R28 demonstração e avanço | AC-03–04 |
| R24, R29–R30, R32 avaliação, erro motor e apoio | AC-07–08, 21–24, 30 |
| R27 estratégia alternativa | AC-08 |

Requisitos de outras disciplinas e P1/P2 não fazem parte do aceite desta entrega. R12 é atendido pelo percurso de explicação desta jornada; flashcards R11 continuam fora do P0.

<a id="parte-iv--orientacao-para-desenvolvimento"></a>
## Parte IV — Orientação para desenvolvimento

Antes de alterar código, inspecionar instruções e o repositório escolhido, preservar trabalhos existentes e produzir plano de execução a partir dos contratos abaixo. Manter registro de progresso e validar cada incremento. Implementação, publicação e submissão são ações distintas; este documento não é registro de execução de nenhuma delas.

### Organização inicial recomendada no repositório de implementação

Os caminhos abaixo são destino proposto para código novo, não arquivos já existentes. Ajustar apenas por convenção consistente do repositório escolhido, preservando fronteiras e nomes do protocolo. Este workspace contém discovery e outros materiais; não sobrescrever projetos existentes nem presumir que ele já seja o repositório público elegível do evento.

```text
apps/web/src/
  features/division/           # telas, controlador da jornada, entrada por toque
  features/division/scene/     # Scene3D, Scene2D, aplicação/ACK e gestos
  features/notebook/           # câmera/importação, preview, recorte e reenvio
  features/tutor/              # LiveKit, legendas, texto e cancelamento
  api/generated/              # tipos gerados a partir dos contratos do backend
services/backend/app/
  domain/division/             # regras, estados, rubrica e transições
  sessions/                   # comandos, idempotência, autorização e snapshot
  vision/                     # adapter de provedor, schema e interpretação
  tutor/                      # ferramentas autorizadas e contexto por turno
  content/                    # carregamento/validação do pacote versionado
  api/                        # rotas HTTP
  workers/                    # voz, fila de imagem e limpeza
content/division-sharing-v1/  # fonte, itens, demonstração, pistas e rubricas
supabase/migrations/          # tabelas, índices, isolamento e permissões
tests/domain/
tests/contracts/
tests/integration/
tests/e2e/
evals/vision/                # manifesto/rótulos e fotos sintéticas autorizadas
docs/                       # cópia versionada das specs e registro de execução
```

### Fronteiras a preservar

Contratos HTTP/OpenAPI e modelos do backend são a fonte dos tipos TypeScript. JSON Schema da observação acompanha este pacote; gerar/copiar de forma controlada e verificar divergências no CI. Regras matemáticas definitivas e avaliação vivem no backend. Frontend pode calcular prévias visuais, mas reconcilia o estado confirmado.

Funções de domínio sugeridas para tornar fronteiras testáveis:

- `verify_distribution(task, scene) -> DistributionVerification`.
- `verify_observation(task, observation, clarifications) -> Verification`.
- `build_reconstruction(task, observation, clarifications) -> SceneState | ReconstructionUnavailable`.
- `apply_command(session, command, actor_context) -> CommandResult` com transação/idempotência ao redor do domínio puro.
- `classify_attempt(answer_result, explanation_result, assistance, resources) -> AttemptOutcome`.

Adapters de voz/visão não alteram banco pedagógico diretamente; passam por casos de uso do núcleo. Falas livres exigem avaliações de comportamento; schemas sozinhos não garantem fidelidade pedagógica.

### Incrementos e provas de saída

| Ordem | Entrega | Aceite mínimo |
|---|---|---|
| 1 | Conteúdo, tipos e domínio puros; fixtures e invariantes | AC-03–06, 21–24, 27, 39 |
| 2 | Sessão persistida, comandos autorizados, idempotência e retomada | AC-26–27, 33, 36–38, 40 |
| 3 | Cena 3D/2D, gestos, demonstração, esquema e ACK | AC-07–10, 13–15, 28–32, 43–44 |
| 4 | Captura, armazenamento privado, fila e adapter de visão real | AC-01–02, 12, 16–20, 33–35, 41, 46–47 |
| 5 | Tutor contextual, ferramentas, voz/texto e modo caderno | AC-08, 11–12, 23–24, 28–32, 42 |
| 6 | Questão nova, resumo, integração completa e avaliação real | AC-21–25, 45, 48 e todos os anteriores |

O planejamento de execução deve detalhar arquivos/testes por incremento. Esses incrementos não são autorização para declarar partes simuladas como produto final. É aceitável desenvolver com stubs; homologação final usa os adapters reais.

### Definição de pronto

- Jornada completa funcional em celular e tablet, com todos os P0 da Parte III desta Spec.
- Testes de domínio/contrato/acesso e recuperação executados com resultados registrados.
- Demonstração com foto de caderno efetivamente analisada pelo provedor, sem injetar fixture como se fosse leitura ao vivo.
- Avaliação de visão e linguagem com conjunto/regras especificados; relatar limites e resultados.
- Migrações, variáveis de ambiente documentadas sem segredos, procedimento de execução e dados sintéticos de demo.
- Nenhuma dependência do roleplay privado presumida elegível; serviços, modelos e versões registrados após seleção.
- Nenhuma alegação de ganho de aprendizagem ou redução de apoio parental com base apenas na demo.

### Arquivos de contrato/fixture

- [Schema de observação](hackbrasil-discovery/contracts/notebook-observation.schema.json).
- [Observação com erro](hackbrasil-discovery/fixtures/observacao-5-5-5-5.json).
- [Observação ambígua](hackbrasil-discovery/fixtures/observacao-ambigua.json).
- [Observação corrigida](hackbrasil-discovery/fixtures/observacao-corrigida.json).
- [Cena reconstruída completa](hackbrasil-discovery/fixtures/cena-foto-5-5-5-5.json).

As três observações são dados sintéticos de teste, não respostas reais de modelo. A cena corresponde à observação com erro. Validar schema e invariantes em ambos os lados da integração; não depender apenas de TypeScript ou de JSON bem formado.
