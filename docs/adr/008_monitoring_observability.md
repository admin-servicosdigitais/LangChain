# ADR-008: Monitoramento e Observabilidade

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** Todos os módulos, SLO tracking, on-call

## Contexto

**SLOs definidos:**
- Coleta de odds (M01): 99.5% uptime, ciclo de coleta completado em P99 < 25s
- Latência detecção→alerta Pro: P95 < 60s, P99 < 120s
- API (M04): P99 < 500ms, 99.9% availability
- Agentes LangChain: sem SLO de latência (assíncronos), mas 100% de execuções com resultado (sucesso ou fallback documentado)

**Tipos de dados de observabilidade:**
1. **Métricas**: taxa de eventos processados, latência por estágio, custo LLM por agente, DLQ depth, erros por módulo
2. **Logs**: JSON estruturado com `correlation_id`, `module`, `event_type`, `user_id`, `duration_ms`
3. **Traces**: distributed tracing de coleta→EV→alerta para debug de latência
4. **Alertas**: degradação detectada antes que SLO seja violado (alertar em 80% do orçamento de erro)
5. **Erros de aplicação**: stack traces de exceções com contexto

**Constraint:** budget de observabilidade < $100/mês para early-stage.

## Opções Consideradas

### Opção A: CloudWatch Puro (AWS Native)

**Prós:**
- Zero custo adicional de infra — Lambdas, ECS, DynamoDB e API Gateway já publicam métricas no CloudWatch
- CloudWatch Logs Insights para queries SQL-like sobre logs estruturados
- X-Ray para distributed tracing nativo em Lambda e API Gateway
- Custo: logs $0.50/GB ingestão + $0.03/GB armazenamento. Para 10GB/mês = ~$5

**Contras:**
- UI de CloudWatch é notoriamente ruim para dashboards complexos
- CloudWatch Logs Insights tem latência de query de 5-30s — não é tempo real
- Sem correlação automática entre logs de Lambda e ECS na mesma trace
- Alertas compostos requerem CloudWatch Composite Alarms — verboso

### Opção B: Datadog

**Prós:**
- UI excelente com dashboards pré-construídos para AWS
- APM com distributed tracing automático
- Log management com parsing automático de JSON

**Contras:**
- Custo: $15/host/mês + $0.10/GB logs + APM por host. Para 10 Lambdas + 2 ECS tasks: ~$150-300/mês. Acima do budget
- Agente em Lambda adiciona overhead de cold start
- Vendor lock-in severo

### Opção C: Grafana Cloud + CloudWatch + Sentry + X-Ray (Híbrido Custo-Eficiente)

**Prós:**
- Grafana Cloud Free tier: 10.000 métricas, 50GB logs, 50GB traces — suficiente para early-stage
- Grafana lê diretamente de CloudWatch via datasource plugin — sem duplicar ingestão
- Sentry Free tier (50K errors/mês) para erros de aplicação com stack trace + contexto
- AWS X-Ray para distributed tracing de Lambda+API Gateway — custo $5/million traces
- CloudWatch Alarms → SNS → Telegram canal ops para on-call
- Custo estimado: ~$20-40/mês no early-stage

**Contras:**
- 4 ferramentas de observabilidade: curva de onboarding para novos devs
- Grafana Free tier limita a 10 usuários — upgrade necessário se time crescer
- Correlação Sentry↔X-Ray manual — `correlation_id` precisa ser propagado explicitamente

## Decisão

**Escolha: Opção C — CloudWatch (métricas nativas) + Grafana Cloud + Sentry + AWS X-Ray**

O budget de $100/mês e o tamanho early-stage eliminam Datadog. CloudWatch puro teria UI inadequada para SLO tracking e correlação de traces. A combinação CloudWatch+Grafana+Sentry+X-Ray oferece cobertura completa com custo estimado de $20-40/mês.

**Logging estruturado obrigatório em todos os módulos:**
```json
{
  "timestamp": "2026-04-06T14:00:00.123Z",
  "level": "INFO",
  "correlation_id": "uuid-v4",
  "module": "M02",
  "event_type": "EV_CALCULATED",
  "event_id": "match_123",
  "ev_percentage": 7.5,
  "duration_ms": 342,
  "user_count_notified": 47
}
```

**SLO tracking via CloudWatch custom metrics:**
- `ValueBetting/M01/CollectionCycleDuration` (target P99 < 25s)
- `ValueBetting/M03/DetectionToAlertLatency` (target P95 < 60s)
- `ValueBetting/API/RequestLatency` (target P99 < 500ms)

**Alertas de degradação (80% error budget):**
- Coleta: alarm se P99 > 20s por 5 minutos consecutivos → SNS → Telegram canal ops
- Latência alerta: alarm se P95 > 48s por 3 minutos → SNS → PagerDuty/Telegram
- DLQ depth > 0 por qualquer fila → alarme imediato
- Custo LLM diário > $150 (150% do expected) → alarme para investigar loop infinito em agente

## Consequências

**Positivas:**
- CloudWatch Alarms em DLQ depth captura falhas de processamento antes que usuário perceba
- Sentry captura stack traces de erros em Lambda com context de `event` e `user_id` — debug rápido
- X-Ray trace mostra latência por segmento (coleta→SQS→EV→SQS→alerta) — identifica gargalo exato
- Grafana dashboard central consolida métricas de CloudWatch + logs — SLO em tempo real

**Negativas / Trade-offs:**
- 4 ferramentas de observabilidade aumentam onboarding de novos devs
- Grafana Free tier limita a 10 usuários — upgrade a ~$29/mês necessário com time maior
- Correlação Sentry↔X-Ray é manual — `correlation_id` propagado explicitamente

**Riscos e Mitigações:**
- Risco: Volume de logs explode com bug de loop de coleta (1M logs/hora) → Mitigação: CloudWatch Log Group com retention 30 dias; alarme em ingestão > 1GB/hora
- Risco: X-Ray sampling rate baixo perde traces de latência alta → Mitigação: Regra de sampling customizada: 100% de traces com `duration > 30s`
- Risco: Grafana Cloud Free tier esgotado antes de upgrade → Mitigação: Monitorar usage; alerta em 80% do limite mensal

## Implementação

```python
# src/shared/logging.py
import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

correlation_id_var: ContextVar[str] = ContextVar('correlation_id', default='')

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "correlation_id": correlation_id_var.get() or str(uuid.uuid4()),
            "module": getattr(record, 'module_id', 'UNKNOWN'),
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        for key in ('event_type', 'event_id', 'user_id', 'duration_ms', 'ev_percentage'):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        return json.dumps(log_entry, ensure_ascii=False)

def get_logger(module_id: str) -> logging.Logger:
    logger = logging.getLogger(module_id)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger
```

```python
# src/shared/metrics.py — CloudWatch custom metrics
import boto3
import os
from datetime import datetime, timezone

cloudwatch = boto3.client('cloudwatch')

def emit_metric(
    metric_name: str,
    value: float,
    unit: str,
    dimensions: dict[str, str],
    namespace: str = "ValueBetting"
) -> None:
    cloudwatch.put_metric_data(
        Namespace=namespace,
        MetricData=[{
            "MetricName": metric_name,
            "Value": value,
            "Unit": unit,
            "Timestamp": datetime.now(timezone.utc),
            "Dimensions": [{"Name": k, "Value": v} for k, v in dimensions.items()]
        }]
    )

# Uso no M03 — emitir latência detecção→alerta
def emit_alert_latency(detected_at: str, delivered_at: str, tier: str) -> None:
    from datetime import datetime
    delta = datetime.fromisoformat(delivered_at) - datetime.fromisoformat(detected_at)
    emit_metric(
        metric_name="DetectionToAlertLatency",
        value=delta.total_seconds() * 1000,  # milliseconds
        unit="Milliseconds",
        dimensions={"Tier": tier, "Module": "M03"}
    )
```

```python
# src/shared/sentry_config.py
import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

def init_sentry(dsn: str, environment: str) -> None:
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[AwsLambdaIntegration(timeout_warning=True)],
        traces_sample_rate=0.1,    # 10% de traces para Sentry (X-Ray faz o resto)
        profiles_sample_rate=0.05,
        before_send=_scrub_pii
    )

def _scrub_pii(event: dict, hint: dict) -> dict:
    """Remove PII antes de enviar ao Sentry — compliance LGPD."""
    if 'user' in event:
        event['user'].pop('email', None)
        event['user'].pop('ip_address', None)
    return event
```

```hcl
# Terraform — CloudWatch Alarm para latência de alerta
resource "aws_cloudwatch_metric_alarm" "alert_latency_p95" {
  alarm_name          = "alert-latency-p95-exceeded"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  threshold           = 48000  # 48s = 80% do budget de 60s

  metric_name = "DetectionToAlertLatency"
  namespace   = "ValueBetting"
  period      = 60
  statistic   = "p95"

  dimensions = {
    Tier   = "pro"
    Module = "M03"
  }

  alarm_actions = [aws_sns_topic.ops_alerts.arn]
  ok_actions    = [aws_sns_topic.ops_alerts.arn]
}
```
