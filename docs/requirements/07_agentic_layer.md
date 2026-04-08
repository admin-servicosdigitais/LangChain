# Módulo de Camada Agêntica (IA-First)

## Contexto de Negócio

O produto base (coleta de odds → cálculo de EV → alertas) é funcionalmente equivalente aos concorrentes atuais: OddsJam ($99/mês), RebelBetting ($150/mês), BetBurger ($30-90/mês). Todos entregam `EV = +X%` em tempo real.

A diferenciação não está nos dados — está na **inteligência sobre os dados**. A camada agêntica transforma o produto de "calculadora de EV" para "analista de mercado autônomo" que:
1. Explica por que o valor existe (não apenas que existe)
2. Diagnóstica a performance do usuário e recomenda ajustes
3. Descobre ineficiências que nenhum concorrente sistematiza
4. Opera e se corrige autonomamente

**O moat real não são os agentes — são os dados proprietários que cada agente acumula ao longo do tempo.** Classificações de movimentação, perfis de performance por usuário, mapa de ineficiências por liga/bookmaker. Esse dataset não se replica com dinheiro — exige tempo de operação.

---

## Princípios de Design

1. **Agentes classificam padrões de mercado — não predizem resultados esportivos.** Distinção jurídica relevante.
2. **Toda ação autônoma é registrada no audit log.** Rastreabilidade idêntica a ações humanas.
3. **Bounds de autonomia configuráveis por Admin.** Nenhum agente tem permissão ilimitada.
4. **Falha de agente não bloqueia pipeline principal.** Timeouts com fallback para comportamento sem agente.
5. **Custo de LLM é monitorado por agente.** Custo marginal de IA visível e controlável.

---

## Catálogo de Agentes

### AGT-A: Data Quality Sentinel

**Função:** Substituir regras binárias estáticas de qualidade de dados por scoring adaptativo baseado em histórico de comportamento de cada bookmaker por liga.

**Problema resolvido:**
- Regra atual `margin > 8% → descarta` é cega ao contexto: bookmakers regionais SEMPRE têm margin > 8% — é o modelo deles. A regra descarta 100% das odds deles, mesmo quando são os únicos cobrindo ligas de nicho.
- Regra atual `< 10% cobertura = unreliable` descarta bookmakers que são sistematicamente lentos em ligas específicas — exatamente onde há valor.

**Comportamento:**
1. Para cada snapshot recebido, consulta histórico de `(bookmaker_id, league_id)` dos últimos 30 dias
2. Calcula `quality_score` (0.0–1.0) baseado em: variância histórica de margin, frequência de updates, correlação com linha Pinnacle, padrão de outliers
3. Classifica o snapshot: `reliable` (>0.8), `acceptable` (0.6-0.8), `illiquid_but_valid` (0.6-0.75 em ligas sem Pinnacle), `suspicious` (0.3-0.6), `discard` (<0.3)
4. Armazena `quality_score` + classificação no snapshot para uso pelo M02

**Dados usados:**
- Série histórica de snapshots por `(bookmaker_id, league_id)` (DynamoDB + S3 Parquet)
- Padrão de margin histórico por bookmaker
- Correlação histórica de odds do bookmaker com fechamento de mercado

**Moat:** Calibração por bookmaker/liga acumula precisão ao longo do tempo. Concorrente que copiar a feature começa do zero.

**Tier:** Pro e Elite (Free usa regras estáticas — reduz custo computacional e diferencia tiers)

**MVP:** V2 (requer 3 meses de histórico de snapshots para calibração inicial)

**Critérios de aceite:**
- `quality_score` calculado em < 100ms por snapshot
- Modelo retreinado semanalmente com novos dados
- Se histórico insuficiente para um par (bookmaker, liga): fallback para regras binárias atuais com flag `scoring_method: rule_based`
- Taxa de falsos positivos (descarte de oportunidades válidas) monitorada semanalmente no painel admin

---

### AGT-B: Odds Movement Classifier

**Função:** Classificar a causa da movimentação de odds antes de enviar o alerta — transformar `EV = +4.3%` em `EV +4.3% — sharp money detectado há 6min, janela estimada de 10-15min`.

**Problema resolvido:**
- O produto atual entrega número sem contexto. Apostador profissional precisa saber SE vale agir agora.
- A regra atual `Pinnacle movendo > 5% → não alertar` descarta sem classificar — tanto descarta oportunidades válidas (Pinnacle corrigindo erro de linha) quanto deixa passar situações de sharp money onde a janela já fechou.

**Comportamento:**
1. Consume evento `OddsMovementDetected` do M01 (RF-COL-C)
2. Analisa série temporal de snapshots: quem moveu primeiro (Pinnacle ou soft book?), correlação com volume do Exchange, timestamp de notícias recentes (via API-Football)
3. Classifica em 5 categorias com probabilidade:
   - `sharp_money`: movimento iniciou em Pinnacle/Exchange, propagou para soft books
   - `bookmaker_error`: linha aberrante em 1-2 books sem propagação, provável erro de linha
   - `news_event`: movimento correlacionado com notícia/escalação (timestamp próximo)
   - `liquidity_correction`: book ajustando após volume de apostas recebido
   - `market_open_inefficiency`: livro abriu com linha defasada (comum 00h-06h UTC)
4. Para EV > 25%: classificação é pré-requisito para envio (RF-EV-B do M02)
5. Adiciona ao alerta: causa + confidence score + janela temporal estimada (baseada em padrão histórico de quanto tempo cada tipo persiste)

**Dados usados:**
- Série dos últimos 5 snapshots do mercado (M01)
- Volume do Betfair Exchange via `exchange_volume` do snapshot (RF-COL-B)
- API-Football para correlação temporal com notícias
- Histórico de "classificação × tempo de fechamento do EV" para estimar janela
- LLM para correlação de notícias (latência < 2s, contexto curto)

**Moat:** O dataset de `(causa_classificada, tempo_de_fechamento_observado)` por liga/bookmaker só existe se você coletar e classificar sistematicamente. Concorrentes sem histórico não podem replicar a estimativa de janela temporal.

**Tier MVP:** Pro (3 categorias: sharp_money, bookmaker_error, market_open) / Elite (5 categorias + janela temporal estimada + Exchange volume)

**MVP:** Versão reduzida (3 categorias, sem janela temporal) no lançamento. Versão completa em V2.

**Critérios de aceite:**
- Classificação produzida em < 5 segundos após recebimento do evento
- Timeout de 10s: se não classificado, alerta enviado com `classification_source: pending`
- Confidence score exibido no alerta apenas se > 0.70 (abaixo disso, exibe categoria sem score)
- Acurácia de classificação monitorada no painel admin: % de `sharp_money` que resultaram em fechamento de EV na direção esperada

---

### AGT-C: Adaptive Bankroll Manager

**Função:** Kelly Criterion dinâmico que se adapta ao histórico real de performance do usuário, em vez de usar fração fixa (1/4 Kelly).

**Problema resolvido:**
- Kelly 1/4 fixo é conservador quando o usuário está em sequência positiva e perigoso quando está em drawdown severo.
- O produto atual não sabe que o usuário perdeu 20% do bankroll — continua recomendando 1/4 Kelly como se nada tivesse acontecido.

**Comportamento:**
1. Monitora histórico de apostas registradas via Bet Tracking (RF-USR-B do M04)
2. Calcula métricas semanais: drawdown atual vs. máximo histórico, edge realizado vs. esperado por liga, volatilidade de resultados por mercado
3. Ajusta `kelly_multiplier` dentro dos bounds configurados pelo usuário:
   - Drawdown > 15% → reduz para limite mínimo configurado (ex: 1/8 Kelly)
   - Edge realizado consistentemente > esperado por 30+ apostas → permite escalar até limite máximo
   - Alta volatilidade em mercado específico → reduz multiplier para aquele mercado
4. Retorna `{ kelly_fraction, justification_text, current_multiplier, adjustment_reason }` para o M02

**Dados usados:**
- Histórico de apostas + resultados via Bet Tracking (RF-USR-B)
- CLV por aposta (M05 — indica se edge foi real ou variância)
- Bounds configurados pelo usuário em `agent_preferences` (RF-USR-D)

**Trade-off crítico:** Requer que o usuário registre apostas. Se o usuário não registrar, o agente degrada para Kelly 1/4 fixo sem dados. Isso cria tensão entre fricção de onboarding e qualidade do agente. O webhook de importação (RF-USR-C) é a mitigação principal.

**Moat:** O modelo é personalizado por usuário — cada instância aprende o perfil de risco específico. Dado que cresce com o tempo de uso e não se transfere para concorrentes.

**Tier:** Elite exclusivo.

**MVP:** V2 (requer histórico mínimo de 20 apostas registradas para significância).

**Critérios de aceite:**
- Multiplicador revisado semanalmente (não por aposta — evita over-fitting a ruído de curto prazo)
- Bounds do usuário são hard limits: agente nunca recomenda fração fora dos bounds configurados
- Relatório semanal enviado via Telegram: "Seu Kelly atual é X porque [razão em 1 frase]"
- Se < 20 apostas no histórico: fallback para 1/4 Kelly com nota informando quantas apostas faltam

---

### AGT-D: Market Inefficiency Hunter

**Função:** Identificar sistematicamente ineficiências persistentes em ligas de menor visibilidade, onde bookmakers têm menos expertise e frequentemente defasam a linha.

**Problema resolvido:**
- O produto atual trata todas as ligas igualmente. Ligas de segunda divisão têm ineficiências estruturais (bookmakers defasando linhas em 15-30 minutos) que ninguém sistematiza.
- Apostadores profissionais descobrem essas ineficiências por tentativa e erro. Um produto que as documenta e entrega tem diferenciação real.

**Comportamento:**
1. Roda em background a cada 6 horas (não em tempo real — análise batch)
2. Para cada par `(league_id, bookmaker_id)` com ≥ 30 dias de histórico:
   - Calcula EV médio histórico de oportunidades detectadas
   - Calcula frequência semanal de oportunidades
   - Testa se o padrão é estatisticamente significativo (p-value < 0.05)
   - Identifica correlações: horário do dia, dia da semana, proximidade ao kickoff
3. Documenta ineficiências confirmadas em `market_inefficiencies` com métricas completas
4. Gera Hunt Report semanal para usuários Elite com novas ineficiências encontradas
5. Retroalimenta M01: sugere aumento de polling para pares com ineficiências ativas

**Dados usados:**
- Histórico completo de snapshots (S3 Parquet via Athena — RF-BCK-008 do M05)
- Calendário de jogos por liga (API-Football)
- Resultados reais para validar se as "ineficiências" geraram EV real ou foram miragem
- LLM para redigir Hunt Reports em linguagem natural

**Moat:** Base de conhecimento de ineficiências por liga/bookmaker é proprietária e cresce com o tempo. Requer 6+ meses de dados históricos para detectar padrões com significância — janela de vantagem de 12-18 meses sobre concorrente que iniciar agora.

**Tier:** Elite exclusivo.

**MVP:** V3 (requer 6 meses de histórico em ligas de cauda).

**Critérios de aceite:**
- Ineficiência documentada somente se p-value < 0.05 e N ≥ 50 observações
- Hunt Report enviado toda segunda-feira às 09h UTC via Telegram + disponível na interface (RF-BCK-B)
- Ineficiências "expiradas" (padrão não observado por 30 dias) marcadas como `expired` e não entregues em novos reports
- Admin pode revisar e invalidar ineficiências detectadas (caso de erro estatístico)

---

### AGT-E: Onboarding Coach

**Função:** Acompanhar os primeiros 7 dias do usuário (trial) com explicações contextuais em linguagem natural, usando o próprio alerta do usuário como exemplo de ensino.

**Problema resolvido:**
- O funil quebra porque EV é contraintuitivo. A maioria dos usuários abandona o trial sem entender por que o produto é valioso — não porque o produto é ruim, mas porque o onboarding é self-service.
- Concorrentes são 100% self-service. Nenhum guia o usuário pelos primeiros alertas.

**Comportamento:**
- **Dia 1 (após primeiro alerta):** explica EV especificamente com os valores do alerta recebido: "Este alerta diz EV +3.2%. Isso significa que, apostando R$100, você esperaria ganhar R$3.20 em média neste tipo de aposta. O valor surgiu porque Pinnacle tem odds 1.87 e [Casa X] tem 1.95."
- **Dia 2-3:** monitora engajamento (abriu o alerta? clicou?), ajusta profundidade. Se alto engajamento: aprofunda em CLV. Se baixo: simplifica e faz pergunta aberta.
- **Dia 4-5:** introduz conceito de CLV e como avaliar qualidade de decisão independente do resultado.
- **Dia 6:** apresenta backtesting simulado com os alertas recebidos durante o trial.
- **Dia 7 (D-24h do fim do trial):** "Seu Relatório da Semana" — alertas recebidos, resultado simulado, o que Pro desbloquearia. CTA explícito.
- **Interação bidirecional:** usuário pode responder `/duvida <texto>` e o agente responde em contexto.

**Dados usados:**
- Alertas gerados para o usuário durante o trial
- Histórico de interações Telegram (cliques, respostas, comandos)
- LLM (GPT-4o ou Claude) para explicações contextuais — não scripts fixos
- Sequência configurável sem deploy (parâmetro em M06)

**Custo de LLM:** ~$0.05-0.15 por trial completo (3-4 chamadas de contexto curto). Com LTV de conversão Pro = $29 × 12 = $348, é aceitável mesmo com taxa de conversão de 10%.

**Moat:** Qualidade das explicações melhora com dados de interação: quais explicações geraram conversão vs. abandono. Modelo de onboarding personalizado em escala é difícil de replicar com scripts estáticos.

**Tier:** Free (crítico para conversão) / Pro (versão aprofundada no primeiro mês).

**MVP:** Lançamento (é o agente com maior impacto direto na conversão Free→Pro).

**Critérios de aceite:**
- Primeira mensagem enviada em até 5 minutos após primeiro alerta do usuário
- Usuário pode digitar `/skip_coach` para desativar a qualquer momento (sem fricção)
- Métricas de conversão: usuários que completaram o coach vs. que pularam — diferença de conversão Free→Pro monitorada no painel admin
- Custo LLM por trial registrado no painel admin (RF-ADM-D)
- Conteúdo gerado pelo agente não pode afirmar que apostas são lucrativas garantidamente — disclaimer automático

---

### AGT-F: Performance Diagnostician

**Função:** Ler o histórico de apostas do usuário Elite e gerar diagnóstico narrativo: o que está funcionando, o que não está, e recomendações específicas — não apenas dados brutos.

**Problema resolvido:**
- Backtesting atual (M05) mostra `win rate: 54%, ROI: +3.2%` — dado, não diagnóstico.
- Usuário Elite paga $79/mês para interpretar seus próprios dados. O produto não agrega inteligência sobre o histórico.
- Concorrentes não fazem isso. Todos param no dado bruto.

**Comportamento:**
1. Roda semanalmente para usuários Elite com ≥ 20 apostas no histórico
2. Analisa performance segmentada por: tipo de mercado, liga, faixa de odds, dia da semana, EV threshold
3. Identifica padrões de sobre/sub-performance com significância estatística (bootstrapping)
4. Diferencia variância de edge genuíno: 5 apostas perdidas em sequência é variância; CLV negativo persistente por 30 apostas é padrão
5. Gera diagnóstico em linguagem natural: "Seu CLV médio em Over/Under é +2.1% (positivo e consistente). Em 1X2 é -0.8% há 6 semanas. Você continua apostando 1X2 com frequência 40% maior. Isso sugere viés de seleção — você prefere 1X2 mas seu edge não está lá."
6. Propõe ajuste de filtro específico para o usuário (RF-ALT-B do M03): "Desativar alertas 1X2 por 2 semanas e reavaliar"

**Dados usados:**
- Histórico completo de apostas + CLV + resultado (M05 + Bet Tracking de M04)
- Métricas agregadas por dimensão (M05 RF-BCK-006)
- Bootstrapping para separar sinal de ruído
- LLM para redigir diagnóstico narrativo baseado nas métricas calculadas

**Moat:** Diagnóstico personalizado se aprofunda com o tempo — após 6 meses, o contexto longitudinal é insubstituível. Cria lock-in intelectual: migrar para concorrente significa perder o histórico de diagnósticos e começar do zero.

**Tier:** Elite exclusivo.

**MVP:** V2 (requer 20+ apostas registradas + M05 funcional).

**Critérios de aceite:**
- Diagnóstico gerado máximo 1x por semana (não a cada aposta)
- Mínimo de 20 apostas: abaixo disso, agente informa "X apostas registradas. Diagnóstico disponível a partir de 20." 
- Disclaimer obrigatório em todo diagnóstico: "Análise baseada em dados passados. Apostas envolvem risco financeiro."
- Histórico de diagnósticos preservado: usuário pode ver evolução das recomendações ao longo do tempo

---

### AGT-G: AIOps Remediator

**Função:** Substituir o ciclo manual `alerta → admin lê → admin decide → admin age` por diagnóstico e remediação autônoma de incidentes operacionais — escalando para humano apenas quando necessário.

**Problema resolvido:**
- MTTF de incidentes em madrugadas ou fins de semana pode ser 30-60 minutos com intervenção humana.
- Degradação gradual (latência subindo 15% ao dia) não gera alerta no modelo reativo atual — só quebra no threshold crítico.

**Comportamento:**
1. Monitora continuamente métricas do sistema via CloudWatch
2. Detecta degradação gradual antes da quebra: tendência de latência, aumento de taxa de erro, quota consumindo mais rápido que o esperado
3. Classifica incidentes em 3 níveis:
   - `auto_remediate`: executa playbook sem aprovação (ex: bookmaker X retornando 503 → ativa fallback layer 2)
   - `recommend_and_escalate`: diagnostica causa, propõe ação, aguarda aprovação admin via Telegram/painel (timeout 30min → escalona como crítico)
   - `escalate_immediately`: incidente sem playbook conhecido → escalona com diagnóstico completo
4. Executa apenas playbooks dentro dos bounds configurados no RF-ADM-C
5. Registra toda ação no audit log (RF-ADM-B)

**Playbooks MVP (auto_remediate sem aprovação):**
- PLB-001: Fonte primária de odds com 3 falhas consecutivas → ativa fallback layer 2 (Betfair como referência)
- PLB-002: Rate limit HTTP 429 → ativa backoff exponencial e reduz polling rate temporariamente
- PLB-003: Fila SQS > 500 mensagens → aumenta concorrência de Lambda de entrega
- PLB-004: Bookmaker com 100% de falhas por 15min → marca como `temporarily_excluded`
- PLB-005: Lambda de EV timeout repetido → reinicia com configuração de memória aumentada

**Dados usados:**
- Métricas AWS CloudWatch (Lambda, DynamoDB, SQS)
- Histórico de incidentes anteriores (padrão de causa)
- Playbooks codificados como funções chamáveis com parâmetros
- LLM para diagnóstico de causa raiz (apenas para `recommend_and_escalate` — não para `auto_remediate`)

**Moat:** Operacional, não de produto. Mas reduz custo de operação e melhora SLA — permite escalar sem crescimento linear de equipe.

**Tier:** Interno (operacional).

**MVP:** Versão básica no lançamento (5 playbooks, modo `recommend_and_escalate` para todos — sem autonomia total no MVP para reduzir risco).

**Critérios de aceite:**
- Toda ação (automática ou aprovada) registrada no audit log com rastreabilidade completa
- Admin pode reverter qualquer ação executada pelo agente quando `rollback_available: true`
- Agente nunca altera configurações de negócio (EV thresholds, tier limits) de forma autônoma
- Alerta ao admin se agente tentou executar ação fora dos bounds configurados

---

### AGT-H: Sharp Action Tracker

**Função:** Detectar influxo antecipado de smart money via volume do Betfair Exchange — gerando sinal de pré-alerta antes que o EV apareça no pipeline principal.

**Problema resolvido:**
- Betfair Exchange é o melhor indicador disponível de sharp money em mercados europeus. O produto atual usa a Exchange apenas como fonte de odds — ignora completamente os dados de volume.
- Quando sharp money entra na Exchange, soft books demoram 5-15 minutos para ajustar. Esse é exatamente o intervalo de oportunidade.

**Comportamento:**
1. Monitora volume do Betfair Exchange por mercado (RF-COL-B do M01)
2. Compara volume atual com baseline do mesmo mercado em horários similares (últimas 4 semanas)
3. Quando volume Exchange > 3x o baseline em janela de 5 minutos SEM movimentação proporcional em soft books: publica evento `SharpActionDetected`
4. Alimenta o Agente B com evidência de `sharp_money` com alta confiança
5. Gera alerta premium Elite "Pré-Alerta": "Volume no Exchange 3.2x acima do normal em [mercado]. Alerta de EV provável em 2-5min."

**Dados usados:**
- `exchange_volume_usd` dos snapshots (RF-COL-B)
- Baseline histórico de volume por `(event_id, market_type, time_to_kickoff)` (série temporal)
- Correlação histórica entre spike de volume e movimentação subsequente de soft books

**Moat:** A correlação entre volume do Exchange e fechamento de EV é um sinal proprietário. Nenhum concorrente usa Exchange volume como feature — apenas Exchange odds. Dataset de `(spike_volume, movimentação_subsequente)` por liga é exclusivo.

**Tier:** Elite exclusivo (Pré-Alertas como feature premium diferencial).

**MVP:** V3 (requer baseline histórico de volume por mercado — mínimo 4 semanas por liga coberta).

**Critérios de aceite:**
- Spike detectado em < 60 segundos após coleta do snapshot com volume elevado
- Pré-Alerta enviado apenas quando confiança > 0.75 (baseline calibrado) para evitar ruído
- Pré-Alerta não conta para throttling diário do usuário (é sinal distinto, não alerta de EV)
- Acurácia monitorada: % de Pré-Alertas seguidos de alerta de EV em ≤ 15min

---

## Roadmap de Entrega

### MVP — Launch (0 semanas de delta além do produto base)
| Agente | Versão | Funcionalidade no MVP |
|--------|--------|-----------------------|
| AGT-E (Onboarding Coach) | Completa | Sequência 7 dias via Telegram, LLM contextual, `/skip_coach` |
| AGT-B (Movement Classifier) | Reduzida | 3 categorias (sharp_money, bookmaker_error, market_open), sem janela temporal |
| AGT-G (AIOps) | Básica | 5 playbooks, modo `recommend_and_escalate` para todos (sem auto_remediate no MVP) |

### V2 — 3 meses pós-launch (com dados históricos)
| Agente | Trigger de ativação |
|--------|---------------------|
| AGT-A (Data Quality) | 3 meses de snapshots por bookmaker/liga |
| AGT-F (Diagnostician) | Usuários Elite com 20+ apostas registradas |
| AGT-C (Bankroll) | AGT-F ativo + bet tracking implementado |
| AGT-B (completo) | Baseline histórico de tempo de fechamento por tipo de ineficiência |
| AGT-G autonomia | Admin habilita `auto_remediate` para playbooks 1-3 após 30 dias de validação |

### V3 — 6+ meses pós-launch
| Agente | Trigger de ativação |
|--------|---------------------|
| AGT-D (Inefficiency Hunter) | 6 meses de histórico em ligas de cauda com N ≥ 50 por liga |
| AGT-H (Sharp Action Tracker) | 4 semanas de baseline de volume Exchange por liga coberta |

---

## Posicionamento Competitivo

| Feature | OddsJam ($99) | RebelBetting ($150) | BetBurger ($30-90) | **Este produto** |
|---------|--------------|--------------------|--------------------|-----------------|
| EV calculado | Sim | Sim | Sim | Sim |
| Alertas em tempo real | Sim | Sim | Sim | Sim |
| Contexto de movimentação | Não | Não | Não | **AGT-B** |
| Diagnóstico de performance | Não | Não | Não | **AGT-F** |
| Bankroll adaptativo | Não | Não | Não | **AGT-C** |
| Ineficiências sistemáticas | Não | Não | Não | **AGT-D** |
| Onboarding guiado | Não | Não | Não | **AGT-E** |
| Pré-alerta de sharp money | Não | Não | Não | **AGT-H** |
| Preço Elite | $99+ | $150+ | $90 | **$79** |

**Posicionamento:** "O único produto de value betting que explica por que o valor existe e o que fazer com ele."

Janela de vantagem competitiva: 12-18 meses enquanto concorrentes desenvolvem features equivalentes. O objetivo durante essa janela é criar lock-in de dados personalizados (AGT-C, AGT-F) e conhecimento acumulado (AGT-D, AGT-H) — de forma que migrar para um concorrente "com agentes" implique perder meses de contexto proprietário.

---

## Restrições e Dependências da Camada Agêntica

| Dependência | Tipo | Impacto em falha |
|---|---|---|
| LLM API (OpenAI/Anthropic) | Externa | AGT-B, AGT-E, AGT-F, AGT-G degradam para versão sem narrativa |
| Bet Tracking (M04 RF-USR-B) | Interna | AGT-C e AGT-F sem dados — fallback para Kelly fixo e sem diagnóstico |
| Histórico de snapshots (S3 Parquet) | Interna | AGT-A, AGT-D, AGT-H sem baseline — fallback para regras estáticas |
| Exchange volume data (M01 RF-COL-B) | Interna | AGT-H inativo; AGT-B sem evidência de sharp money |
| SQS filas dedicadas de agentes | Infraestrutura | Agentes param de receber eventos; pipeline principal não é afetado |

**Custo estimado da camada agêntica (1.000 usuários Elite ativos, V2 completo):**
- LLM (AGT-B + AGT-E + AGT-F + AGT-G): ~$2.000-4.000/mês
- Compute adicional (Lambda para agentes): ~$200-400/mês
- **Total: ~$2.200-4.400/mês = 3-6% da receita Elite ($79 × 1.000 = $79.000/mês)**

Margem bruta permanece > 90% mesmo com camada agêntica completa.
