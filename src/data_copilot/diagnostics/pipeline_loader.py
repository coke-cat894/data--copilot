"""Explicit path-safe JSON/JSONL loading for structured pipeline runs."""

from collections.abc import Iterable, Sequence
import json
from pathlib import Path

from pydantic import ValidationError

from data_copilot.diagnostics.pipeline_constants import (
    MAX_LOGICAL_SOURCE_CHARS,
    MAX_PIPELINE_FILE_BYTES,
    MAX_PIPELINE_FILES,
    MAX_PIPELINE_RUNS,
    MAX_RUNS_PER_FILE,
)
from data_copilot.diagnostics.pipeline_models import PipelineProvenance, PipelineRun
from data_copilot.errors import PipelineConfigurationError, PipelineLimitError


_SUPPORTED_SUFFIXES = {".json", ".jsonl"}


class PipelineRunLoader:
    """Load explicit structured run files within configured roots."""

    def __init__(
        self,
        sources: str | Path | Sequence[str | Path],
        *,
        allowed_roots: Iterable[str | Path],
        max_files: int = MAX_PIPELINE_FILES,
        max_file_bytes: int = MAX_PIPELINE_FILE_BYTES,
        max_runs_per_file: int = MAX_RUNS_PER_FILE,
        max_runs: int = MAX_PIPELINE_RUNS,
    ) -> None:
        if isinstance(sources, (str, Path)):
            self._sources = (Path(sources),)
        elif isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
            self._sources = tuple(Path(source) for source in sources)
        else:
            raise TypeError("sources must be a path or sequence of paths.")
        if not self._sources:
            raise PipelineConfigurationError("At least one pipeline source is required.")
        self._allowed_roots = tuple(
            dict.fromkeys(self._validate_root(root) for root in allowed_roots)
        )
        if not self._allowed_roots:
            raise PipelineConfigurationError(
                "At least one allowed pipeline root is required."
            )
        self._max_files = _positive_limit("max_files", max_files)
        self._max_file_bytes = _positive_limit("max_file_bytes", max_file_bytes)
        self._max_runs_per_file = _positive_limit(
            "max_runs_per_file", max_runs_per_file
        )
        self._max_runs = _positive_limit("max_runs", max_runs)

    def load(self) -> tuple[PipelineRun, ...]:
        files = self._resolve_files()
        if not files:
            raise PipelineConfigurationError("No supported pipeline files were found.")
        runs: list[PipelineRun] = []
        identities: set[tuple[str, str]] = set()
        for path in files:
            records = self._read_records(path)
            for record_index, record in enumerate(records):
                if "provenance" in record:
                    raise PipelineConfigurationError(
                        f"Pipeline source '{path.name}' contains caller-managed provenance."
                    )
                provenance = PipelineProvenance(
                    logical_source=path.name,
                    record_index=record_index,
                )
                try:
                    run = PipelineRun.model_validate(
                        {**record, "provenance": provenance}
                    )
                except ValidationError as error:
                    raise _validation_error(path.name, record_index, error) from None
                identity = (run.pipeline_id, run.run_id)
                if identity in identities:
                    raise PipelineConfigurationError(
                        "Pipeline run identities must be unique within a load."
                    )
                identities.add(identity)
                runs.append(run)
                if len(runs) > self._max_runs:
                    raise PipelineLimitError("Pipeline input contains too many runs.")
        return tuple(
            sorted(
                runs,
                key=lambda run: (
                    run.provenance.logical_source.casefold(),
                    run.provenance.record_index,
                ),
            )
        )

    def _resolve_files(self) -> tuple[Path, ...]:
        files: list[Path] = []
        for source in self._sources:
            if _has_symlink_component(source):
                raise PipelineConfigurationError(
                    "Pipeline source cannot contain a symbolic-link component."
                )
            try:
                resolved = source.expanduser().resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                raise PipelineConfigurationError(
                    "Pipeline source does not exist or cannot be resolved."
                ) from None
            self._ensure_allowed(resolved)
            self._ensure_not_hidden(resolved)
            if resolved.is_file():
                self._validate_suffix(resolved)
                files.append(resolved)
                self._validate_file_count(files)
                continue
            if resolved.is_dir():
                try:
                    candidates = sorted(
                        resolved.iterdir(), key=lambda candidate: candidate.name.casefold()
                    )
                except OSError:
                    raise PipelineConfigurationError(
                        "Pipeline directory cannot be read."
                    ) from None
                for candidate in candidates:
                    if candidate.suffix.lower() not in _SUPPORTED_SUFFIXES:
                        continue
                    if candidate.is_symlink() or not candidate.is_file():
                        raise PipelineConfigurationError(
                            "Pipeline files must be regular, not symbolic links."
                        )
                    self._ensure_not_hidden(candidate)
                    files.append(candidate)
                    self._validate_file_count(files)
                continue
            raise PipelineConfigurationError(
                "Pipeline source must be a regular file or directory."
            )
        logical_sources = [path.name.casefold() for path in files]
        if len(logical_sources) != len(set(logical_sources)):
            raise PipelineConfigurationError(
                "Pipeline logical source names must be unique."
            )
        return tuple(sorted(files, key=lambda path: path.name.casefold()))

    def _read_records(self, path: Path) -> tuple[dict[str, object], ...]:
        if len(path.name) > MAX_LOGICAL_SOURCE_CHARS:
            raise PipelineLimitError(
                "Pipeline logical source exceeds the character limit."
            )
        try:
            if path.stat().st_size > self._max_file_bytes:
                raise PipelineLimitError(
                    f"Pipeline source '{path.name}' exceeds the file size limit."
                )
            content = path.read_text(encoding="utf-8")
        except PipelineLimitError:
            raise
        except (OSError, UnicodeError):
            raise PipelineConfigurationError(
                f"Pipeline source '{path.name}' cannot be read as UTF-8."
            ) from None
        if not content.strip():
            raise PipelineConfigurationError(
                f"Pipeline source '{path.name}' cannot be empty."
            )
        if path.suffix.lower() == ".jsonl":
            records = self._parse_jsonl(path.name, content)
        else:
            records = self._parse_json(path.name, content)
        if not records:
            raise PipelineConfigurationError(
                f"Pipeline source '{path.name}' contains no run records."
            )
        if len(records) > self._max_runs_per_file:
            raise PipelineLimitError(
                f"Pipeline source '{path.name}' contains too many run records."
            )
        return records

    @staticmethod
    def _parse_json(source: str, content: str) -> tuple[dict[str, object], ...]:
        try:
            value = json.loads(content)
        except (json.JSONDecodeError, UnicodeError):
            raise PipelineConfigurationError(
                f"Pipeline source '{source}' contains malformed JSON."
            ) from None
        if isinstance(value, dict):
            return (value,)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return tuple(value)
        raise PipelineConfigurationError(
            f"Pipeline source '{source}' must contain a run object or list of run objects."
        )

    @staticmethod
    def _parse_jsonl(source: str, content: str) -> tuple[dict[str, object], ...]:
        records: list[dict[str, object]] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                raise PipelineConfigurationError(
                    f"Pipeline source '{source}' has malformed JSON at line "
                    f"{line_number}."
                ) from None
            if not isinstance(value, dict):
                raise PipelineConfigurationError(
                    f"Pipeline source '{source}' line {line_number} must be a run object."
                )
            records.append(value)
        return tuple(records)

    @staticmethod
    def _validate_root(root: str | Path) -> Path:
        try:
            resolved = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            raise PipelineConfigurationError(
                "An allowed pipeline root does not exist or cannot be resolved."
            ) from None
        if not resolved.is_dir():
            raise PipelineConfigurationError(
                "An allowed pipeline root is not a directory."
            )
        return resolved

    def _ensure_allowed(self, path: Path) -> None:
        if not any(path == root or root in path.parents for root in self._allowed_roots):
            raise PipelineConfigurationError(
                "Pipeline source is outside the configured allowed roots."
            )

    def _ensure_not_hidden(self, path: Path) -> None:
        for root in self._allowed_roots:
            if path != root and root not in path.parents:
                continue
            relative = path.relative_to(root)
            if any(part.startswith(".") for part in relative.parts):
                raise PipelineConfigurationError(
                    "Hidden pipeline files and directories are not allowed."
                )
            return

    @staticmethod
    def _validate_suffix(path: Path) -> None:
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            raise PipelineConfigurationError(
                "Pipeline source must be JSON or JSONL."
            )

    def _validate_file_count(self, files: list[Path]) -> None:
        if len(files) > self._max_files:
            raise PipelineLimitError("Pipeline input contains too many files.")


def _validation_error(
    source: str,
    record_index: int,
    error: ValidationError,
) -> PipelineConfigurationError:
    first = error.errors(include_input=False)[0]
    location = ".".join(str(part) for part in first["loc"])
    issue = "a required field is missing" if first["type"] == "missing" else "a field is invalid"
    suffix = f" at '{location}'" if location else ""
    return PipelineConfigurationError(
        f"Pipeline source '{source}' record {record_index} has {issue}{suffix}."
    )


def _positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PipelineLimitError(f"{name} must be a positive integer.")
    return value


def _has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))
