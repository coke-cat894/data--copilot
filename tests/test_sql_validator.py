from unittest.mock import patch

import pytest

from data_copilot.errors import (
    MultipleStatementsError,
    SQLParseError,
    UnsafeSQLError,
)
from data_copilot.sql import SQLStatementType, SQLValidator, ValidatedSQL


@pytest.mark.parametrize(
    ("sql", "expected_normalized"),
    [
        ("SELECT * FROM orders", "SELECT * FROM orders"),
        (
            "SELECT o.id, c.name FROM orders o JOIN customers c "
            "ON c.id = o.customer_id",
            "SELECT o.id, c.name FROM orders AS o JOIN customers AS c "
            "ON c.id = o.customer_id",
        ),
        (
            "select region, count(*) from orders group by region",
            "SELECT region, COUNT(*) FROM orders GROUP BY region",
        ),
        (
            "WITH recent AS (SELECT * FROM orders WHERE created_at >= DATE "
            "'2026-01-01') SELECT * FROM recent",
            "WITH recent AS (SELECT * FROM orders WHERE created_at >= CAST("
            "'2026-01-01' AS DATE)) SELECT * FROM recent",
        ),
        (
            "SELECT id FROM current_orders UNION ALL SELECT id FROM old_orders",
            "SELECT id FROM current_orders UNION ALL SELECT id FROM old_orders",
        ),
    ],
)
def test_allows_read_only_select_forms(
    sql: str,
    expected_normalized: str,
) -> None:
    result = SQLValidator().validate(sql)

    assert isinstance(result, ValidatedSQL)
    assert result.original_sql == sql
    assert result.normalized_sql == expected_normalized
    assert result.statement_type is SQLStatementType.SELECT
    assert result.is_explain is False


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN SELECT * FROM orders",
        "explain select * from orders where id = 1",
        "/* plan only */ EXPLAIN WITH x AS (SELECT 1) SELECT * FROM x",
    ],
)
def test_allows_plain_explain_select(sql: str) -> None:
    result = SQLValidator().validate(sql)

    assert result.normalized_sql.startswith("EXPLAIN ")
    assert result.statement_type is SQLStatementType.SELECT
    assert result.is_explain is True


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders(id) VALUES (1)",
        "UPDATE orders SET status = 'done'",
        "DELETE FROM orders",
        "MERGE INTO orders o USING staged s ON o.id = s.id "
        "WHEN MATCHED THEN UPDATE SET status = s.status",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN note text",
        "CREATE TABLE copied AS SELECT * FROM orders",
        "TRUNCATE TABLE orders",
        "GRANT SELECT ON orders TO analyst",
        "REVOKE SELECT ON orders FROM analyst",
        "COPY orders TO STDOUT",
        "CALL rebuild_orders()",
        "DO $$ BEGIN RAISE NOTICE 'x'; END $$",
        "VACUUM orders",
        "ANALYZE orders",
        "REFRESH MATERIALIZED VIEW daily_orders",
        "SET search_path TO public",
        "RESET search_path",
        "LOCK TABLE orders IN ACCESS EXCLUSIVE MODE",
        "LISTEN order_updates",
        "NOTIFY order_updates",
    ],
)
def test_rejects_mutation_and_administration_statements(sql: str) -> None:
    with pytest.raises((UnsafeSQLError, SQLParseError)):
        SQLValidator().validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "WITH changed AS (DELETE FROM orders RETURNING *) SELECT * FROM changed",
        "WITH changed AS (UPDATE orders SET status = 'done' RETURNING *) "
        "SELECT * FROM changed",
        "WITH changed AS (INSERT INTO orders(id) VALUES (1) RETURNING *) "
        "SELECT * FROM changed",
        "WITH changed AS (MERGE INTO orders o USING staged s ON o.id = s.id "
        "WHEN MATCHED THEN DELETE RETURNING *) SELECT * FROM changed",
    ],
)
def test_rejects_writes_nested_anywhere_in_ast(sql: str) -> None:
    with pytest.raises(UnsafeSQLError, match="not allowed"):
        SQLValidator().validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE x",
        "; SELECT 1",
        "SELECT 1;;",
    ],
)
def test_rejects_multiple_or_empty_statement_slots(sql: str) -> None:
    with pytest.raises(MultipleStatementsError, match="Exactly one"):
        SQLValidator().validate(sql)


@pytest.mark.parametrize(
    "sql",
    ["", "   ", "\n\t", ";", "-- comment only", "/* comment only */"],
)
def test_rejects_empty_sql(sql: str) -> None:
    with pytest.raises(SQLParseError, match="exactly one"):
        SQLValidator().validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_catalog.pg_read_binary_file('/tmp/file')",
        "SELECT pg_ls_dir('/tmp')",
        "SELECT lo_import('/tmp/file')",
        "SELECT lo_export(123, '/tmp/file')",
        "SELECT dblink('connection', 'SELECT 1')",
        "SELECT public.dblink_connect('connection')",
        "SELECT dblinkcustom('connection')",
        "SELECT dblink_exec('connection', 'DELETE FROM x')",
        "SELECT nextval('orders_id_seq')",
        "SELECT setval('orders_id_seq', 10)",
        "SELECT pg_catalog.set_config('statement_timeout', '0', false)",
        "SELECT pg_advisory_lock(1)",
        "SELECT pg_try_advisory_xact_lock(1)",
        "SELECT pg_terminate_backend(123)",
        "SELECT pg_reload_conf()",
        "SELECT pg_logical_emit_message(true, 'prefix', 'message')",
        "SELECT pg_sleep(10)",
    ],
)
def test_rejects_explicitly_denied_functions(sql: str) -> None:
    with pytest.raises(UnsafeSQLError, match="Function"):
        SQLValidator().validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * INTO copied_orders FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT * FROM orders FOR NO KEY UPDATE",
        "SELECT * FROM orders FOR SHARE",
        "SELECT * FROM orders FOR KEY SHARE",
    ],
)
def test_rejects_select_write_adjacent_clauses(sql: str) -> None:
    with pytest.raises(UnsafeSQLError, match="not allowed"):
        SQLValidator().validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN ANALYZE SELECT * FROM orders",
        "EXPLAIN (ANALYZE TRUE) SELECT * FROM orders",
        "EXPLAIN (ANALYZE FALSE) SELECT * FROM orders",
        "EXPLAIN (COSTS FALSE) SELECT * FROM orders",
    ],
)
def test_rejects_explain_analyze_and_all_explain_options(sql: str) -> None:
    with pytest.raises(UnsafeSQLError, match="EXPLAIN"):
        SQLValidator().validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN DELETE FROM orders",
        "EXPLAIN UPDATE orders SET status = 'done'",
        "EXPLAIN WITH changed AS (DELETE FROM orders RETURNING *) "
        "SELECT * FROM changed",
    ],
)
def test_explain_inner_statement_gets_full_tree_validation(sql: str) -> None:
    with pytest.raises(UnsafeSQLError, match="not allowed"):
        SQLValidator().validate(sql)


@pytest.mark.parametrize(
    ("sql", "normalized"),
    [
        ("  select 1  ", "SELECT 1"),
        ("-- comment\nSeLeCt 1", "SELECT 1"),
        ("/* leading */ SELECT 1;", "SELECT 1"),
        ("SELECT 1; -- trailing", "SELECT 1"),
    ],
)
def test_parser_handles_comments_whitespace_case_and_terminal_semicolon(
    sql: str,
    normalized: str,
) -> None:
    result = SQLValidator().validate(sql)

    assert result.normalized_sql == normalized


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT FROM",
        "SELECT (",
        "WITH x AS SELECT 1 SELECT * FROM x",
        "EXPLAIN",
    ],
)
def test_rejects_malformed_sql_with_safe_parse_error(sql: str) -> None:
    with pytest.raises(SQLParseError) as captured:
        SQLValidator().validate(sql)

    assert "Line " not in str(captured.value)
    assert captured.value.__cause__ is None


def test_validation_does_not_connect_to_or_execute_against_postgresql() -> None:
    with patch("psycopg.connect") as connect:
        result = SQLValidator().validate("SELECT * FROM orders")

    connect.assert_not_called()
    assert result.normalized_sql == "SELECT * FROM orders"


def test_validator_exposes_no_execution_or_rewriting_api() -> None:
    validator = SQLValidator()

    assert not hasattr(validator, "execute")
    assert not hasattr(validator, "run_sql")
    assert not hasattr(validator, "rewrite")


def test_validated_sql_contains_no_database_or_execution_fields() -> None:
    dumped = SQLValidator().validate("SELECT 1").model_dump()

    assert set(dumped) == {
        "original_sql",
        "normalized_sql",
        "statement_type",
        "is_explain",
    }
    assert "database_id" not in dumped
    assert "result" not in dumped
