from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

_ENV = os.environ.get("VB_ENV", "dev")
_ADMIN_JWT_SECRET = os.environ.get("VB_ADMIN_JWT_SECRET", "")
if not _ADMIN_JWT_SECRET and _ENV != "dev":
    raise RuntimeError("VB_ADMIN_JWT_SECRET must be set in non-dev environments")
if not _ADMIN_JWT_SECRET:
    _ADMIN_JWT_SECRET = "dev-secret"
_JWT_ALGORITHM = "HS256"


async def verify_admin_jwt(
    authorization: str = Header(..., alias="Authorization"),
) -> dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou ausente",
        )
    token = authorization.removeprefix("Bearer ")
    try:
        payload = jwt.decode(token, _ADMIN_JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except JWTError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        ) from e
    role = payload.get("role")
    if role not in ("ops", "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissão insuficiente",
        )
    return payload


def _load_valid_api_keys() -> set[str]:
    raw = os.environ.get("VB_ELITE_API_KEYS", "")
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


_VALID_API_KEYS = _load_valid_api_keys()


async def verify_elite_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    if not x_api_key.startswith("vb_elite_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida",
        )
    if _VALID_API_KEYS and x_api_key not in _VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida",
        )
    if not _VALID_API_KEYS and _ENV != "dev":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API Key validation not configured",
        )
    return x_api_key


AdminAuth = Depends(verify_admin_jwt)
EliteAuth = Depends(verify_elite_api_key)
