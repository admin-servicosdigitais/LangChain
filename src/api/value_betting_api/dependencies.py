from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt

_ADMIN_JWT_SECRET = os.environ.get("VB_ADMIN_JWT_SECRET", "dev-secret")
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token inválido: {e}",
        ) from e
    role = payload.get("role")
    if role not in ("ops", "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissão insuficiente",
        )
    return payload


async def verify_elite_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> str:
    if not x_api_key.startswith("vb_elite_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida",
        )
    return x_api_key


AdminAuth = Depends(verify_admin_jwt)
EliteAuth = Depends(verify_elite_api_key)
