"""Pure deterministic comparison of validated diagnostic snapshots."""

from datetime import date, datetime
from decimal import Decimal
import math

from data_copilot.diagnostics.constants import (
    PERCENTAGE_DECIMAL_PLACES,
)
from data_copilot.diagnostics.models import (
    ColumnSnapshot,
    DatasetSnapshot,
    DriftFinding,
    DriftReport,
    DriftType,
    FindingValue,
    RangeValue,
)
from data_copilot.errors import SnapshotComparisonError


class DriftDetector:
    """Compare validated snapshots without thresholds or interpretation."""

    def compare(
        self, before: DatasetSnapshot, after: DatasetSnapshot
    ) -> DriftReport:
        return compare_snapshots(before, after)


def compare_snapshots(
    before: DatasetSnapshot, after: DatasetSnapshot
) -> DriftReport:
    """Return every comparable observed change in canonical order."""

    if before.dataset_id != after.dataset_id:
        raise SnapshotComparisonError(
            "Cannot compare snapshots with different dataset identities."
        )

    before_columns = {column.name: column for column in before.columns}
    after_columns = {column.name: column for column in after.columns}
    before_names = set(before_columns)
    after_names = set(after_columns)
    common_names = sorted(before_names & after_names)
    findings: list[DriftFinding] = []

    for name in sorted(after_names - before_names):
        column = after_columns[name]
        findings.append(
            _finding(
                DriftType.COLUMN_ADDED,
                column_name=name,
                before_value=None,
                after_value=column.data_type,
                description=(
                    f"column {_quote(name)} was added with data_type "
                    f"{_quote(column.data_type)}"
                ),
            )
        )
    for name in sorted(before_names - after_names):
        column = before_columns[name]
        findings.append(
            _finding(
                DriftType.COLUMN_REMOVED,
                column_name=name,
                before_value=column.data_type,
                after_value=None,
                description=(
                    f"column {_quote(name)} with data_type "
                    f"{_quote(column.data_type)} was removed"
                ),
            )
        )

    for name in common_names:
        old = before_columns[name]
        new = after_columns[name]
        if old.data_type != new.data_type:
            findings.append(
                _finding(
                    DriftType.DATA_TYPE_CHANGED,
                    column_name=name,
                    before_value=old.data_type,
                    after_value=new.data_type,
                    description=(
                        f"data_type for {_quote(name)} changed from "
                        f"{_quote(old.data_type)} to {_quote(new.data_type)}"
                    ),
                )
            )
    for name in common_names:
        old = before_columns[name]
        new = after_columns[name]
        if (
            old.nullable is not None
            and new.nullable is not None
            and old.nullable != new.nullable
        ):
            findings.append(
                _finding(
                    DriftType.NULLABLE_CHANGED,
                    column_name=name,
                    before_value=old.nullable,
                    after_value=new.nullable,
                    description=(
                        f"nullable for {_quote(name)} changed from "
                        f"{str(old.nullable).lower()} to {str(new.nullable).lower()}"
                    ),
                )
            )

    if before.row_count != after.row_count:
        findings.append(_count_finding(
            DriftType.ROW_COUNT_CHANGED,
            "row_count",
            before.row_count,
            after.row_count,
        ))

    for name in common_names:
        old = before_columns[name]
        new = after_columns[name]
        if (
            old.null_count is not None
            and new.null_count is not None
            and old.null_count != new.null_count
        ):
            findings.append(
                _count_finding(
                    DriftType.NULL_COUNT_CHANGED,
                    "null_count",
                    old.null_count,
                    new.null_count,
                    column_name=name,
                )
            )
    for name in common_names:
        old = before_columns[name]
        new = after_columns[name]
        if (
            old.null_rate is not None
            and new.null_rate is not None
            and old.null_rate != new.null_rate
        ):
            findings.append(
                _rate_finding(
                    DriftType.NULL_RATE_CHANGED,
                    "null_rate",
                    old.null_rate,
                    new.null_rate,
                    column_name=name,
                )
            )
    for name in common_names:
        old = before_columns[name]
        new = after_columns[name]
        if (
            old.distinct_count is not None
            and new.distinct_count is not None
            and old.distinct_count != new.distinct_count
        ):
            findings.append(
                _count_finding(
                    DriftType.DISTINCT_COUNT_CHANGED,
                    "distinct_count",
                    old.distinct_count,
                    new.distinct_count,
                    column_name=name,
                )
            )

    if (
        before.duplicate_count is not None
        and after.duplicate_count is not None
        and before.duplicate_count != after.duplicate_count
    ):
        findings.append(
            _count_finding(
                DriftType.DUPLICATE_COUNT_CHANGED,
                "duplicate_count",
                before.duplicate_count,
                after.duplicate_count,
            )
        )
    if (
        before.duplicate_rate is not None
        and after.duplicate_rate is not None
        and before.duplicate_rate != after.duplicate_rate
    ):
        findings.append(
            _rate_finding(
                DriftType.DUPLICATE_RATE_CHANGED,
                "duplicate_rate",
                before.duplicate_rate,
                after.duplicate_rate,
            )
        )

    for drift_type, attribute, label in (
        (DriftType.MIN_VALUE_CHANGED, "min_value", "minimum"),
        (DriftType.MAX_VALUE_CHANGED, "max_value", "maximum"),
    ):
        for name in common_names:
            old_column = before_columns[name]
            new_column = after_columns[name]
            old_value = getattr(old_column, attribute)
            new_value = getattr(new_column, attribute)
            if old_value is None or new_value is None or old_value == new_value:
                continue
            _ensure_comparable_range(name, old_value, new_value)
            findings.append(
                _range_finding(
                    drift_type,
                    label,
                    name,
                    old_value,
                    new_value,
                )
            )

    return DriftReport(
        dataset_id=before.dataset_id,
        before_snapshot_id=before.snapshot_id,
        after_snapshot_id=after.snapshot_id,
        before_captured_at=before.captured_at,
        after_captured_at=after.captured_at,
        findings=tuple(findings),
    )


def _finding(
    drift_type: DriftType,
    *,
    column_name: str | None = None,
    before_value: FindingValue | None,
    after_value: FindingValue | None,
    description: str,
    absolute_delta: int | float | None = None,
    percentage_delta: float | None = None,
    percentage_point_delta: float | None = None,
) -> DriftFinding:
    return DriftFinding(
        drift_type=drift_type,
        column_name=column_name,
        before_value=before_value,
        after_value=after_value,
        absolute_delta=absolute_delta,
        percentage_delta=percentage_delta,
        percentage_point_delta=percentage_point_delta,
        description=description,
    )


def _count_finding(
    drift_type: DriftType,
    metric: str,
    before: int,
    after: int,
    *,
    column_name: str | None = None,
) -> DriftFinding:
    delta = after - before
    percentage_delta = _percentage_delta(before, after)
    subject = metric if column_name is None else f"{metric} for {_quote(column_name)}"
    suffix = (
        "percentage change undefined for zero baseline"
        if percentage_delta is None
        else f"{_format_signed_percentage(percentage_delta)}"
    )
    return _finding(
        drift_type,
        column_name=column_name,
        before_value=before,
        after_value=after,
        absolute_delta=delta,
        percentage_delta=percentage_delta,
        description=(
            f"{subject} {_direction(delta)} from {_format_number(before)} to "
            f"{_format_number(after)} ({suffix})"
        ),
    )


def _rate_finding(
    drift_type: DriftType,
    metric: str,
    before: float,
    after: float,
    *,
    column_name: str | None = None,
) -> DriftFinding:
    delta = _numeric_delta(before, after)
    assert delta is not None
    points = _rounded(delta * 100, PERCENTAGE_DECIMAL_PLACES)
    subject = metric if column_name is None else f"{metric} for {_quote(column_name)}"
    return _finding(
        drift_type,
        column_name=column_name,
        before_value=before,
        after_value=after,
        absolute_delta=delta,
        percentage_point_delta=points,
        description=(
            f"{subject} {_direction(delta)} from {_format_rate(before)} to "
            f"{_format_rate(after)} ({_format_signed_number(points)} percentage points)"
        ),
    )


def _range_finding(
    drift_type: DriftType,
    label: str,
    column_name: str,
    before: RangeValue,
    after: RangeValue,
) -> DriftFinding:
    delta: int | float | None = None
    if _range_kind(before) == "numeric":
        delta = _numeric_delta(before, after)  # type: ignore[arg-type]
    return _finding(
        drift_type,
        column_name=column_name,
        before_value=before,
        after_value=after,
        absolute_delta=delta,
        description=(
            f"{label} for {_quote(column_name)} changed from "
            f"{_format_value(before)} to {_format_value(after)}"
        ),
    )


def _percentage_delta(before: int, after: int) -> float | None:
    if before == 0:
        return None
    return _rounded(
        ((after - before) / before) * 100,
        PERCENTAGE_DECIMAL_PLACES,
    )


def _ensure_comparable_range(
    column_name: str, before: RangeValue, after: RangeValue
) -> None:
    before_kind = _range_kind(before)
    after_kind = _range_kind(after)
    if before_kind != after_kind:
        raise SnapshotComparisonError(
            f"Range values for column {column_name!r} are not comparable."
        )
    if before_kind == "datetime":
        before_aware = before.tzinfo is not None  # type: ignore[union-attr]
        after_aware = after.tzinfo is not None  # type: ignore[union-attr]
        if before_aware != after_aware:
            raise SnapshotComparisonError(
                f"Range values for column {column_name!r} use incompatible timezones."
            )


def _range_kind(value: RangeValue) -> str:
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    return "numeric"


def _rounded(value: int | float, places: int) -> int | float:
    result = round(value, places)
    return 0.0 if result == 0 else result


def _numeric_delta(
    before: int | float, after: int | float
) -> int | float | None:
    if isinstance(before, int) and isinstance(after, int):
        return after - before
    result = float(Decimal(str(after)) - Decimal(str(before)))
    return result if math.isfinite(result) else None


def _direction(delta: int | float) -> str:
    return "increased" if delta > 0 else "decreased"


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _format_value(value: RangeValue) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return _format_number(value)


def _format_number(value: int | float) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:.12g}"


def _format_rate(value: float) -> str:
    return f"{_format_decimal(value * 100)}%"


def _format_signed_percentage(value: float) -> str:
    return f"{_format_signed_number(value)}%"


def _format_signed_number(value: float) -> str:
    prefix = "+" if value > 0 else ""
    return f"{prefix}{_format_decimal(value)}"


def _format_decimal(value: float) -> str:
    text = f"{value:.{PERCENTAGE_DECIMAL_PLACES}f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text
