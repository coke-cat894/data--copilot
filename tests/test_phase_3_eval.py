from pathlib import Path
from unittest.mock import MagicMock

from data_copilot.databases import (
    ColumnMetadata,
    TableInspectionResult,
    TableType,
)
from data_copilot.documents import (
    BusinessDocumentChunker,
    BusinessDocumentIndex,
    BusinessDocumentLoader,
)
from data_copilot.evals.semantic_consistency import (
    check_semantic_database_consistency,
)
from data_copilot.execution import PostgresEngine
from data_copilot.semantics import SemanticCatalogLoader


PROJECT_ROOT = Path(__file__).parents[1]
SEMANTIC_FIXTURE = PROJECT_ROOT / "evals/fixtures/phase_3_semantic"
DOCUMENT_FIXTURE = PROJECT_ROOT / "evals/fixtures/phase_3_documents"
INTENTIONAL_MISMATCH = ("commerce.orders.margin_amount",)


def _inspection(
    schema_name: str,
    table_name: str,
    columns: tuple[str, ...],
) -> TableInspectionResult:
    return TableInspectionResult(
        schema_name=schema_name,
        table_name=table_name,
        table_type=TableType.TABLE,
        columns=tuple(
            ColumnMetadata(name=name, postgres_type="text", nullable=False)
            for name in columns
        ),
        primary_key=(),
        foreign_keys=(),
        basic_indexes=(),
        truncated=False,
    )


def _engine(*, include_margin: bool = False) -> MagicMock:
    engine = MagicMock(spec=PostgresEngine)
    tables = {
        ("commerce", "orders"): _inspection(
            "commerce",
            "orders",
            (
                "order_id",
                "status",
                "created_at",
                *(("margin_amount",) if include_margin else ()),
            ),
        ),
        ("commerce", "order_items"): _inspection(
            "commerce", "order_items", ("quantity", "unit_price")
        ),
        ("commerce", "users"): _inspection(
            "commerce", "users", ("region",)
        ),
    }
    engine.inspect_table.side_effect = (
        lambda _database_id, *, schema_name, table_name: tables[
            (schema_name, table_name)
        ]
    )
    return engine


def test_phase_3_catalog_matches_database_except_isolated_mismatch() -> None:
    catalog = SemanticCatalogLoader(SEMANTIC_FIXTURE).load()
    engine = _engine()

    result = check_semantic_database_consistency(
        catalog,
        engine,
        "db_test",
        expected_missing_fields=INTENTIONAL_MISMATCH,
    )

    assert result.passed is True
    assert len(result.checks) == 7
    assert result.unexpected_missing_fields == ()
    assert result.expected_missing_fields_found == ()
    mismatch = next(
        check
        for check in result.checks
        if check.field_reference == "commerce.orders.margin_amount"
    )
    assert mismatch.exists is False
    assert mismatch.expected_missing is True
    assert engine.inspect_table.call_count == 3


def test_consistency_smoke_fails_if_controlled_mismatch_stops_being_a_mismatch() -> None:
    catalog = SemanticCatalogLoader(SEMANTIC_FIXTURE).load()

    result = check_semantic_database_consistency(
        catalog,
        _engine(include_margin=True),
        "db_test",
        expected_missing_fields=INTENTIONAL_MISMATCH,
    )

    assert result.passed is False
    assert result.expected_missing_fields_found == (
        "commerce.orders.margin_amount",
    )


def test_phase_3_documents_cover_policy_conflict_injection_and_irrelevant_text() -> None:
    documents = BusinessDocumentLoader(DOCUMENT_FIXTURE).load()
    index = BusinessDocumentIndex(BusinessDocumentChunker().chunk(documents))

    policy = index.search("cancelled revenue fulfillment", top_k=1)
    conflict = index.search("historical cancelled revenue", top_k=1)
    injection = index.search("evidence handling delete", top_k=1)

    assert policy[0].logical_source == "revenue_policy.md"
    assert conflict[0].logical_source == "historical_revenue.md"
    assert injection[0].logical_source == "evidence_safety.txt"
    assert any(
        document.logical_source == "warehouse_maintenance.txt"
        for document in documents
    )
