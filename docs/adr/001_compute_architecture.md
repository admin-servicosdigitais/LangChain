# ADR-001: Arquitetura de Compute — Serverless vs. Container vs. VM

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** M01 (Coleta de Odds), M02 (Cálculo de EV), M03 (Entrega de Alertas), M06 (Admin/Ops)

## Contexto

O pipeline crítico do sistema executa três jobs sequenciais com SLAs duros: coleta de odds (polling 30-60s), cálculo de EV (< 20s), e entrega de alertas (detecção→alerta Pro < 60s no total). O sistema precisa escalar de zero a pico em eventos esportivos (fins de semana, Champions League) e cair para custo próximo de zero em idle.

Forças em jogo:
- Cold starts de Lambda em Python com dependências pesadas (LangChain, pandas) podem ser 2-8 segundos
- O budget de tempo total detecção→alerta é 60s — cada segundo conta
- Agentes LangChain têm dependências grandes (~200MB+) incompatíveis com o limite de 250MB de Lambda sem Container Images
- ECS Fargate tem latência de scale-up de 30-90s (nova task), inviável para resposta a eventos pontuais
- EC2 paga ociosa 24/7, inadequado para workload esporádico
- Os agentes LangChain são jobs assíncronos batch — não precisam de latência sub-segundo

## Opções Consideradas

### Opção A: AWS Lambda Puro

**Prós:**
- Custo zero em idle; billing por 100ms de execução
- Escala automática sem configuração de auto-scaling
- Deploy simples via Container Image (até 10GB)
- Provisioned Concurrency elimina cold starts para funções críticas (~$0.015/GB-hora)
- Integração nativa com SQS, EventBridge, DynamoDB Streams

**Contras:**
- Cold starts Python + dependências: 1.5-4s sem Provisioned Concurrency
- Limite de 15 minutos de execução (AGT-D e AGT-H podem exceder em análises batch)
- Agentes LangChain com múltiplos LLM calls podem exceder 15min

### Opção B: ECS Fargate (Containers Managed)

**Prós:**
- Sem limite de tempo de execução — ideal para agentes LangChain batch
- Controle total sobre dependências Python sem gestão de Layers
- Debugging com ECS Exec e logging estruturado nativo

**Contras:**
- Task startup: 30-90 segundos — inviável para resposta a SQS no hot path
- Custo mínimo mesmo com task count 0 não existe — tarefas precisam estar rodando para processar
- Para polling de 30-60s, precisaria de tasks persistentes (quasi-EC2 em custo)

### Opção C: Híbrido — Lambda para Pipeline Crítico + ECS Fargate para Agentes LangChain

**Prós:**
- Lambda para coleta (M01), EV (M02), alertas (M03): latência controlada com Provisioned Concurrency
- ECS Fargate para agentes assíncronos: sem limite de 15 min, dependências ilimitadas
- Provisioned Concurrency apenas para Lambda de entrega de alertas (hot path Pro/Elite)
- Agentes schedulados via EventBridge Scheduler → ECS RunTask API (spin-up sob demanda)
- Custo otimizado: Lambda billing por invocação, Fargate billing apenas quando agente executa

**Contras:**
- Dois compute paradigms para operar e monitorar
- Pipeline de deploy separado para Lambda (Terraform) e ECS (task definitions)
- Container images para agentes precisam ser buildadas e publicadas no ECR

## Decisão

**Escolha: Opção C — Híbrido Lambda Container Images + ECS Fargate**

O constraint de 60s detecção→alerta elimina ECS Fargate do hot path (startup 30-90s). Lambda com Container Image resolve o problema de dependências pesadas — LangChain cabe numa imagem de ~400MB, dentro do limite de 10GB. Provisioned Concurrency em 2 instâncias da Lambda de alertas custa ~$8/mês e elimina completamente o cold start no caminho Pro/Elite.

Para os agentes LangChain assíncronos, ECS Fargate via RunTask é superior: AGT-D e AGT-H são análises batch que podem levar 5-20 minutos, e AGT-G (AIOps Remediator) precisa executar múltiplos playbooks em série. O modelo EventBridge Scheduler → ECS RunTask garante que tasks só pagam quando executam (billing por segundo no Fargate).

**Estimativa de custo mensal para 500 usuários:**
- Lambda coleta M01: ~2M invocações/mês + compute ~$15
- Lambda EV M02: ~2M invocações + compute ~$10
- Lambda alertas M03 (Provisioned Concurrency 2 instâncias, 512MB): ~$16/mês
- ECS Fargate agentes (8 agentes × média 1h/dia): 0.25 vCPU × 0.5GB × 8h/mês × $0.04/vCPU-hora = ~$3/mês
- **Total compute: ~$45/mês**

## Consequências

**Positivas:**
- Hot path com latência controlada e custo pago por uso
- Agentes LangChain sem constraint de 15 minutos, com ambiente Python completo
- Lambda escala automaticamente em picos — sem configuração adicional
- Provisioned Concurrency garante SLA de 60s mesmo com spike de novos alertas

**Negativas / Trade-offs:**
- Dois paradigmas de deploy: Lambda via Terraform + ECS via Task Definitions
- Monitoramento distribuído: CloudWatch Logs de Lambda + ECS diferem em estrutura
- Container images para Lambda precisam de ECR e pipeline de build Docker

**Riscos e Mitigações:**
- Risco: Cold start de Lambda de alertas excede budget de 60s durante spike → Mitigação: Provisioned Concurrency em 2 instâncias permanentes; CloudWatch Alarm em p99 > 45s dispara aumento via Application Auto Scaling
- Risco: Lambda de coleta (M01) excede 25s em ciclo pesado com 10+ ligas → Mitigação: Paralelismo por liga via SQS fan-out; cada Lambda coleta 1-3 ligas por invocação
- Risco: ECS Fargate task startup 90s para AGT-G durante incidente → Mitigação: AGT-G mantém 1 Fargate task em standby durante horário de pico (18h-02h UTC), custo ~$5/mês

## Implementação

```
infrastructure/
├── modules/
│   ├── lambda-function/          # M01, M02, M03, API como Lambda Container Images
│   │   ├── main.tf               # ECR, Lambda, IAM, LogGroup, Alias, Provisioned Concurrency
│   │   ├── variables.tf
│   │   └── outputs.tf
│   └── ecs-agent/                # AGT-A até AGT-H como ECS Tasks
│       ├── main.tf               # Task Definition, IAM, EventBridge Schedule
│       ├── variables.tf
│       └── outputs.tf
```

```hcl
# Terraform — Provisioned Concurrency para Lambda crítica
resource "aws_lambda_provisioned_concurrency_config" "alert_dispatcher" {
  function_name                  = aws_lambda_function.alert_dispatcher.function_name
  qualifier                      = aws_lambda_alias.alert_dispatcher_live.name
  provisioned_concurrent_executions = 2
}
```

Lambda de coleta usa SQS trigger com `batch_size=1` e `maximum_concurrency=10` para paralelismo controlado por liga. EventBridge Scheduler para agentes: AGT-B a cada 5 minutos durante horário de pico, AGT-D diariamente às 03:00 UTC, AGT-F semanalmente aos domingos 04:00 UTC.
