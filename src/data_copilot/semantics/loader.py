"""Bounded YAML loader for explicitly configured trusted semantic files."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
import yaml

from data_copilot.errors import SemanticConfigurationError
from data_copilot.semantics.catalog import SemanticCatalog
from data_copilot.semantics.models import (
    DimensionDefinition,
    GlossaryTerm,
    MetricDefinition,
    SemanticProvenance,
)


MAX_SEMANTIC_FILES = 100
MAX_SEMANTIC_FILE_BYTES = 1_000_000
MAX_DEFINITIONS_PER_FILE = 1_000
_SUPPORTED_SUFFIXES = {".yaml", ".yml"}
_SUPPORTED_DEFINITION_TYPES = {"metrics", "dimensions", "glossary"}


class _SemanticDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    type: str
    definitions: list[dict[str, object]]


class SemanticCatalogLoader:
    """Load one explicit YAML file or one non-recursive semantic directory."""

    def __init__(self, semantic_path: str | Path) -> None:
        self._semantic_path = Path(semantic_path)

    def load(self, *, allow_empty: bool = False) -> SemanticCatalog:
        files = self._resolve_files()
        if not files and not allow_empty:
            raise SemanticConfigurationError("No semantic YAML files were found.")

        metrics: list[MetricDefinition] = []
        dimensions: list[DimensionDefinition] = []
        glossary: list[GlossaryTerm] = []
        for path in files:
            document = self._load_document(path)
            source = path.name
            for raw_definition in document.definitions:
                if "provenance" in raw_definition:
                    raise SemanticConfigurationError(
                        f"Provenance in '{source}' must be program-managed."
                    )
                try:
                    if document.type == "metrics":
                        definition_id = raw_definition.get("metric_id")
                        provenance = self._provenance(source, definition_id)
                        metrics.append(
                            MetricDefinition.model_validate(
                                {**raw_definition, "provenance": provenance}
                            )
                        )
                    elif document.type == "dimensions":
                        definition_id = raw_definition.get("dimension_id")
                        provenance = self._provenance(source, definition_id)
                        dimensions.append(
                            DimensionDefinition.model_validate(
                                {**raw_definition, "provenance": provenance}
                            )
                        )
                    else:
                        definition_id = raw_definition.get("term_id")
                        provenance = self._provenance(source, definition_id)
                        glossary.append(
                            GlossaryTerm.model_validate(
                                {**raw_definition, "provenance": provenance}
                            )
                        )
                except ValidationError as error:
                    raise self._configuration_error(source, error) from None

        catalog = SemanticCatalog(
            metrics=metrics,
            dimensions=dimensions,
            glossary=glossary,
        )
        if not allow_empty and not (catalog.metrics or catalog.dimensions or catalog.glossary):
            raise SemanticConfigurationError("Semantic catalog cannot be empty.")
        return catalog

    def _resolve_files(self) -> tuple[Path, ...]:
        path = self._semantic_path
        if path.is_symlink():
            raise SemanticConfigurationError("Semantic path cannot be a symbolic link.")
        if path.is_file():
            if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
                raise SemanticConfigurationError("Semantic source must be a YAML file.")
            return (path,)
        if not path.is_dir():
            raise SemanticConfigurationError("Semantic path does not exist.")

        try:
            files = tuple(
                sorted(
                    (
                        candidate
                        for candidate in path.iterdir()
                        if candidate.suffix.lower() in _SUPPORTED_SUFFIXES
                    ),
                    key=lambda candidate: candidate.name,
                )
            )
        except OSError:
            raise SemanticConfigurationError(
                "Semantic directory cannot be read."
            ) from None
        if len(files) > MAX_SEMANTIC_FILES:
            raise SemanticConfigurationError("Semantic directory has too many YAML files.")
        if any(candidate.is_symlink() or not candidate.is_file() for candidate in files):
            raise SemanticConfigurationError(
                "Semantic YAML sources must be regular files, not symbolic links."
            )
        return files

    def _load_document(self, path: Path) -> _SemanticDocument:
        source = path.name
        try:
            if path.stat().st_size > MAX_SEMANTIC_FILE_BYTES:
                raise SemanticConfigurationError(
                    f"Semantic source '{source}' exceeds the file size limit."
                )
            content = path.read_text(encoding="utf-8")
        except SemanticConfigurationError:
            raise
        except (OSError, UnicodeError):
            raise SemanticConfigurationError(
                f"Semantic source '{source}' cannot be read as UTF-8."
            ) from None
        try:
            raw_document = yaml.safe_load(content)
        except yaml.YAMLError:
            raise SemanticConfigurationError(
                f"Semantic source '{source}' contains malformed YAML."
            ) from None
        try:
            document = _SemanticDocument.model_validate(raw_document)
        except ValidationError as error:
            raise self._configuration_error(source, error) from None
        if document.type not in _SUPPORTED_DEFINITION_TYPES:
            raise SemanticConfigurationError(
                f"Semantic source '{source}' has an unsupported definition type."
            )
        if len(document.definitions) > MAX_DEFINITIONS_PER_FILE:
            raise SemanticConfigurationError(
                f"Semantic source '{source}' has too many definitions."
            )
        return document

    @staticmethod
    def _provenance(source: str, definition_id: object) -> SemanticProvenance:
        try:
            return SemanticProvenance(
                source=source,
                definition_id=definition_id,
            )
        except ValidationError as error:
            raise SemanticCatalogLoader._configuration_error(source, error) from None

    @staticmethod
    def _configuration_error(
        source: str,
        error: ValidationError,
    ) -> SemanticConfigurationError:
        first = error.errors(include_input=False)[0]
        location = ".".join(str(part) for part in first["loc"])
        issue = (
            "a required field is missing"
            if first["type"] == "missing"
            else "a field is invalid"
        )
        suffix = f" at '{location}'" if location else ""
        return SemanticConfigurationError(
            f"Semantic source '{source}' has {issue}{suffix}."
        )
