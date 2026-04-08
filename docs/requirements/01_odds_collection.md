# Módulo de Coleta de Odds

## Contexto de Negócio

A detecção de value bets depende inteiramente da atualização e confiabilidade dos dados de odds. Janelas de valor se abrem e fecham em minutos — frequentemente segundos após a Pinnacle mover sua linha. O módulo de coleta é a fundação do produto: latência aqui é latência no alerta final.

Trade-off central: polling mais frequente = mais quota consumida da API e maior custo; polling mais espaçado = menor atualização dos dados e janelas de valor perdidas. A calibração do intervalo de polling é decisão de negócio com impacto direto em custo e qualidade do produto.

---

## Atores

- **Sistema (job de coleta):** executor principal — AWS Lambda agendado via EventBridge
- **The Odds API:** fonte primária de odds de 40+ casas + Pinnacle
- **Betfair Exchange API:** fonte secundária de odds e dados de liquidez
- **API-Football:** fonte de dados contextuais de partidas
- **Admin:** configura ligas habilitadas, intervalos de polling, parâmetros de qualidade

---

## Requisitos Funcionais

### RF-COL-001 — Polling de Odds em Quase-Tempo-Real
**Descrição:** O sistema deve executar polling de odds a cada 30–60 segundos para eventos dentro de 24 horas de início, para todos os mercados habilitados.
**Prioridade:** Must
**Critério de aceite:**
- Lambda dispara a cada 30 segundos via EventBridge para eventos nas próximas 24h
- Lambda dispara a cada 5 minutos para eventos entre 24h e 72h de início
- Lambda dispara a cada 30 minutos para eventos com mais de 72h de início
- Log de execução registra timestamp de início, fim e número de mercados coletados
- Alerta interno disparado se execução exceder 25 segundos (risco de sobreposição)

### RF-COL-002 — Coleta da Linha Pinnacle como Referência
**Descrição:** Para cada mercado coletado, as odds da Pinnacle devem ser armazenadas separadamente como linha de referência, explicitamente identificadas.
**Prioridade:** Must
**Critério de aceite:**
- Todo snapshot de mercado contém campo `pinnacle_odds` e `pinnacle_margin` calculada
- Se Pinnacle não retornar odds para um mercado específico, o mercado é marcado como `no_sharp_reference` e excluído do cálculo de EV
- Nunca calcular EV sem linha Pinnacle presente — requisito inegociável

### RF-COL-003 — Cobertura de Esportes e Ligas
**Descrição:** O sistema deve cobrir futebol como esporte prioritário, com suporte expansível a outros esportes.
**Prioridade:** Must (futebol), Should (outros esportes)
**Critério de aceite:**
- Fase 1 (launch): futebol — Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League, Europa League, Copa do Brasil, Brasileirão Série A
- Fase 1: tênis — ATP/WTA Grand Slams e Masters 1000
- Fase 2 (Q2 pós-launch): basquete (NBA, EuroLeague), beisebol (MLB)
- Lista de ligas habilitadas é configurável por Admin sem deploy
- Cada liga tem flag `active: boolean` e `tier_required: free|pro|elite`

### RF-COL-004 — Tipos de Mercado Suportados
**Descrição:** O sistema deve coletar e processar os tipos de mercado mais líquidos e disponíveis na maioria das casas.
**Prioridade:** Must (1X2, Over/Under), Should (Asian Handicap, BTTS)
**Critério de aceite:**
- **1X2 (Match Winner):** coletado para todos os jogos habilitados
- **Over/Under Goals (2.5, 3.5):** coletado onde disponível em 70%+ das casas monitoradas
- **Asian Handicap:** coletado onde Pinnacle oferece linha (garantia de referência sharp)
- **BTTS (Both Teams to Score):** coletado como mercado secundário
- Tipo de mercado ausente em uma casa não bloqueia coleta dos outros tipos
- Novo tipo de mercado pode ser adicionado via configuração, sem alteração de código core

### RF-COL-005 — Armazenamento Imutável de Snapshots
**Descrição:** Cada coleta deve gerar um snapshot imutável com timestamp, preservado para backtesting e auditoria.
**Prioridade:** Must
**Critério de aceite:**
- Cada snapshot contém: `event_id`, `market_type`, `bookmaker_id`, `odds_home`, `odds_draw`, `odds_away`, `collected_at` (UTC ISO 8601), `source` (the_odds_api|betfair)
- Snapshots nunca são atualizados — apenas inseridos (append-only)
- TTL: snapshots de eventos encerrados há mais de 13 meses são removidos automaticamente (DynamoDB TTL)
- Usuários Elite têm acesso a histórico de 12 meses; outros tiers não acessam snapshots históricos

### RF-COL-006 — Integração com Betfair Exchange
**Descrição:** O sistema deve coletar dados de volume e liquidez do Betfair para enriquecer avaliação de qualidade do mercado.
**Prioridade:** Should
**Critério de aceite:**
- Para cada mercado futebol 1X2, coletar `matched_amount` (volume total negociado) e `available_to_back` por seleção
- Mercados com `matched_amount` < $10.000 são marcados como `low_liquidity` — usado pelo módulo de EV para filtrar alertas
- Betfair é fonte secundária: falha total da Betfair não bloqueia coleta de odds via The Odds API
- Dados de liquidez armazenados no mesmo snapshot de mercado, com `betfair_data: null` quando indisponível

### RF-COL-007 — Enriquecimento com API-Football
**Descrição:** Dados contextuais de partidas (hora de início confirmada, status, escalações quando disponíveis) devem ser coletados para enriquecer alertas.
**Prioridade:** Could
**Critério de aceite:**
- Para cada partida futebol, coletar: `status` (scheduled|live|finished|postponed|cancelled), `venue`, `round`
- Partidas com status `postponed` ou `cancelled` devem ter todos os alertas pendentes cancelados imediatamente
- Dados de API-Football são opcionais — ausência não bloqueia coleta ou cálculo de EV

### RF-COL-008 — Fallback em Falha de Fonte Primária
**Descrição:** Se The Odds API retornar erro ou ficar indisponível, o sistema deve operar em modo degradado com alertas internos.
**Prioridade:** Must
**Critério de aceite:**
- Após 3 falhas consecutivas de The Odds API, alerta interno é enviado para canal Telegram admin e/ou Slack
- Em modo degradado, pipeline de EV para de processar novos alertas (sem dados = sem alertas falsos)
- Retomada automática quando The Odds API responder com sucesso
- Status de degradação visível no painel admin em tempo real
- Job não gera exceção não tratada — toda falha é capturada, logada e reportada

### RF-COL-009 — Gestão de Rate Limit e Quota de API
**Descrição:** O sistema deve respeitar os rate limits das APIs contratadas e alertar quando consumo de quota se aproximar dos limites.
**Prioridade:** Must
**Critério de aceite:**
- Contador de requisições para The Odds API armazenado em DynamoDB, resetado mensalmente
- Alerta interno quando consumo atingir 80% da quota mensal
- Alerta crítico quando consumo atingir 95% da quota mensal — reduzir frequência de polling automaticamente
- Em caso de resposta HTTP 429 (rate limit), implementar exponential backoff: 1s, 2s, 4s, 8s (máx 4 tentativas)
- Requisições para Betfair limitadas a 3 req/segundo (limite da API)
- Métricas de consumo de quota disponíveis no painel admin

### RF-COL-010 — Alertas de Degradação de Qualidade
**Descrição:** O sistema deve detectar e reportar anomalias nos dados coletados que possam comprometer a qualidade dos alertas.
**Prioridade:** Should
**Critério de aceite:**
- Se Pinnacle retornar odds para < 50% dos jogos esperados em uma liga habilitada, alerta de qualidade disparado
- Se desvio padrão das odds Pinnacle de uma partida entre coletas consecutivas exceder 15%, marcado como `high_volatility` — módulo de EV deve usar com cautela
- Se um bookmaker retornar odds em < 10% dos mercados esperados por 3 coletas consecutivas, bookmaker marcado como `unreliable` e excluído temporariamente dos cálculos de EV

### RF-COL-A — Polling Rate Variável por Par Liga/Bookmaker (Agente G e Agente D)
**Descrição:** A frequência de polling deve ser ajustável por par (liga, bookmaker) via API interna, sem deploy, para suportar o Agente D (que identifica pares de alta ineficiência) e o Agente G (que pode elevar frequência durante incidentes).
**Prioridade:** Should
**Critério de aceite:**
- Tabela `polling_overrides` em DynamoDB: `(league_id, bookmaker_id) → interval_seconds`
- Lambda de coleta consulta a tabela no início de cada ciclo e aplica overrides
- Override máximo permitido: 15 segundos (abaixo disso, risco de exceder quota)
- Override mínimo permitido: 300 segundos
- Mudanças refletem na próxima execução sem restart

### RF-COL-B — Exchange Volume no Snapshot (Agente H)
**Descrição:** Cada snapshot deve incluir dados de volume do Betfair Exchange quando disponível, para alimentar o Agente H (Sharp Action Tracker).
**Prioridade:** Should
**Critério de aceite:**
- Campo `exchange_volume_usd` adicionado ao snapshot (nullable)
- Campo `exchange_back_available` por seleção (nullable)
- Coleta de volume via Betfair Exchange API no mesmo ciclo de polling — sem job separado
- Se Betfair indisponível, campos ficam `null`; pipeline de EV não é bloqueado

### RF-COL-C — Evento OddsMovementDetected (Agente B)
**Descrição:** Pipeline deve emitir evento enriquecido quando delta de odds excede threshold, para consumo pelo Agente B (Odds Movement Classifier).
**Prioridade:** Must (para suporte ao Agente B MVP)
**Critério de aceite:**
- Threshold de emissão: odds Pinnacle moveram > 2% em relação ao snapshot anterior
- Payload do evento: `event_id, market_type, bookmaker_id, previous_odds, current_odds, delta_pct, series_last_5_snapshots, exchange_volume_delta, collected_at`
- Evento publicado em fila SQS dedicada (`odds-movement-events`) consumida pelos agentes
- Se delta = 0 (odds inalteradas), evento não emitido — reduz ruído

---

## Regras de Negócio

### RN-COL-001 — Pinnacle como única fonte de linha sharp
A Pinnacle é a única fonte aceita como linha de referência para cálculo de EV. Betfair pode ser usada para estimativa de probabilidade apenas quando Pinnacle estiver ausente de um mercado específico, e nesse caso o alerta deve ser marcado com flag `reference: betfair` e confiança reduzida.

### RN-COL-002 — Imutabilidade de snapshots
Snapshots nunca são modificados após inserção. Correções de dados são registradas como novos snapshots com campo `correction_of: <snapshot_id>`. Qualquer snapshot com `correction_of` preenchido não é usado no pipeline de alertas — apenas em backtesting.

### RN-COL-003 — Escopo temporal de coleta
Apenas eventos com início entre 5 minutos e 72 horas a partir do momento atual são coletados ativamente. Eventos com início em < 5 minutos são ignorados (odds de fechamento, não acionáveis). Eventos com início em > 72 horas são coletados com baixa frequência apenas para histórico.

### RN-COL-004 — Identificação canônica de eventos
O mesmo jogo pode aparecer com IDs diferentes em The Odds API, Betfair e API-Football. O sistema deve manter um mapa de equivalência `event_canonical_id` gerado internamente, baseado em nome dos times (normalizado) + data + liga. Falha no mapeamento não bloqueia coleta, mas impede enriquecimento cruzado.

### RN-COL-005 — Custo de quota por liga
Ligas com baixo volume de apostas (< 5 mercados por rodada) consomem quota desproporcionalmente. Admin pode definir `min_markets_per_round` por liga para justificar custo de coleta.

---

## Restrições e Dependências

| Dependência | Tipo | Impacto em falha |
|---|---|---|
| The Odds API | Externa crítica | Pipeline para completamente |
| Betfair Exchange API | Externa secundária | Perde dados de liquidez; EV continua |
| API-Football | Externa opcional | Perde contexto; alertas continuam |
| AWS EventBridge | Infraestrutura | Lambda não dispara; pipeline para |
| DynamoDB | Infraestrutura | Snapshots não são persistidos |

**Restrições de infraestrutura:**
- Lambda timeout máximo: 15 minutos; job de coleta deve finalizar em < 25 segundos para evitar sobreposição de execuções
- DynamoDB write capacity: calcular baseado em `(número de mercados) × (número de casas) × (frequência de polling)` — revisar antes do launch
- Custo de The Odds API escala com número de requisições; plano deve cobrir volume calculado com margem de 30%
