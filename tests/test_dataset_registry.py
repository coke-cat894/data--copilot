from pathlib import Path

import pytest

from data_copilot.datasets import DatasetFormat, DatasetRegistry
from data_copilot.errors import (
    DatasetFileNotFoundError,
    DatasetNotFoundError,
    DatasetPathNotAllowedError,
    DatasetRegistrationError,
    UnsupportedFormatError,
)


@pytest.mark.parametrize(
    ("key", "expected_format"),
    [
        ("csv", DatasetFormat.CSV),
        ("parquet", DatasetFormat.PARQUET),
        ("jsonl", DatasetFormat.JSONL),
    ],
)
def test_register_supported_dataset(
    sample_files: dict[str, Path],
    tmp_path: Path,
    key: str,
    expected_format: DatasetFormat,
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])

    dataset = registry.register(sample_files[key])

    assert dataset.dataset_id.startswith("ds_")
    assert len(dataset.dataset_id) == 11
    assert dataset.format is expected_format
    assert dataset.resolved_path == sample_files[key].resolve()
    assert dataset.file_size_bytes == sample_files[key].stat().st_size
    assert registry.get(dataset.dataset_id) == dataset


def test_extension_matching_is_case_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "SAMPLE.CSV"
    path.write_text("value\n1\n", encoding="utf-8")
    registry = DatasetRegistry(allowed_roots=[tmp_path])

    assert registry.register(path).format is DatasetFormat.CSV


def test_duplicate_registration_returns_existing_dataset(
    sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])

    first = registry.register(sample_files["csv"])
    second = registry.register(sample_files["csv"])

    assert second is first


def test_unknown_dataset_id_fails_closed(tmp_path: Path) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])

    with pytest.raises(DatasetNotFoundError, match="Unknown dataset ID"):
        registry.get("ds_doesnotexist")


def test_missing_file_cannot_be_registered(tmp_path: Path) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])

    with pytest.raises(DatasetFileNotFoundError):
        registry.register(tmp_path / "missing.csv")


def test_unsupported_extension_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "sample.json"
    path.write_text("{}", encoding="utf-8")
    registry = DatasetRegistry(allowed_roots=[tmp_path])

    with pytest.raises(UnsupportedFormatError):
        registry.register(path)


def test_path_outside_allowed_root_fails_closed(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside_path = tmp_path / "outside.csv"
    outside_path.write_text("value\n1\n", encoding="utf-8")
    registry = DatasetRegistry(allowed_roots=[allowed_root])

    with pytest.raises(DatasetPathNotAllowedError):
        registry.register(outside_path)


def test_symlink_escape_fails_closed(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside_path = tmp_path / "outside.csv"
    outside_path.write_text("value\n1\n", encoding="utf-8")
    link = allowed_root / "linked.csv"
    link.symlink_to(outside_path)
    registry = DatasetRegistry(allowed_roots=[allowed_root])

    with pytest.raises(DatasetPathNotAllowedError):
        registry.register(link)


def test_hidden_dataset_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / ".private.csv"
    path.write_text("value\n1\n", encoding="utf-8")
    registry = DatasetRegistry(allowed_roots=[tmp_path])

    with pytest.raises(DatasetPathNotAllowedError):
        registry.register(path)


def test_allowed_roots_must_be_explicit() -> None:
    with pytest.raises(DatasetRegistrationError):
        DatasetRegistry(allowed_roots=[])


def test_public_metadata_omits_resolved_path(
    sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(sample_files["csv"])

    public_metadata = dataset.to_public_metadata().model_dump()

    assert public_metadata["dataset_id"] == dataset.dataset_id
    assert "resolved_path" not in public_metadata


def test_registered_file_removal_is_detected(
    sample_files: dict[str, Path], tmp_path: Path
) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])
    dataset = registry.register(sample_files["csv"])
    sample_files["csv"].unlink()

    with pytest.raises(DatasetFileNotFoundError):
        registry.get(dataset.dataset_id)


def test_registered_file_replaced_by_escaping_symlink_is_detected(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    registered_path = allowed_root / "sample.csv"
    registered_path.write_text("value\n1\n", encoding="utf-8")
    outside_path = tmp_path / "outside.csv"
    outside_path.write_text("value\n2\n", encoding="utf-8")
    registry = DatasetRegistry(allowed_roots=[allowed_root])
    dataset = registry.register(registered_path)
    registered_path.unlink()
    registered_path.symlink_to(outside_path)

    with pytest.raises(DatasetPathNotAllowedError):
        registry.get(dataset.dataset_id)


def test_registry_has_no_filesystem_scanning_api(tmp_path: Path) -> None:
    registry = DatasetRegistry(allowed_roots=[tmp_path])

    assert not hasattr(registry, "list_directory")
    assert not hasattr(registry, "glob")
    assert not hasattr(registry, "scan")
