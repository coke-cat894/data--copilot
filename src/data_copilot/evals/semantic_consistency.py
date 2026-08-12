"""Bounded Phase 3 eval check for declared semantic fields in PostgreSQL."""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from data_copilot.execution import PostgresEngine
from data_copilot.semantics import SemanticCatalog


class SemanticFieldCheck(BaseModel):
    """One safe field-reference observation from database metadata."""

    model_config = ConfigDict(frozen=True)

    definition_type: str
    definition_id: str
    field_reference: str
    exists: bool
    expected_missing: bool


class SemanticDatabaseConsistencyResult(BaseModel):
    """Summary that distinguishes fixture mismatches from regressions."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    checks: tuple[SemanticFieldCheck, ...]
    unexpected_missing_fields: tuple[str, ...]
    expected_missing_fields_found: tuple[str, ...]


def check_semantic_database_consistency(
    catalog: SemanticCatalog,
    engine: PostgresEngine,
    database_id: str,
    *,
    expected_missing_fields: Iterable[str] = (),
) -> SemanticDatabaseConsistencyResult:
    """Verify configured field references without creating a sync subsystem."""

    expected_missing = frozenset(expected_missing_fields)
    declarations = _field_declarations(catalog)
    declared_fields = {field for _, _, field in declarations}
    if not expected_missing.issubset(declared_fields):
        raise ValueError("Expected missing fields must be declared by the catalog.")

    columns_by_table: dict[tuple[str, str], frozenset[str]] = {}
    checks: list[SemanticFieldCheck] = []
    for definition_type, definition_id, field_reference in declarations:
        schema_name, table_name, column_name = field_reference.split(".")
        table_key = (schema_name, table_name)
        if table_key not in columns_by_table:
            inspection = engine.inspect_table(
                database_id,
                schema_name=schema_name,
                table_name=table_name,
            )
            columns_by_table[table_key] = frozenset(
                column.name for column in inspection.columns
            )
        checks.append(
            SemanticFieldCheck(
                definition_type=definition_type,
                definition_id=definition_id,
                field_reference=field_reference,
                exists=column_name in columns_by_table[table_key],
                expected_missing=field_reference in expected_missing,
            )
        )

    unexpected_missing = tuple(
        check.field_reference
        for check in checks
        if not check.exists and not check.expected_missing
    )
    expected_found = tuple(
        check.field_reference
        for check in checks
        if check.exists and check.expected_missing
    )
    return SemanticDatabaseConsistencyResult(
        passed=not unexpected_missing and not expected_found,
        checks=tuple(checks),
        unexpected_missing_fields=unexpected_missing,
        expected_missing_fields_found=expected_found,
    )


def _field_declarations(
    catalog: SemanticCatalog,
) -> tuple[tuple[str, str, str], ...]:
    declarations: list[tuple[str, str, str]] = []
    for metric in catalog.metrics:
        for field_reference in (*metric.required_fields, *metric.optional_filters):
            declarations.append(("metric", metric.metric_id, field_reference))
    for dimension in catalog.dimensions:
        for field_reference in dimension.source_fields:
            declarations.append(
                ("dimension", dimension.dimension_id, field_reference)
            )
    return tuple(declarations)
