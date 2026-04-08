# ADR-007: Autenticação e Autorização

**Status:** Accepted  
**Data:** 2026-04-06  
**Deciders:** Equipe de Arquitetura  
**Módulos Afetados:** M04 (auth), M06 (admin MFA), Elite (API Keys), M03 (throttling por tier)

## Contexto

O sistema tem três superfícies de autenticação com requisitos distintos:

1. **Usuário web/mobile** (Free, Pro, Elite): JWT stateless com refresh tokens. Invalidação obrigatória em downgrade de tier — Elite→Pro não pode usar recursos Elite após downgrade.
2. **API Elite** (programática): API Keys de longa duração com rate limiting rigoroso. Rotação por usuário. Risco de exposição em logs.
3. **Admin** (M06): MFA obrigatório TOTP, acesso de IP restrito, audit log de todas as ações.

O problema central do JWT stateless: tokens são válidos até expirar, mesmo após downgrade ou banimento. Um usuário Elite que faz downgrade às 14:00 manteria acesso Elite até às 14:15 (TTL do access token). Para recursos caros (API Elite, webhooks, exportação CSV), 15 minutos de acesso indevido é inaceitável.

LGPD compliance requer: direito ao esquecimento (deletar dados do usuário) e invalidação de todos os tokens associados.

## Opções Consideradas

### Opção A: JWT Stateless Puro (sem invalidação server-side)

**Prós:**
- Sem round-trip ao banco para validar token — latência mínima
- Escala horizontal sem estado compartilhado
- Implementação simples

**Contras:**
- Impossível invalidar token antes do `exp` — downgrade de tier mantém acesso por até 15min no access token
- Logout não revoga token — session hijacking persiste até expiração
- Não atende ao requisito de invalidação imediata do JWT claim de tier após downgrade

### Opção B: Sessões Server-Side (Redis/DynamoDB)

**Prós:**
- Invalidação imediata via delete da sessão
- Logout real
- Controle total sobre sessão ativa

**Contras:**
- Round-trip ao Redis/DynamoDB em todo request — +5-20ms de latência
- Estado distribuído: Redis requer ElastiCache (~$15/mês mínimo)
- Não aproveita JWT Authorizer nativo do API Gateway (ver ADR-004)

### Opção C: JWT Stateless com JTI Blocklist Seletiva para Refresh Tokens

**Prós:**
- Access tokens de vida curta (15 minutos): janela de exposição máxima em downgrade = 15min
- Refresh tokens de vida longa (7 dias) com JTI registrado em DynamoDB
- Invalidação de refresh token imediata via DynamoDB delete por `jti`
- Em downgrade: novo access token (com novo claim `tier`) emitido apenas via refresh token — que pode ser invalidado server-side
- JWT Authorizer do API Gateway valida assinatura sem round-trip ao banco na maioria dos requests
- JTI blocklist em DynamoDB com TTL = exp do token — cleanup automático

**Contras:**
- Access token ainda válido por até 15min após downgrade (janela aceitável de negócio)
- Lambda de refresh precisa checar DynamoDB (jti blocklist) — +5-10ms para operação de refresh
- Múltiplos dispositivos requerem múltiplos refresh tokens por usuário

## Decisão

**Escolha: Opção C — JWT Stateless com JTI Blocklist para Refresh Tokens**

A janela de 15 minutos de access token é um trade-off aceitável. Durante downgrade, o sistema invalida o refresh token imediatamente, forçando re-login para obter access token com tier correto. Para recursos Elite de alto valor (exportação em massa, API Key programática), verificação adicional de tier diretamente no Aurora pode ser adicionada como guard extra.

**Token strategy:**
- **Access token**: JWT RS256, TTL=15min, claims: `user_id`, `tier`, `jti`, `exp`, `iss`
- **Refresh token**: JWT RS256, TTL=7 dias, claims: `user_id`, `jti`, `exp`, `type: refresh`. JTI registrado em DynamoDB `refresh_tokens` com TTL automático
- **API Key Elite**: `vb_elite_` + 32 chars (`secrets.token_urlsafe(32)`). SHA-256 hash armazenado no DynamoDB. Apresentado em plain-text apenas uma vez na criação. Rate limit: 1000 req/hora via API Gateway Usage Plan

**Admin MFA:**
- TOTP (RFC 6238) via `pyotp`. Seed armazenado encriptado em Secrets Manager
- Login admin: email+senha → challenge TOTP → JWT de admin com `role=admin` e TTL=4h
- IP whitelist: resource policy no API Gateway Admin restrito a IPs do office/VPN (ver ADR-004)

## Consequências

**Positivas:**
- API Gateway JWT Authorizer valida assinatura sem DynamoDB — latência de auth ~5ms por request
- Refresh token blocklist previne acesso após logout ou downgrade
- API Keys Elite hasheadas — exposição em log não compromete a chave
- TTL automático no DynamoDB limpa JTIs expirados sem job de limpeza

**Negativas / Trade-offs:**
- Janela de 15min de access token válido após downgrade: documentar como comportamento esperado
- Múltiplos dispositivos por usuário: limitar a 5 refresh tokens ativos por `user_id`
- TOTP MFA requer que admin configure authenticator app no onboarding

**Riscos e Mitigações:**
- Risco: Access token vazado em log via header `Authorization` → Mitigação: API Gateway log masking; Lambda middleware nunca loga o header completo; tokens em URL são proibidos
- Risco: API Key Elite exposta em git acidentalmente → Mitigação: Plain-text mostrado apenas uma vez na criação; rotação disponível no dashboard Elite; scanning de secrets no CI via `git-secrets`
- Risco: Ataque de força bruta no login admin → Mitigação: Rate limiting no API Gateway (100 req/min por IP em `/admin/auth`); lockout após 5 tentativas por 15 minutos (DynamoDB counter com TTL)
- Risco: LGPD — deletar usuário requer invalidar todos os tokens → Mitigação: Soft delete com `deleted_at` + `invalidate_all_user_tokens(user_id)` invalidando todos os JTIs do usuário

## Implementação

```python
# src/auth/tokens.py
import jwt
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

def create_access_token(user_id: str, tier: str, private_key: bytes) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tier": tier,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "iss": "value-betting-api"
    }
    return jwt.encode(payload, private_key, algorithm="RS256")

def create_refresh_token(user_id: str, private_key: bytes) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(days=7),
        "type": "refresh"
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token, jti

def hash_api_key(plain_key: str) -> str:
    return hashlib.sha256(plain_key.encode()).hexdigest()

def generate_api_key() -> tuple[str, str]:
    """Retorna (plain_key para mostrar uma vez, hashed_key para armazenar)."""
    plain = f"vb_elite_{secrets.token_urlsafe(32)}"
    return plain, hash_api_key(plain)
```

```python
# src/auth/invalidation.py
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('refresh_tokens')

def register_refresh_token(user_id: str, jti: str, exp: datetime) -> None:
    table.put_item(Item={
        "jti": jti,
        "user_id": user_id,
        "expires_at": int(exp.timestamp()),  # TTL DynamoDB
        "created_at": datetime.now(timezone.utc).isoformat()
    })

def invalidate_refresh_token(jti: str) -> None:
    table.delete_item(Key={"jti": jti})

def invalidate_all_user_tokens(user_id: str) -> int:
    """Invalida todos os refresh tokens de um usuário (downgrade, banimento, LGPD)."""
    response = table.query(
        IndexName="user_id-index",
        KeyConditionExpression="user_id = :uid",
        ExpressionAttributeValues={":uid": user_id}
    )
    count = 0
    for item in response['Items']:
        table.delete_item(Key={"jti": item['jti']})
        count += 1
    return count

def is_refresh_token_valid(jti: str) -> bool:
    response = table.get_item(Key={"jti": jti})
    return 'Item' in response
```

```python
# src/auth/mfa.py
import pyotp
import boto3
import base64

def generate_totp_secret() -> str:
    return pyotp.random_base32()

def verify_totp(secret: str, token: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(token, valid_window=1)  # ±30s de tolerância

def get_admin_totp_secret(admin_id: str) -> str:
    sm = boto3.client('secretsmanager')
    response = sm.get_secret_value(SecretId=f"admin-totp-{admin_id}")
    return response['SecretString']
```
