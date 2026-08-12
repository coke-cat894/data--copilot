"""Explicit bounded loading of trusted local Markdown and plain-text documents."""

from collections.abc import Sequence
import hashlib
from pathlib import Path
import re

from data_copilot.documents.constants import (
    MAX_DOCUMENT_CHARS,
    MAX_DOCUMENT_FILE_BYTES,
    MAX_DOCUMENT_FILES,
    MAX_DOCUMENT_LOGICAL_SOURCE_CHARS,
    MAX_DOCUMENT_TITLE_CHARS,
)
from data_copilot.documents.models import BusinessDocument
from data_copilot.errors import (
    BusinessDocumentConfigurationError,
    BusinessDocumentLimitError,
)


_SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt"}
_MARKDOWN_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class BusinessDocumentLoader:
    """Load explicit files/directories without recursion or path disclosure."""

    def __init__(
        self,
        sources: str | Path | Sequence[str | Path],
        *,
        max_files: int = MAX_DOCUMENT_FILES,
        max_file_bytes: int = MAX_DOCUMENT_FILE_BYTES,
        max_document_chars: int = MAX_DOCUMENT_CHARS,
    ) -> None:
        if isinstance(sources, (str, Path)):
            self._sources = (Path(sources),)
        elif isinstance(sources, Sequence):
            self._sources = tuple(Path(source) for source in sources)
        else:
            raise TypeError("sources must be a path or sequence of paths.")
        self._max_files = _positive_limit("max_files", max_files)
        self._max_file_bytes = _positive_limit("max_file_bytes", max_file_bytes)
        self._max_document_chars = _positive_limit(
            "max_document_chars",
            max_document_chars,
        )

    def load(self, *, allow_empty: bool = False) -> tuple[BusinessDocument, ...]:
        files = self._resolve_files()
        if not files and not allow_empty:
            raise BusinessDocumentConfigurationError(
                "No supported business-document files were found."
            )
        documents = tuple(self._load_file(path) for path in files)
        if not documents and not allow_empty:
            raise BusinessDocumentConfigurationError(
                "Business-document collection cannot be empty."
            )
        return documents

    def _resolve_files(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for source in self._sources:
            if _has_symlink_component(source):
                raise BusinessDocumentConfigurationError(
                    "Business-document source cannot be a symbolic link."
                )
            if source.is_file():
                self._validate_suffix(source)
                paths.append(source)
                self._validate_file_count(paths)
                continue
            if source.is_dir():
                try:
                    candidates = sorted(source.iterdir(), key=lambda path: path.name)
                except OSError:
                    raise BusinessDocumentConfigurationError(
                        "Business-document directory cannot be read."
                    ) from None
                for candidate in candidates:
                    if candidate.suffix.lower() not in _SUPPORTED_SUFFIXES:
                        continue
                    if candidate.is_symlink() or not candidate.is_file():
                        raise BusinessDocumentConfigurationError(
                            "Business-document files must be regular, not symbolic links."
                        )
                    paths.append(candidate)
                    self._validate_file_count(paths)
                continue
            raise BusinessDocumentConfigurationError(
                "Business-document source does not exist."
            )
        logical_sources = [path.name.casefold() for path in paths]
        if len(set(logical_sources)) != len(logical_sources):
            raise BusinessDocumentConfigurationError(
                "Business-document logical source names must be unique."
            )
        return tuple(sorted(paths, key=lambda path: path.name.casefold()))

    def _validate_file_count(self, paths: list[Path]) -> None:
        if len(paths) > self._max_files:
            raise BusinessDocumentLimitError(
                "Business-document source has too many files."
            )

    @staticmethod
    def _validate_suffix(path: Path) -> None:
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            raise BusinessDocumentConfigurationError(
                "Business-document source must be Markdown or plain text."
            )

    def _load_file(self, path: Path) -> BusinessDocument:
        source = path.name
        if len(source) > MAX_DOCUMENT_LOGICAL_SOURCE_CHARS:
            raise BusinessDocumentLimitError(
                "Business-document logical source exceeds the character limit."
            )
        try:
            if path.stat().st_size > self._max_file_bytes:
                raise BusinessDocumentLimitError(
                    f"Business document '{source}' exceeds the file size limit."
                )
            content = path.read_text(encoding="utf-8")
        except BusinessDocumentLimitError:
            raise
        except (OSError, UnicodeError):
            raise BusinessDocumentConfigurationError(
                f"Business document '{source}' cannot be read as UTF-8."
            ) from None
        content = content.strip()
        if not content:
            raise BusinessDocumentConfigurationError(
                f"Business document '{source}' cannot be empty."
            )
        if len(content) > self._max_document_chars:
            raise BusinessDocumentLimitError(
                f"Business document '{source}' exceeds the character limit."
            )
        title = self._title(path, content)
        if not title:
            raise BusinessDocumentConfigurationError(
                f"Business document '{source}' has no usable title."
            )
        if len(title) > MAX_DOCUMENT_TITLE_CHARS:
            raise BusinessDocumentLimitError(
                f"Business document '{source}' title exceeds the character limit."
            )
        document_id = "doc_" + hashlib.sha256(
            f"{source}\n{content}".encode("utf-8")
        ).hexdigest()[:16]
        return BusinessDocument(
            document_id=document_id,
            title=title,
            logical_source=source,
            content=content,
        )

    @staticmethod
    def _title(path: Path, content: str) -> str:
        if path.suffix.lower() in {".md", ".markdown"}:
            match = _MARKDOWN_TITLE.search(content)
            if match is not None and match.group(1).strip():
                return match.group(1).strip()
        return path.stem.replace("_", " ").replace("-", " ").strip()


def _positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BusinessDocumentLimitError(f"{name} must be a positive integer.")
    return value


def _has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))
