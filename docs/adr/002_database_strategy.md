# ADR-002: Banco de Dados — DynamoDB vs. PostgreSQL vs. Híbrido

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** M01 (snapshots), M02 (EV results), M04 (usuários/billing), M05 (histórico), M06 (audit log)

## Contexto

O sistema tem cinco padrões de acesso distintos com requisitos conflitantes:

1. **Snapshots de odds** (M01): append-only, 2-4 writes/segundo em pico, nunca atualizados, TTL 13 meses, acesso por `event_id + timestamp`
2. **Usuários e subscriptions** (M04): relacional (user → subscription → tier → features), consistência forte necessária, < 100 writes/segundo
3. **Audit log** (M06): imutável, append-only, nunca DELETE/UPDATE, consultas ad-hoc por admin, retenção 24 meses
4. **Resultados EV** (M02): alta escrita durante janela de apostas, leitura para dashboard, TTL 90 dias hot / 13 meses cold
5. **Backtesting/Histórico** (M05): queries analíticas (GROUP BY league, data range, EV threshold), baixa frequência mas alta cardinalidade

O constraint mais crítico: snapshot da Pinnacle é campo separado obrigatório. Sem snapshot da Pinnacle, o registro de EV não pode ser criado. Esta invariante precisa ser enforced no nível de dados.

## Opções Consideradas

### Opção A: DynamoDB Puro

**Prós:**
- Escala automática de throughput sem capacity planning
- Latência single-digit ms em P99 para reads/writes por PK
- TTL nativo sem jobs de limpeza
- Serverless — sem instância gerenciada
- Streams para event-driven (DynamoDB Streams → Lambda)

**Contras:**
- Sem joins — dados relacionais requerem desnormalização ou multiple round-trips
- Queries analíticas (backtesting com filtros complexos) requerem GSI ou full scan caro
- Transações distribuídas limitadas (máx 100 itens por TransactWrite)
- Modelo de dados de usuários/subscriptions com relacionamentos bidirecionais é anti-pattern
- Sem constraint de integridade referencial: impossível enforçar "sem Pinnacle, sem EV" no DB layer
- Custo de GSI por write: cada GSI adiciona custo equivalente ao da tabela principal

### Opção B: PostgreSQL (Aurora Serverless v2)

**Prós:**
- Modelo relacional nativo: FK constraints, transações ACID, CHECK constraints
- `CHECK (pinnacle_fair_odds IS NOT NULL)` enforça invariante de Pinnacle no DB layer
- Queries analíticas com WINDOW functions, CTEs, índices parciais
- Aurora Serverless v2 escala de 0.5 ACU (idle ~$0.06/hora) a 128 ACU sem restart
- JSONB para campos semi-estruturados (odds de múltiplos bookmakers)

**Contras:**
- Aurora Serverless v2 nunca escala para zero (mínimo 0.5 ACU = ~$43/mês)
- Cold start de conexão em Lambda: connection pooling via RDS Proxy adiciona $0.015/hora (~$11/mês)
- Escrita de snapshots (2-4/s com spikes de 20/s) pode saturar conexões em Lambda concorrente

### Opção C: Híbrido — DynamoDB (hot write path) + Aurora Serverless v2 (relacional/analítico)

**Prós:**
- DynamoDB absorve o write path de alta frequência (snapshots, EV results, audit log)
- Aurora Serverless v2 para dados relacionais onde consistência e joins são necessários
- S3 Parquet + Athena para queries analíticas do backtesting (ver ADR-009)
- Cada banco otimizado para seu padrão de acesso

**Contras:**
- Dois bancos para operar, monitorar e fazer backup
- Eventual consistency entre sistemas: usuário pode ter subscription no Aurora mas dados de alert throttle no DynamoDB desatualizados por milissegundos
- Migrations de schema mais complexas (Alembic para Aurora, sem migration para DynamoDB)

## Decisão

**Escolha: Opção C — Híbrido DynamoDB + Aurora Serverless v2**

O padrão de acesso diverge demais para um único banco servir bem. Snapshots de odds têm throughput imprevisível (Copa do Mundo = 10× tráfego normal) — DynamoDB absorve isso sem capacity planning. Dados de usuários têm relacionamentos bidirecionais onde FK constraints e transações ACID previnem estados inválidos.

A invariante "sem Pinnacle, sem EV" é implementada via `NOT NULL CONSTRAINT` no Aurora para a tabela `ev_results` e via validação de schema no código Lambda para DynamoDB (snapshots).

RDS Proxy reduz connection overhead de Lambda para Aurora de 50-200ms para 1-5ms em conexões já aquecidas.

**Modelo de tabelas:**

**DynamoDB** — 3 tabelas:
- `odds_snapshots`: PK=`event_id`, SK=`snapshot_ts#source`. TTL=`expires_at`. GSI: `source-ts-index`
- `audit_log`: PK=`entity_type#entity_id`, SK=`timestamp#uuid`. TTL=`expires_at` (24 meses). IAM Deny para UPDATE/DELETE
- `alert_delivery_log`: PK=`user_id`, SK=`alert_id#ts`. TTL 90 dias. Para anti-duplicatas e throttling

**Aurora Serverless v2 (PostgreSQL 16)** — schema `value_betting`:
- `users`, `subscriptions`, `stripe_events`, `api_keys`, `webhook_configs`
- `ev_results`: com `pinnacle_fair_odds DECIMAL(10,4) NOT NULL`, particionada por mês

## Consequências

**Positivas:**
- DynamoDB elimina connection pooling no hot write path — Lambda de coleta escala sem saturar conexões
- Aurora enforça integridade relacional com FK e CHECK constraints — estados inválidos impossíveis no DB layer
- TTL nativo do DynamoDB para snapshots e audit log — zero custo operacional de cleanup
- Aurora Serverless v2 escala automaticamente em picos de queries analíticas

**Negativas / Trade-offs:**
- Custo fixo de Aurora mínimo ~$54/mês (0.5 ACU + RDS Proxy) mesmo em idle
- Dois sistemas de migration: Alembic para Aurora, IaC para DynamoDB schema
- Monitoramento separado: DynamoDB CloudWatch metrics + Aurora Performance Insights

**Riscos e Mitigações:**
- Risco: Aurora Serverless v2 cold start (0.5→2 ACU) adiciona latência em pico inesperado → Mitigação: min_capacity=1 ACU em horário de pico (18h-02h UTC via scheduled scaling)
- Risco: DynamoDB audit_log editável via Console AWS → Mitigação: IAM policy com Deny explícito para `dynamodb:DeleteItem` e `dynamodb:UpdateItem` na tabela `audit_log` para todos os roles exceto root
- Risco: Aurora sem dados de odds correlacionados com DynamoDB → Mitigação: `event_id` como chave compartilhada; joins são feitos em memória na Lambda quando necessário

## Implementação

```sql
-- Aurora PostgreSQL 16 — tabela ev_results com invariante Pinnacle
CREATE TABLE ev_results (
    alert_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id           VARCHAR(255) NOT NULL,
    market_type        VARCHAR(50) NOT NULL,
    bookmaker_id       VARCHAR(100) NOT NULL,
    outcome            VARCHAR(50) NOT NULL,
    book_odds          DECIMAL(10, 4) NOT NULL CHECK (book_odds > 1.0),
    pinnacle_fair_odds DECIMAL(10, 4) NOT NULL,  -- NOT NULL enforça invariante
    ev_percentage      DECIMAL(10, 4) NOT NULL,
    detected_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alert_sent         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (detected_at);

CREATE INDEX idx_ev_results_event ON ev_results (event_id, detected_at);
CREATE INDEX idx_ev_results_user_alert ON ev_results (alert_sent, detected_at);
```

```python
# DynamoDB — odds_snapshots schema (enforçado no código, não no banco)
from pydantic import BaseModel, field_validator
from decimal import Decimal

class OddsSnapshot(BaseModel):
    event_id: str
    snapshot_ts: str          # ISO 8601 UTC
    source: str               # the_odds_api | betfair
    bookmaker_id: str
    pinnacle_odds: dict       # {'home': Decimal, 'draw': Decimal, 'away': Decimal}
    pinnacle_margin: Decimal
    book_odds: dict | None = None
    exchange_volume_usd: Decimal | None = None
    expires_at: int           # Unix timestamp para DynamoDB TTL

    @field_validator('pinnacle_odds')
    @classmethod
    def pinnacle_required(cls, v):
        if not v:
            raise ValueError('pinnacle_odds é obrigatório — sem Pinnacle, sem snapshot válido')
        return v
```

```hcl
# Terraform — IAM Deny para audit_log
resource "aws_iam_policy" "audit_log_immutable" {
  name = "audit-log-immutable"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Deny"
      Action   = ["dynamodb:DeleteItem", "dynamodb:UpdateItem"]
      Resource = aws_dynamodb_table.audit_log.arn
    }]
  })
}
```
