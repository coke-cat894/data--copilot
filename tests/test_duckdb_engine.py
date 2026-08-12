from pathlib import Path

import pytest

from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import DatasetExecutionError, DatasetNotFoundError
from data_copilot.execution import DuckDBEngine


@pytest.mark.parametrize("key", ["csv", "parquet", "jsonl"])
def test_register_then_inspect_supported_dataset(
    sample_files: dict[str, Path], tmp_path: Path, key: str
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(sample_files[key])
    engine = DuckDBEngine(registry)

    inspection = engine.inspect(dataset.dataset_id)

    assert inspection.row_count == 3
    assert inspection.column_count == 3
    assert [column.name for column in inspection.columns] == [
        "order_id",
        "amount",
        "region",
    ]
    assert all(column.duckdb_type for column in inspection.columns)
    assert inspection.columns[0].duckdb_type in {"BIGINT", "INTEGER"}
    amount_type = inspection.columns[1].duckdb_type
    assert amount_type == "DOUBLE" or amount_type.startswith("DECIMAL(")
    assert inspection.columns[2].duckdb_type == "VARCHAR"


def test_engine_unknown_dataset_id_fails_closed(tmp_path: Path) -> None:
    engine = DuckDBEngine(DatasetRegistry(allowed_roots=[tmp_path]))

    with pytest.raises(DatasetNotFoundError):
        engine.inspect("ds_unknown")


def test_engine_exposes_no_arbitrary_sql_api(tmp_path: Path) -> None:
    engine = DuckDBEngine(DatasetRegistry(allowed_roots=[tmp_path]))

    assert not hasattr(engine, "run_sql")
    assert not hasattr(engine, "execute_sql")


def test_malformed_jsonl_returns_safe_domain_error(tmp_path: Path) -> None:
    path = tmp_path / "malformed.jsonl"
    path.write_text('{"value": 1}\nnot-json\n', encoding="utf-8")
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)
    engine = DuckDBEngine(registry)

    with pytest.raises(DatasetExecutionError) as exc_info:
        engine.inspect(dataset.dataset_id)

    assert str(path) not in str(exc_info.value)
