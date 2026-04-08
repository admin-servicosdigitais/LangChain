# Módulo Administrativo e Operacional

## Contexto de Negócio

O módulo admin é a cabine de controle do SaaS. Com infraestrutura serverless e um time pequeno, a capacidade de observar e intervir no sistema sem deploy é crítica. Problemas de dados corrompidos, jobs travados ou usuários com billing incorreto precisam ser resolvidos em minutos, não horas.

O painel admin também é a fonte de verdade para decisões de produto: MRR, conversão Free→Pro, ligas com maior engajamento — dados que informam roadmap e pricing.

---

## Atores

- **Admin operacional:** monitora saúde do sistema, responde a incidentes, gerencia usuários
- **Admin produto/negócio:** analisa métricas, configura parâmetros de produto
- **Sistema (jobs automáticos):** gera alertas internos, escreve audit logs
- **Slack/Telegram admin channel:** canal de recebimento de alertas críticos do sistema

---

## Requisitos Funcionais

### RF-ADM-001 — Painel de Saúde do Sistema
**Descrição:** Dashboard em tempo real com status de todos os componentes críticos do pipeline.
**Prioridade:** Must
**Critério de aceite:**
Componentes monitorados e status esperado:

| Componente | Métrica principal | Threshold de alerta |
|---|---|---|
| Job de coleta de odds | Última execução bem-sucedida | > 2 minutos sem execução |
| Job de cálculo de EV | Última execução bem-sucedida | > 2 minutos sem execução |
| Fila de alertas (SQS) | Profundidade da fila | > 500 mensagens em espera |
| Entrega de alertas | Taxa de falha de entrega | > 5% em 15 minutos |
| The Odds API | Status de conectividade | Falha em qualquer requisição |
| DynamoDB | Erros de write/read | Qualquer erro em produção |
| Latência ponta a ponta | Detecção → entrega Pro | > 90 segundos |

- Dashboard atualizado a cada 30 segundos (polling do frontend)
- Cada componente tem indicador visual: verde (ok), amarelo (degradado), vermelho (falha)
- Clique em componente exibe últimos 10 eventos de log daquele componente
- Horário do último check e status exibidos para cada componente

### RF-ADM-002 — Alertas Internos para Falhas Críticas
**Descrição:** Falhas críticas devem gerar notificações automáticas para o time de operações via Slack e/ou Telegram admin.
**Prioridade:** Must
**Critério de aceite:**
Eventos que disparam alerta crítico imediato:
- Job de coleta falhou por 3 execuções consecutivas
- The Odds API retornou erro 5xx por > 5 minutos
- Taxa de falha de entrega de alertas > 10% em 15 minutos
- DynamoDB retornou erro de capacidade (ProvisionedThroughputExceededException)
- Quota de The Odds API atingiu 95%
- Mais de 100 contas com billing em estado `past_due` simultaneamente
- Lambda de EV com erro não tratado (exceção não capturada)

Formato do alerta interno:
```
[CRÍTICO] <componente>: <descrição do problema>
Horário: HH:mm UTC
Impacto estimado: <N usuários afetados | pipeline parado>
Runbook: <link para procedimento de recuperação>
```
- Canal Telegram admin: grupo dedicado (não o canal de usuários)
- Canal Slack: webhook configurado por variável de ambiente
- Alertas não se repetem para o mesmo evento em janela de 15 minutos (anti-flood)

### RF-ADM-003 — Gestão de Usuários
**Descrição:** Interface de busca e edição manual de contas de usuário para casos de suporte e edge cases de billing.
**Prioridade:** Must
**Critério de aceite:**
- Busca por: email, user_id, telegram_chat_id
- Campos exibidos no perfil: tier atual, data de criação, data de próxima cobrança, status Stripe, alertas recebidos (count), último acesso
- Ações disponíveis:
  - **Alterar tier manualmente:** com campo obrigatório "motivo" (auditado)
  - **Suspender conta:** bloqueia login e entrega de alertas; campo motivo obrigatório
  - **Reativar conta suspensa**
  - **Forçar downgrade/upgrade sem cobrança:** para correções e compensações
  - **Resetar vinculação Telegram:** desvincula `telegram_chat_id` (para casos de Telegram trocado)
  - **Regenerar API key Elite**
  - **Visualizar histórico de assinaturas Stripe** (link direto para dashboard Stripe)
- Ação de alterar tier aciona mesmo fluxo de webhook que o Stripe acionaria (para garantir consistência de estado)

### RF-ADM-004 — Configuração de Parâmetros do Sistema
**Descrição:** Parâmetros operacionais do pipeline devem ser configuráveis pelo Admin sem necessidade de deploy.
**Prioridade:** Must
**Critério de aceite:**
Parâmetros configuráveis em runtime (armazenados em DynamoDB, lidos no início de cada Lambda):

| Parâmetro | Tipo | Valor padrão |
|---|---|---|
| `polling_interval_24h_sec` | int | 30 |
| `polling_interval_72h_sec` | int | 300 |
| `ev_threshold_default` | Decimal | 0.03 |
| `ev_threshold_free` | Decimal | 0.05 |
| `dedup_window_minutes` | int | 60 |
| `min_liquidity_betfair_usd` | int | 10000 |
| `max_pinnacle_margin` | Decimal | 0.08 |
| `alert_free_delay_seconds` | int | 1800 |
| `leagues_enabled` | JSON array | [lista de ligas] |
| `bookmakers_excluded` | JSON array | [] |
| `suspicious_ev_threshold` | Decimal | 0.25 |

- Mudança de parâmetro é efetiva na próxima execução do Lambda (sem necessidade de restart)
- Histórico de mudanças de parâmetros no audit log com valor anterior e novo
- Validação de range: Admin não pode configurar `ev_threshold_default < 0.01` ou `polling_interval_24h_sec < 15`

### RF-ADM-005 — Gestão de Ligas Habilitadas
**Descrição:** Admin pode habilitar/desabilitar ligas e configurar qual tier tem acesso a cada liga.
**Prioridade:** Must
**Critério de aceite:**
- Interface lista todas as ligas disponíveis na The Odds API com status `active: boolean`
- Para cada liga: `tier_required` (free | pro | elite), `sport`, `country`, `collection_priority` (high | medium | low)
- Mudança de status da liga é efetiva imediatamente para novas coletas
- Desabilitar liga: alertas pendentes daquela liga são cancelados e descartados
- Admin pode definir a liga gratuita padrão (a 1 liga disponível para Free)
- Relatório de ligas: última coleta bem-sucedida, número de mercados coletados nas últimas 24h, custo estimado de quota por liga

### RF-ADM-006 — Métricas de Negócio
**Descrição:** Dashboard com KPIs de negócio para tomada de decisão de produto e receita.
**Prioridade:** Must
**Critério de aceite:**
Métricas em tempo real:
- MRR (Monthly Recurring Revenue): `(Pro_ativos × $29) + (Elite_ativos × $79)`
- Distribuição de usuários por tier (count e % do total)
- Usuários em trial ativo e data de expiração dos trials
- Contas em `past_due` (em risco de churn)

Métricas de conversão (período selecionável):
- Taxa de conversão Free → Pro (% dos Free que assinaram Pro)
- Taxa de conversão Free → Elite
- Taxa de conversão trial → Pro pago
- Tempo médio Free → Pro (dias entre registro e primeira assinatura)
- Churn rate mensal: `(cancelamentos no mês / assinantes início do mês) × 100`

Métricas operacionais (período selecionável):
- Total de alertas enviados por dia (por tier, por liga, por tipo de mercado)
- Taxa de entrega bem-sucedida de alertas
- Latência mediana de entrega (detecção → Telegram)
- EV médio dos alertas enviados
- Número de oportunidades detectadas vs. alertas enviados (razão = impacto dos filtros)

- Métricas exportáveis em CSV para período selecionado
- Gráficos de série temporal (últimos 7/30/90 dias) para MRR, churn, alertas enviados

### RF-ADM-007 — Audit Log de Ações Administrativas
**Descrição:** Todas as ações do Admin no painel devem ser registradas com rastreabilidade completa.
**Prioridade:** Must
**Critério de aceite:**
Eventos auditados:
- Login no painel admin (sucesso e falha)
- Qualquer alteração de tier de usuário (manual)
- Suspensão/reativação de conta
- Mudança de parâmetro de sistema
- Habilitar/desabilitar liga
- Regeneração de API key Elite (pelo Admin)
- Exportação de dados de usuário (LGPD request)

Estrutura de cada entrada de audit log:
```
- audit_id: UUID
- admin_id: quem executou
- action: string descritiva
- target_type: user | system_config | league
- target_id: ID do objeto afetado
- old_value: JSON | null
- new_value: JSON | null
- reason: string (obrigatório para ações em usuários)
- timestamp: ISO 8601 UTC
- ip_address: IP do Admin
```
- Audit log é append-only; não pode ser editado nem deletado via painel
- Retenção mínima: 24 meses
- Filtros no painel: por admin, por tipo de ação, por período, por target

### RF-ADM-008 — Controle de Acesso ao Painel Admin
**Descrição:** Acesso ao painel admin deve ser separado da autenticação de usuários, com MFA obrigatório.
**Prioridade:** Must
**Critério de aceite:**
- Autenticação separada do sistema de login de usuários (domínio/subdomínio separado)
- MFA obrigatório para todos os admins (TOTP via Google Authenticator ou Authy)
- Roles de admin: `ops` (acesso a tudo exceto configurações de sistema), `super_admin` (acesso total)
- Session timeout: 4 horas de inatividade força re-login
- IP allowlist configurável: acesso ao painel admin bloqueado para IPs não listados
- Tentativas de login falhas: após 3 tentativas, conta admin bloqueada por 30 minutos; alerta interno disparado

### RF-ADM-009 — Monitoramento de Custo de Infraestrutura
**Descrição:** Visibilidade de custos em tempo real para evitar surpresas de billing da AWS.
**Prioridade:** Should
**Critério de aceite:**
- Exibir custos estimados do mês corrente por serviço: Lambda, DynamoDB, SQS, SES, S3+Athena
- Alertas de billing: se custo estimado do mês superar 80% do budget configurado, alerta interno
- Custo de APIs externas: contador de requisições The Odds API com estimativa de custo do ciclo atual
- Projeção de custo do mês baseada em consumo dos últimos 7 dias

---

### RF-ADM-A — Fila de Ações do Agente G (AIOps Remediator)
**Descrição:** Painel de saúde deve exibir fila de ações do Agente G: histórico de remediações automáticas e ações pendentes de aprovação.
**Prioridade:** Must (Agente G é MVP)
**Critério de aceite:**
- Seção "AIOps Actions" no painel de saúde com duas abas:
  - `Auto-Remediadas`: lista de ações executadas automaticamente pelo Agente G com resultado (sucesso/falha)
  - `Aguardando Aprovação`: ações que o Agente G classificou como `recommend_and_escalate`
- Para cada ação pendente: diagnóstico do agente, ação proposta, urgência (1-5), botões Aprovar / Rejeitar / Postergar 30min
- Aprovação registra `approved_by: admin_id` no audit log antes de executar
- Timeout: ação pendente sem resposta em 30 minutos é escalada como crítica via Telegram admin

### RF-ADM-B — Audit Log de Ações de Agentes
**Descrição:** Todas as ações executadas pelos agentes (autônomas ou aprovadas) devem ser registradas no audit log com mesma rastreabilidade que ações humanas.
**Prioridade:** Must
**Critério de aceite:**
- Estrutura de entrada de agente no audit log:
  ```json
  {
    "audit_id": "uuid",
    "actor_type": "agent",
    "agent_id": "AGT-G",
    "action": "activate_fallback_layer_2",
    "playbook_id": "PLB-003",
    "trigger": "the_odds_api_3_consecutive_failures",
    "diagnosis": "...",
    "result": "success|failure",
    "approved_by": "admin_id | null (auto)",
    "timestamp": "...",
    "rollback_available": true
  }
  ```
- Entradas de agentes visíveis no painel de audit log com filtro `actor_type: agent`
- Rollback de ação de agente disponível para Admin quando `rollback_available: true`

### RF-ADM-C — Configuração de Bounds de Autonomia dos Agentes
**Descrição:** Admin deve poder configurar o nível de autonomia de cada agente — quais ações são automáticas vs. requerem aprovação humana.
**Prioridade:** Must
**Critério de aceite:**
- Para cada agente com capacidade de ação (AGT-G e AGT-C), Admin configura:
  - Lista de playbooks/ações permitidas em modo `auto` (sem aprovação)
  - Lista de playbooks/ações que exigem `approval` antes de executar
  - Lista de playbooks/ações `disabled` (agente não pode executar, apenas sugerir)
- Configuração armazenada em DynamoDB, lida por cada agente no início de cada ciclo
- Mudança de bounds registrada no audit log com valores anterior e novo

### RF-ADM-D — Métricas de Performance dos Agentes no Painel
**Descrição:** Painel admin deve exibir métricas de operação e acurácia de cada agente ativo.
**Prioridade:** Should
**Critério de aceite:**
- Por agente: execuções nas últimas 24h, taxa de sucesso, latência mediana, custo LLM (tokens consumidos/USD)
- Agente B: acurácia de classificação (% de classificações que corresponderam ao comportamento observado das odds)
- Agente E: taxa de conclusão de onboarding, taxa de conversão Free→Pro para usuários que completaram o coach vs. que pularam
- Agente G: incidentes auto-remediados vs. escalados vs. ignorados (últimos 30 dias)
- Custo total da camada agêntica (LLM + compute) vs. receita do período

## Regras de Negócio

### RN-ADM-001 — Ação admin com motivo é obrigatória para ações em usuários
Qualquer alteração manual em conta de usuário (tier, suspensão, etc.) requer campo "motivo" preenchido. Sem motivo, ação não é executada. Isso garante rastreabilidade para disputas de chargeback e auditorias LGPD.

### RN-ADM-002 — Audit log é imutável
Nenhum admin, incluindo super_admin, pode deletar ou editar entradas do audit log via interface. Deleção só é possível via acesso direto ao banco com procedimento documentado e aprovação de 2 admins (four-eyes principle).

### RN-ADM-003 — Parâmetros de sistema têm validação de range
Admin não pode configurar valores fora do range válido definido no código. A validação ocorre no servidor, não apenas no frontend. Tentativa de configurar valor inválido retorna erro com range permitido.

### RN-ADM-004 — Alertas internos têm anti-flood
O mesmo tipo de alerta interno não é disparado mais de uma vez em 15 minutos para o mesmo componente. Isso evita flood no canal Slack/Telegram admin durante incidentes prolongados.

### RN-ADM-005 — Dados de usuários só acessíveis com IP autorizado
Admin só pode visualizar dados pessoais de usuários (email, histórico de apostas, dados de pagamento) de IPs na allowlist. Acesso de IP não autorizado é logado como evento de segurança e alerta crítico interno é disparado.

---

## Restrições e Dependências

| Dependência | Tipo | Impacto em falha |
|---|---|---|
| AWS CloudWatch | Infraestrutura | Métricas de Lambda e DynamoDB indisponíveis |
| Stripe Dashboard | Externa | Dados de billing precisam ser verificados direto no Stripe |
| DynamoDB (audit log) | Infraestrutura | Audit log não registrado; ação ainda pode ser executada |
| Slack/Telegram admin | Externa | Alertas críticos não entregues ao time |

**Restrições de segurança:**
- Painel admin nunca é exposto em IP público sem VPN ou IP allowlist
- Credenciais de admin não compartilham base com credenciais de usuários finais
- Logs do painel admin armazenados separados dos logs do pipeline principal — acesso segregado
