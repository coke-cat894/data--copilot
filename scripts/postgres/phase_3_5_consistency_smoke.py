"""Manual Phase 3.5 SemanticCatalog/PostgreSQL consistency smoke."""

from pathlib import Path

from data_copilot.config import load_environment, read_postgres_config
from data_copilot.databases import DatabaseRegistry
from data_copilot.evals.semantic_consistency import (
    check_semantic_database_consistency,
)
from data_copilot.execution import PostgresEngine
from data_copilot.semantics import SemanticCatalogLoader


PROJECT_ROOT = Path(__file__).parents[2]
SEMANTIC_FIXTURE = PROJECT_ROOT / "evals/fixtures/phase_3_semantic"
INTENTIONAL_MISMATCH = frozenset({"commerce.orders.margin_amount"})


def main() -> int:
    load_environment()
    config = read_postgres_config()
    registry = DatabaseRegistry()
    database = registry.register(
        config,
        display_name="Phase 3.5 Consistency Smoke",
    )
    catalog = SemanticCatalogLoader(SEMANTIC_FIXTURE).load()
    result = check_semantic_database_consistency(
        catalog,
        PostgresEngine(registry),
        database.database_id,
        expected_missing_fields=INTENTIONAL_MISMATCH,
    )

    for check in result.checks:
        if check.exists:
            outcome = "present"
        elif check.expected_missing:
            outcome = "expected-missing"
        else:
            outcome = "unexpected-missing"
        print(
            f"{check.definition_type} {check.definition_id} "
            f"field={check.field_reference} outcome={outcome}"
        )
    print(f"semantic_database_consistency={'passed' if result.passed else 'failed'}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
