# PRD — Tutor de estudos a partir da apostila

**Versão:** 1.0 consolidada  
**Data:** 05/11/2026 · America/Sao_Paulo  
**Status:** direção arquitetural aprovada; MVP de divisão especificado para desenvolvimento. Produto ainda não implementado nem validado com crianças.  
**Nome do produto:** provisório, sem marca definida.  
**Documento técnico:** [Spec.md](Spec.md).

## 1. Resumo do produto

Plataforma para alunos do 4º e 5º ano do ensino fundamental estudarem o conteúdo da escola com mais autonomia. A criança envia uma página da apostila, acompanha uma demonstração, interage com representações do conteúdo, registra seu raciocínio no caderno e recebe comentário contextual sobre uma foto do trabalho.

O tutor conversa naturalmente enquanto a explicação acontece na tela. Ele identifica evidências da tentativa, oferece apoio proporcional e convida a criança a explicar, perguntar e conferir. A experiência combina celular/tablet, objetos manipuláveis, escrita no papel e aplicação em uma questão nova.

O MVP entrega essa jornada completa em divisão por partilha. Cobertura curricular pequena permite construir uma experiência próxima do produto final e verificar a qualidade de cada etapa.

## 2. Problema e público

A hipótese inicial é que crianças com dificuldade de compreender as aulas ou manter a atenção diante do material escolar dependem dos pais para explicar conteúdos e conduzir a lição. O relato do proponente orienta o problema; frequência, causas e magnitude ainda precisam de pesquisa.

| Pessoa | Necessidade | Papel no MVP |
|---|---|---|
| Aluno do 4º/5º ano | Compreender a tarefa, saber começar, perguntar e verificar o próprio trabalho | Usuário principal |
| Responsável | Reduzir intervenções constantes e entender onde o aluno precisa de apoio | Viabiliza acesso; consulta resumo da sessão |
| Educador | Garantir fidelidade ao conceito, método e critério de avaliação | Revisa conteúdo e rubrica |

Contexto de uso: casa, celular possivelmente compartilhado, tablet, conexão variável, interrupções e caderno físico. Não inferir diagnóstico clínico, dificuldade permanente ou falta de atenção a partir de silêncio, rapidez ou voz.

## 3. Objetivos e evidência de sucesso

1. Ajudar o aluno a compreender a tarefa e iniciar uma estratégia.
2. Permitir alternar tela e caderno, retomando sem perder contexto.
3. Apoiar revisão de um erro com evidência identificável, preservando a iniciativa da criança.
4. Verificar aplicação em uma questão nova, distinguindo ajuda recebida de desempenho sem ajuda específica.
5. Ensinar práticas de estudo: perguntar, representar, conferir, explicar e revisar.

Redução da intervenção dos pais e retenção em outro dia são hipóteses de impacto. Conclusão de tarefa, tempo de tela ou acerto após uma pista não comprovam essas hipóteses.

## 4. Princípios de experiência

- Demonstrar primeiro com um exemplo semelhante; depois devolver o controle à criança.
- Fazer o conteúdo responder às ações e perguntas, com uma ação cognitiva principal por vez.
- Usar ritmo breve, movimento e participação inspirados na familiaridade com vídeos verticais; a sessão tem finalidade e encerramento, sem feed infinito como requisito.
- Manter a explicação ligada à tarefa e ao método revisado. Não impor narrativa de fantasia à matemática ou ao português.
- Conectar representação concreta, esquema, expressão numérica e registro no papel.
- Adaptar pela tentativa observada e pelo pedido da criança, sem classificá-la em estilos fixos de aprendizagem.
- Reconhecer incerteza da leitura; permitir que a criança corrija o tutor.
- Oferecer ajuda e demonstração direta quando necessário. Não prolongar perguntas frustrantes para evitar revelar qualquer resposta.
- Registrar assistência e procedência da evidência; não confundir cópia guiada com aplicação independente.

## 5. Escopo do MVP

### P0 — Jornada completa de divisão

Capturar/importar página → confirmar exercício → demonstração análoga → tentativa manipulável → esquema/caderno → foto do trabalho → comentário fundamentado → correção e reenvio quando necessários → explicação → questão nova → resumo.

Inclui voz e texto, cena 3D e alternativa 2D, pausa, interrupção, retomada, tratamento de foto ambígua, contestação da leitura, registro de apoio e isolamento de acesso. O retorno ao papel pode acontecer antes de concluir a montagem digital.

### Conteúdo de referência

| Etapa | Atividade | Finalidade |
|---|---|---|
| Demonstração | 12 peças em 4 recipientes | Mostrar distribuição igual e uso de todas as peças |
| Questão principal | 24 peças em 4 recipientes | Tentar, representar, conferir e corrigir |
| Questão nova | 20 peças em 5 recipientes | Verificar aplicação com menos apoio |

Esses valores são defaults de desenvolvimento. A [atividade própria](hackbrasil-discovery/fixtures/atividade-divisao.md) permite começar sem uma apostila comercial. Uma página real de escola exige revisão de fonte/método; o sistema não promete reconhecer e ensinar qualquer conteúdo enviado.

O módulo aceita apenas tarefas versionadas autorizadas de divisão exata por partilha. O limite técnico inicial é até 30 objetos e 2–6 grupos; a interface pública v1 oferece o pacote de referência acima.

### P1 — Após a jornada principal

- Flashcards derivados de dificuldades observadas.
- Revisão em outro dia, com nova evidência de retenção.

### P2 e fora do primeiro corte

Outras disciplinas, ingestão irrestrita de apostilas, geração de vídeos completos durante a aula, avatar de vídeo, editor de conteúdo, painel escolar amplo e marketplace. Divisão com resto, divisor desconhecido e algoritmo longo/reagrupamento não fazem parte do módulo v1.

## 6. Histórias de usuário

- Como aluno, quero mostrar o exercício para receber ajuda no conteúdo certo.
- Como aluno, quero ver uma demonstração antes de tentar e poder interromper para perguntar.
- Como aluno, quero manipular objetos e conferir minha ideia sem receber a solução automaticamente.
- Como aluno, quero registrar no caderno, mostrar o trabalho e entender o que preciso revisar.
- Como aluno, quero avisar quando o tutor leu algo diferente do que escrevi.
- Como aluno, quero pausar e retomar sem repetir toda a aula.
- Como aluno, quero participar por texto/toque quando não puder usar voz.
- Como responsável, quero distinguir o que a criança realizou com apoio do que demonstrou numa questão nova.

## 7. Jornada de referência

1. **Confirmar a tarefa:** a criança fotografa a página; o tutor confirma enunciado, quantidade e grupos. Imagem ambígua pede esclarecimento; tema fora da cobertura é explicitado.
2. **Ver uma demonstração:** o tutor distribui 12 peças entre quatro recipientes. Fala e visual permanecem sincronizados; a criança pode perguntar e ajustar o ritmo.
3. **Tentar:** a criança distribui 24 peças. O botão Conferir avalia a tentativa; gestos isolados não são tratados como erros.
4. **Receber apoio:** comparar grupos desiguais, conferir uso do total ou demonstrar um passo conforme evidência/pedido. Toda ajuda relevante é registrada.
5. **Ir ao caderno:** a montagem pode virar esquema superior; a criança escreve. O tutor fica silencioso e preserva a etapa. Também é permitido tentar no papel com a cena ainda incompleta.
6. **Mostrar o trabalho:** foto do caderno gera leitura e comentário. O tutor distingue o que observou, o que verificou matematicamente e o que é hipótese sobre a dificuldade.
7. **Revisar:** se necessário, reconstruir a tentativa na cena, permitir ação da criança e retornar ao papel. Reenvio exige análise nova.
8. **Explicar e aplicar:** aceitar fala, texto ou desenho como evidência. A questão 20 ÷ 5 começa sem resposta ou cena resolvida; ajuda continua disponível e é registrada.
9. **Encerrar:** apresentar resultado factual, apoio utilizado e pendência. Permitir encerrar parcialmente, sem exigir acerto.

### Caso central de correção

Uma foto fictícia mostra quatro grupos de cinco e a conta 24 ÷ 4 = 5. A leitura identifica 20 objetos representados; a matemática verifica a diferença para os 24 pedidos. A intervenção começa por conferir se todas as peças foram usadas.

Se a criança pedir a representação, aparecem quatro grupos de cinco e quatro peças adicionais identificadas como ainda não representadas no desenho. Essas quatro são derivadas do enunciado, não observadas na foto e não constituem resto matemático. A criança testa uma distribuição; o tutor não coloca automaticamente seis em cada recipiente. A correção do caderno só é confirmada após nova evidência.

## 8. Requisitos do produto

IDs preservados para rastrear decisões do discovery e os critérios AC-01 a AC-48 da Spec. Prioridades desta tabela valem para o módulo de divisão v1; requisitos de outras disciplinas permanecem no histórico.

| ID | Prioridade | Comportamento e critério |
|---|---|---|
| R01 | P0 | Capturar/importar página. Dada imagem ilegível, solicitar nova captura ou confirmação do símbolo; nenhuma avaliação ocorre a partir de texto inventado. |
| R02 | P0 | Confirmar trecho/objetivo. Cada missão deve referenciar fonte, página/região e conceito; conteúdo fora da cobertura é explicitado. |
| R03 | P0 | Sondar e adaptar. Duas respostas conceitualmente distintas acionam percursos distintos definidos; resposta ambígua pede esclarecimento. |
| R04 | P0 | Área visual participativa adequada à matéria. Oferecer uma ação de previsão/manipulação/explicação, controles de pausa/replay e retorno à tarefa; assistir não marca domínio. |
| R05 | P0 | Tutor contextual. Ao abrir dúvida, conservar exercício e etapa; após resposta, retornar ao estado anterior. Texto/toque disponíveis se áudio falhar. |
| R06 | P0 | Apoio progressivo. Registrar cada pista; uma resposta com ajuda não é marcada como independente. Explicar diretamente quando faltar base. |
| R07 | P0 | Modo caderno. Pausar estímulos e persistir etapa; ausência de fala não encerra a tarefa. Ao voltar, recuperar missão e pendência. |
| R08 | P0 | Verificação de aprendizagem. Nova questão inicia sem pistas; rubricar o conceito, registrar ajuda e apresentar resultado provisório. |
| R09 | P0 | Retorno compreensível. Mostrar o que foi demonstrado e o que falta revisar; distinguir evidência ausente de erro. |
| R10 | P0 | Encerramento e resumo. Missão tem final explícito; responsável vê conteúdo, ajuda e dúvida pendente. |
| R11 | P1 | Flashcard criado a partir de dificuldade real. Registrar resposta antes de revelar o verso; persistir próxima revisão. |
| R12 | P0 | Explicação pelo aluno. Aceitar voz/texto/desenho ou manipulação; avaliar correção conceitual, sem premiar aparência ou fluência como domínio. Personagem ou história não é obrigatório. |
| R13 | P0 | Cena 3D explicativa de divisão, com alternativa 2D e controles por toque quando arraste/renderização falharem; conservar quantidades e identidades dos objetos. |
| R14 | P0 | Receber foto do caderno, identificar o exercício e comentar o desenho/cálculo em relação à atividade. Confirmar conteúdo duvidoso, solicitar recorte/nova foto quando necessário e permitir explicação complementar; upload não é prova de resolução. |
| R15 | P2 | Produção de vídeos personalizados sob demanda. Só após validar latência, custo, fidelidade e política de conteúdo. |
| R16 | P0 | A conversa pode solicitar alterações da cena pelo catálogo de ações e parâmetros autorizados. O tutor recebe confirmação do estado visual real; ambiguidade exige esclarecimento antes da alteração. |
| R17 | P0 | Estados pensando/escrevendo/pausado suspendem avisos de ausência de fala; retomada recupera a etapa e a pendência. |
| R19 | P0 | Distinguir produção da criança de conteúdo fornecido pelo tutor; não pontuar reprodução de resposta demonstrada como explicação independente. |
| R20 | P0 | Quem demonstra compreensão pode avançar à aplicação; não exigir consumo completo de mídia para encerrar a missão. |
| R21 | P0 | Sincronizar fala, indicação visual e estado real da atividade. Ao apontar um grupo/palavra/etapa, o tutor deve referenciar o elemento exibido correto. |
| R22 | P0 | Transformar representação em esquema legível para o caderno; manter relações e quantidades. Distinguir cópia guiada de reconstrução sem referência. |
| R24 | P0 | Separar demonstração e avaliação. Destaques, setas e resultados que ensinam ficam ocultos antes da tentativa independente, reaparecendo como ajuda registrada quando solicitado. |
| R27 | P0 | Oferecer outra representação/estratégia quando necessário; explicitar a ligação entre elas e permitir abreviar o percurso quando houver compreensão. |
| R28 | P0 | Demonstrar primeiro com exemplo análogo claramente identificado; depois devolver o controle na questão do aluno. Distinguir números e resultado da demonstração daqueles da apostila. |
| R29 | P0 | Adaptar ajuda a evidências: grupos desiguais, peças restantes, confusão sobre divisor, dificuldade de contagem ou problema de interação. Não classificar movimento incompleto, lentidão ou falha de arraste como erro conceitual automaticamente. |
| R30 | P0 | Interrupção da conversa preserva um estado visual consistente; fala, contagens e retomada usam a última ação confirmada. |
| R31 | P0 | Registrar a origem da evidência do caderno: autorrelato, resposta estruturada ou foto analisada. Não alegar ter visto/corrigido um desenho sem recebê-lo e interpretá-lo. |
| R32 | P0 | Distinguir nível e tipo de suporte: demonstração, pistas, objetos virtuais, modelo disponível e papel sem modelo. Nova tentativa inicia sem resposta/cena resolvida; ajuda solicitada continua disponível e é registrada. |
| R33 | P0 | Ancorar o comentário numa evidência identificável da foto: grupo, quantidade, símbolo ou relação com o cálculo. Distinguir observação de hipótese; não inventar contagem nem penalizar estética/caligrafia. |
| R34 | P0 | Permitir corrigir no papel e reenviar, relacionando as versões à mesma tentativa. Comparar apenas elementos legíveis e registrar a ajuda oferecida; não declarar correção verificada quando a imagem permanece inconclusiva. |
| R35 | P0 | Reconstruir fielmente a tentativa observada antes de ajudar a corrigi-la. Distinguir objetos extraídos da foto de quantidades derivadas do enunciado; nunca corrigir silenciosamente a cena ou chamar peças ainda não distribuídas de resto matemático. |
| R36 | P0 | Separar observação, verificação matemática e hipótese de dificuldade. Validar contagens/símbolos ambíguos antes de orientar; uma diferença no papel pode ser de registro, contagem ou conceito e não define perfil permanente. |

## 9. Medição e critérios de sucesso

| Dimensão | Medida | Interpretação |
|---|---|---|
| Ativação | Concluir captura/confirmação e chegar à primeira atividade | Navegação e entendimento do começo |
| Continuidade | Retomar do caderno sem assistência de navegação | Qualidade da passagem digital/papel |
| Compreensão | Resposta e explicação na questão nova | Evidência por item, com rubrica e ajuda registrada |
| Apoio | Pistas, passos demonstrados e recursos usados | Não equiparar todos os acertos |
| Qualidade de visão | Extração, abstenção, falsa certeza e adequação do comentário | Capacidade técnica no recorte avaliado |
| Autonomia | Intervenções de adultos declaradas e observação de uso | Não inferir ajuda parental secretamente |
| Operação | Latência, falhas, desempenho e custo por sessão | Viabilidade da experiência |

Hipótese para primeiro teste exploratório: pelo menos quatro de cinco participantes chegam à atividade e retomam do caderno sem ajuda de navegação. Não é resultado obtido nem validação estatística. Metas educacionais de ganho/retenção dependem de baseline e pesquisa.

A Spec define 48 critérios P0 e o conjunto inicial de avaliação de visão: 50 fotos próprias/autorizadas, com parte reservada. Metas técnicas iniciais: prévia de interação até 100 ms, cena pelo menos 30 fps no aparelho-alvo, P95 de voz até 3 s e de análise até 10 s após upload. São metas de engenharia a medir.

## 10. Qualidade, confiança e acesso

A identidade de tutor de IA deve ser clara. Nenhuma inferência sobre capacidade da criança se baseia em timbre, velocidade, silêncio, estética do desenho ou consumo de mídia. Leitura incerta gera pedido de esclarecimento; a criança pode contestar.

A experiência oferece texto/toque, legendas, alternativa 2D, movimento reduzido e controles confortáveis. Captura e retorno da câmera não podem apagar a sessão. Uma falha técnica não vira erro de aprendizagem.

Fotos e evidências têm acesso restrito. Não gravar áudio bruto por padrão nem encaminhar conteúdo pessoal a analytics. A demo usa perfis fictícios e material próprio/autorizado. Piloto com crianças reais exige fluxo do responsável, política de retenção e revisão apropriada antes de habilitação.

## 11. Arquitetura e dependências

Direção aprovada: React/TypeScript para aplicação web responsiva/PWA; React Three Fiber/Three.js e SVG para representações; Python/FastAPI para núcleo e API; LiveKit Agents para voz; Supabase para autenticação, Postgres, Storage e fila persistente de análise.

O núcleo guarda a verdade sobre estado, números, ajuda e evidências. O tutor solicita ações tipadas, o servidor valida e a cena confirma a execução. Voz e visão podem usar modelos diferentes, escolhidos por avaliação; não há modelo vencedor ou custo comprovado definido nesta documentação.

A ferramenta de roleplay existente foi inspecionada estaticamente; reutilização técnica e elegibilidade no evento não foram confirmadas. O MVP não deve depender de copiar código privado anterior ou seus assets. Manter adapters que permitam integração futura autorizada.

## 12. Pendências e responsáveis

| Pendência | Responsável | Momento necessário |
|---|---|---|
| Seleção de modelos/credenciais e orçamento | Engenharia/proponente | Integração e homologação reais |
| Revisão pedagógica do conteúdo e rubrica | Educador/produto | Antes de piloto educacional |
| Apostila comercial e método escolar | Produto/educador | Antes de prometer aderência àquela apostila |
| Aparelhos-alvo e condições de teste | Produto/engenharia | Homologação mobile/desempenho |
| Política de acesso e retenção para crianças reais | Produto e revisão apropriada | Antes do piloto real |
| Elegibilidade do roleplay anterior | Proponente | Antes de adotar código ou serviço existente |
| Marca, identidade visual e tom refinado | Produto/design | Durante desenvolvimento, sem bloquear domínio |

## 13. Entrega e evolução

Entrega P0: uma jornada completa demonstrável, com captura, voz/cena, papel, foto realmente analisada, correção, questão nova e retomada. Stubs são permitidos no desenvolvimento, mas não comprovam a capacidade anunciada na demo. Os critérios de aceite devem ser executados e seus resultados registrados antes de declarar o MVP pronto.

Depois, ampliar atividades de divisão e validar uso doméstico; adicionar revisão/flashcards; então introduzir módulos próprios de português, ciências, história e geografia. Cada disciplina exige representações e rubricas específicas. Vídeo, motion e 3D são escolhidos pelo que ajudam a compreender.

A hipótese comercial inicial é acesso viabilizado pela família, com professor como participante da validação. Preço, aquisição, contratos escolares e modelo de receita ainda não foram validados.

## 14. Governança dos documentos

Este PRD e [Spec.md](Spec.md) são os documentos consolidados de entrada para desenvolvimento. O PRD define produto e escopo; a Spec detalha comportamento, estados, contratos e aceite. Uma nova decisão explícita do usuário prevalece; atualizar os dois documentos quando alterar escopo ou comportamento.

Os arquivos em [hackbrasil-discovery](hackbrasil-discovery/PROGRESSO.md) preservam pesquisa e decisões anteriores. Não promover alternativas históricas a requisitos. Materiais do painel Hack Brasil são mantidos separadamente; gerar estes arquivos não publica nem submete o projeto.
