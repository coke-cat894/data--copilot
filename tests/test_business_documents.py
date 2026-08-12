from pathlib import Path
import subprocess
import sys

import pytest

from data_copilot.documents import BusinessDocument, BusinessDocumentLoader
from data_copilot.errors import (
    BusinessDocumentConfigurationError,
    BusinessDocumentLimitError,
)


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "business_documents"


def test_loads_markdown_with_heading_title_and_path_safe_identity() -> None:
    path = FIXTURE_DIRECTORY / "revenue_policy.md"

    document = BusinessDocumentLoader(path.resolve()).load()[0]

    assert isinstance(document, BusinessDocument)
    assert document.title == "Revenue Policy"
    assert document.logical_source == "revenue_policy.md"
    assert document.document_id.startswith("doc_")
    assert len(document.document_id) == 20
    assert "Completed orders" in document.content
    assert str(path.parent.resolve()) not in repr(document)


def test_loads_plain_text_with_filename_title() -> None:
    document = BusinessDocumentLoader(
        FIXTURE_DIRECTORY / "customer_regions.txt"
    ).load()[0]

    assert document.title == "customer regions"
    assert document.logical_source == "customer_regions.txt"


def test_directory_load_is_deterministically_sorted() -> None:
    first = BusinessDocumentLoader(FIXTURE_DIRECTORY).load()
    second = BusinessDocumentLoader(FIXTURE_DIRECTORY).load()

    expected = (
        "customer_regions.txt",
        "order_status_policy.md",
        "revenue_policy.md",
        "warehouse_maintenance.txt",
    )
    assert tuple(document.logical_source for document in first) == expected
    assert first == second


def test_multiple_explicit_files_are_sorted_not_caller_order() -> None:
    documents = BusinessDocumentLoader(
        [
            FIXTURE_DIRECTORY / "revenue_policy.md",
            FIXTURE_DIRECTORY / "customer_regions.txt",
        ]
    ).load()

    assert tuple(document.logical_source for document in documents) == (
        "customer_regions.txt",
        "revenue_policy.md",
    )


def test_empty_explicit_directory_requires_opt_in(tmp_path: Path) -> None:
    with pytest.raises(BusinessDocumentConfigurationError, match="No supported"):
        BusinessDocumentLoader(tmp_path).load()

    assert BusinessDocumentLoader(tmp_path).load(allow_empty=True) == ()


def test_explicit_unsupported_extension_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "policy.pdf"
    path.write_bytes(b"not a PDF")

    with pytest.raises(BusinessDocumentConfigurationError, match="Markdown"):
        BusinessDocumentLoader(path).load()


def test_file_count_limit_fails_closed() -> None:
    with pytest.raises(BusinessDocumentLimitError, match="too many files"):
        BusinessDocumentLoader(FIXTURE_DIRECTORY, max_files=3).load()


def test_file_byte_limit_fails_without_exposing_absolute_path() -> None:
    path = (FIXTURE_DIRECTORY / "revenue_policy.md").resolve()

    with pytest.raises(BusinessDocumentLimitError) as raised:
        BusinessDocumentLoader(path, max_file_bytes=10).load()

    assert "revenue_policy.md" in str(raised.value)
    assert str(path.parent) not in str(raised.value)


def test_document_character_limit_fails_closed() -> None:
    with pytest.raises(BusinessDocumentLimitError, match="character limit"):
        BusinessDocumentLoader(
            FIXTURE_DIRECTORY / "revenue_policy.md",
            max_document_chars=20,
        ).load()


def test_empty_and_invalid_utf8_documents_fail_safely(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")
    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff\xfe")

    with pytest.raises(BusinessDocumentConfigurationError, match="cannot be empty"):
        BusinessDocumentLoader(empty).load()
    with pytest.raises(BusinessDocumentConfigurationError, match="UTF-8"):
        BusinessDocumentLoader(invalid).load()


def test_symlink_file_and_directory_are_rejected(tmp_path: Path) -> None:
    file_link = tmp_path / "policy.md"
    file_link.symlink_to(FIXTURE_DIRECTORY / "revenue_policy.md")
    directory_link = tmp_path / "documents"
    directory_link.symlink_to(FIXTURE_DIRECTORY, target_is_directory=True)

    for source in (file_link, directory_link):
        with pytest.raises(BusinessDocumentConfigurationError, match="symbolic"):
            BusinessDocumentLoader(source).load()


def test_source_below_symlinked_parent_is_rejected(tmp_path: Path) -> None:
    parent_link = tmp_path / "linked"
    parent_link.symlink_to(FIXTURE_DIRECTORY, target_is_directory=True)

    with pytest.raises(BusinessDocumentConfigurationError, match="symbolic"):
        BusinessDocumentLoader(parent_link / "revenue_policy.md").load()


def test_duplicate_logical_sources_from_explicit_paths_fail_closed(
    tmp_path: Path,
) -> None:
    first_directory = tmp_path / "a"
    second_directory = tmp_path / "b"
    first_directory.mkdir()
    second_directory.mkdir()
    first = first_directory / "policy.txt"
    second = second_directory / "policy.txt"
    first.write_text("First policy.", encoding="utf-8")
    second.write_text("Second policy.", encoding="utf-8")

    with pytest.raises(BusinessDocumentConfigurationError, match="unique"):
        BusinessDocumentLoader([first, second]).load()


def test_loader_does_not_recursively_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("recursive filesystem scan was used")

    monkeypatch.setattr(Path, "rglob", forbidden)

    assert len(BusinessDocumentLoader(FIXTURE_DIRECTORY).load()) == 4


def test_loading_and_retrieval_make_no_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    from data_copilot.documents import BusinessDocumentChunker, BusinessDocumentIndex

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("external network call was attempted")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)

    documents = BusinessDocumentLoader(FIXTURE_DIRECTORY).load()
    chunks = BusinessDocumentChunker().chunk(documents)
    results = BusinessDocumentIndex(chunks).search("refund revenue")

    assert results[0].logical_source == "revenue_policy.md"


def test_document_import_is_isolated_from_runtime_services() -> None:
    project_root = Path(__file__).parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import data_copilot.documents; "
            "forbidden={'openai','psycopg','data_copilot.agent',"
            "'data_copilot.database_agent','data_copilot.sql.validator',"
            "'data_copilot.semantics'}; assert forbidden.isdisjoint(sys.modules)",
        ],
        cwd=project_root,
        env={"PYTHONPATH": str(project_root / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
