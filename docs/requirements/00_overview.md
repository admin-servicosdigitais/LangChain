# Value Betting SaaS — Visão Geral do Produto

## Contexto de Negócio

Mercados de apostas esportivas são ineficientes o suficiente para que apostadores informados extraiam valor esperado positivo (EV+) de forma consistente. A Pinnacle Sports, por operar como "sharp book" (aceita apostas de profissionais sem limitar), funciona como proxy do mercado eficiente. Qualquer casa que ofereça odds acima da linha Pinnacle (após remoção do vigorish) representa oportunidade de value bet.

O problema: identificar essas janelas de valor exige monitoramento contínuo de 40+ casas, cálculo matemático em tempo real e entrega de alertas antes que as odds se fechem — tarefa inviável manualmente. Este SaaS automatiza o fluxo completo.

---

## Objetivo do Sistema

Monitorar continuamente odds de múltiplas casas de apostas, calcular Expected Value usando a linha Pinnacle como referência de mercado eficiente, e entregar alertas em tempo real para usuários quando oportunidades de value bet ultrapassam threshold configurável.

**Métricas de sucesso do produto:**
- Latência alerta → usuário Pro: < 60 segundos após detecção
- Falso positivo (EV calculado incorreto por erro de dado): < 2% dos alertas
- Uptime do pipeline de coleta: > 99,5% (SLA interno)

---

## Personas / Atores

### Free
- Apostador recreativo, testando o produto
- Recebe alertas com delay de 30 minutos, apenas 1 liga
- Objetivo: avaliar qualidade do sinal antes de assinar
- Sem acesso a configurações avançadas

### Pro ($29/mês)
- Apostador semi-profissional, acompanha múltiplas ligas
- Alertas em tempo real, todas as ligas, threshold de EV customizável
- Principal segmento gerador de receita recorrente

### Elite ($79/mês)
- Apostador profissional ou sindicato de apostas
- Acesso via API (integração com ferramentas próprias)
- Backtesting, histórico 12 meses, Kelly Criterion para sizing
- Exportação de dados em CSV/JSON

### Admin
- Operador interno do SaaS
- Acesso ao painel de saúde do sistema, gestão de usuários, configuração de parâmetros globais
- Não é apostador — é o time de operações/produto

---

## Fronteiras do Sistema

### In Scope
- Coleta de odds via APIs contratadas (The Odds API, Betfair Exchange, API-Football)
- Cálculo de EV usando linha Pinnacle como referência
- Entrega de alertas via Telegram bot, email e webhook (conforme tier)
- Gestão de usuários, autenticação, planos e cobrança (Stripe)
- Backtesting e histórico para tier Elite
- Painel administrativo para operações internas
- Cálculo de Kelly Criterion para sizing de stake (Elite)
- Detecção de arbitragem como feature secundária
- **Camada agêntica (IA-First):** agentes autônomos para classificação de movimentação de odds, qualidade de dados adaptativa, diagnóstico de performance do usuário, bankroll management adaptativo, descoberta de ineficiências sistemáticas, onboarding conversacional e operação autônoma de infraestrutura

### Out of Scope
- Execução de apostas (integração com sportsbooks para bet placement)
- Aconselhamento financeiro regulado
- Odds de mercados in-play (ao vivo) — escopo futuro
- Cassino, slots, poker ou qualquer mercado não-esportivo
- **Predição de resultado esportivo** — os agentes classificam padrões de mercado, não predizem quem vence (distinção regulatória relevante)
- Suporte a moedas além de USD para cobrança (fase inicial)

---

## Arquitetura de Produto: Abordagem IA-First

O produto adota uma camada agêntica sobre o pipeline de dados. Os agentes **não substituem** o pipeline de coleta e cálculo de EV — enriquecem, adaptam e diagnosticam em cima dele.

### Agentes do Sistema (ver `07_agentic_layer.md` para especificação completa)

| ID | Agente | Função | Tier | MVP |
|----|--------|--------|------|-----|
| AGT-A | Data Quality Sentinel | Qualidade adaptativa de dados (substitui regras estáticas) | Pro/Elite | V2 |
| AGT-B | Odds Movement Classifier | Classifica causa da movimentação antes de enviar alerta | Pro/Elite | MVP (v. reduzida) |
| AGT-C | Adaptive Bankroll Manager | Kelly dinâmico baseado em histórico real do usuário | Elite | V2 |
| AGT-D | Market Inefficiency Hunter | Descobre ineficiências persistentes em ligas de cauda | Elite | V3 |
| AGT-E | Onboarding Coach | Acompanha trial com explicações contextuais via Telegram | Free/Pro | MVP |
| AGT-F | Performance Diagnostician | Diagnóstico narrativo do histórico de performance Elite | Elite | V2 |
| AGT-G | AIOps Remediator | Auto-remediação de incidentes operacionais | Interno | MVP (playbooks básicos) |
| AGT-H | Sharp Action Tracker | Detecta influxo de smart money via volume Betfair Exchange | Elite | V3 |

### Princípios da Camada Agêntica
1. **Agentes classificam padrões de mercado — não predizem resultados esportivos**
2. **Toda ação autônoma de agente é registrada no audit log com rastreabilidade completa**
3. **Agentes têm bounds de autonomia configuráveis por Admin — sem ação fora do escopo autorizado**
4. **O moat real é o dataset acumulado pelos agentes ao longo do tempo, não os agentes em si**

---

## Glossário de Termos de Negócio

**Value Bet**
Aposta onde as odds oferecidas pela casa implicam uma probabilidade menor do que a probabilidade real do evento. Matematicamente: `book_odds > fair_odds`. Uma value bet tem EV positivo — rentável no longo prazo.

**Expected Value (EV)**
Retorno esperado de uma aposta em relação ao stake. Calculado como:
```
ev = (book_odds / fair_odds) - 1
```
EV de +0.05 significa retorno esperado de 5% sobre o valor apostado. EV positivo não garante lucro em aposta individual — garante lucro estatístico com volume.

**Sharp Odds / Sharp Book**
Odds definidas por casas que aceitam apostadores profissionais sem limitar contas. Refletem o consenso do mercado informado. Pinnacle é o benchmark do setor.

**Implied Probability**
Probabilidade implícita nas odds de uma casa: `implied_prob = 1 / odds`. A soma das probabilidades implícitas de todos os resultados excede 100% — o excesso é o vigorish (margem da casa).

**Vigorish / Margin / Vig**
Margem embutida nas odds pela casa. Pinnacle opera com ~2–3% de margin, sendo a mais baixa do mercado. Para extrair probabilidade justa, remove-se a margin.

**Fair Odds**
Odds sem margin da casa — refletem a probabilidade real estimada pelo mercado. Calculadas a partir da Pinnacle:
```
fair_odds = 1 / (pinnacle_implied_prob / (1 - pinnacle_margin))
```

**Closing Line Value (CLV)**
Comparação entre as odds no momento do alerta e as odds de fechamento (minutos antes do evento). CLV positivo indica que o modelo identificou valor antes do mercado convergir — é a principal métrica de qualidade de longo prazo de um apostador profissional.

**Kelly Criterion**
Fórmula para sizing ótimo de stake dado o EV e a probabilidade estimada:
```
kelly_fraction = (ev * p) / (book_odds - 1)
```
Onde `p` é a probabilidade estimada. Uso de Kelly fracionado (1/4 ou 1/2 Kelly) é padrão para reduzir volatilidade.

**Arbitragem (Arb)**
Quando odds de casas diferentes cobrem todos os resultados de um evento com soma de probabilidades implícitas < 100%. Garante lucro independente do resultado. Janelas de arb fecham rapidamente (segundos a minutos).

**Pinnacle Margin**
Margem aplicada pela Pinnacle por mercado. Calculada como:
```
pinnacle_margin = 1 - (1 / sum(1/odds_i para cada resultado i))
```
Varia por esporte e liga (tipicamente 1,5%–4%).

**Snapshot de Odds**
Registro imutável do estado de odds de um mercado em um timestamp específico. Base para backtesting e auditoria.

---

## Dependências Externas e Riscos

### The Odds API ($49/mês)
- **Função:** fonte primária de odds de 40+ casas, incluindo Pinnacle como referência
- **SLA declarado:** 99,9% uptime
- **Risco principal:** mudança de estrutura de preços, remoção de Pinnacle como fonte disponível, ou aumento de preço tornando o modelo inviável
- **Mitigação:** contrato formal; monitorar changelog da API; plano de fallback com Betfair para estimativa de linha justa
- **Rate limit:** varia por plano contratado; gestão de quota obrigatória

### Betfair Exchange API (gratuita)
- **Função:** dados de volume e liquidez para validar qualidade do mercado; fonte secundária de linha de referência
- **Risco principal:** requer conta ativa na Betfair; API pode exigir credenciais com saldo; restrições geográficas
- **Mitigação:** conta de serviço dedicada; monitorar status da conta

### API-Football ($12/mês)
- **Função:** dados contextuais de partidas (odds de início, escalações, lesões) para enriquecimento de alertas
- **Risco principal:** latência de dados; cobertura incompleta de ligas menores
- **Mitigação:** dados contextuais são opcionais — alerta funciona sem eles

### AWS Lambda + DynamoDB
- **Função:** infraestrutura serverless de processamento e armazenamento
- **Risco principal:** cold starts de Lambda introduzem latência variável; custo de DynamoDB escala com volume de snapshots
- **Mitigação:** funções warm com scheduled pings; TTL em snapshots antigos; monitorar custos por alarme de billing

### Stripe
- **Função:** processamento de pagamentos e gestão de assinaturas
- **Risco principal:** mudança de preços ou termos; bloqueio de conta por atividade de gambling (apostas)
- **Mitigação:** verificar termos de uso do Stripe para SaaS relacionado a apostas; ter PayPal como alternativa

### Telegram Bot API (gratuita)
- **Função:** canal primário de entrega de alertas
- **Risco principal:** Telegram pode bloquear bot por volume excessivo de mensagens; API sem SLA formal
- **Mitigação:** respeitar rate limits (30 mensagens/segundo por bot); fallback para email em caso de bloqueio
