# ADR-003: Estratégia de Mensageria — SQS vs. EventBridge vs. Kafka

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** M01→M02→M03 (pipeline principal), M04 (eventos de billing), M05 (resultado de apostas), Agentes (consumo de eventos)

## Contexto

O sistema tem dois tipos distintos de eventos com requisitos opostos:

1. **Hot path** (M01→M02→M03): `OddsMovementDetected` e `AlertReady` são processados com SLA de 60s total. Latência de mensageria deve ser < 500ms. Volume: 1.000-25.000 msgs/hora em pico.
2. **Eventos de negócio** (M04, M05): `UserUpgraded`, `UserDowngraded`, `BetResultRecorded`, `SubscriptionCancelled`. Baixa frequência (dezenas/hora), mas requerem fan-out para múltiplos consumers.
3. **Delay obrigatório Free** (M03): alertas Free precisam de delay exato de 30 minutos. SQS `DelaySeconds` máximo é 900s (15min) — insuficiente para 1800s.

## Opções Consideradas

### Opção A: SQS Puro

**Prós:**
- Latência < 100ms de ingestão e < 500ms de entrega para Lambda
- SQS FIFO: deduplication via `MessageDeduplicationId`, ordering por `MessageGroupId`
- Sem overhead de roteamento — publisher envia diretamente para a fila do consumer
- DLQ nativa com `maxReceiveCount` configurável
- Custo: $0.40/million messages (Standard), $0.50/million (FIFO)

**Contras:**
- Sem fan-out nativo: para múltiplos consumers de um mesmo evento, precisaria de SNS + SQS fan-out
- `DelaySeconds` máximo de 900s — insuficiente para delay de 1800s dos usuários Free
- Sem Archive/Replay nativo — eventos perdidos em DLQ são o único mecanismo de recovery

### Opção B: EventBridge Puro

**Prós:**
- Fan-out nativo: um evento → múltiplas rules → múltiplos targets
- Archive e Replay: reprocessar eventos históricos sem código
- Schema Registry para validação de payload
- Integração com 300+ serviços AWS sem código de integração

**Contras:**
- Latência: típico 0.5-2s de overhead adicional vs. SQS direto
- Sem delay queue nativa — ainda precisa de SQS com visibility timeout para delay de 30min
- Custo: $1.00/million eventos (2.5× mais caro que SQS Standard)
- Ordering não garantido
- Para alta frequência (OddsMovementDetected), o overhead pode comprometer SLA de 60s

### Opção C: MSK (Managed Kafka)

**Prós:**
- Ordering por partition garantido
- Retention configurável
- Consumer groups para múltiplos consumers independentes
- Throughput massivo (> 100K msgs/s)

**Contras:**
- Custo mínimo: ~$150/mês para cluster MSK mínimo (3 brokers m5.large) — inviável para early-stage
- Complexidade operacional desproporcional para o volume atual (< 100 msgs/s em pico)
- Over-engineered para o problema

### Opção D: Híbrido SQS + EventBridge + Step Functions

**Prós:**
- SQS FIFO para hot path: latência mínima, deduplication via `MessageDeduplicationId`
- EventBridge para eventos de negócio de baixa frequência: fan-out simples, Archive para auditoria
- Step Functions Standard para delay exato de 1800s Free (suporta waits de horas)
- DLQ dedicada por fila com alarme CloudWatch

**Contras:**
- Três sistemas de mensageria para monitorar
- Step Functions Standard tem latência mínima de ~1s por state — aceitável para Free (delay já é 30min)

## Decisão

**Escolha: Opção D — Híbrido SQS FIFO (hot path) + EventBridge (eventos de negócio) + Step Functions (delay Free)**

O constraint de 60s elimina EventBridge do hot path (overhead de 0.5-2s inaceitável). SQS FIFO com `MessageGroupId=event_id` garante ordering por evento e deduplication via `MessageDeduplicationId=hash(event_id+snapshot_ts+source)`.

Para o delay de 1800s Free: Step Functions Standard com Wait State de exatamente 1800 segundos é auditável, ressiliente (estado persiste entre falhas) e custo negligível ($0.025/1000 execuções = ~$1/mês para 1000 Free users ativos).

**Arquitetura de filas:**
- `odds-movement-fifo.fifo` → Lambda M02 EV Calculator (batch=10, concurrency=5)
- `alert-ready-pro-elite.fifo` → Lambda M03 Alert Dispatcher (batch=1, concurrency=20)
- `alert-ready-free-delayed` → Step Functions Standard (Wait 1800s) → Lambda M03 Alert Dispatcher
- `agent-tasks-standard` → Lambda intermediária → ECS RunTask (para agentes assíncronos)
- `dlq-*` — uma DLQ por fila, maxReceiveCount=3

**EventBridge:**
- Bus `value-betting-business`: UserUpgraded, UserDowngraded, BetResultRecorded, SubscriptionCancelled
- Rule: `UserUpgraded` → Lambda `update-user-permissions` + Lambda `invalidate-refresh-tokens`
- Rule: `BetResultRecorded` → Lambda `update-clv-tracking` (alimenta AGT-C e AGT-F)

## Consequências

**Positivas:**
- Hot path SQS FIFO com latência < 500ms de mensageria — SLA de 60s preservado com margem
- Deduplication de `OddsMovementDetected` via FIFO elimina processamento duplo de snapshots
- EventBridge Archive permite replay de `UserUpgraded` em caso de falha de Lambda
- Step Functions provê audit trail do delay Free — `detected_at` e `delivered_at` auditáveis
- DLQ por fila com alarme CloudWatch garante visibilidade de falhas antes que usuário perceba

**Negativas / Trade-offs:**
- Três sistemas de mensageria aumentam superfície de monitoring (CloudWatch separado por serviço)
- FIFO tem throughput de 3.000 msg/s — suficiente até ~50M snapshots/dia; monitorar se escala
- Step Functions Standard tem custo de $0.025/1000 execuções (negligível mas não zero)

**Riscos e Mitigações:**
- Risco: Lambda M02 perde mensagem SQS por timeout (> 25s budget) → Mitigação: Visibility timeout = 60s; após 3 falhas vai para DLQ com alarme imediato
- Risco: Step Functions para delay Free tem execuções acumuladas sem retry em falha → Mitigação: Step Functions Standard com `Retry` em cada state e `Catch` para notificar DLQ
- Risco: `MessageDeduplicationId` collision entre eventos legítimos distintos → Mitigação: hash inclui `book_odds_hash` além de `event_id` e `snapshot_ts`, tornando collision matematicamente improvável

## Implementação

```python
# Lambda M02 — publicar em SQS por tier do usuário
import hashlib, json, os, boto3
from typing import Any

sqs = boto3.client('sqs')
sfn = boto3.client('stepfunctions')

def publish_alert(ev_result: dict[str, Any], user: dict[str, Any]) -> None:
    dedup_id = hashlib.sha256(
        f"{ev_result['event_id']}#{ev_result['snapshot_ts']}#{user['user_id']}".encode()
    ).hexdigest()[:128]

    if user['tier'] in ('pro', 'elite'):
        sqs.send_message(
            QueueUrl=os.environ['ALERT_PRO_ELITE_QUEUE_URL'],
            MessageBody=json.dumps(ev_result),
            MessageGroupId=ev_result['event_id'],
            MessageDeduplicationId=dedup_id
        )
    else:  # free tier — Step Functions com Wait de 30min
        sfn.start_execution(
            stateMachineArn=os.environ['FREE_DELAY_SFN_ARN'],
            name=dedup_id,  # idempotency key
            input=json.dumps({
                'wait_seconds': 1800,
                'alert_payload': ev_result,
                'user_id': user['user_id'],
                'detected_at': ev_result['detected_at']
            })
        )
```

```json
{
  "Comment": "Delay de 30 minutos obrigatório para tier Free",
  "StartAt": "ValidateNotExpired",
  "States": {
    "ValidateNotExpired": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:check-alert-expiry",
      "Next": "Wait30Min",
      "Catch": [{"ErrorEquals": ["AlertExpired"], "Next": "DiscardExpired"}]
    },
    "Wait30Min": {
      "Type": "Wait",
      "Seconds": 1800,
      "Next": "ValidateStillValid"
    },
    "ValidateStillValid": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:check-alert-expiry",
      "Next": "DeliverAlert",
      "Catch": [{"ErrorEquals": ["AlertExpired"], "Next": "DiscardExpired"}]
    },
    "DeliverAlert": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:alert-dispatcher",
      "End": true
    },
    "DiscardExpired": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:log-expired-alert",
      "End": true
    }
  }
}
```

```python
# Publicar evento de negócio no EventBridge
def publish_user_upgraded(user_id: str, old_tier: str, new_tier: str) -> None:
    events = boto3.client('events')
    events.put_events(Entries=[{
        'Source': 'value-betting.subscriptions',
        'DetailType': 'UserUpgraded',
        'Detail': json.dumps({
            'user_id': user_id,
            'old_tier': old_tier,
            'new_tier': new_tier,
            'upgraded_at': datetime.now(timezone.utc).isoformat()
        }),
        'EventBusName': os.environ['BUSINESS_EVENT_BUS_NAME']
    }])
```
