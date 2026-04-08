# Módulo de Usuário e Assinatura

## Contexto de Negócio

Gestão de usuários e assinaturas é o módulo que monetiza o produto. Erros aqui têm impacto direto em receita (cobrança incorreta, downgrade indevido) ou em reputação (dados de usuário vazados, LGPD não cumprida). A complexidade está nos edge cases: upgrades/downgrades no meio do ciclo, falhas de pagamento, trial expirado, conta suspensa com dados ainda acessíveis.

A integração Telegram é um diferencial do produto — e uma fonte de fricção de onboarding. O fluxo de vinculação deve ser simples e resistente a erros de usuário.

---

## Atores

- **Usuário anônimo:** pode se registrar, iniciar trial
- **Usuário Free:** acesso gratuito com limitações
- **Usuário Pro:** assinante $29/mês, em trial ou ativo
- **Usuário Elite:** assinante $79/mês
- **Stripe (webhook):** notifica eventos de cobrança (pagamento, falha, cancelamento)
- **Admin:** gerencia usuários manualmente quando necessário

---

## Requisitos Funcionais

### RF-USR-001 — Registro de Conta
**Descrição:** Novos usuários podem criar conta via email/senha ou OAuth Google.
**Prioridade:** Must
**Critério de aceite:**
- Email/senha: email válido (RFC 5322), senha mínimo 8 caracteres com ao menos 1 número e 1 letra maiúscula
- OAuth Google: integração via Google OAuth 2.0; email do Google é o identificador único
- Email de confirmação enviado após registro via email/senha; conta inativa até confirmação (TTL 24h no link)
- OAuth Google não requer confirmação de email (email já verificado pelo Google)
- Registro duplicado (mesmo email): retornar erro 409 com mensagem "Email já cadastrado"
- Após registro bem-sucedido: conta criada com tier `free`, `created_at` registrado, redirect para onboarding

### RF-USR-002 — Autenticação
**Descrição:** Login seguro com suporte a múltiplos fatores de autenticação.
**Prioridade:** Must
**Critério de aceite:**
- Email/senha: retornar JWT com `exp: 7 dias` + refresh token com `exp: 30 dias`
- OAuth Google: retornar JWT com mesmos parâmetros
- Após 5 tentativas de login falhas em 15 minutos: bloquear conta por 15 minutos, enviar email de aviso
- JWT contém: `user_id`, `tier`, `email`, `telegram_linked: boolean`
- Refresh token rotaciona a cada uso (rotation strategy)
- Logout invalida refresh token no servidor; JWT continua válido até expirar (stateless)

### RF-USR-003 — Vinculação de Conta Telegram
**Descrição:** Para receber alertas via Telegram, usuário deve vincular sua conta Telegram ao perfil do SaaS via handshake com o bot.
**Prioridade:** Must
**Critério de aceite:**
- Fluxo de vinculação:
  1. Usuário acessa dashboard e clica em "Vincular Telegram"
  2. Sistema gera token único de 6 dígitos com TTL de 10 minutos
  3. Usuário abre bot Telegram e envia `/start <token>`
  4. Bot valida token, associa `telegram_chat_id` ao `user_id`, confirma via mensagem no Telegram e atualiza dashboard
- Token expirado: usuário solicita novo token via dashboard
- Token já usado: retornar erro "Token já utilizado ou expirado"
- Um `telegram_chat_id` pode estar associado a apenas um `user_id`; tentativa de vincular Telegram já vinculado a outra conta retorna erro com instrução de desvincular primeiro
- Desvinculação: usuário pode desvincular Telegram pelo dashboard; alertas futuros caem para fallback email

### RF-USR-004 — Upgrade de Plano
**Descrição:** Usuário Free ou Pro pode fazer upgrade de plano com cobrança imediata e acesso instantâneo.
**Prioridade:** Must
**Critério de aceite:**
- Upgrade Free → Pro: criar assinatura Stripe; se em trial, trial é mantido até expirar sem cobrança imediata
- Upgrade Pro → Elite: Stripe calcula valor prorrateado do ciclo restante; cobrança imediata da diferença
- Acesso ao novo tier é imediato após confirmação de pagamento (webhook Stripe `invoice.paid`)
- Email de confirmação de upgrade enviado com novo valor mensal e data de próxima cobrança
- Falha no pagamento de upgrade: tentativa cancelada, usuário permanece no tier atual, email de falha enviado

### RF-USR-005 — Downgrade de Plano
**Descrição:** Usuário pode fazer downgrade ao final do período atual de faturamento.
**Prioridade:** Must
**Critério de aceite:**
- Downgrade é agendado para o final do ciclo de faturamento atual (não imediato)
- Durante período restante, usuário mantém acesso ao tier atual
- Na data de renovação, Stripe cancela plano atual e cria novo plano; tier no banco atualizado via webhook
- Downgrade Elite → Pro: histórico de 12 meses é preservado no banco; usuário perde acesso de leitura, mas dados não são deletados (pode reativar Elite e recuperar acesso)
- Downgrade Pro → Free: alertas em tempo real cessam imediatamente após downgrade efetivado; configurações Pro são arquivadas (não deletadas)
- Email de confirmação de downgrade com data efetiva enviado no momento da solicitação

### RF-USR-006 — Cancelamento de Assinatura
**Descrição:** Usuário pode cancelar assinatura a qualquer momento.
**Prioridade:** Must
**Critério de aceite:**
- Cancelamento é agendado para fim do ciclo atual; usuário mantém acesso Pro/Elite até lá
- Após cancelamento efetivo, conta downgrade para Free automaticamente (não deletada)
- Stripe webhook `customer.subscription.deleted` dispara downgrade no banco
- Email de confirmação de cancelamento com data efetiva e instrução de como reativar
- Dados do usuário preservados por 12 meses após cancelamento (LGPD — dados podem ser exportados)
- Usuário pode reativar assinatura cancelada a qualquer momento antes da exclusão de dados

### RF-USR-007 — Trial de 7 Dias para Pro
**Descrição:** Novos usuários podem experimentar o plano Pro por 7 dias sem cobrança.
**Prioridade:** Must
**Critério de aceite:**
- Trial disponível apenas uma vez por conta (CPF/email) — não é possível criar nova conta para novo trial
- Trial requer cartão de crédito válido cadastrado no Stripe (autorização sem cobrança)
- Acesso Pro completo durante o trial, incluindo todas as ligas e alertas em tempo real
- 3 dias antes do fim do trial: email de lembrete com opção de cancelar
- 1 dia antes do fim do trial: segundo email de lembrete
- Fim do trial: cobrança automática de $29 via Stripe; se falhar, conta downgrade para Free com email explicativo
- Trial só disponível para tier Free → Pro; não existe trial Elite

### RF-USR-008 — Período de Graça em Falha de Cobrança
**Descrição:** Falha no pagamento mensal não resulta em downgrade imediato.
**Prioridade:** Must
**Critério de aceite:**
- Stripe tenta cobrança em D+0, D+3, D+7 (configuração de retry do Stripe)
- Em D+0 (primeira falha): email informativo ao usuário com link de atualização de cartão
- Em D+3 (segunda falha): segundo email com urgência; acesso mantido
- Em D+7 (terceira falha): Stripe marca assinatura como `past_due`; acesso mantido por mais 3 dias
- Em D+10: sem pagamento, Stripe cancela assinatura; webhook dispara downgrade para Free
- Usuário que atualiza cartão e paga a qualquer momento antes de D+10 retoma tier sem interrupção

### RF-USR-009 — Matriz de Acesso por Tier
**Descrição:** Cada funcionalidade tem visibilidade e acesso definidos por tier.
**Prioridade:** Must
**Critério de aceite:**

| Feature | Free | Pro | Elite |
|---|---|---|---|
| Alertas via Telegram | Sim (delay 30min) | Sim (tempo real) | Sim (tempo real) |
| Alertas via email | Sim (delay 30min) | Sim | Sim |
| Alertas via webhook | Não | Não | Sim |
| Número de ligas | 1 (fixa por Admin) | Todas | Todas |
| Threshold EV customizável | Não (fixo 5%) | Sim (1%–20%) | Sim (1%–30%) |
| Alertas de arbitragem | Não | Sim | Sim |
| Histórico de alertas | 7 dias | 30 dias | 12 meses |
| Interface de backtesting | Não | Não | Sim |
| Exportação de dados | Não | Não | Sim (CSV/JSON) |
| Kelly Criterion | Não | Não | Sim |
| API access (API key) | Não | Não | Sim |
| Resumo semanal | Sim | Sim | Sim |
| Resumo diário | Não | Sim | Sim |
| Configuração horário silêncio | Não | Sim | Sim |
| Suporte | Email (48h SLA) | Email (24h SLA) | Chat prioritário (4h SLA) |

### RF-USR-010 — API Keys para Usuários Elite
**Descrição:** Usuários Elite recebem chave de API para integração programática com o sistema.
**Prioridade:** Must (Elite only)
**Critério de aceite:**
- API key gerada automaticamente na ativação do plano Elite
- Formato: prefixo `vb_elite_` + 32 caracteres alfanuméricos (ex.: `vb_elite_aBcD1234...`)
- Armazenamento: somente hash SHA-256 da key é armazenado no banco — key em texto claro exibida apenas uma vez no dashboard
- Usuário pode gerar nova key (rotação) — key anterior é invalidada imediatamente
- Usuário pode ter no máximo 2 keys ativas simultaneamente (para zero-downtime rotation)
- Rate limit por API key: 100 requisições/minuto, 5.000 requisições/dia
- Exceder rate limit retorna HTTP 429 com header `Retry-After`
- API key revogada automaticamente se conta downgrade de Elite; requisições com key revogada retornam HTTP 401

### RF-USR-011 — Direitos LGPD
**Descrição:** Usuários têm direito à portabilidade e exclusão de seus dados pessoais conforme LGPD.
**Prioridade:** Must
**Critério de aceite:**
- **Exportação de dados (portabilidade):** usuário solicita via dashboard; arquivo gerado em até 48h; link de download enviado por email com TTL de 7 dias
  - Dados exportados: perfil, configurações, histórico de alertas recebidos, histórico de assinaturas
  - Formato: JSON estruturado
- **Exclusão de conta (direito ao esquecimento):**
  - Usuário solicita exclusão via dashboard (com confirmação de senha obrigatória)
  - Dados pessoais deletados em até 30 dias
  - Dados financeiros (histórico de transações Stripe) mantidos por 5 anos por obrigação fiscal
  - Dados de alertas anonimizados (removido `user_id`), não deletados — necessários para métricas de produto
  - Após exclusão: conta não pode ser reativada com mesmo email por 90 dias

### RF-USR-A — Ativação do Agente E (Onboarding Coach) após Registro
**Descrição:** Ao completar o registro com bot Telegram vinculado, o sistema deve ativar automaticamente o Agente E (Onboarding Coach) para acompanhar os primeiros 7 dias.
**Prioridade:** Must (Agente E é MVP)
**Critério de aceite:**
- Trigger: evento `UserRegistered` publicado após confirmação de email OU OAuth + Telegram vinculado
- Se Telegram não vinculado no momento do registro: Agente E ativado assim que a vinculação ocorrer (janela de 48h; após 48h sem vinculação, coach inicia via email com CTA para vincular Telegram)
- Agente E envia primeira mensagem em até 5 minutos após o primeiro alerta gerado para o usuário (não imediatamente após registro — aguarda dado real para contextualizar)
- Usuário pode digitar `/skip_coach` para desativar o onboarding a qualquer momento
- Status do Agente E armazenado no perfil: `onboarding_status: active | completed | skipped`

### RF-USR-B — Bet Tracking para Usuários Elite
**Descrição:** Usuários Elite devem poder registrar apostas realizadas, vinculando cada aposta a um alerta do sistema, para alimentar os Agentes C e F.
**Prioridade:** Must (Elite — sem bet tracking, Agentes C e F não têm dados)
**Critério de aceite:**
- Endpoint `POST /bets` com payload: `alert_id (optional), bookmaker, market_type, outcome, odds_placed, stake, result (win|loss|void|pending)`
- Resultado `pending` é atualizado automaticamente quando M05 coleta resultado real (por `event_id`)
- Webhook de importação: usuário Elite pode configurar webhook para envio de apostas de exchanges externas (ex.: Betfair integration)
- Dashboard de bet tracking exibe: apostas registradas, % vinculadas a alertas, P&L total, P&L por liga

### RF-USR-C — Importação de Histórico de Apostas (Bootstrap dos Agentes)
**Descrição:** Usuários Elite podem importar histórico anterior de apostas em CSV para inicializar os Agentes C e F sem esperar acumulação orgânica.
**Prioridade:** Should
**Critério de aceite:**
- Endpoint de upload CSV com colunas obrigatórias: `date, bookmaker, market, outcome, odds, stake, result`
- Colunas opcionais: `league, ev_at_bet, notes`
- Validação: rejeitar linhas com campos obrigatórios ausentes com relatório de erros linha a linha
- Processamento assíncrono: arquivo de até 10.000 linhas processado em background; usuário notificado quando completo
- Dados importados são marcados como `source: import` (distintos de apostas registradas via sistema)
- Agentes C e F usam dados importados + dados do sistema para inicializar modelo

### RF-USR-D — Preferências de Agentes no Perfil
**Descrição:** Perfil do usuário deve incluir configurações de quais agentes estão ativos e seus parâmetros.
**Prioridade:** Should
**Critério de aceite:**
- Objeto `agent_preferences` no perfil com estrutura por agente:
  ```json
  {
    "agent_c": { "active": true, "kelly_min_fraction": 0.125, "kelly_max_fraction": 0.5 },
    "agent_f": { "active": true, "diagnosis_frequency": "weekly" },
    "agent_e": { "status": "completed" }
  }
  ```
- UI no dashboard Elite para gerenciar preferências de cada agente
- Valores padrão aplicados automaticamente ao ativar Elite — usuário pode customizar a partir deles

---

## Regras de Negócio

### RN-USR-001 — Tier é a fonte de verdade no JWT
O tier no JWT deve ser atualizado sempre que houver mudança (upgrade, downgrade, trial expirado). Tokens com tier desatualizado permitem acesso incorreto. Estratégia: ao upgrade/downgrade, invalidar todos os refresh tokens do usuário, forçando re-login e emissão de novo JWT com tier correto.

### RN-USR-002 — Um trial por identidade
Trial não é por conta, mas por identidade (email + fingerprint do cartão de crédito). Não é obrigatório implementar detecção de fraude sofisticada no MVP — verificação por email é suficiente na fase inicial.

### RN-USR-003 — Webhook Stripe é a fonte de verdade para billing
Nunca confiar apenas na resposta síncrona da API Stripe. Toda mudança de estado de assinatura (ativa, cancelada, past_due) deve ser processada via webhook Stripe com verificação de assinatura (`stripe-signature` header). Atualizar tier no banco somente após webhook validado.

### RN-USR-004 — Conta Free não expira
Conta Free permanece ativa indefinidamente sem cobrança. Usuário Free inativo por 12 meses recebe email de reativação; se não interagir em mais 30 dias, conta é arquivada (não deletada) e não recebe alertas (preserva quota de Telegram).

### RN-USR-005 — Telegram chat_id é imutável para o usuário
Após vinculação, o `telegram_chat_id` não muda a menos que o usuário desvincule e vincule novamente. Não existe atualização automática de `chat_id`.

---

## Restrições e Dependências

| Dependência | Tipo | Impacto em falha |
|---|---|---|
| Stripe | Externa crítica | Sem cobrança, sem gestão de assinaturas |
| Telegram Bot API | Externa | Vinculação de conta indisponível |
| AWS SES | Infraestrutura | Emails de confirmação/notificação não enviados |
| Google OAuth | Externa | Login OAuth indisponível; email/senha como fallback |

**Restrições regulatórias:**
- LGPD (Lei 13.709/2018): dados de usuários brasileiros sob jurisdição brasileira
- Verificar se Stripe aceita processamento de pagamentos para serviços relacionados a gambling/apostas na jurisdição alvo — pode exigir conta Stripe com aprovação especial
- GDPR: se usuários europeus forem aceitos, política de cookies e consentimento explícito obrigatório
