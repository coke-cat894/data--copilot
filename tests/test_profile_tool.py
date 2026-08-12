from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pytest

from data_copilot.config import MAX_PROFILE_COLUMNS, MAX_TOP_VALUES
from data_copilot.datasets import DatasetRegistry
from data_copilot.errors import (
    ColumnNotFoundError,
    DatasetExecutionError,
    DatasetNotFoundError,
    InvalidProfileRequestError,
    ResourceLimitError,
)
from data_copilot.execution import (
    BooleanColumnProfile,
    CategoricalColumnProfile,
    DatetimeColumnProfile,
    LogicalColumnType,
    NumericColumnProfile,
    OtherColumnProfile,
)
from data_copilot.execution.type_system import classify_duckdb_type
from data_copilot.tools import ProfileDatasetResult, ProfileDatasetTool


def _profile_parquet(
    tmp_path: Path,
    parquet_factory: Callable[[Path, str], Path],
    query: str,
    *,
    columns: list[str] | None = None,
    top_k: int = 10,
) -> ProfileDatasetResult:
    path = parquet_factory(tmp_path / "profile.parquet", query)
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)
    return ProfileDatasetTool(registry)(
        dataset.dataset_id, columns=columns, top_k=top_k
    )


@pytest.mark.parametrize("key", ["csv", "parquet", "jsonl"])
def test_profile_dataset_integration_for_each_supported_format(
    sample_files: dict[str, Path], tmp_path: Path, key: str
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(sample_files[key])

    result = ProfileDatasetTool(registry)(
        dataset.dataset_id, columns=["order_id", "region"], top_k=2
    )

    assert isinstance(result, ProfileDatasetResult)
    assert result.dataset_id == dataset.dataset_id
    assert result.row_count == 3
    assert result.column_count == 3
    assert result.profiled_column_count == 2
    assert isinstance(result.columns[0], NumericColumnProfile)
    assert isinstance(result.columns[1], CategoricalColumnProfile)
    assert result.columns[1].top_values[0].value == "north"
    serialized = result.model_dump_json()
    assert "resolved_path" not in serialized
    assert str(sample_files[key]) not in serialized


def test_numeric_profile_is_exact_and_handles_nulls_and_negative_values(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _profile_parquet(
        tmp_path,
        parquet_factory,
        """
        SELECT * FROM (VALUES
            (-2::INTEGER), (0::INTEGER), (2::INTEGER),
            (4::INTEGER), (NULL::INTEGER)
        ) AS rows(metric)
        """,
    )

    profile = result.columns[0]
    assert isinstance(profile, NumericColumnProfile)
    assert profile.logical_type is LogicalColumnType.NUMERIC
    assert profile.null_count == 1
    assert profile.null_rate == pytest.approx(0.2)
    assert profile.distinct_count == 4
    assert profile.min == -2
    assert profile.max == 4
    assert profile.mean == pytest.approx(1.0)
    assert profile.median == pytest.approx(1.0)
    assert profile.p25 == pytest.approx(-0.5)
    assert profile.p75 == pytest.approx(2.5)


def test_categorical_profile_orders_ties_and_excludes_null(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _profile_parquet(
        tmp_path,
        parquet_factory,
        """
        SELECT * FROM (VALUES
            ('b'::VARCHAR), ('b'), ('a'), ('a'), ('c'), (NULL)
        ) AS rows(category)
        """,
        top_k=3,
    )

    profile = result.columns[0]
    assert isinstance(profile, CategoricalColumnProfile)
    assert profile.null_count == 1
    assert profile.null_rate == pytest.approx(1 / 6)
    assert profile.distinct_count == 3
    assert [value.value for value in profile.top_values] == ["a", "b", "c"]
    assert [value.count for value in profile.top_values] == [2, 2, 1]
    assert [value.rate for value in profile.top_values] == pytest.approx(
        [2 / 6, 2 / 6, 1 / 6]
    )
    assert all(value.value is not None for value in profile.top_values)


def test_datetime_profile_handles_date_and_timestamp(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _profile_parquet(
        tmp_path,
        parquet_factory,
        """
        SELECT * FROM (VALUES
            (DATE '2024-01-02', TIMESTAMP '2024-01-02 12:00:00'),
            (DATE '2024-01-01', TIMESTAMP '2024-01-03 08:30:00'),
            (NULL::DATE, NULL::TIMESTAMP)
        ) AS rows(event_date, event_at)
        """,
    )

    date_profile, timestamp_profile = result.columns
    assert isinstance(date_profile, DatetimeColumnProfile)
    assert date_profile.min == date(2024, 1, 1)
    assert date_profile.max == date(2024, 1, 2)
    assert date_profile.null_count == 1
    assert date_profile.null_rate == pytest.approx(1 / 3)
    assert date_profile.distinct_count == 2
    assert isinstance(timestamp_profile, DatetimeColumnProfile)
    assert timestamp_profile.min == datetime(2024, 1, 2, 12)
    assert timestamp_profile.max == datetime(2024, 1, 3, 8, 30)
    assert timestamp_profile.null_count == 1
    assert timestamp_profile.distinct_count == 2


def test_boolean_profile_counts_true_false_and_null(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _profile_parquet(
        tmp_path,
        parquet_factory,
        """
        SELECT * FROM (VALUES
            (TRUE), (TRUE), (FALSE), (NULL::BOOLEAN)
        ) AS rows(flag)
        """,
    )

    profile = result.columns[0]
    assert isinstance(profile, BooleanColumnProfile)
    assert profile.logical_type is LogicalColumnType.BOOLEAN
    assert profile.true_count == 2
    assert profile.false_count == 1
    assert profile.null_count == 1
    assert profile.null_rate == pytest.approx(0.25)
    assert profile.distinct_count == 2


def test_empty_dataset_returns_none_for_undefined_numeric_statistics(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _profile_parquet(
        tmp_path,
        parquet_factory,
        """
        SELECT CAST(NULL AS INTEGER) AS metric,
               CAST(NULL AS VARCHAR) AS label
        WHERE FALSE
        """,
    )

    numeric, categorical = result.columns
    assert result.row_count == 0
    assert isinstance(numeric, NumericColumnProfile)
    assert numeric.null_count == 0
    assert numeric.null_rate == 0.0
    assert numeric.distinct_count == 0
    assert numeric.min is None
    assert numeric.max is None
    assert numeric.mean is None
    assert numeric.median is None
    assert numeric.p25 is None
    assert numeric.p75 is None
    assert isinstance(categorical, CategoricalColumnProfile)
    assert categorical.top_values == ()


def test_all_null_and_constant_columns_are_profiled_without_nan(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _profile_parquet(
        tmp_path,
        parquet_factory,
        """
        SELECT CAST(NULL AS DOUBLE) AS all_null,
               CAST(NULL AS VARCHAR) AS optional_note,
               5::INTEGER AS constant
        FROM range(3)
        """,
    )

    all_null, optional_note, constant = result.columns
    assert isinstance(all_null, NumericColumnProfile)
    assert all_null.null_count == 3
    assert all_null.null_rate == 1.0
    assert all_null.distinct_count == 0
    assert all_null.min is None
    assert all_null.mean is None
    assert isinstance(optional_note, CategoricalColumnProfile)
    assert optional_note.null_count == 3
    assert optional_note.null_rate == 1.0
    assert optional_note.distinct_count == 0
    assert optional_note.top_values == ()
    assert isinstance(constant, NumericColumnProfile)
    assert constant.distinct_count == 1
    assert constant.min == 5
    assert constant.max == 5
    assert constant.mean == 5
    assert constant.p25 == 5
    assert constant.p75 == 5


def test_columns_none_caps_wide_dataset_and_returns_warning(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    aliases = ", ".join(f"{index} AS c{index}" for index in range(51))
    result = _profile_parquet(
        tmp_path, parquet_factory, f"SELECT {aliases}"
    )

    assert result.column_count == 51
    assert result.profiled_column_count == MAX_PROFILE_COLUMNS
    assert [profile.name for profile in result.columns] == [
        f"c{index}" for index in range(MAX_PROFILE_COLUMNS)
    ]
    assert result.warnings == (
        "Dataset has 51 columns. 50 columns were profiled because "
        "MAX_PROFILE_COLUMNS=50.",
    )


def test_explicit_columns_over_limit_fail_closed(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    aliases = ", ".join(f"{index} AS c{index}" for index in range(51))
    path = parquet_factory(tmp_path / "wide.parquet", f"SELECT {aliases}")
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)

    with pytest.raises(ResourceLimitError, match="MAX_PROFILE_COLUMNS=50"):
        ProfileDatasetTool(registry)(
            dataset.dataset_id, columns=[f"c{index}" for index in range(51)]
        )


def test_invalid_top_k_values_fail_closed(
    sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(sample_files["csv"])
    tool = ProfileDatasetTool(registry)

    with pytest.raises(ResourceLimitError, match="MAX_TOP_VALUES=20"):
        tool(dataset.dataset_id, top_k=MAX_TOP_VALUES + 1)
    with pytest.raises(InvalidProfileRequestError):
        tool(dataset.dataset_id, top_k=0)
    with pytest.raises(InvalidProfileRequestError):
        tool(dataset.dataset_id, top_k=True)


def test_unknown_and_duplicate_columns_fail_closed(
    sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(sample_files["csv"])
    tool = ProfileDatasetTool(registry)

    with pytest.raises(ColumnNotFoundError, match="missing"):
        tool(dataset.dataset_id, columns=["missing"])
    with pytest.raises(InvalidProfileRequestError, match="Duplicate"):
        tool(dataset.dataset_id, columns=["region", "region"])
    with pytest.raises(InvalidProfileRequestError, match="cannot be empty"):
        tool(dataset.dataset_id, columns=[])


def test_unknown_dataset_fails_closed(tmp_path: Path) -> None:
    tool = ProfileDatasetTool(DatasetRegistry(allowed_roots=[tmp_path]))

    with pytest.raises(DatasetNotFoundError):
        tool("ds_unknown")


def test_identifier_quoting_handles_reserved_and_unusual_column_names(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    names = ["order", "select", "user name", "amount$", "mixed-case", 'quote"name']
    result = _profile_parquet(
        tmp_path,
        parquet_factory,
        """
        SELECT
            1 AS "order",
            'selected' AS "select",
            'Ada' AS "user name",
            12.5 AS "amount$",
            TRUE AS "mixed-case",
            'quoted' AS "quote""name"
        """,
        columns=names,
    )

    assert [profile.name for profile in result.columns] == names
    assert result.profiled_column_count == len(names)


def test_uncommon_type_uses_safe_other_profile(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _profile_parquet(
        tmp_path,
        parquet_factory,
        "SELECT 'hello'::BLOB AS payload",
    )

    profile = result.columns[0]
    assert isinstance(profile, OtherColumnProfile)
    assert profile.logical_type is LogicalColumnType.OTHER
    assert profile.null_count == 0
    assert profile.null_rate == 0.0


def test_logical_type_classification_covers_common_duckdb_types() -> None:
    expected_types = {
        "TINYINT": LogicalColumnType.NUMERIC,
        "SMALLINT": LogicalColumnType.NUMERIC,
        "INTEGER": LogicalColumnType.NUMERIC,
        "BIGINT": LogicalColumnType.NUMERIC,
        "UTINYINT": LogicalColumnType.NUMERIC,
        "USMALLINT": LogicalColumnType.NUMERIC,
        "UINTEGER": LogicalColumnType.NUMERIC,
        "UBIGINT": LogicalColumnType.NUMERIC,
        "FLOAT": LogicalColumnType.NUMERIC,
        "DOUBLE": LogicalColumnType.NUMERIC,
        "REAL": LogicalColumnType.NUMERIC,
        "DECIMAL": LogicalColumnType.NUMERIC,
        "DECIMAL(18,2)": LogicalColumnType.NUMERIC,
        "VARCHAR": LogicalColumnType.CATEGORICAL,
        "DATE": LogicalColumnType.DATETIME,
        "TIMESTAMP": LogicalColumnType.DATETIME,
        "TIMESTAMP WITH TIME ZONE": LogicalColumnType.DATETIME,
        "TIME": LogicalColumnType.DATETIME,
        "BOOLEAN": LogicalColumnType.BOOLEAN,
        "BLOB": LogicalColumnType.OTHER,
        "INTEGER[]": LogicalColumnType.OTHER,
    }

    assert {
        duckdb_type: classify_duckdb_type(duckdb_type)
        for duckdb_type in expected_types
    } == expected_types


def test_profile_execution_error_does_not_expose_path(tmp_path: Path) -> None:
    path = tmp_path / "malformed.jsonl"
    path.write_text('{"value": 1}\nnot-json\n', encoding="utf-8")
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(path)

    with pytest.raises(DatasetExecutionError) as exc_info:
        ProfileDatasetTool(registry)(dataset.dataset_id)

    assert str(path) not in str(exc_info.value)


def test_profile_100k_rows_stays_on_duckdb_aggregate_path(
    tmp_path: Path, parquet_factory: Callable[[Path, str], Path]
) -> None:
    result = _profile_parquet(
        tmp_path,
        parquet_factory,
        """
        SELECT i::BIGINT AS id,
               ('group_' || ((i % 10)::VARCHAR)) AS category
        FROM range(100000) AS rows(i)
        """,
        columns=["id", "category"],
        top_k=10,
    )

    numeric, categorical = result.columns
    assert result.row_count == 100000
    assert isinstance(numeric, NumericColumnProfile)
    assert numeric.distinct_count == 100000
    assert isinstance(categorical, CategoricalColumnProfile)
    assert categorical.distinct_count == 10
    assert sum(item.count for item in categorical.top_values) == 100000


def test_profile_tool_accepts_no_path_or_sql_arguments(
    sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(sample_files["csv"])
    tool = ProfileDatasetTool(registry)

    with pytest.raises(TypeError):
        tool(dataset.dataset_id, path=sample_files["csv"])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        tool(dataset.dataset_id, sql="SELECT 1")  # type: ignore[call-arg]
