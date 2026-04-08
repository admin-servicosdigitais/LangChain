# Módulo de Detecção de Expected Value

## Contexto de Negócio

O módulo de EV é o coração analítico do produto. Ele transforma dados brutos de odds em sinais acionáveis. A qualidade aqui determina diretamente a reputação do produto: alertas de EV calculado incorretamente, ou emitidos em mercados com dados ruins, destroem a confiança do usuário profissional — o segmento de maior valor (Elite).

Trade-offs centrais:
- **Sensibilidade vs. precisão:** threshold baixo de EV gera mais alertas, mas com mais ruído (EV calculado com imprecisão). Threshold alto reduz volume, mas usuário sente que "perde oportunidades".
- **Velocidade vs. confiabilidade:** processar snapshot imediatamente após coleta minimiza latência, mas pode usar dados ruidosos. Aguardar confirmação em múltiplas coletas aumenta confiança, mas perde a janela.
- A decisão de design é: processar imediatamente, mas com filtros de qualidade rigorosos e marcação de confiança.

---

## Atores

- **Sistema (job de EV):** executa após cada ciclo de coleta de odds
- **Usuário Pro/Elite:** configura threshold de EV mínimo personalizado
- **Admin:** configura parâmetros globais de threshold, filtros de liquidez e ligas habilitadas
- **Módulo de Alertas:** consome output deste módulo (lista de oportunidades validadas)

---

## Requisitos Funcionais

### RF-EV-001 — Cálculo de Margin da Pinnacle
**Descrição:** Para cada mercado Pinnacle, calcular a margem embutida (vigorish) antes de extrair a probabilidade justa.
**Prioridade:** Must
**Critério de aceite:**
- Para mercado 1X2 com odds `(h, d, a)`:
  ```
  pinnacle_margin = 1 - (1/h + 1/d + 1/a)^(-1)... 
  
  # Cálculo correto:
  total_implied = (1/h) + (1/d) + (1/a)
  pinnacle_margin = 1 - (1 / total_implied)
  ```
- Para mercado Over/Under (2 resultados) com odds `(o, u)`:
  ```
  total_implied = (1/o) + (1/u)
  pinnacle_margin = 1 - (1 / total_implied)
  ```
- Margin calculada e armazenada por snapshot; se margin > 8%, snapshot descartado como dado suspeito
- Margin típica Pinnacle futebol: 1,5%–3,5%; valores fora de 0,5%–8% disparam alerta de qualidade

### RF-EV-002 — Cálculo de Fair Odds (Probabilidade Justa)
**Descrição:** Remover a margin da Pinnacle para extrair a probabilidade implícita justa de cada resultado.
**Prioridade:** Must
**Critério de aceite:**
- Para cada resultado `i` de mercado Pinnacle:
  ```
  implied_prob_i = 1 / pinnacle_odds_i
  fair_prob_i = implied_prob_i / total_implied  # normalização
  fair_odds_i = 1 / fair_prob_i
  ```
- Verificação: soma de `fair_prob_i` para todos os resultados do mercado deve ser 1,0 (±0,001 por arredondamento)
- `fair_odds` armazenado no registro de oportunidade para auditoria

### RF-EV-003 — Cálculo de Expected Value por Bookmaker
**Descrição:** Para cada par (bookmaker, resultado), calcular EV contra a fair odds da Pinnacle.
**Prioridade:** Must
**Critério de aceite:**
- Fórmula:
  ```
  ev = (book_odds / fair_odds) - 1
  ```
- EV calculado para todos os resultados de todos os bookmakers com odds disponíveis no snapshot
- EV armazenado com 4 casas decimais de precisão
- Bookmaker Pinnacle nunca gera oportunidade contra ele mesmo (excluído do cálculo de EV como "book")
- Se `book_odds` ou `fair_odds` for <= 1.0, registro descartado como inválido

### RF-EV-004 — Thresholds Configuráveis de EV
**Descrição:** Oportunidades são promovidas a alertas apenas quando EV ultrapassa threshold configurado — global e por usuário.
**Prioridade:** Must
**Critério de aceite:**
- Threshold padrão global: `ev > 0.03` (3%)
- Usuário Pro pode configurar threshold entre 0.01 (1%) e 0.20 (20%)
- Usuário Elite pode configurar threshold entre 0.01 (1%) e 0.30 (30%)
- Usuário Free: threshold fixo em 0.05 (5%) — não configurável
- Oportunidades abaixo do threshold do usuário são descartadas silenciosamente (não armazenadas como alertas pendentes)
- Configuração de threshold é por usuário, não por liga ou mercado (fase 1)

### RF-EV-005 — Filtros de Qualidade antes de Emitir Oportunidade
**Descrição:** Oportunidades com EV positivo que passam pelo threshold ainda devem passar por filtros de qualidade para reduzir falsos positivos.
**Prioridade:** Must
**Critério de aceite:**
- **Filtro de tempo:** evento deve iniciar em > 5 minutos e < 48 horas a partir do momento do cálculo
- **Filtro de liquidez Betfair:** mercado futebol com `matched_amount` < $10.000 é descartado (dado ausente = pass, não bloqueia)
- **Filtro de volatilidade:** se o mesmo bookmaker mudou odds para esse mercado por > 10% em < 5 minutos, oportunidade marcada como `volatile: true` e não gera alerta (aguarda estabilização)
- **Filtro de bookmaker:** bookmakers marcados como `unreliable` (ver RF-COL-010) são excluídos
- **Filtro de mercado habilitado:** apenas tipos de mercado em `allowed_markets` da configuração global

### RF-EV-006 — Regra de Confiança: Quando não Alertar com EV Positivo
**Descrição:** Situações onde EV calculado é positivo mas o contexto sugere dado não confiável.
**Prioridade:** Must
**Critério de aceite:**
- Se odds da Pinnacle para esse mercado mudaram > 5% na última hora, flag `pinnacle_moving: true` — alerta não emitido (mercado com informação assimétrica, possível insider trading)
- Se apenas 1 bookmaker (além da Pinnacle) tem odds para o mercado, alerta não emitido (amostra insuficiente para validar)
- Se EV > 0.25 (25%), alerta marcado como `suspicious_ev: true` — enviado apenas para Elite, com aviso explícito de verificação manual; não enviado para Pro/Free
- Se snapshot tem menos de 30 segundos desde o anterior com odds idênticas da Pinnacle, usar o anterior (evitar duplicatas por retry)

### RF-EV-007 — Detecção de Arbitragem
**Descrição:** Identificar situações onde odds de casas diferentes cobrem todos os resultados com margem de lucro garantido.
**Prioridade:** Should
**Critério de aceite:**
- Para mercado 1X2, calcular:
  ```
  arb_margin = 1 - (1/best_home + 1/best_draw + 1/best_away)
  ```
  Se `arb_margin > 0`, existe oportunidade de arbitragem
- Oportunidade de arb inclui: `arb_margin`, `bookmaker_home`, `bookmaker_draw`, `bookmaker_away`, `stake_distribution` (proporção ideal por resultado)
- Arb é entregue como tipo de alerta distinto (`alert_type: arb`), separado dos alertas de EV
- Filtro temporal: arb com `arb_margin < 0.005` (< 0,5%) não é reportado (comissões podem eliminar o lucro)
- Alertas de arb disponíveis para Pro e Elite; não disponíveis para Free

### RF-EV-008 — Cálculo de Kelly Criterion (Elite)
**Descrição:** Para usuários Elite, calcular o tamanho recomendado de stake usando Kelly Criterion.
**Prioridade:** Could (Elite only)
**Critério de aceite:**
- Fórmula Kelly completo:
  ```
  b = book_odds - 1  # lucro por unidade apostada
  p = fair_prob      # probabilidade estimada (da Pinnacle)
  q = 1 - p
  kelly_full = (b*p - q) / b
  ```
- Sistema sempre retorna Kelly fracionado a 1/4 como recomendação padrão:
  ```
  kelly_recommended = kelly_full / 4
  ```
- Se `kelly_full <= 0`, aposta não deve ser feita (EV negativo nessa estimativa) — não emitir alerta
- Usuário Elite pode configurar fração Kelly (1/4, 1/3, 1/2, full) — padrão 1/4
- Kelly calculado sobre bankroll configurado pelo usuário; resultado em unidades monetárias no alerta
- Se usuário não configurar bankroll, Kelly é exibido como fração (0,023 = 2,3% do bankroll)

### RF-EV-009 — Registro de Histórico de EV para Backtesting
**Descrição:** Cada oportunidade de EV detectada (independente de ter gerado alerta) deve ser armazenada para backtesting posterior.
**Prioridade:** Must (armazenar), Could (interface de consulta)
**Critério de aceite:**
- Registro contém: `event_id`, `market_type`, `bookmaker_id`, `outcome`, `book_odds_at_detection`, `fair_odds_at_detection`, `ev_at_detection`, `pinnacle_margin_at_detection`, `detected_at`, `filters_passed: boolean`, `alert_generated: boolean`
- Odds de fechamento (`closing_odds_pinnacle`) adicionadas ao registro após o evento fechar
- Resultado real (`outcome_result: win|loss|void`) adicionado após resolução do evento
- Registros de histórico de EV são acessíveis apenas para usuários Elite via API e interface de backtesting
- Retenção: 13 meses (cobre requisito de 12 meses de histórico Elite com margem)

### RF-EV-010 — Pipeline Idempotente
**Descrição:** Reprocessamento do mesmo snapshot de odds não deve gerar oportunidades duplicadas.
**Prioridade:** Must
**Critério de aceite:**
- Chave de idempotência: `hash(event_id + market_type + bookmaker_id + outcome + snapshot_id)`
- Se oportunidade com mesma chave já existe na janela de 1 hora, descartada silenciosamente
- Lambda de EV pode ser reexecutada com segurança após falha parcial

### RF-EV-A — Integração com Quality Score do Agente A
**Descrição:** Substituir filtros binários de qualidade por `quality_score` contínuo produzido pelo Agente A (Data Quality Sentinel), quando disponível.
**Prioridade:** Should (V2 — Agente A requer histórico de 3 meses)
**Critério de aceite:**
- Campo `quality_score` (0.0–1.0) adicionado ao snapshot pelo Agente A
- Se `quality_score` presente: usar threshold configurável (default: 0.6) em vez de regras binárias
- Se `quality_score` ausente (Agente A não processou ainda): fallback para regras binárias atuais
- Classificação adicional: `illiquid_but_valid` (score 0.6-0.75) permite cálculo de EV com flag `low_confidence: true` no alerta
- Transição gradual: regras binárias permanecem ativas em paralelo por 30 dias após ativação do Agente A

### RF-EV-B — EV > 25% Requer Classificação do Agente B
**Descrição:** Oportunidades com EV > 25% não são descartadas automaticamente — são obrigatoriamente encaminhadas ao Agente B (Odds Movement Classifier) antes do envio.
**Prioridade:** Must (alteração de comportamento atual)
**Critério de aceite:**
- EV > 25% publica evento em fila `high-ev-classification` para o Agente B processar
- Timeout: se Agente B não responder em 10 segundos, fallback para comportamento atual (`suspicious_ev: true`, envio apenas para Elite com aviso)
- Se Agente B classifica como `bookmaker_error` → descarta
- Se Agente B classifica como qualquer outra causa com confidence > 0.7 → alerta enviado para Elite com contexto completo
- Se Agente B classifica com confidence < 0.7 → comportamento atual (Elite com aviso, não Pro/Free)

### RF-EV-C — Kelly Output via Agente C (Elite)
**Descrição:** Para usuários Elite com Agente C ativo, o campo `kelly_fraction` do alerta é fornecido pelo Agente C em vez do cálculo fixo 1/4 Kelly.
**Prioridade:** Should (V2 — Agente C requer histórico de apostas)
**Critério de aceite:**
- Se Agente C ativo para o usuário: alerta inclui `kelly_fraction` do agente + justificativa em texto curto
- Se Agente C inativo (sem histórico suficiente): fallback para 1/4 Kelly fixo com nota "Kelly adaptativo disponível após 20 apostas registradas"
- Kelly do Agente C respeita bounds do usuário (configurado no perfil: min/max fraction)
- Cálculo do Agente C não bloqueia o pipeline principal — é assíncrono; alerta enviado com 1/4 Kelly se Agente C não responder em 5s

### RF-EV-D — Campo classification_source no Alerta
**Descrição:** Todo alerta gerado deve informar se a classificação de qualidade e contexto veio de agente ou de regras estáticas.
**Prioridade:** Must
**Critério de aceite:**
- Campo `classification_source`: `agent_b` | `rule_based` | `pending`
- Campo `agent_context` (nullable): objeto JSON com saída do Agente B quando disponível
- Campos armazenados no registro histórico do M05 para análise de acurácia dos agentes ao longo do tempo

---

## Regras de Negócio

### RN-EV-001 — Pinnacle é a única fonte de fair odds
Fair odds são calculadas exclusivamente a partir das odds da Pinnacle, após remoção de margin. Não existe fallback para outra casa como referência de fair odds. Se Pinnacle não tem odds para um mercado, o mercado não tem cálculo de EV.

### RN-EV-002 — EV é calculado sobre resultado único
EV é calculado por resultado (ex.: vitória do time da casa), não por partida. Um alerta pode existir para "Over 2.5 na Bet365" sem que exista alerta para "Under 2.5" ou para "1X2" no mesmo jogo — são oportunidades independentes.

### RN-EV-003 — Não usar odds de mercados in-play
O módulo de EV processa apenas odds pré-jogo. Mercados in-play (ao vivo) têm dinâmica diferente e estão fora do escopo atual. Snapshots coletados após início oficial do evento são descartados do pipeline de EV.

### RN-EV-004 — Ligas sem linha Pinnacle são inválidas
Se The Odds API não inclui Pinnacle para uma determinada liga/mercado (ex.: liga de nicho sem cobertura da Pinnacle), essa liga não pode ter cálculo de EV e não deve ser exibida como disponível para usuários.

### RN-EV-005 — Threshold de EV é sobre EV bruto, não ajustado por liquidez
O threshold configurado (ex.: 3%) é comparado ao EV calculado matematicamente, sem desconto por liquidez. A liquidez (volume Betfair) é um filtro binário separado — ou passa ou não passa.

---

## Restrições e Dependências

| Dependência | Tipo | Impacto em falha |
|---|---|---|
| Módulo de Coleta (snapshots) | Interna crítica | Sem snapshots = sem cálculo de EV |
| DynamoDB (leitura de snapshots) | Infraestrutura | Lambda de EV falha; pipeline parado |
| Configurações de usuário (thresholds) | Interna | Usa threshold padrão global como fallback |
| API-Football (status de partida) | Externa opcional | Filtragem por status suspenso indisponível |

**Restrições computacionais:**
- Lambda de EV deve processar todos os snapshots de um ciclo de coleta em < 20 segundos
- Volume estimado por ciclo: ~200 mercados × 40 casas × 3 resultados = ~24.000 cálculos de EV
- DynamoDB read capacity deve comportar leitura de snapshots + escrita de oportunidades no mesmo ciclo
- Precisão de ponto flutuante: usar `Decimal` (Python) ou equivalente — nunca `float` nativo para valores monetários e probabilidades
