# Módulo de Entrega de Alertas

## Contexto de Negócio

O alerta é o produto percebido pelo usuário. Todo o pipeline de coleta e cálculo de EV é invisível — o que o apostador vê é a mensagem que chega no Telegram. Qualidade de entrega significa: informação correta, no momento certo, sem ruído, no canal certo.

Problemas críticos a evitar:
- **Alerta tardio:** oportunidade já fechou quando o usuário recebeu
- **Alerta duplicado:** mesmo bet notificado múltiplas vezes — irrita o usuário, queima confiança
- **Alerta falso:** dados incorretos, EV inflado — usuário apostou em EV negativo real
- **Flood de alertas:** muitos alertas sem filtro destrói a relação sinal/ruído do canal

Trade-off de negócio: o delay de 30min para Free é o principal gatilho de conversão para Pro. Deve ser real e verificável — não pode ser contornado.

---

## Atores

- **Usuário Free:** recebe alertas com delay de 30 minutos, apenas 1 liga configurada
- **Usuário Pro:** recebe alertas em tempo real, todas as ligas, threshold customizável
- **Usuário Elite:** recebe alertas em tempo real + webhooks + acesso a todos os campos do alerta
- **Telegram Bot API:** canal primário de entrega
- **Sistema de email (SES):** canal secundário de entrega
- **Webhook endpoint do usuário:** canal terciário, exclusivo Elite
- **Sistema:** processa fila de alertas pendentes, aplica delay e throttling

---

## Requisitos Funcionais

### RF-ALT-001 — Estrutura Obrigatória de uma Mensagem de Alerta
**Descrição:** Todo alerta enviado deve conter conjunto mínimo de campos para o usuário tomar decisão informada.
**Prioridade:** Must
**Critério de aceite:**
Campos obrigatórios em todos os alertas (Telegram, email, webhook):
```
- Evento: [Time Casa] vs [Time Visitante]
- Liga: [nome da liga]
- Data/Hora início: [DD/MM/YYYY HH:mm UTC]
- Mercado: [tipo: 1X2 | O/U 2.5 | AH | BTTS]
- Aposta: [resultado específico: ex. "Over 2.5"]
- Casa de apostas: [nome do bookmaker]
- Odds disponíveis: [valor numérico com 2 casas decimais, ex: 2.15]
- Fair Odds (Pinnacle): [valor numérico com 2 casas decimais]
- EV calculado: [percentual com 1 casa decimal, ex: +4.3%]
- Horário do alerta: [HH:mm UTC]
```
Campos adicionais para Pro/Elite:
```
- Pinnacle Margin: [percentual]
- Tempo restante para o evento: [HH:mm]
- Liquidez Betfair: [valor em USD ou "N/A"]
```
Campos exclusivos Elite:
```
- Kelly Recomendado: [fração ou valor em unidades monetárias]
- Alert ID: [UUID para referência em API]
- Confidence flags: [lista de flags se aplicável: volatile, pinnacle_moving, etc.]
```

### RF-ALT-002 — Canal Primário: Telegram Bot
**Descrição:** Telegram é o canal principal de entrega. Todos os tiers recebem alertas via Telegram.
**Prioridade:** Must
**Critério de aceite:**
- Alerta entregue via `sendMessage` na Telegram Bot API com `parse_mode: HTML`
- Usuário deve ter vinculado conta Telegram previamente (ver módulo de usuário)
- Se `sendMessage` retornar erro 403 (bot bloqueado pelo usuário), marcar canal Telegram como inativo e tentar email como fallback
- Se `sendMessage` retornar erro 429 (rate limit), implementar fila de retry com backoff exponencial: 1s, 2s, 4s
- Confirmação de entrega: Telegram retorna `message_id`; armazenar no registro do alerta como prova de entrega
- Formato mobile-first: mensagem legível em tela de smartphone sem scroll horizontal

### RF-ALT-003 — Canal Secundário: Email
**Descrição:** Email como fallback quando Telegram falha ou como preferência do usuário.
**Prioridade:** Should
**Critério de aceite:**
- Email enviado via AWS SES com template HTML responsivo
- Subject padronizado: `[Value Bet] +X.X% EV | [Time A] vs [Time B] | [Bookmaker]`
- Email como canal principal configurável pelo usuário (substitui Telegram, não duplica)
- Em falha de Telegram, email enviado automaticamente sem ação do usuário
- Bounce permanente de email (código 5xx SES): marcar email como inválido, notificar usuário via Telegram

### RF-ALT-004 — Canal Terciário: Webhook (Elite)
**Descrição:** Usuários Elite podem configurar endpoint HTTP para receber alertas como payload JSON.
**Prioridade:** Could (Elite only)
**Critério de aceite:**
- Payload JSON contém todos os campos do alerta incluindo campos exclusivos Elite
- Entregue via HTTP POST com header `X-ValueBet-Signature: HMAC-SHA256(payload, user_secret)`
- Usuário configura URL, secret e eventos que deseja receber (todos | apenas EV > X% | apenas arb)
- Retry: 3 tentativas com backoff 5s, 15s, 45s em resposta não-2xx
- Timeout por requisição: 5 segundos
- Log de entregas (sucesso/falha) acessível pelo usuário Elite via dashboard

### RF-ALT-005 — Delay Obrigatório para Tier Free
**Descrição:** Alertas para usuários Free devem ser entregues com delay mínimo de 30 minutos após detecção da oportunidade.
**Prioridade:** Must (pilar do modelo de negócio)
**Critério de aceite:**
- Timestamp de enfileiramento do alerta Free: `detected_at + 1800 segundos`
- Antes de enviar, verificar se evento ainda não iniciou; se iniciou, descartar alerta (não enviar stale)
- Delay implementado na fila SQS com `DelaySeconds: 1800` — não pode ser contornado via retry ou reprocessamento
- Auditoria: log registra `detected_at` e `delivered_at`; diferença deve ser ≥ 30min para Free
- Não existe configuração de usuário Free para reduzir o delay — é hardcoded no tier

### RF-ALT-006 — Regras de Throttling por Tier
**Descrição:** Limites máximos de alertas por período para evitar flood e gerenciar custos de entrega.
**Prioridade:** Must
**Critério de aceite:**

| Tier | Máx alertas/hora | Máx alertas/dia | Máx ligas simultaneamente |
|------|-----------------|-----------------|--------------------------|
| Free | 3 | 10 | 1 |
| Pro | 20 | 100 | Todas |
| Elite | 50 | 300 | Todas |

- Alertas acima do limite são descartados (não enfileirados) com log de motivo `throttle_limit_reached`
- Usuário é notificado UMA vez por sessão (24h) quando limite foi atingido: "X alertas suprimidos por limite do plano"
- Throttling é por usuário, não global
- Contadores de throttling resetam à meia-noite UTC

### RF-ALT-007 — Regra Anti-Duplicata
**Descrição:** O mesmo alerta (mesma aposta no mesmo bookmaker para o mesmo evento) não deve ser enviado mais de uma vez em janela de tempo configurável.
**Prioridade:** Must
**Critério de aceite:**
- Chave de duplicata: `hash(event_id + market_type + bookmaker_id + outcome + user_id)`
- Janela de deduplicação: 60 minutos (configurável por Admin, range 15–120 minutos)
- Se EV da mesma oportunidade aumentar significativamente (> 2pp) dentro da janela, NOVO alerta é enviado com flag `ev_improved: true` e comparação com alerta anterior
- Registro de deduplicação armazenado em cache (DynamoDB com TTL = janela configurada)

### RF-ALT-008 — Expiração de Alerta antes do Envio
**Descrição:** Alertas enfileirados devem ser verificados antes do envio para garantir que a oportunidade ainda é válida.
**Prioridade:** Must
**Critério de aceite:**
- Antes de enviar (especialmente relevante para Free com 30min de delay), verificar:
  1. Evento ainda não iniciou (`start_time > now`)
  2. Odds do bookmaker ainda existem (não foram removidas)
  3. EV ainda é positivo com odds mais recentes (recalcular no momento do envio)
- Se qualquer verificação falhar, alerta descartado com log `alert_expired: <motivo>`
- Para Free: se odds originais desapareceram, alerta descartado — não enviar com odds desatualizadas
- Para Pro/Elite: verificação feita no momento do envio imediato (risco baixo de expiração)

### RF-ALT-009 — Configurações de Preferência do Usuário
**Descrição:** Usuários devem poder personalizar quais alertas recebem para reduzir ruído.
**Prioridade:** Must
**Critério de aceite:**
- Configurações disponíveis por tier:

| Configuração | Free | Pro | Elite |
|---|---|---|---|
| Liga ativa | 1 liga fixa | Múltiplas | Múltiplas |
| Threshold EV mínimo | Fixo 5% | 1%–20% | 1%–30% |
| Tipos de mercado | Todos habilitados | Selecionável | Selecionável |
| Odds mínimas (evitar favoritos extremos) | N/A | Configurável | Configurável |
| Odds máximas (evitar longshots) | N/A | Configurável | Configurável |
| Stake máximo recomendado | N/A | Informativo | Com Kelly |
| Alertas de arb | Não | Sim | Sim |
| Horário de silêncio (não receber alertas) | N/A | Configurável | Configurável |

- Configuração de horário de silêncio: Pro e Elite podem definir janela (ex.: 23h–07h) sem alertas; alertas nesse período são descartados (não acumulados)

### RF-ALT-010 — Resumo Diário e Semanal
**Descrição:** Broadcast periódico com resumo de performance do usuário com os alertas enviados.
**Prioridade:** Should
**Critério de aceite:**
- Resumo diário (Pro e Elite): enviado às 09h UTC com alertas do dia anterior
  - Conteúdo: número de alertas enviados, EV médio, melhores oportunidades por EV
- Resumo semanal (todos os tiers): enviado segunda-feira às 09h UTC
  - Free: resumo de alertas + CTA de upgrade para Pro
  - Pro/Elite: ROI simulado da semana (se usuário tivesse seguido todos os alertas com stake fixo)
- Usuário pode desabilitar resumos nas configurações
- Resumo não conta para limite de throttling diário

### RF-ALT-011 — Fallback entre Canais
**Descrição:** Se canal primário falhar, tentar canal secundário automaticamente.
**Prioridade:** Should
**Critério de aceite:**
- Ordem de tentativa: Telegram → Email → (webhook se Elite)
- Fallback para email somente se Telegram falhou definitivamente (não em retry temporário)
- Se todos os canais falharem, alerta marcado como `delivery_failed`; Admin notificado se falha afeta > 5% dos alertas em 1 hora
- Usuário não recebe alerta duplicado em múltiplos canais por padrão; pode optar por receber em todos os canais simultâneos (configuração Pro/Elite)

### RF-ALT-A — Campo agent_context no Template de Alerta Pro/Elite
**Descrição:** Alertas Pro e Elite devem incluir saída do Agente B quando disponível: causa da movimentação, janela temporal estimada e confidence score.
**Prioridade:** Must (para MVP do Agente B)
**Critério de aceite:**
- Se `agent_context` presente no alerta: renderizar no Telegram como bloco separado abaixo dos dados principais
- Formato Telegram (Pro):
  ```
  📊 Contexto: Sharp money detectado (87% confiança)
  ⏱ Janela estimada: ~10-15 min
  ```
- Formato Telegram (Elite): contexto completo + série de movimentação + exchange volume
- Se `agent_context` ausente: alerta enviado normalmente sem o bloco de contexto
- Alerta via webhook Elite inclui `agent_context` como objeto JSON completo

### RF-ALT-B — Opt-in de Sugestões do Agente F
**Descrição:** Usuários Elite podem optar por receber sugestões automáticas do Agente F (Performance Diagnostician) aplicadas às suas configurações de alerta.
**Prioridade:** Should (V2 — depende do Agente F)
**Critério de aceite:**
- Configuração `apply_agent_f_suggestions: boolean` no perfil Elite (default: false)
- Quando ativo: Agente F pode propor ajustes de filtro (ex: desativar mercado 1X2 por 2 semanas) com prazo determinado
- Proposta é apresentada ao usuário via Telegram + dashboard antes de ser aplicada (não automática — requer confirmação)
- Usuário pode aceitar, rejeitar ou postergar sugestão
- Todas as sugestões e respostas registradas para análise de eficácia do Agente F

### RF-ALT-C — Seção "Insights do Agente" no Resumo Semanal
**Descrição:** O resumo semanal deve incluir uma seção com insights gerados pelos agentes ativos para aquele usuário.
**Prioridade:** Should
**Critério de aceite:**
- Resumo semanal Pro: inclui classificações de movimentação da semana (Ex.: "12 alertas esta semana — 7 por sharp money, 3 por erro de bookmaker, 2 por market open")
- Resumo semanal Elite: inclui insights do Agente F + Hunt Report do Agente D (quando disponível)
- Seção de insights é gerada assincronamente antes do envio do resumo; se não disponível no momento, omitida sem bloquear envio
- Usuário pode desabilitar seção de insights separadamente do resumo

---

## Regras de Negócio

### RN-ALT-001 — Delay do Free é inviolável
O delay de 30 minutos para usuários Free não pode ser reduzido por nenhum path técnico (retry, reprocessamento, bug de fila). É a principal barreira de conversão do produto. Qualquer falha que resulte em alerta Free chegando em < 25 minutos deve ser tratada como incidente crítico.

### RN-ALT-002 — Alerta sem verificação de expiração é proibido
Nunca enviar um alerta sem antes verificar se o evento ainda não começou. Alertas de partidas que já iniciaram são inúteis e prejudicam a reputação do produto.

### RN-ALT-003 — Campos de EV e odds são imutáveis após geração
Os valores de EV e odds registrados no momento de detecção da oportunidade não são alterados no alerta enviado, mesmo que a verificação pré-envio calcule EV diferente. O alerta informa as odds e EV no momento de detecção; a verificação pré-envio confirma apenas se a oportunidade ainda existe — se não existe, descarta.

### RN-ALT-004 — Webhook Elite é assíncrono
Falha na entrega de webhook não bloqueia entrega via Telegram/email. Os canais são independentes.

### RN-ALT-005 — Rate limit do Telegram é compartilhado
O bot Telegram tem limite de 30 mensagens/segundo. Com muitos usuários recebendo alertas simultaneamente (ex.: jogo popular com EV em múltiplas casas), o sistema deve enfileirar e distribuir envios para não exceder o limite e não ter mensagens bloqueadas por rate limit.

---

## Restrições e Dependências

| Dependência | Tipo | Impacto em falha |
|---|---|---|
| Telegram Bot API | Externa crítica | Canal primário indisponível; fallback email |
| AWS SES | Infraestrutura | Canal secundário indisponível |
| AWS SQS | Infraestrutura | Fila de alertas para; sem delay controlado para Free |
| DynamoDB (cache de deduplicação) | Infraestrutura | Alertas duplicados podem ser enviados |
| Módulo de EV (oportunidades) | Interna | Sem input = sem alertas |
| Configurações de usuário | Interna | Usa defaults como fallback |

**Restrições de volume:**
- Telegram: máx 30 msg/segundo por bot; com 1000 usuários ativos e spike de alertas simultâneos, enfileiramento obrigatório
- AWS SES: limite inicial de envio verificar antes do launch; pode requerer aumento de quota
- SQS: `DelaySeconds` máximo por mensagem é 900 segundos (15 minutos) — para delay de 30 minutos do Free, usar DynamoDB scheduled ou Step Functions, não apenas `DelaySeconds` nativo do SQS
