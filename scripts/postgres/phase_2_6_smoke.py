"""Manual Phase 2.6 smoke and permission checks against local PostgreSQL."""

from collections.abc import Callable

import psycopg

from data_copilot.config import load_environment, read_postgres_config
from data_copilot.databases import DatabaseRegistry
from data_copilot.errors import UnsafeSQLError
from data_copilot.execution import PostgresEngine


def main() -> int:
    load_environment()
    config = read_postgres_config()
    registry = DatabaseRegistry()
    database = registry.register(config, display_name="Phase 2.6 Local Fixture")
    engine = PostgresEngine(registry)

    ping = engine.ping(database.database_id)
    tables = engine.list_tables(database.database_id)
    inspection = engine.inspect_table(
        database.database_id,
        schema_name="commerce",
        table_name="orders",
    )
    relationships = engine.get_relationships(
        database.database_id,
        schema_name="commerce",
        table_name="orders",
    )
    rows = engine.execute_read_query(
        database.database_id,
        "SELECT order_id, status FROM commerce.orders ORDER BY order_id LIMIT 3",
    )
    aggregate = engine.execute_read_query(
        database.database_id,
        "SELECT date_trunc('month', o.created_at) AS month, "
        "SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM commerce.orders AS o "
        "JOIN commerce.order_items AS oi ON oi.order_id = o.order_id "
        "WHERE o.status = 'completed' GROUP BY month ORDER BY month",
    )
    bounded = engine.execute_read_query(
        database.database_id,
        "SELECT value FROM generate_series(1, 250) AS value",
    )
    plan = engine.explain_query(
        database.database_id,
        "SELECT * FROM commerce.orders WHERE order_id = 1",
    )

    validator_blocked = False
    try:
        engine.execute_read_query(
            database.database_id,
            "DELETE FROM commerce.orders WHERE order_id = 1",
        )
    except UnsafeSQLError:
        validator_blocked = True

    checks = {
        "register": bool(database.database_id),
        "ping": ping.connected,
        "list_tables": len(tables.tables) == 5,
        "inspect_table": inspection.primary_key == ("order_id",),
        "get_relationships": len(relationships.relationships) >= 2,
        "select": rows.row_count == 3,
        "aggregate": aggregate.row_count == 4,
        "bounded_result": bounded.row_count == 200 and bounded.truncated,
        "explain_query": plan.node_count >= 1,
        "validator_mutation_block": validator_blocked,
    }
    for name, passed in checks.items():
        print(f"engine {name}={'passed' if passed else 'failed'}")

    permission_checks = (
        ("select", True, lambda cursor: cursor.execute("SELECT 1")),
        (
            "metadata",
            True,
            lambda cursor: cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables"
            ),
        ),
        (
            "aggregate",
            True,
            lambda cursor: cursor.execute(
                "SELECT SUM(quantity * unit_price) FROM commerce.order_items"
            ),
        ),
        (
            "explain",
            True,
            lambda cursor: cursor.execute(
                "EXPLAIN (FORMAT JSON) SELECT * FROM commerce.orders"
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
            "create_table",
            False,
            lambda cursor: cursor.execute(
                "CREATE TABLE commerce.blocked_create (id integer)"
            ),
        ),
        (
            "drop_table",
            False,
            lambda cursor: cursor.execute("DROP TABLE commerce.orders"),
        ),
        (
            "alter_table",
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
