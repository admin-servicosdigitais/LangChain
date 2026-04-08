# Workflow padrão de desenvolvimento com Claude Code

Este documento descreve o fluxo de trabalho adotado neste projeto para uso do Claude Code como co-piloto em todo o ciclo de desenvolvimento — da análise de requisitos ao monitoramento em produção. O objetivo é garantir consistência, rastreabilidade e qualidade em cada fase, aproveitando os subagentes, skills e MCP servers configurados.

---

## Índice

1. [Visão geral do setup](#1-visão-geral-do-setup)
2. [Princípios gerais de uso](#2-princípios-gerais-de-uso)
3. [Fase 1 — Análise e requisitos](#3-fase-1--análise-e-requisitos)
4. [Fase 2 — Arquitetura e decisões técnicas](#4-fase-2--arquitetura-e-decisões-técnicas)
5. [Fase 3 — Design de API](#5-fase-3--design-de-api)
6. [Fase 4 — Implementação](#6-fase-4--implementação)
7. [Fase 5 — Revisão e segurança](#7-fase-5--revisão-e-segurança)
8. [Fase 6 — CI/CD e deploy](#8-fase-6--cicd-e-deploy)
9. [Fase 7 — Monitoramento e manutenção](#9-fase-7--monitoramento-e-manutenção)
10. [Referência rápida de comandos](#10-referência-rápida-de-comandos)
11. [Manutenção do próprio setup](#11-manutenção-do-próprio-setup)

---

## 1. Visão geral do setup

### Subagentes disponíveis

| Agente | Modelo | Uso principal |
|---|---|---|
| `analyst` | Opus | Estruturação de requisitos, user stories, edge cases |
| `architect` | Opus | Decisões arquiteturais, ADRs, trade-off analysis |
| `api-designer` | Sonnet | Design de contratos REST, schemas, OpenAPI |
| `code-reviewer` | Sonnet | Revisão de qualidade, correção, manutenibilidade |
| `security-scanner` | Sonnet | Vulnerabilidades, CVEs, configurações IAM |
| `devops` | Sonnet | Infraestrutura, CI/CD, Docker, Terraform |
| `test-runner` | Sonnet | Execução e correção de testes após mudanças |

### Skills disponíveis

| Skill | Invocação | Uso principal |
|---|---|---|
| `feature` | `/feature <descrição>` | Workflow completo de implementação de feature |
| `debug` | `/debug <descrição-do-bug>` | Investigação sistemática de bugs |
| `commit` | `/commit "<mensagem>"` | Review automático + commit seguro |
| `pr-review` | `/pr-review <branch-base>` | Review estruturado de Pull Request |
| `api-doc` | `/api-doc <path-do-endpoint>` | Documentação de endpoint a partir do código |

### MCP servers conectados

| Servidor | Uso no workflow |
|---|---|
| `github` | Issues, PRs, workflows de CI/CD |
| `postgres` | Consulta de schema e análise de queries em desenvolvimento |
| `sentry` | Investigação de erros em produção |

---

## 2. Princípios gerais de uso

**Plan mode é obrigatório para tarefas não-triviais.** Qualquer tarefa com 3 ou mais passos começa com planejamento explícito antes de qualquer código. Pressione `Shift+Tab` ou diga "entre em plan mode" antes de descrever a tarefa.

**Contexto limpo entre tarefas não relacionadas.** Use `/clear` ao iniciar uma tarefa de escopo diferente da anterior. O Claude Code acumula contexto e isso degrada a qualidade das respostas ao longo de uma sessão longa.

**Subagentes mantêm o contexto principal limpo.** Tarefas de pesquisa, análise e exploração devem ser delegadas a subagentes. O resultado retorna sintetizado, sem poluir o contexto da sessão principal com intermediários.

**O padrão Writer/Reviewer é a regra para revisão.** O Claude que escreveu o código tem viés de confirmação — ele tende a não encontrar os próprios erros. Toda revisão de PR acontece em uma nova sessão do Claude Code, com contexto fresco.

**Toda lição aprendida atualiza o CLAUDE.md.** Quando o Claude errar algo que uma instrução explícita evitaria, a instrução vai para o `CLAUDE.md` do projeto. O arquivo é tratado como código: versionado, revisado, e podado quando fica redundante.

---

## 3. Fase 1 — Análise e requisitos

**Subagente:** `analyst`
**Quando usar:** início de qualquer funcionalidade nova, mudança de processo de negócio, ou refinamento de escopo.

### Fluxo

```
1. Invoke analyst → estrutura requisitos vagos
2. Responda às perguntas sobre regras de negócio implícitas
3. Valide user stories e critérios de aceite
4. Persista o output em docs/requirements/
```

### Como invocar

```
Use o analyst para: [descrição do processo ou funcionalidade]
```

Ou via @-mention durante a sessão:

```
@"analyst (agent)" analise o processo de aprovação de crédito e estruture os requisitos
```

### O que o analyst produz

- User stories no formato `Como [papel], quero [ação] para [benefício]`
- Critérios de aceite testáveis para cada story
- Mapeamento de dependências entre funcionalidades
- Edge cases e cenários de erro identificados
- Perguntas abertas sobre regras de negócio (a serem respondidas antes de prosseguir)

### Onde salvar o output

```
docs/requirements/<funcionalidade>.md
```

> **Importante:** não avance para a fase de arquitetura com requisitos em aberto. Toda pergunta não respondida pelo analyst é um risco de retrabalho.

---

## 4. Fase 2 — Arquitetura e decisões técnicas

**Subagente:** `architect`
**Quando usar:** antes de implementar qualquer componente novo, integração externa, ou mudança estrutural no sistema.

### Fluxo

```
1. Entre em plan mode
2. Invoke architect com o contexto de requisitos da fase anterior
3. Avalie as alternativas apresentadas
4. Solicite o ADR da decisão escolhida
5. Salve o ADR em docs/adr/
```

### Como invocar

```
[plan mode ativo]
Use o architect para avaliar as opções de [autenticação / persistência / comunicação / ...]
Contexto de requisitos: @docs/requirements/<funcionalidade>.md
```

### O que o architect produz

Para cada decisão, apresenta no mínimo duas alternativas com análise de:

- Complexidade de implementação e operação
- Impacto em performance e escalabilidade
- Custo de infraestrutura
- Observabilidade e facilidade de diagnóstico
- Implicações de segurança

O ADR segue o formato:

```markdown
# ADR-NNNN: Título da decisão

## Status
Aceito | Proposto | Substituído por ADR-XXXX

## Contexto
O que motivou esta decisão.

## Alternativas consideradas
### Opção A — [nome]
Descrição, prós, contras.

### Opção B — [nome]
Descrição, prós, contras.

## Decisão
Opção escolhida e justificativa.

## Consequências
O que muda, o que fica mais fácil, o que fica mais difícil.
```

### Onde salvar

```
docs/adr/NNNN-titulo-da-decisao.md
```

> **Nota:** o `architect` tem `memory: project` configurado. Decisões de sessões anteriores ficam acessíveis — evite repetir contexto que já foi documentado nos ADRs.

---

## 5. Fase 3 — Design de API

**Subagente:** `api-designer`
**Skill:** `/api-doc`
**Quando usar:** antes de implementar qualquer endpoint novo; para documentar endpoints existentes.

### Fluxo — design de contrato novo

```
1. Invoke api-designer com os requisitos da funcionalidade
2. Revise o contrato antes de qualquer implementação
3. Solicite a especificação OpenAPI se a API for pública ou consumida por terceiros
4. Via MCP GitHub: crie issue de revisão de contrato ou abra PR de spec
```

### Como invocar

```
Use o api-designer para projetar o contrato de API para: [descrição da funcionalidade]
Requisitos: @docs/requirements/<funcionalidade>.md
```

### Fluxo — documentação de endpoint existente

```
/api-doc src/api/<modulo>/<handler>.ts
```

### O que o api-designer produz

- Lista de endpoints com método HTTP, path e descrição
- Schemas de request e response em TypeScript ou JSON Schema
- Regras de validação e error codes específicos
- Considerações de autenticação e autorização
- Especificação OpenAPI quando solicitado

### Padrões obrigatórios seguidos pelo agente

- URLs em kebab-case, recursos no plural: `/api/v1/user-profiles`
- Propriedades JSON em camelCase: `firstName`, `createdAt`
- Versionamento via path: `/v1/`, `/v2/`
- Error response no formato padrão do projeto com `code`, `message`, `details` e `traceId`
- Paginação com `data`, `pagination.page`, `pagination.totalItems`

---

## 6. Fase 4 — Implementação

**Skill principal:** `/feature`
**Subagente auxiliar:** `test-runner`
**Skills auxiliares:** `/debug`, `/commit`
**MCP auxiliar:** `postgres`

### Fluxo padrão de uma feature

```
1. /feature <descrição>         → análise → plan → branch → implement → test → verify → commit
2. test-runner (automático)     → verifica testes relevantes após cada mudança
3. /debug <descrição>           → se bug aparecer durante implementação
4. /commit "<mensagem>"         → ao finalizar um conjunto coeso de mudanças
```

### Como invocar a skill feature

```
/feature implementar aprovação automática de crédito para PF
```

A skill executa o seguinte processo internamente:

1. Lê requisitos, identifica componentes afetados
2. Cria checklist detalhado do plano de implementação
3. Cria branch `feature/<descrição>` a partir da branch padrão
4. Executa o plano passo a passo
5. Escreve e roda testes unitários e de integração
6. Roda typecheck, lint e testes
7. Cria commits atômicos com mensagens descritivas

### Uso do MCP postgres durante a implementação

Com o MCP postgres conectado, o Claude consulta o schema real do banco sem precisar que você o descreva:

```
Qual é a estrutura da tabela credit_applications e suas foreign keys?
```

Isso evita erros de tipo, nomes de coluna incorretos e queries com N+1 que só aparecem em runtime.

### Quando usar /debug

```
/debug o cálculo de score de crédito retorna valor negativo para renda acima de 50k
```

O processo do debug segue:

1. **Reproduzir** — identifica os passos mínimos para reproduzir
2. **Isolar** — localiza o componente responsável
3. **Diagnosticar** — lê logs, traces e estado relevante
4. **Root cause** — identifica a causa raiz, não o sintoma
5. **Fix** — implementa correção mínima e precisa
6. **Prevent** — adiciona teste que falha sem o fix
7. **Verify** — roda os testes e confirma que o bug não retorna

### Commit seguro com /commit

```
/commit "feat(credito): adiciona cálculo de score para PF"
```

Antes de commitar, a skill verifica automaticamente:

- `console.log` ou `print` de debug esquecidos
- Código comentado que deveria ter sido removido
- TODOs que deveriam ter sido resolvidos antes do merge
- Arquivos `.env` ou secrets adicionados acidentalmente ao staging

### Sessões paralelas com worktrees

Para features paralelas sem conflito de contexto:

```bash
git worktree add ../projeto-feature-x feature/x
# abra uma nova instância do Claude Code nesse diretório
```

Cada worktree tem seu próprio diretório de trabalho e contexto de Claude Code completamente isolado.

### Regras de implementação do CLAUDE.md

- Funções com no máximo 50 linhas (preferencialmente abaixo de 30)
- Complexidade ciclomática máxima de 10 por função
- Linhas com no máximo 120 caracteres
- Tipagem forte obrigatória (TypeScript strict, Python type hints)
- Zero error swallowing silencioso — todo erro é tratado ou propagado explicitamente
- Nunca hardcodar credenciais, tokens ou secrets

---

## 7. Fase 5 — Revisão e segurança

**Skill:** `/pr-review <branch-base>`
**Subagentes:** `code-reviewer` (via skill), `security-scanner`
**MCP:** `github`

### Princípio do Writer/Reviewer

Esta é a regra mais importante desta fase: **a revisão acontece sempre em uma nova sessão do Claude Code**, separada da sessão onde o código foi escrito. Um contexto fresco elimina o viés de confirmação que faz o autor não enxergar os próprios erros — o mesmo motivo pelo qual peer review humano funciona.

```
Sessão A (escrita) → /commit → fecha a sessão
Sessão B (revisão) → /pr-review <branch-base> → corrige → /commit
```

### Como invocar a revisão de PR

```
/pr-review develop
```

A skill detecta automaticamente o diff, os arquivos alterados e os commits em relação à branch base informada. Ela delega internamente para o subagente `code-reviewer` rodando em contexto isolado (`context: fork`).

> **Atenção:** a branch base deve ser passada explicitamente como argumento para evitar que a skill compare contra uma branch incorreta. Use `develop`, `main`, `master` ou qualquer branch base do projeto.

### O que o code-reviewer analisa

A revisão segue esta ordem de prioridade:

1. **Segurança** — injeções, exposição de dados, autenticação, autorização, validação de entrada
2. **Correção** — bugs, edge cases, null handling, race conditions, error handling
3. **Arquitetura** — separação de responsabilidades, acoplamento, coesão
4. **Performance** — N+1 queries, memory leaks, loops desnecessários
5. **Manutenibilidade** — legibilidade, naming, complexidade, duplicação
6. **Testes** — cobertura, qualidade, cenários edge case

### Classificação dos findings

| Classificação | Significado | Ação |
|---|---|---|
| 🔴 Crítico | Bug, falha de segurança, risco de data loss | Bloqueia o merge — corrigir antes |
| 🟡 Importante | Code smell, performance, manutenibilidade | Deve ser corrigido no mesmo PR |
| 🟢 Sugestão | Melhoria de estilo, refactoring futuro | Opcional — pode virar issue |

### Análise de segurança em paralelo

Enquanto o code-reviewer analisa qualidade, chame o security-scanner em paralelo para análise de vulnerabilidades:

```
Use o security-scanner para analisar as mudanças desta branch antes do merge
```

O security-scanner cobre:

- Injeções (SQL, NoSQL, Command, XSS, SSRF)
- Exposição de dados sensíveis (PII, secrets em código ou logs)
- Dependências com CVEs conhecidas
- Criptografia fraca ou chaves hardcoded
- Em infraestrutura AWS: IAM excessivamente permissivo, S3 público, security groups abertos

### Classificação de vulnerabilidades

| Classificação | CVSS | Ação |
|---|---|---|
| 🔴 Crítica | 9.0–10.0 | Bloqueia o merge imediatamente |
| 🟠 Alta | 7.0–8.9 | Bloqueia o merge |
| 🟡 Média | 4.0–6.9 | Corrigir no mesmo PR ou abrir issue prioritária |
| 🟢 Baixa | 0.1–3.9 | Issue de hardening para backlog |

### Via MCP GitHub

Com o MCP github conectado, é possível:

```
Crie um PR para esta branch com a descrição das mudanças e os findings do code-reviewer
```

```
Abra uma issue para os findings 🟡 que não serão corrigidos neste PR
```

---

## 8. Fase 6 — CI/CD e deploy

**Subagente:** `devops`
**MCPs:** `github`, `sentry`

### Quando invocar o devops

- Otimização de Dockerfiles (multi-stage builds, layer caching, imagem final mínima)
- Criação ou ajuste de GitHub Actions workflows (caching, paralelismo, matrix builds)
- Análise de configurações Terraform (drift detection, least privilege IAM, security groups)
- Troubleshooting de falhas em ambientes de staging ou produção

### Como invocar

```
Use o devops para otimizar o Dockerfile do serviço de crédito para produção
```

```
Use o devops para criar o workflow de CI que rode testes, lint e build em paralelo
```

### Regra do devops: dry-run antes de aplicar

O subagente sempre valida configurações com dry-run antes de propor mudanças destrutivas. Para Terraform:

```bash
terraform plan -out=tfplan   # antes de qualquer apply
```

Para mudanças de pipeline, o agente propõe a alteração e aguarda confirmação antes de criar o arquivo.

### Pós-deploy com MCP Sentry

Após um deploy, o MCP sentry permite investigar erros em produção diretamente no contexto do Claude:

```
Analise os últimos erros do serviço credit-api no Sentry das últimas 2 horas
```

O Claude acessa as issues reais do Sentry sem que você precise copiar stack traces — e consegue correlacionar os erros com o código-fonte da branch deployada.

---

## 9. Fase 7 — Monitoramento e manutenção

**Subagentes:** `security-scanner`, `code-reviewer`, `devops`
**Skills:** `/debug`
**MCPs:** `sentry`, `postgres`

### Bug em produção

```
1. /debug <descrição do comportamento observado>
   + MCP sentry para acessar o stack trace real
   + MCP postgres para analisar queries ou estado do banco
2. Root cause identificado → fix em branch fix/<descrição>
3. Fluxo completo das fases 4 e 5 antes de mergear
```

### Auditoria periódica de segurança

Execute a cada ciclo de release ou ao adicionar dependências:

```
Use o security-scanner para auditar as dependências do projeto e verificar CVEs conhecidas
```

```
Use o security-scanner para revisar as policies IAM do ambiente de produção
```

### Análise de performance com MCP postgres

Para queries lentas identificadas via monitoramento:

```
Analise o plano de execução desta query e sugira índices ou reestruturação:
[query]
```

O Claude executa `EXPLAIN ANALYZE` diretamente via MCP e interpreta o resultado no contexto da aplicação.

### Refatoração segura

Para mudanças de manutenção em código legado, use o code-reviewer antes e depois:

```
Use o code-reviewer para mapear os riscos desta refatoração antes de executá-la
```

Após a refatoração, o test-runner verifica que nenhum contrato foi quebrado.

---

## 10. Referência rápida de comandos

### Fluxo principal de uma feature

```bash
# Fase 1 — análise
Use o analyst para: <descrição>

# Fase 2 — arquitetura (quando aplicável)
[plan mode] Use o architect para avaliar: <decisão>

# Fase 3 — API (quando aplicável)
Use o api-designer para projetar o contrato de: <funcionalidade>

# Fase 4 — implementação
/feature <descrição da feature>
/debug <descrição do bug>          # se necessário
/commit "<mensagem>"

# Fase 5 — revisão (NOVA SESSÃO)
/pr-review <branch-base>
Use o security-scanner para analisar as mudanças desta branch
```

### Comandos de controle de sessão

| Comando | Quando usar |
|---|---|
| `Shift+Tab` | Ativar plan mode antes de tarefas complexas |
| `/clear` | Entre tarefas não relacionadas |
| `/compact` | Quando o contexto ficar pesado (CLAUDE.md é recarregado) |
| `Ctrl+B` | Mover tarefa em andamento para background |

### Invocação de subagentes

```
Use o <nome-do-agente> para: <tarefa>
@"<nome-do-agente> (agent)" <tarefa>
```

### Worktree para features paralelas

```bash
git worktree add ../<projeto>-<feature> feature/<nome>
# abrir nova instância do Claude Code no novo diretório
git worktree remove ../<projeto>-<feature>   # ao finalizar
```

---

## 11. Manutenção do próprio setup

O setup do Claude Code é um artefato vivo do projeto e deve ser tratado como código.

### Quando atualizar o CLAUDE.md

- Claude repetiu um erro que uma instrução explícita evitaria → adicione a instrução
- Um padrão novo foi adotado pelo time → documente no CLAUDE.md
- Uma seção ficou redundante com o código ou com outros arquivos → remova

### Quando adicionar um subagente

- A tarefa se repete com frequência e segue um processo estruturado
- O output da tarefa é verboso e poluiria o contexto principal
- A tarefa exige ferramentas restritas (somente leitura, somente bash, etc.)

### Quando adicionar uma skill

- A tarefa tem uma sequência de passos fixa que o Claude não precisa raciocinar
- O acionamento precisa de um slash command claro e repetível
- A skill pode compor com um subagente existente via `context: fork`

### Limite de tamanho do CLAUDE.md

O arquivo deve ficar abaixo de 200 linhas. Acima disso, mova as regras por domínio para arquivos em `.claude/rules/` com path-specific loading via frontmatter `paths: ["src/api/**"]`. Isso preserva o contexto e carrega apenas as regras relevantes para o arquivo em edição.

### Revisão periódica do setup

A cada sprint ou ciclo de release, avalie:

- Subagentes que não foram invocados nenhuma vez → considere remover ou fundir
- Skills que estão sendo ignoradas em favor de prompts manuais → investigue por quê
- Regras do CLAUDE.md que o Claude consistentemente não segue → reescreva de forma mais específica e verificável
- MCP servers configurados mas não utilizados → removê-los reduz o overhead de inicialização
