from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | dict[str, Any] | None = None
    trace_id: str = Field(alias="traceId", default="")


class OffsetPagination(BaseModel):
    page: int = Field(ge=1, default=1)
    page_size: int = Field(ge=1, le=100, default=20)
    total_items: int = Field(ge=0, default=0)
    total_pages: int = Field(ge=0, default=0)


class CursorPagination(BaseModel):
    limit: int = 100
    cursor: str | None = None
    has_more: bool = False


class DataResponse[T](BaseModel):
    data: T


class PaginatedResponse[T](BaseModel):
    data: list[T]
    pagination: OffsetPagination


class CursorPaginatedResponse[T](BaseModel):
    data: list[T]
    pagination: CursorPagination
