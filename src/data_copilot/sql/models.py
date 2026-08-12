"""Typed results from deterministic SQL validation."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class SQLStatementType(str, Enum):
    """Statement types accepted by the Phase 2.3 policy."""

    SELECT = "select"


class ValidatedSQL(BaseModel):
    """One parsed SQL statement approved by the read-only policy."""

    model_config = ConfigDict(frozen=True)

    original_sql: str
    normalized_sql: str
    statement_type: SQLStatementType
    is_explain: bool
