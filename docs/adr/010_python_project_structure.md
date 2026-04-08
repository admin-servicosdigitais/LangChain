# ADR-010: Estrutura do Projeto Python — Monorepo vs. Multi-repo

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** Todos os módulos Python (M01-M06, AGT-A a AGT-H)

## Contexto

O sistema tem os seguintes componentes Python:
- **6 Lambda functions** (M01 coletor, M02 EV calculator, M03 alert dispatcher, M04 auth/API, M05 archiving, M06 admin API)
- **8 agentes LangChain** (AGT-A a AGT-H) em ECS Fargate
- **Modelos de dados compartilhados** (OddsSnapshot, EVResult, User, Alert) usados por múltiplos módulos
- **Utilitários compartilhados** (logging estruturado, métricas CloudWatch, clients AWS, auth helpers)
- **Testes** (unitários, integração, e2e)

Constraints: time pequeno (2-4 devs), deploy independente por componente (uma Lambda não deve quebrar quando outro módulo muda), dependências pesadas dos agentes (LangChain ~200MB) não devem inflar as Lambdas do pipeline de coleta.

## Opções Consideradas

### Opção A: Multi-repo (um repositório por componente)

**Prós:**
- Deploy totalmente independente por repositório
- Sem risco de mudança em um módulo afetar outros no CI
- Cada repo tem suas próprias dependências sem conflito

**Contras:**
- Modelos compartilhados precisam ser pacotes PyPI privados (AWS CodeArtifact ~$2/mês + overhead de publish)
- Mudança em modelo compartilhado requer: publish nova versão → atualizar dependency em cada repo → PR em cada repo
- 15+ repositórios para time de 2-4 devs — overhead de gestão desproporcional
- Sem visibilidade de consistência entre módulos

### Opção B: Monorepo com uv Workspaces (Python)

**Prós:**
- Um repositório, `pyproject.toml` raiz com workspaces por módulo
- `uv` (Rust-based) suporta workspaces nativamente — resolvedor de deps 10-100× mais rápido que pip
- Dependências compartilhadas (`shared/`) como workspace package: mudança imediata visível em todos os módulos sem publish
- Testes cross-módulo possíveis: testar M01→M02→M03 em um único `pytest`
- Refactoring de modelo compartilhado: um PR, um diff, um review
- Deploy independente: cada Lambda tem seu próprio `Dockerfile` que instala apenas as deps do seu workspace member
- CI: `uv run --package m01-collector pytest` roda testes apenas do módulo afetado

**Contras:**
- `uv workspaces` é relativamente novo — menos documentação que Poetry
- Docker layers precisam ser construídos para não incluir deps de outros módulos
- Lock file único (`uv.lock`) pode ter conflitos em PRs paralelos que mudam deps

### Opção C: Monorepo com Poetry

**Prós:**
- Poetry é estabelecido e documentado

**Contras:**
- `poetry-multiproject-plugin` não é oficial — risco de abandono
- Resolvedor de deps de Poetry é lento para projetos grandes com LangChain (50+ dependências transitivas)
- `uv` é superior em velocidade e é o padrão moderno em 2025-2026

## Decisão

**Escolha: Opção B — Monorepo com uv Workspaces**

O time de 2-4 devs com 14 componentes Python (6 Lambdas + 8 agentes) não pode absorver o overhead de 14+ repositórios. O monorepo com uv workspaces oferece deploy independente via Dockerfiles por módulo, com modelos e utilitários compartilhados sem publish de pacote privado.

`uv` é a escolha certa sobre Poetry: mais rápido, suporte nativo a workspaces sem plugins, resolve o lock file de LangChain em segundos.

**Isolamento de dependências por módulo:**
- `m01_collector/pyproject.toml`: boto3, httpx, pydantic. **Sem LangChain.** Image Docker ~80MB
- `m02_ev_calculator/pyproject.toml`: boto3, numpy, pydantic. **Sem LangChain.** Image ~120MB
- `agents/pyproject.toml`: langchain, langchain-anthropic, langgraph, boto3, pandas, pyarrow. Image ~600MB (ECS Fargate)
- `api/pyproject.toml`: fastapi, mangum, boto3, pydantic, python-jose. Image ~200MB
- `shared/pyproject.toml`: pydantic, boto3-stubs. **Sem LLM deps.** Usada por todos como workspace dep

## Consequências

**Positivas:**
- Modelo compartilhado alterado em um commit — todos os módulos atualizam sem publish de pacote
- `uv` resolve LangChain + dependências em < 30s (vs. 5min com pip)
- Deploy independente por módulo: alterar `m01_collector` não redeploya agentes
- Testes de integração cross-módulo possíveis no mesmo repositório
- Developer experience: um `git clone`, um `uv sync` configura todo o ambiente

**Negativas / Trade-offs:**
- Monorepo com 14 módulos: `git clone` baixa todo o histórico — mitigado com `git clone --depth=1`
- Lock file único: PR que muda deps de agents pode conflitar com PR que muda deps de api
- CI completo em `main` pode ser lento — matrix de testes por workspace member mitiga

**Riscos e Mitigações:**
- Risco: Dependência de LangChain vaza para image Docker do m01_collector → Mitigação: `uv export --package m01-collector` gera requirements apenas do workspace member; Dockerfile usa multi-stage build com apenas o requirements do módulo
- Risco: Dependência circular entre workspace members → Mitigação: `shared/` nunca importa de outros workspace members; `import-linter` enforça hierarquia em CI
- Risco: Lock file conflito em PRs paralelos → Mitigação: `uv lock --check` em CI; merge de lock file com `uv lock --upgrade-package <pkg>` quando necessário

## Implementação

```
value-betting/                          # Raiz do monorepo
├── pyproject.toml                      # uv workspace root
├── uv.lock                             # Lock file único
├── src/
│   ├── shared/                         # Workspace member: modelos e utilitários
│   │   ├── pyproject.toml
│   │   └── value_betting_shared/
│   │       ├── models/
│   │       │   ├── odds.py             # OddsSnapshot, MarketType
│   │       │   ├── user.py             # User, Subscription, UserTier
│   │       │   └── alert.py           # Alert, AlertDelivery
│   │       ├── logging.py             # JSONFormatter (ADR-008)
│   │       ├── metrics.py             # CloudWatch helpers (ADR-008)
│   │       └── aws_clients.py         # boto3 client factories
│   ├── m01_collector/                  # Workspace member: coleta de odds
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── value_betting_collector/
│   │       ├── handler.py             # Lambda handler
│   │       ├── sources/
│   │       │   ├── odds_api.py        # The Odds API client
│   │       │   ├── betfair.py         # Betfair Exchange client
│   │       │   └── api_football.py    # API-Football client
│   │       └── snapshot.py            # OddsSnapshot creation + DynamoDB write
│   ├── m02_ev_calculator/              # Workspace member: cálculo de EV
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── value_betting_ev/
│   │       ├── handler.py
│   │       ├── calculator.py          # ev = (book_odds/fair_odds) - 1
│   │       ├── filters.py             # Filtros de qualidade (RF-EV-005)
│   │       └── kelly.py               # Kelly Criterion (Elite)
│   ├── m03_alert_dispatcher/           # Workspace member: entrega de alertas
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── value_betting_alerts/
│   │       ├── handler.py
│   │       ├── channels/
│   │       │   ├── telegram.py
│   │       │   ├── email_ses.py
│   │       │   └── webhook.py         # Elite HMAC-SHA256
│   │       └── throttling.py          # Rate limiting por tier
│   ├── api/                            # Workspace member: FastAPI (M04 + M06)
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── value_betting_api/
│   │       ├── main.py                # FastAPI app + Mangum handler
│   │       ├── routers/
│   │       │   ├── auth.py
│   │       │   ├── alerts.py
│   │       │   ├── elite.py
│   │       │   ├── backtesting.py
│   │       │   └── admin.py
│   │       └── dependencies.py        # verify_jwt, require_tier, verify_api_key
│   └── agents/                         # Workspace member: todos os 8 agentes
│       ├── pyproject.toml             # LangChain, LangGraph, pandas, pyarrow aqui
│       ├── Dockerfile
│       └── value_betting_agents/
│           ├── base.py
│           ├── agt_a_data_quality/
│           ├── agt_b_odds_classifier/
│           ├── agt_c_bankroll_manager/
│           ├── agt_d_inefficiency_hunter/
│           ├── agt_e_onboarding_coach/
│           ├── agt_f_performance_diagnostician/
│           ├── agt_g_aiops_remediator/
│           ├── agt_h_sharp_action_tracker/
│           └── shared/
│               ├── llm_factory.py
│               ├── memory.py
│               └── sqs_consumer.py
├── tests/
│   ├── unit/
│   ├── integration/                   # Usa moto para mock de AWS
│   └── e2e/
├── infrastructure/                     # Terraform (ADR-006)
│   └── ...
└── .github/
    └── workflows/
        ├── ci.yml                     # testes por workspace member
        └── deploy.yml                 # build + push + terraform apply
```

```toml
# pyproject.toml (raiz — uv workspace)
[tool.uv.workspace]
members = [
    "src/shared",
    "src/m01_collector",
    "src/m02_ev_calculator",
    "src/m03_alert_dispatcher",
    "src/api",
    "src/agents",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "moto[dynamodb,sqs,s3,ses]>=5.0",
    "pytest-cov>=5.0",
    "ruff>=0.4",
    "mypy>=1.10",
    "import-linter>=2.0",
]

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true
```

```toml
# src/m01_collector/pyproject.toml
[project]
name = "m01-collector"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "value-betting-shared",   # workspace dep — sem publish necessário
    "boto3>=1.34",
    "httpx>=0.27",
    "pydantic>=2.7",
]

[tool.uv.sources]
value-betting-shared = { workspace = true }
```

```toml
# src/agents/pyproject.toml
[project]
name = "value-betting-agents"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "value-betting-shared",
    "langchain>=0.3",
    "langchain-anthropic>=0.3",
    "langgraph>=0.2",
    "boto3>=1.34",
    "pandas>=2.2",
    "pyarrow>=16.0",
    "psycopg[binary]>=3.1",   # PostgresSaver para LangGraph checkpointing
]

[tool.uv.sources]
value-betting-shared = { workspace = true }
```

```dockerfile
# src/m01_collector/Dockerfile — sem LangChain
FROM public.ecr.aws/lambda/python:3.12

WORKDIR /var/task

# Instalar apenas deps do m01-collector (sem deps de agents)
COPY src/shared/ /build/shared/
COPY src/m01_collector/ /build/m01_collector/
RUN pip install uv && \
    uv pip install --no-cache --system \
        /build/shared \
        /build/m01_collector

COPY src/m01_collector/value_betting_collector/ ./value_betting_collector/

CMD ["value_betting_collector.handler.handler"]
```

```yaml
# .github/workflows/ci.yml — matrix por workspace member
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        package: [m01-collector, m02-ev-calculator, m03-alert-dispatcher, api, agents]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - name: Install dependencies
        run: uv sync --package ${{ matrix.package }}
      - name: Run tests
        run: uv run --package ${{ matrix.package }} pytest tests/unit/ -v --cov
      - name: Type check
        run: uv run --package ${{ matrix.package }} mypy src/${{ matrix.package }}/
```
