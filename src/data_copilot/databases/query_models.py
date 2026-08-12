"""Typed bounded PostgreSQL read-query results."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class DatabaseQueryResult(BaseModel):
    """Bounded rows from one validated read-only PostgreSQL query."""

    model_config = ConfigDict(frozen=True)

    database_id: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    truncated: bool
    warnings: tuple[str, ...] = ()
