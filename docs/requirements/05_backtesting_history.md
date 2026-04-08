# Módulo de Histórico e Backtesting (Elite)

## Contexto de Negócio

Backtesting transforma o produto de "ferramenta de alertas" em "ferramenta de análise profissional". Para o apostador Elite, ROI histórico verificável é o que justifica $79/mês — e o que diferencia o produto de concorrentes que entregam apenas alertas sem evidência de performance.

O dado mais valioso não é o resultado da aposta (o usuário controla isso), mas o **Closing Line Value (CLV)**: se a odd alertada estava acima da linha de fechamento da Pinnacle, o modelo identificou valor real antes do mercado convergir — independentemente do resultado de curto prazo. CLV positivo consistente é evidência matemática de edge.

Trade-offs centrais:
- **Armazenamento vs. custo:** 12 meses de histórico para todos os usuários Elite com todos os campos = DynamoDB caro. Estratégia: armazenamento quente (DynamoDB) para 3 meses; arquivo frio (S3 Parquet) para 4–12 meses, com query via Athena.
- **Completude vs. latência:** resultado real de uma partida pode demorar horas para ser confirmado. Sistema deve lidar com estado `pending_result` sem bloquear interface.

---

## Atores

- **Usuário Elite:** único tier com acesso à interface de backtesting e exportação
- **Sistema (job de enriquecimento):** coleta odds de fechamento e resultados reais após eventos
- **Admin:** monitora qualidade do histórico, pode reprocessar resultados incorretos

---

## Requisitos Funcionais

### RF-BCK-001 — Estrutura de Dados do Registro Histórico
**Descrição:** Cada oportunidade detectada (que gerou ou não alerta) deve ter registro completo para análise histórica.
**Prioridade:** Must
**Critério de aceite:**
Campos armazenados no momento da detecção:
```
- alert_id: UUID
- event_id: identificador canônico do evento
- event_name: "[Time A] vs [Time B]"
- league_id + league_name
- market_type: 1X2 | over_under | asian_handicap | btts
- outcome: home | draw | away | over | under | btts_yes | btts_no | ah_home | ah_away
- bookmaker_id + bookmaker_name
- book_odds_at_alert: Decimal(4)
- fair_odds_at_alert: Decimal(4)
- ev_at_alert: Decimal(4)  # ex: 0.0432 = +4.32%
- pinnacle_margin_at_alert: Decimal(4)
- detected_at: ISO 8601 UTC
- alert_sent: boolean
- alert_sent_at: ISO 8601 UTC | null
- user_id: FK para usuário (para histórico individual)
```
Campos adicionados após fechamento do mercado (pré-jogo):
```
- closing_odds_pinnacle: Decimal(4) | null
- closing_odds_bookmaker: Decimal(4) | null
- closing_fair_odds: Decimal(4) | null
- clv: Decimal(4) | null  # calculado após fechamento
- market_closed_at: ISO 8601 UTC | null
```
Campos adicionados após resolução do evento:
```
- outcome_result: win | loss | void | postponed
- event_finished_at: ISO 8601 UTC | null
- result_source: api_football | manual
- result_confirmed_at: ISO 8601 UTC | null
```

### RF-BCK-002 — Coleta de Odds de Fechamento
**Descrição:** O sistema deve coletar as odds finais (de fechamento) da Pinnacle para cada mercado antes do início do evento.
**Prioridade:** Must
**Critério de aceite:**
- Job executa coleta de odds de fechamento nos 5 minutos antes do início oficial de cada evento
- "Odds de fechamento" = último snapshot da Pinnacle antes de `event_start_time`
- Se Pinnacle não tiver odds nos 5 minutos finais (mercado suspenso), usar último snapshot disponível com flag `closing_odds_estimated: true`
- Odds de fechamento armazenadas vinculadas a todos os registros históricos desse mercado
- Dados de fechamento disponíveis no histórico em até 15 minutos após início do evento

### RF-BCK-003 — Cálculo de Closing Line Value (CLV)
**Descrição:** CLV mede se as odds no momento do alerta eram melhores que as odds de fechamento — principal métrica de qualidade de longo prazo.
**Prioridade:** Must
**Critério de aceite:**
- Fórmula:
  ```
  clv = (book_odds_at_alert / closing_fair_odds) - 1
  ```
  Onde `closing_fair_odds` = fair odds calculadas a partir da Pinnacle de fechamento
- CLV positivo: odds alertadas eram melhores que o fechamento → modelo identificou valor antes do mercado
- CLV negativo: mercado já havia precificado o valor corretamente antes do alerta → sinal tardio
- CLV armazenado por registro; CLV médio calculado como métrica de performance agregada
- CLV exibido por: liga, tipo de mercado, bookmaker, período (configurável na interface)

### RF-BCK-004 — Coleta de Resultados Reais
**Descrição:** O sistema deve coletar o resultado real de cada evento para calcular ROI histórico.
**Prioridade:** Must
**Critério de aceite:**
- Fonte primária: API-Football (resultado final com placar)
- Polling de resultado a cada 5 minutos durante janela de 3h após `event_start_time`
- Resultado considerado final quando `match_status == "FT"` (Full Time) na API-Football
- Se API-Football não confirmar resultado em 4h após início, status permanece `pending_result` e Admin é notificado
- Tradução de resultado para `outcome_result`:
  - 1X2: comparar placar final com seleção alertada
  - Over/Under: somar gols totais e comparar com linha
  - BTTS: verificar se ambos times marcaram
  - Asian Handicap: aplicar handicap ao placar e determinar win/loss/push
- `void`: evento anulado, adiado ou cancelado → sem impacto no ROI

### RF-BCK-005 — Interface de Backtesting com Filtros
**Descrição:** Usuários Elite devem poder filtrar e analisar performance histórica com granularidade.
**Prioridade:** Must (Elite only)
**Critério de aceite:**
Filtros disponíveis na interface:
- **Período:** date range com seletor (últimos 7/30/90/180/365 dias + range customizado)
- **Liga:** multi-select (todas as ligas disponíveis no histórico do usuário)
- **Tipo de mercado:** 1X2, Over/Under, Asian Handicap, BTTS, ou todos
- **Bookmaker:** multi-select
- **Threshold de EV:** slider (ex.: "mostrar apenas apostas com EV > 3% no momento do alerta")
- **Resultado:** win | loss | void | todos
- **CLV:** positivo | negativo | todos

Métricas exibidas para o conjunto filtrado:
- Total de alertas no período
- Taxa de acerto (win rate): % de apostas ganhas (excluindo void)
- ROI simulado: com stake fixo de 1 unidade por aposta
- EV médio no momento do alerta
- CLV médio
- Yield por liga (ROI / número de apostas por liga)
- Melhor e pior período (por semana)

Critério de aceite técnico:
- Query com filtros máximos (12 meses, todas as ligas, todos os tipos) deve retornar em < 3 segundos
- Resultados paginados: máximo 200 registros por página, com cursor-based pagination
- Interface deve exibir aviso quando conjunto filtrado tem < 30 apostas: "Amostra pequena — resultados não são estatisticamente significativos"

### RF-BCK-006 — Métricas Calculadas por Dimensão
**Descrição:** O sistema calcula e exibe métricas de performance agregadas por diferentes dimensões analíticas.
**Prioridade:** Should
**Critério de aceite:**
- **ROI por liga:** `((total_ganhos - total_stakes) / total_stakes) × 100` para stakes fixos unitários
- **ROI por tipo de mercado:** mesmo cálculo segmentado por 1X2, O/U, etc.
- **ROI por bookmaker:** identificar em quais casas o sinal é mais forte
- **ROI por período:** gráfico de ROI acumulado ao longo do tempo (curva de capital)
- **Degradação temporal de EV:** comparar EV médio de alertas gerados com CLV médio — se CLV << EV, sinal está sendo gerado tarde
- Todas as métricas incluem intervalo de confiança a 95% quando N ≥ 30

### RF-BCK-007 — Exportação de Dados Históricos
**Descrição:** Usuários Elite podem exportar todo o histórico de alertas recebidos com dados completos.
**Prioridade:** Must (Elite only)
**Critério de aceite:**
- Formatos disponíveis: CSV e JSON
- CSV: cabeçalho com todos os campos do registro histórico (RF-BCK-001)
- JSON: array de objetos com mesmos campos
- Filtros aplicados na interface de backtesting são aplicados na exportação (usuário exporta o subset filtrado)
- Exportação completa (sem filtros): gera arquivo assíncrono; usuário recebe link por email em até 30 minutos
- Exportação filtrada (< 10.000 registros): síncrona, download imediato
- Arquivos de exportação têm TTL de 24h no S3
- Nome do arquivo: `valuebet_history_{user_id}_{date_range}_{timestamp}.{csv|json}`

### RF-BCK-008 — Armazenamento em Camadas (Hot/Cold)
**Descrição:** Para controlar custos de armazenamento mantendo performance de consulta aceitável.
**Prioridade:** Should
**Critério de aceite:**
- **Hot storage (DynamoDB):** últimos 90 dias de registros — consultas < 100ms
- **Cold storage (S3 Parquet):** 91 dias a 13 meses — queries via Amazon Athena, latência 1–10s
- Job diário de archiving: move registros com `detected_at` > 90 dias de DynamoDB para S3
- Interface de backtesting é transparente quanto ao storage tier (usuário não vê diferença além de latência)
- Consultas que cruzam hot/cold storage (ex.: filtro de 6 meses): Athena para dados frios + DynamoDB para dados quentes, merge em memória na Lambda

### RF-BCK-009 — Histórico de ROI Simulado (Resumos)
**Descrição:** Cálculo periódico de ROI simulado para resumos enviados a usuários Elite.
**Prioridade:** Could
**Critério de aceite:**
- Calculado semanalmente: ROI se usuário tivesse apostado 1 unidade em cada alerta recebido
- Benchmark de comparação: ROI com apostas aleatórias na mesma liga no período (baseline)
- Incluído no resumo semanal do usuário Elite
- Exibido no dashboard com gráfico de curva de capital (semanal, últimos 12 meses)

### RF-BCK-A — Fase 4: Diagnóstico do Agente F
**Descrição:** Pipeline de registro deve incluir fase 4 (após resultado real), onde o Agente F processa o histórico acumulado e armazena diagnóstico narrativo.
**Prioridade:** Should (V2 — requer 20+ apostas registradas para significância)
**Critério de aceite:**
- Evento `BetResultRecorded` publicado em SQS após confirmação de resultado (`result_confirmed_at` preenchido)
- Agente F consome evento, analisa histórico do usuário e armazena diagnóstico em `user_performance_diagnoses`
- Estrutura do diagnóstico: `{ diagnosis_id, user_id, generated_at, period_analyzed, findings: [{ dimension, metric, value, interpretation, recommendation }], summary_text }`
- Diagnóstico gerado no máximo 1x por semana por usuário (não a cada aposta)
- Interface de backtesting exibe diagnóstico mais recente na barra lateral, com link para histórico de diagnósticos
- Diagnósticos anteriores preservados: usuário pode ver evolução das recomendações ao longo do tempo

### RF-BCK-B — Hunt Reports do Agente D na Interface
**Descrição:** Hunt Reports gerados pelo Agente D (ineficiências sistemáticas identificadas) devem ser acessíveis na interface de backtesting.
**Prioridade:** Should (V3 — Agente D requer 6+ meses de histórico)
**Critério de aceite:**
- Aba "Ineficiências Detectadas" na interface Elite exibe lista de Hunt Reports ordenados por data
- Cada report contém: liga, bookmaker, mercado, horário padrão, EV médio histórico, frequência semanal, confiança estatística (p-value), período analisado
- Usuário pode "ativar" uma ineficiência: sistema prioriza alertas daquele par liga/bookmaker para o usuário
- Reports são recalculados mensalmente; ineficiências que deixaram de ser sistemáticas são marcadas como `expired`

### RF-BCK-C — Métricas de Acurácia dos Agentes (Meta-análise)
**Descrição:** Armazenar métricas de acurácia dos próprios agentes para análise de qualidade e melhoria contínua.
**Prioridade:** Should
**Critério de aceite:**
- Para o Agente B: comparar classificação de causa com resultado observado (ex.: classificou como `sharp_money` → odds fecharam na direção indicada? Sim/Não)
- Para o Agente C: comparar Kelly recomendado com resultado de ROI daquela aposta
- Métricas de acurácia por agente disponíveis no painel Admin (não para usuários)
- Retenção: 24 meses de histórico de acurácia (necessário para melhoria do modelo)

---

## Regras de Negócio

### RN-BCK-001 — Dados históricos são imutáveis após confirmação
Após `outcome_result` ser marcado como confirmado (`result_confirmed_at` preenchido), o registro não pode ser alterado. Correções são registradas como novo registro com `corrects_record: <alert_id>` e o registro original é marcado `superseded: true`. O sistema de métricas usa apenas registros ativos (não superseded).

### RN-BCK-002 — Apostas void não entram no cálculo de ROI
Registros com `outcome_result: void` são excluídos de todos os cálculos de ROI e win rate. Fazem parte do histórico exibido com tag visual "Void".

### RN-BCK-003 — CLV só é calculado quando ambas as odds estão disponíveis
Se odds de fechamento da Pinnacle não estiverem disponíveis, CLV permanece `null`. O sistema nunca extrapola CLV de dados parciais. Alertas sem CLV são exibidos na interface com "CLV: N/D" e não entram na métrica de CLV médio.

### RN-BCK-004 — Acesso ao histórico cessa com downgrade de Elite
Se usuário faz downgrade de Elite para Pro ou Free, perde acesso à interface de backtesting e exportação. Os dados são preservados no banco por 12 meses. Se usuário reativar Elite dentro desse prazo, dados voltam a ser acessíveis imediatamente. Após 12 meses sem plano Elite ativo, dados são deletados (com notificação por email 30 dias antes).

### RN-BCK-005 — Backtesting não é aconselhamento financeiro
A interface deve exibir disclaimer permanente: "Performance passada não garante resultados futuros. Apostas esportivas envolvem risco financeiro. Dados apresentados têm fins informativos."

---

## Restrições e Dependências

| Dependência | Tipo | Impacto em falha |
|---|---|---|
| API-Football (resultados) | Externa | Resultados pendentes; ROI incalculável |
| The Odds API (odds fechamento) | Externa | CLV não calculado |
| DynamoDB (hot storage) | Infraestrutura | Histórico recente indisponível |
| S3 + Athena (cold storage) | Infraestrutura | Histórico > 90 dias indisponível |
| Módulo de EV (registros de detecção) | Interna | Sem input para histórico |

**Restrições de custo:**
- DynamoDB com 90 dias de histórico para base Elite: estimar volume baseado em `alertas_por_dia × usuários_elite × 90 dias`
- Athena cobra por TB escaneado ($5/TB); Parquet com compressão Snappy e particionamento por `(league_id, year, month)` é essencial para controlar custo
- Job de archiving deve rodar fora do horário de pico (03h–05h UTC) para não competir com pipeline de alertas
