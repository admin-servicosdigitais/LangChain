# ADR-004: Stack de API — FastAPI vs. Lambda Function URLs vs. API Gateway

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** M04 (auth, perfil, configurações), M06 (admin dashboard), Elite (API programática)

## Contexto

O sistema precisa expor três superfícies de API com requisitos distintos:

1. **API de usuário** (M04): auth (login, refresh, logout), perfil, configurações de alerta, histórico. Carga estimada: 100-500 req/s em pico. JWT validation obrigatória. Rate limiting por tier.
2. **API Admin** (M06): dashboard de saúde, gestão de usuários, audit log, MFA TOTP. Acesso restrito a IPs internos. Baixa frequência.
3. **API Elite** (programática): endpoints RESTful com API Key, rate limiting rigoroso (1000 req/hora por chave), webhooks HMAC, exportação CSV/JSON. Documentação OpenAPI obrigatória.

Constraints: documentação automática OpenAPI 3.0 é exigência do produto para Elite. JWT validation e rate limiting não podem adicionar > 200ms de overhead. FastAPI em Lambda via Container Image (ADR-001) é o contexto de deploy.

## Opções Consideradas

### Opção A: Lambda Function URLs com FastAPI (Mangum adapter)

**Prós:**
- FastAPI nativa com documentação automática OpenAPI/Swagger e ReDoc
- Mangum adapter converte ASGI→Lambda event em < 1ms overhead
- Sem custo adicional de API Gateway
- Pydantic validation, dependency injection, middleware stack completo
- Deploy: mesma Lambda Container Image do ADR-001

**Contras:**
- Lambda Function URLs não têm WAF nativo — requer CloudFront + AWS WAF adicional
- Rate limiting requer Redis externo (ElastiCache) para estado distribuído
- JWT validation precisa ser implementada na FastAPI (não delegada ao API Gateway Authorizer)
- Uma URL por função — múltiplas funções ou monólito para múltiplas APIs

### Opção B: API Gateway (REST API) + Lambda

**Prós:**
- JWT Authorizer nativo
- Rate limiting via Usage Plans e API Keys
- WAF integrado

**Contras:**
- Custo: $3.50/million requests — 3.5× mais caro que HTTP API
- Sem documentação OpenAPI automática — precisa exportar e manter manualmente
- Configuração de routes e integration mais verbosa

### Opção C: FastAPI em ECS Fargate com ALB

**Prós:**
- Sem cold start, connection pool real para Aurora
- Health checks e rolling deploys via ALB

**Contras:**
- Custo fixo: 0.5 vCPU + 1GB RAM = ~$15/mês + ALB ~$16/mês = ~$31/mês fixo
- Cria terceiro paradigma de compute, violando coerência do ADR-001
- Auto-scaling de ECS tem latência de 2-5 minutos horizontalmente

### Opção D: API Gateway HTTP API + FastAPI/Mangum

Combinação: API Gateway HTTP API para JWT Authorizer e rate limiting nativos + FastAPI/Mangum para routing, validação Pydantic e geração de OpenAPI.

**Prós:**
- JWT Authorizer nativo: valida assinatura RS256 sem código na Lambda (~5ms, não 50-100ms)
- Rate limiting Elite via Usage Plans sem Redis externo
- Documentação OpenAPI gerada automaticamente pela FastAPI (em `/api/v1/docs`)
- WAF opcional na frente do API Gateway
- FastAPI mantém developer experience completo (type hints, Depends, middleware)
- Custo HTTP API: $1.00/million requests (vs. REST API $3.50)

**Contras:**
- Routes definidas no API Gateway E no FastAPI — risco de dessincronização
- JWT Authorizer do API Gateway e FastAPI Depends precisam estar alinhados em claims validation
- CORS precisa ser configurado em ambos

## Decisão

**Escolha: Opção D — API Gateway HTTP API + FastAPI/Mangum**

O JWT Authorizer nativo do API Gateway elimina a necessidade de Redis para blacklist de tokens — invalidação é feita via claim `exp` e JTI blocklist no DynamoDB (ver ADR-007). Rate limiting para Elite API Keys via Usage Plans é gerenciado pelo próprio AWS sem estado distribuído externo. A documentação OpenAPI do FastAPI é servida em `/api/v1/docs`.

**Estrutura de APIs:**
- `api.valuebetting.com` → API Gateway HTTP API → Lambda `api-main` (FastAPI + Mangum)
- `admin.valuebetting.com` → API Gateway HTTP API (resource policy: IP allowlist) → Lambda `api-admin` (FastAPI)
- `/api/v1/elite/*` → mesma Lambda `api-main`, API Key required, Usage Plan: 1000 req/hora

**Custo estimado para 1M req/mês:** API Gateway HTTP API $1.00 + Lambda execution ~$5.00 = $6/mês total.

## Consequências

**Positivas:**
- JWT validation offline via API Gateway Authorizer: sem round-trip ao banco por request
- Rate limiting Elite via AWS Usage Plans: sem estado distribuído no MVP
- OpenAPI/Swagger gerado automaticamente — documentação sempre sincronizada com código
- CloudWatch metrics por route no API Gateway para SLO tracking (ver ADR-008)

**Negativas / Trade-offs:**
- Routes duplicadas: definidas no API Gateway E no FastAPI — risco de dessincronização
- CORS configurado em dois lugares
- Cold start da Lambda `api-main` em idle → Provisioned Concurrency 3 instâncias (~$12/mês)

**Riscos e Mitigações:**
- Risco: JWT Authorizer valida token mas Lambda não re-valida claims de tier → Mitigação: FastAPI `Depends` extrai e re-valida `tier` claim em todas as rotas com autorização de feature
- Risco: API Key Elite exposta em logs → Mitigação: API Gateway masking de headers sensíveis; API Keys hasheadas em SHA-256 no DynamoDB (ver ADR-007)
- Risco: Routes do FastAPI não correspondem ao API Gateway → Mitigação: teste de contrato automatizado em CI valida que todas as routes FastAPI têm mapping no API Gateway

## Implementação

```python
# src/api/main.py
from fastapi import FastAPI, Depends
from mangum import Mangum
from .routers import auth, alerts, elite, backtesting
from .dependencies import verify_jwt, require_tier

app = FastAPI(
    title="Value Betting API",
    version="1.0.0",
    docs_url="/api/v1/docs",       # exposto apenas para Elite via API Gateway route
    openapi_url="/api/v1/openapi.json"
)

app.include_router(auth.router, prefix="/api/v1/auth")
app.include_router(alerts.router, prefix="/api/v1/alerts", dependencies=[Depends(verify_jwt)])
app.include_router(elite.router, prefix="/api/v1/elite", dependencies=[Depends(verify_api_key)])
app.include_router(backtesting.router, prefix="/api/v1/backtesting",
                   dependencies=[Depends(require_tier("elite"))])

# Mangum handler para Lambda
handler = Mangum(app, lifespan="off")
```

```python
# src/api/dependencies.py
from fastapi import HTTPException, Header, Security
from fastapi.security import APIKeyHeader
from .auth import decode_jwt, validate_api_key
from ..shared.models.user import UserTier

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_jwt(authorization: str = Header(...)) -> dict:
    token = authorization.removeprefix("Bearer ")
    claims = decode_jwt(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")
    return claims

async def require_tier(minimum_tier: str):
    async def _check(claims: dict = Depends(verify_jwt)) -> dict:
        if not UserTier(claims["tier"]).has_access(minimum_tier):
            raise HTTPException(status_code=403, detail="Tier insuficiente para este recurso")
        return claims
    return _check

async def verify_api_key(api_key: str = Security(api_key_header)) -> dict:
    user = await validate_api_key(api_key)
    if not user:
        raise HTTPException(status_code=401, detail="API Key inválida ou revogada")
    return user
```

```hcl
# Terraform — API Gateway HTTP API com JWT Authorizer
resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "jwt-authorizer"

  jwt_configuration {
    audience = [var.api_audience]
    issuer   = "https://${var.domain}/api/v1/auth"
  }
}

resource "aws_apigatewayv2_api" "admin" {
  name          = "value-betting-admin"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = [var.admin_origin]
    allow_methods = ["GET", "POST", "PUT", "DELETE"]
    allow_headers = ["Authorization", "Content-Type"]
  }
}
```
