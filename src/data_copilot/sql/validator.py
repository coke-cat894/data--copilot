"""PostgreSQL AST validation for a narrow read-only SQL policy."""

from collections.abc import Sequence

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError
from sqlglot.dialects.postgres import Postgres

from data_copilot.errors import (
    MultipleStatementsError,
    SQLParseError,
    UnsafeSQLError,
)
from data_copilot.sql.models import SQLStatementType, ValidatedSQL


_POSTGRES_DIALECT = "postgres"


class _PostgresValidationDialect(Postgres):
    """PostgreSQL dialect that does not log sqlglot's EXPLAIN fallback text."""

    class Parser(Postgres.Parser):
        def _parse_command(self) -> exp.Command:
            return self.expression(
                exp.Command,
                comments=self._prev_comments,
                this=self._prev.text.upper(),
                expression=self._parse_string(),
            )


# These node types are forbidden wherever they occur in the AST, not merely at
# the root. The explicit classes supplement DDL/DML because sqlglot does not
# derive every administrative expression from those common bases.
_UNSAFE_NODE_TYPES = (
    exp.DDL,
    exp.DML,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Revoke,
    exp.Copy,
    exp.Analyze,
    exp.Set,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Use,
    exp.Attach,
    exp.Detach,
    exp.Cache,
    exp.Uncache,
)

_UNSAFE_FUNCTION_NAMES = frozenset(
    {
        "lo_export",
        "lo_import",
        "nextval",
        "pg_advisory_lock",
        "pg_advisory_lock_shared",
        "pg_advisory_unlock",
        "pg_advisory_unlock_all",
        "pg_advisory_unlock_shared",
        "pg_cancel_backend",
        "pg_create_restore_point",
        "pg_export_snapshot",
        "pg_logical_emit_message",
        "pg_ls_dir",
        "pg_read_binary_file",
        "pg_read_file",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "pg_sleep",
        "pg_switch_wal",
        "pg_terminate_backend",
        "setval",
        "set_config",
    }
)


class SQLValidator:
    """Parse one PostgreSQL statement and enforce a full-tree read-only policy."""

    def validate(self, sql: str) -> ValidatedSQL:
        """Return typed normalized SQL or fail closed without executing it."""

        if not isinstance(sql, str) or not sql.strip():
            raise SQLParseError("SQL must contain exactly one statement.")

        expressions = _parse_statements(sql)
        root = _one_statement(expressions)
        is_explain = _is_explain(root)
        query = _explain_query(root) if is_explain else root

        if not isinstance(query, (exp.Select, exp.SetOperation)):
            statement_name = type(query).__name__.upper()
            raise UnsafeSQLError(
                f"Statement type {statement_name} is not allowed."
            )

        self._validate_tree(query)
        normalized_query = query.sql(
            dialect=_POSTGRES_DIALECT,
            pretty=False,
            comments=False,
        )
        normalized_sql = (
            f"EXPLAIN {normalized_query}" if is_explain else normalized_query
        )
        return ValidatedSQL(
            original_sql=sql,
            normalized_sql=normalized_sql,
            statement_type=SQLStatementType.SELECT,
            is_explain=is_explain,
        )

    @staticmethod
    def _validate_tree(root: exp.Expression) -> None:
        for node in root.walk():
            if isinstance(node, exp.Into):
                raise UnsafeSQLError("SELECT INTO is not allowed.")
            if isinstance(node, exp.Lock):
                raise UnsafeSQLError("Locking clauses are not allowed.")
            if isinstance(node, _UNSAFE_NODE_TYPES):
                raise UnsafeSQLError(
                    f"Statement type {type(node).__name__.upper()} is not allowed."
                )
            if isinstance(node, exp.Func):
                function_name = _function_name(node)
                if _is_unsafe_function(function_name):
                    raise UnsafeSQLError(
                        f"Function {function_name!r} is not allowed."
                    )


def _parse_statements(sql: str) -> list[exp.Expression | None]:
    try:
        return sqlglot.parse(
            sql,
            read=_PostgresValidationDialect,
            error_level=sqlglot.ErrorLevel.RAISE,
        )
    except (ParseError, TokenError, ValueError, TypeError):
        raise SQLParseError("SQL could not be parsed as PostgreSQL.") from None


def _one_statement(
    expressions: Sequence[exp.Expression | None],
) -> exp.Expression:
    # sqlglot represents a comment following a terminal semicolon as a separate
    # Semicolon expression. It is not a second SQL statement.
    if (
        len(expressions) == 2
        and isinstance(expressions[0], exp.Expression)
        and isinstance(expressions[1], exp.Semicolon)
    ):
        return expressions[0]
    if len(expressions) == 1 and expressions[0] is None:
        raise SQLParseError("SQL must contain exactly one statement.")
    if len(expressions) != 1 or not isinstance(expressions[0], exp.Expression):
        raise MultipleStatementsError("Exactly one SQL statement is allowed.")
    return expressions[0]


def _is_explain(root: exp.Expression) -> bool:
    return isinstance(root, exp.Command) and str(root.this).upper() == "EXPLAIN"


def _explain_query(root: exp.Expression) -> exp.Expression:
    expression = root.args.get("expression")
    if not isinstance(expression, exp.Literal) or not expression.is_string:
        raise SQLParseError("EXPLAIN could not be parsed safely.")
    inner_sql = str(expression.this)
    tokens = sqlglot.Dialect.get_or_raise(_POSTGRES_DIALECT).tokenize(inner_sql)
    if not tokens:
        raise SQLParseError("EXPLAIN must contain a SELECT statement.")
    first_token = tokens[0]
    if first_token.token_type in {
        sqlglot.TokenType.ANALYZE,
        sqlglot.TokenType.L_PAREN,
    }:
        raise UnsafeSQLError("EXPLAIN ANALYZE and EXPLAIN options are not allowed.")
    return _one_statement(_parse_statements(inner_sql))


def _function_name(function: exp.Func) -> str:
    name = function.name or function.sql_name()
    return str(name).strip('"').casefold()


def _is_unsafe_function(function_name: str) -> bool:
    return (
        function_name in _UNSAFE_FUNCTION_NAMES
        or function_name.startswith("dblink")
        or function_name.startswith("pg_advisory_")
        or function_name.startswith("pg_try_advisory_")
    )
