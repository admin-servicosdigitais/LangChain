# ADR-009: Estratégia de Armazenamento de Dados — Hot/Cold e Archiving

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** M01 (snapshots), M02 (EV results), M05 (backtesting/histórico Elite)

## Contexto

O sistema acumula dois tipos de dados de alto volume com requisitos de retenção longos:

1. **Snapshots de odds** (M01): ~10-50 snapshots/minuto por evento, ~100-500 eventos ativos = 1.000-25.000 snapshots/hora. TTL mandatório de 13 meses.
2. **EV results** (M02): derivados dos snapshots, menor volume (~10-100 EV > 0 por hora), fundamentais para backtesting e CLV tracking.

**Requisitos de acesso:**
- **Hot path** (< 90 dias): Lambda de EV acessa snapshots das últimas 24h. Dashboard acessa alertas dos últimos 30 dias. Latência alvo: < 10ms.
- **Cold path** (91 dias - 13 meses): Backtesting Elite consulta até 12 meses. Latência aceitável: 5-60 segundos. Frequência baixa (2-10 queries/semana por usuário Elite).

**Problema de custo crítico:**
- 25.000 snapshots/hora × 24h × 365 dias × 13 = ~2.8 bilhões de items no DynamoDB
- A ~1KB/item = 2.8TB → custo de storage DynamoDB ~$700/mês
- **$700/mês é inviável para early-stage**

## Opções Consideradas

### Opção A: DynamoDB com TTL 13 meses (hot only)

**Prós:**
- Simples: TTL nativo elimina dados antigos automaticamente
- Sem pipeline de archiving

**Contras:**
- Custo de $700/mês para 13 meses de storage no DynamoDB — inaceitável
- Queries analíticas de backtesting sobre DynamoDB são caras (full table scan) e lentas
- DynamoDB não suporta queries de range com múltiplos atributos sem GSI adicional

### Opção B: DynamoDB Hot (90 dias) + S3 Parquet + Athena (cold, 91 dias–13 meses)

**Prós:**
- DynamoDB com TTL 90 dias: latência < 10ms, custo proporcional ao volume hot
- S3 Parquet comprimido (Snappy): 10-15× compressão vs. JSON raw → 2.8TB → ~200-280GB = **$6-8/mês em S3**
- Athena: $5/TB escaneado. Query de backtesting com 10GB de Parquet particionado = $0.05 por query
- Particionamento `s3://bucket/snapshots/year=2025/month=11/league_id=premier_league/` minimiza scan

**Contras:**
- Pipeline de archiving: Lambda exporta DynamoDB → S3 Parquet diariamente
- Athena tem latência de query de 5-60s — não serve para hot path
- Queries cruzam hot+cold storage: Lambda faz merge em memória quando necessário

### Opção C: Aurora (hot) + S3 Parquet + Athena (cold)

**Prós:**
- Queries analíticas nativas no Aurora para dados hot (< 90 dias)

**Contras:**
- Aurora não escala bem para 25.000 writes/hora concorrentes de Lambda (connection pool)
- Contradiz ADR-002 que define DynamoDB como hot write path para snapshots

## Decisão

**Escolha: Opção B — DynamoDB (TTL 90 dias) + S3 Parquet + Athena (cold)**

O custo de storage é o driver principal. S3 Parquet a $6-8/mês para 13 meses vs. $700/mês em DynamoDB é decisão inequívoca. O pipeline de archiving é um Lambda daily simples.

**Particionamento do Parquet:**
```
s3://value-betting-cold-storage/
├── odds_snapshots/
│   └── year=2025/month=11/league_id=premier_league/
│       └── snapshot_20251101.parquet
├── ev_results/
│   └── year=2025/month=11/
│       └── ev_20251101.parquet
└── alert_history/
    └── year=2025/month=11/user_id_prefix=a/
        └── alerts_20251101.parquet
```

**Job de archiving** (Lambda, executa daily às 02:00 UTC):
1. Query DynamoDB para items com `created_at` entre D-91 e D-92
2. Converte para Pandas DataFrame
3. Escreve como Parquet com Snappy compression
4. Upload para S3 com partição correta
5. Confirma S3 antes de finalizar (TTL DynamoDB faz cleanup gradual como safety net)

**Custo de Athena estimado para 1000 Elite users:**
- 5000 queries/semana × Query média escaneando 5GB = $0.025/query
- Com Result Caching (TTL 24h): 80% das queries são cache hits → custo realista ~$50-100/mês

**Proteção de custo:** `bytes_scanned_cutoff_per_query = 10GB` no Athena Workgroup + rate limiting de 10 queries/hora por Elite user via API.

## Consequências

**Positivas:**
- Custo de storage cold reduzido de $700/mês para $6-8/mês (97% de economia)
- Athena queries para backtesting Elite são ad-hoc, sem provisionamento de capacidade analítica
- Particionamento por `league_id` e data permite que queries escaneiem apenas a liga monitorada
- DynamoDB TTL 90 dias limpa hot data automaticamente — zero manutenção

**Negativas / Trade-offs:**
- Latência de Athena (5-60s) impede uso em real-time dashboard — hot path sempre vai ao DynamoDB
- Pipeline de archiving daily é ponto de falha adicional — DLQ e alarme CloudWatch necessários
- Colunar Parquet requer conversão de schema: Pandas/PyArrow adiciona dependência ao job de archiving

**Riscos e Mitigações:**
- Risco: Job de archiving falha silenciosamente e dados são removidos pelo TTL sem estar no S3 → Mitigação: Archiving verifica S3 antes de considerar sucesso; alarme CloudWatch se S3 prefix não recebeu novos arquivos em 26h
- Risco: Custo de Athena excede $100/mês por uso abusivo → Mitigação: Workgroup com `bytes_scanned_cutoff_per_query = 10GB`; rate limiting de queries backtesting via API (10 queries/hora por Elite user)
- Risco: Parquet schema evolution (novo campo em `ev_results`) quebra queries antigas → Mitigação: Glue Schema Registry com evolução compatível (adicionar colunas nullable); versionar schema no nome do arquivo

## Implementação

```python
# src/jobs/archiving/daily_archive.py
import boto3
import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, timedelta, timezone
from io import BytesIO

logger = get_logger("M05-ARCHIVING")

def archive_daily(event: dict, context) -> dict:
    archive_date = datetime.now(timezone.utc).date() - timedelta(days=91)

    items = _scan_dynamodb_by_date("odds_snapshots", archive_date)
    if not items:
        logger.info("Nenhum item para arquivar", extra={"date": str(archive_date)})
        return {"archived": 0}

    df = pd.DataFrame(items)
    df['snapshot_ts'] = pd.to_datetime(df['snapshot_ts'])

    table = pa.Table.from_pandas(df, preserve_index=False)
    s3_key = (
        f"odds_snapshots/"
        f"year={archive_date.year}/"
        f"month={archive_date.month:02d}/"
        f"snapshot_{archive_date.isoformat()}.parquet"
    )

    buffer = BytesIO()
    pq.write_table(table, buffer, compression='snappy')
    buffer.seek(0)

    s3 = boto3.client('s3')
    s3.put_object(
        Bucket=os.environ['COLD_STORAGE_BUCKET'],
        Key=s3_key,
        Body=buffer.read(),
        ContentType='application/octet-stream'
    )

    # Confirmar S3 antes de reportar sucesso
    s3.head_object(Bucket=os.environ['COLD_STORAGE_BUCKET'], Key=s3_key)

    logger.info("Archiving concluído", extra={"archived": len(items), "s3_key": s3_key})
    return {"archived": len(items), "s3_key": s3_key}


def _scan_dynamodb_by_date(table_name: str, date) -> list[dict]:
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)
    start = datetime.combine(date, datetime.min.time()).isoformat()
    end = datetime.combine(date + timedelta(days=1), datetime.min.time()).isoformat()

    items = []
    kwargs = {
        "FilterExpression": "created_at BETWEEN :start AND :end",
        "ExpressionAttributeValues": {":start": start, ":end": end}
    }
    while True:
        response = table.scan(**kwargs)
        items.extend(response['Items'])
        if 'LastEvaluatedKey' not in response:
            break
        kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    return items
```

```sql
-- Athena query de backtesting Elite (executada via API, não pelo usuário diretamente)
-- Custo estimado: ~$0.05 por query com particionamento correto
SELECT
    DATE_TRUNC('week', detected_at) AS week,
    league_id,
    bookmaker,
    COUNT(*) AS total_bets,
    AVG(ev_percentage) AS avg_ev,
    AVG(closing_pinnacle_odds / book_odds - 1) AS avg_clv,
    SUM(CASE WHEN actual_result = 'win' THEN stake ELSE -stake END) AS total_pnl
FROM ev_results
WHERE
    year BETWEEN :start_year AND :end_year
    AND month BETWEEN :start_month AND :end_month
    AND user_id = :user_id
GROUP BY 1, 2, 3
ORDER BY 1 DESC;
```

```hcl
# Terraform — Athena Workgroup com proteção de custo
resource "aws_athena_workgroup" "backtesting" {
  name = "value-betting-backtesting"

  configuration {
    bytes_scanned_cutoff_per_query     = 10737418240  # 10GB
    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.bucket}/results/"
    }
    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
  }
}
```
