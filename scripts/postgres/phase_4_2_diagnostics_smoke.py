"""Focused Phase 4.2 diagnostics and read-only permission smoke."""

from collections.abc import Callable

import psycopg

from data_copilot.config import read_postgres_config
from data_copilot.databases import DatabaseRegistry
from data_copilot.diagnostics import (
    PostgresDiagnosticCollector,
    compare_snapshots,
)


def main() -> int:
    config = read_postgres_config()
    if config.database_name != "data_copilot_test":
        print(
            "safety fixture=failed expected_database=data_copilot_test; "
            "no diagnostic or permission checks were executed"
        )
        return 1
    registry = DatabaseRegistry()
    database = registry.register(config, display_name="Phase 4.2 Local Fixture")
    collector = PostgresDiagnosticCollector(registry)

    before = collector.collect(
        database.database_id,
        schema_name="commerce",
        table_name="orders",
    )
    after = collector.collect(
        database.database_id,
        schema_name="commerce",
        table_name="orders",
    )
    drift = compare_snapshots(before.snapshot, after.snapshot)
    columns = {column.name: column for column in before.snapshot.columns}
    checks = {
        "typed_snapshot": before.snapshot.dataset_id == "commerce.orders",
        "row_count": before.snapshot.row_count == 1200,
        "metadata": set(columns) == {"order_id", "user_id", "status", "created_at"},
        "null_stats": columns["status"].null_count == 0,
        "distinct_stats": columns["status"].distinct_count == 2,
        "numeric_range": columns["order_id"].min_value == 1
        and columns["order_id"].max_value == 1200,
        "datetime_range": columns["created_at"].min_value is not None
        and columns["created_at"].max_value is not None,
        "exact_duplicates": before.snapshot.duplicate_count == 0,
        "phase_4_1_compatibility": drift.findings == (),
    }
    for name, passed in checks.items():
        print(f"diagnostic {name}={'passed' if passed else 'failed'}")

    permission_checks = (
        (
            "select",
            True,
            lambda cursor: cursor.execute(
                "SELECT COUNT(*) FROM commerce.orders"
            ),
        ),
        (
            "insert",
            False,
            lambda cursor: cursor.execute(
                "INSERT INTO commerce.users VALUES "
                "(99999, 'Blocked', 'North', now())"
            ),
        ),
        (
            "update",
            False,
            lambda cursor: cursor.execute(
                "UPDATE commerce.orders SET status = 'cancelled' "
                "WHERE order_id = 1"
            ),
        ),
        (
            "delete",
            False,
            lambda cursor: cursor.execute(
                "DELETE FROM commerce.order_items WHERE order_item_id = 1"
            ),
        ),
        (
            "create",
            False,
            lambda cursor: cursor.execute(
                "CREATE TABLE commerce.blocked_create (id integer)"
            ),
        ),
        (
            "drop",
            False,
            lambda cursor: cursor.execute("DROP TABLE commerce.orders"),
        ),
        (
            "alter",
            False,
            lambda cursor: cursor.execute(
                "ALTER TABLE commerce.orders ADD COLUMN blocked integer"
            ),
        ),
    )
    permission_results = tuple(
        _permission_check(config.dsn, name, should_succeed, operation)
        for name, should_succeed, operation in permission_checks
    )
    return 0 if all(checks.values()) and all(permission_results) else 1


def _permission_check(
    dsn: str,
    name: str,
    should_succeed: bool,
    operation: Callable[[psycopg.Cursor[object]], object],
) -> bool:
    succeeded = False
    category = "none"
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            with connection.cursor() as cursor:
                operation(cursor)
        succeeded = True
    except psycopg.Error as exc:
        category = type(exc).__name__
    passed = succeeded is should_succeed
    outcome = "allowed" if succeeded else "blocked"
    print(
        f"permission {name}={'passed' if passed else 'failed'} "
        f"outcome={outcome} category={category}"
    )
    return passed


if __name__ == "__main__":
    raise SystemExit(main())
