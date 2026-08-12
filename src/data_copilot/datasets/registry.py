"""Explicit, in-memory registration of local datasets."""

import secrets
from collections.abc import Iterable
from pathlib import Path

from data_copilot.datasets.models import Dataset, DatasetFormat
from data_copilot.errors import (
    DatasetFileNotFoundError,
    DatasetNotFoundError,
    DatasetPathNotAllowedError,
    DatasetRegistrationError,
    UnsupportedFormatError,
)


_FORMAT_BY_SUFFIX = {
    ".csv": DatasetFormat.CSV,
    ".parquet": DatasetFormat.PARQUET,
    ".jsonl": DatasetFormat.JSONL,
}


class DatasetRegistry:
    """Register explicit local files and resolve opaque dataset IDs."""

    def __init__(self, *, allowed_roots: Iterable[str | Path]) -> None:
        roots = tuple(self._validate_root(root) for root in allowed_roots)
        if not roots:
            raise DatasetRegistrationError(
                "At least one allowed dataset root must be configured."
            )

        self._allowed_roots = tuple(dict.fromkeys(roots))
        self._datasets: dict[str, Dataset] = {}
        self._dataset_ids_by_path: dict[Path, str] = {}

    def register(self, file_path: str | Path) -> Dataset:
        """Validate and register one user-provided file.

        Re-registering the same resolved file in this registry returns the
        original dataset and does not allocate another ID.
        """

        resolved_path = self._resolve_existing_file(file_path)
        self._ensure_path_allowed(resolved_path)
        self._ensure_not_hidden(resolved_path)

        dataset_format = _FORMAT_BY_SUFFIX.get(resolved_path.suffix.lower())
        if dataset_format is None:
            raise UnsupportedFormatError(
                "Unsupported dataset format; expected CSV, Parquet, or JSONL."
            )

        existing_id = self._dataset_ids_by_path.get(resolved_path)
        if existing_id is not None:
            return self._datasets[existing_id]

        try:
            file_size_bytes = resolved_path.stat().st_size
        except OSError as exc:
            raise DatasetRegistrationError(
                "Dataset metadata could not be read safely."
            ) from exc

        dataset = Dataset(
            dataset_id=self._new_dataset_id(),
            display_name=resolved_path.name,
            format=dataset_format,
            resolved_path=resolved_path,
            file_size_bytes=file_size_bytes,
        )
        self._datasets[dataset.dataset_id] = dataset
        self._dataset_ids_by_path[resolved_path] = dataset.dataset_id
        return dataset

    def get(self, dataset_id: str) -> Dataset:
        """Resolve a registered ID and re-check that its file is still safe."""

        if not isinstance(dataset_id, str):
            raise DatasetNotFoundError("Unknown dataset ID.")

        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            raise DatasetNotFoundError("Unknown dataset ID.")

        current_path = self._resolve_existing_file(dataset.resolved_path)
        if current_path != dataset.resolved_path:
            raise DatasetPathNotAllowedError(
                "The registered dataset path no longer resolves to its original file."
            )
        self._ensure_path_allowed(current_path)
        self._ensure_not_hidden(current_path)
        return dataset

    @staticmethod
    def _validate_root(root: str | Path) -> Path:
        try:
            resolved_root = Path(root).expanduser().resolve(strict=True)
        except (
            TypeError,
            ValueError,
            FileNotFoundError,
            OSError,
            RuntimeError,
        ) as exc:
            raise DatasetRegistrationError(
                "An allowed dataset root does not exist or cannot be resolved."
            ) from exc
        if not resolved_root.is_dir():
            raise DatasetRegistrationError("An allowed dataset root is not a directory.")
        return resolved_root

    @staticmethod
    def _resolve_existing_file(file_path: str | Path) -> Path:
        try:
            resolved_path = Path(file_path).expanduser().resolve(strict=True)
        except (
            TypeError,
            ValueError,
            FileNotFoundError,
            OSError,
            RuntimeError,
        ) as exc:
            raise DatasetFileNotFoundError(
                "Dataset file does not exist or cannot be resolved."
            ) from exc
        if not resolved_path.is_file():
            raise DatasetFileNotFoundError(
                "Dataset file does not exist or is not a regular file."
            )
        return resolved_path

    def _ensure_path_allowed(self, resolved_path: Path) -> None:
        if not any(
            resolved_path == root or root in resolved_path.parents
            for root in self._allowed_roots
        ):
            raise DatasetPathNotAllowedError(
                "Dataset path is outside the configured allowed roots."
            )

    def _ensure_not_hidden(self, resolved_path: Path) -> None:
        for root in self._allowed_roots:
            if resolved_path == root or root not in resolved_path.parents:
                continue
            relative_path = resolved_path.relative_to(root)
            if any(part.startswith(".") for part in relative_path.parts):
                raise DatasetPathNotAllowedError(
                    "Hidden files and hidden directories cannot be registered."
                )
            return

    def _new_dataset_id(self) -> str:
        while True:
            dataset_id = f"ds_{secrets.token_hex(4)}"
            if dataset_id not in self._datasets:
                return dataset_id
