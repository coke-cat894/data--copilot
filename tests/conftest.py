from collections.abc import Callable, Iterator
import json
from pathlib import Path

import duckdb
import pytest


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


@pytest.fixture
def parquet_factory() -> Callable[[Path, str], Path]:
    """Create a typed Parquet fixture from a deterministic DuckDB query."""

    def create(path: Path, query: str) -> Path:
        connection = duckdb.connect(database=":memory:")
        try:
            escaped_path = str(path).replace("'", "''")
            connection.execute(
                f"COPY ({query}) TO '{escaped_path}' (FORMAT PARQUET)"
            )
        finally:
            connection.close()
        return path

    return create


@pytest.fixture
def sample_files(tmp_path: Path) -> Iterator[dict[str, Path]]:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "order_id,amount,region\n1,10.5,north\n2,20.0,south\n3,7.25,north\n",
        encoding="utf-8",
    )

    jsonl_path = tmp_path / "sample.jsonl"
    jsonl_path.write_text(
        '{"order_id":1,"amount":10.5,"region":"north"}\n'
        '{"order_id":2,"amount":20.0,"region":"south"}\n'
        '{"order_id":3,"amount":7.25,"region":"north"}\n',
        encoding="utf-8",
    )

    parquet_path = tmp_path / "sample.parquet"
    connection = duckdb.connect(database=":memory:")
    try:
        escaped_path = str(parquet_path).replace("'", "''")
        connection.execute(
            "COPY (SELECT * FROM (VALUES "
            "(1, 10.5, 'north'), "
            "(2, 20.0, 'south'), "
            "(3, 7.25, 'north')"
            ") AS rows(order_id, amount, region)) "
            f"TO '{escaped_path}' (FORMAT PARQUET)"
        )
    finally:
        connection.close()

    yield {"csv": csv_path, "parquet": parquet_path, "jsonl": jsonl_path}


@pytest.fixture
def query_sample_files(tmp_path: Path) -> dict[str, Path]:
    """Equivalent CSV, Parquet, and JSONL fixtures for Phase 1.3 queries."""

    columns = [
        "id",
        "user_id",
        "region",
        "status",
        "amount",
        "created_at",
        "optional_note",
        "active",
    ]
    rows = [
        (1, "u1", "north", "completed", 10, "2024-01-05", "n1", True),
        (2, "u2", "south", "completed", 20, "2024-01-20", None, False),
        (3, "u1", "north", "pending", 30, "2024-02-01", "n3", True),
        (4, "u3", "east", "completed", -5, "2024-02-10", None, None),
        (5, "u4", "south", "completed", 40, "2024-03-15", "n5", False),
        (6, "u5", "north", "canceled", 0, "2024-04-01", "n6", True),
        (
            7,
            "u6",
            "west",
            "Robert'); DROP TABLE x;--",
            50,
            "2024-05-01",
            "n7",
            False,
        ),
        (8, "u7", "north", "completed", 60, "2024-06-01", None, True),
    ]

    csv_path = tmp_path / "query_sample.csv"
    csv_lines = [",".join(columns)]
    csv_lines.extend(
        ",".join(_csv_cell(value) for value in row)
        for row in rows
    )
    csv_path.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

    jsonl_path = tmp_path / "query_sample.jsonl"
    jsonl_path.write_text(
        "\n".join(
            json.dumps(dict(zip(columns, row, strict=True))) for row in rows
        )
        + "\n",
        encoding="utf-8",
    )

    parquet_path = tmp_path / "query_sample.parquet"
    connection = duckdb.connect(database=":memory:")
    try:
        escaped_path = str(parquet_path).replace("'", "''")
        connection.execute(
            """
            CREATE TABLE query_sample (
                id INTEGER,
                user_id VARCHAR,
                region VARCHAR,
                status VARCHAR,
                amount INTEGER,
                created_at DATE,
                optional_note VARCHAR,
                active BOOLEAN
            )
            """
        )
        connection.executemany(
            "INSERT INTO query_sample VALUES (?, ?, ?, ?, ?, ?::DATE, ?, ?)", rows
        )
        connection.execute(
            f"COPY query_sample TO '{escaped_path}' (FORMAT PARQUET)"
        )
    finally:
        connection.close()

    return {"csv": csv_path, "parquet": parquet_path, "jsonl": jsonl_path}
