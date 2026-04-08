from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mangum import Mangum

from value_betting_api.routers import collection

app = FastAPI(
    title="Value Betting API — M01 Odds Collection",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(
    collection.admin_router,
    prefix="/api/v1/admin/collection",
    tags=["Admin Collection"],
)
app.include_router(
    collection.elite_router,
    prefix="/api/v1/elite",
    tags=["Elite"],
)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "code": "VALIDATION_ERROR",
            "message": str(exc),
            "details": None,
            "traceId": _trace_id(request),
        },
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Any) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "code": "NOT_FOUND",
            "message": "Recurso não encontrado",
            "details": None,
            "traceId": _trace_id(request),
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "Erro interno do servidor",
            "details": None,
            "traceId": _trace_id(request),
        },
    )


def _trace_id(request: Request) -> str:
    return request.headers.get("x-amzn-trace-id", str(uuid.uuid4()))


mangum_handler = Mangum(app, lifespan="off")
