from pathlib import Path
import subprocess
import sys

import pytest

from data_copilot.errors import (
    SemanticAmbiguityError,
    SemanticConfigurationError,
    SemanticNotFoundError,
    SemanticReferenceError,
)
from data_copilot.semantics import SemanticCatalogLoader


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "semantic"


def _write_document(
    directory: Path,
    name: str,
    *,
    definition_type: str,
    definitions: str,
) -> Path:
    path = directory / name
    path.write_text(
        f"version: 1\ntype: {definition_type}\ndefinitions:\n{definitions}",
        encoding="utf-8",
    )
    return path


def _metric_definition(
    *,
    metric_id: str = "completed_revenue",
    name: str = "completed revenue",
    synonyms: str = "      - fulfilled revenue\n",
    business_definition: str = "Revenue from completed orders.",
    required_field: str = "commerce.orders.amount",
    extra: str = "",
) -> str:
    return (
        f"  - metric_id: {metric_id}\n"
        f"    name: {name}\n"
        "    display_name: Completed Revenue\n"
        "    description: A synthetic metric.\n"
        "    synonyms:\n"
        f"{synonyms}"
        f"    business_definition: {business_definition}\n"
        "    required_fields:\n"
        f"      - {required_field}\n"
        f"{extra}"
    )


def _dimension_definition(
    *,
    dimension_id: str = "region",
    name: str = "region",
    synonyms: str = "      - customer region\n",
) -> str:
    return (
        f"  - dimension_id: {dimension_id}\n"
        f"    name: {name}\n"
        "    display_name: Customer Region\n"
        "    description: A synthetic dimension.\n"
        "    synonyms:\n"
        f"{synonyms}"
        "    source_fields:\n"
        "      - commerce.users.region\n"
    )


def _glossary_definition(
    *,
    term_id: str = "revenue",
    term: str = "Revenue",
    related_metrics: str = "      - completed_revenue\n",
    related_dimensions: str = "",
) -> str:
    metric_block = (
        f"    related_metrics:\n{related_metrics}"
        if related_metrics
        else ""
    )
    dimension_block = (
        f"    related_dimensions:\n{related_dimensions}"
        if related_dimensions
        else ""
    )
    return (
        f"  - term_id: {term_id}\n"
        f"    term: {term}\n"
        "    definition: A synthetic business concept.\n"
        "    synonyms:\n"
        "      - sales value\n"
        f"{metric_block}"
        f"{dimension_block}"
    )


def test_loads_multiple_typed_fixture_files() -> None:
    catalog = SemanticCatalogLoader(FIXTURE_DIRECTORY).load()

    assert [metric.metric_id for metric in catalog.metrics] == [
        "completed_revenue",
        "order_count",
    ]
    assert [dimension.dimension_id for dimension in catalog.dimensions] == ["region"]
    assert [term.term_id for term in catalog.glossary] == [
        "completed_order",
        "revenue",
        "customer_region",
    ]


@pytest.mark.parametrize(
    ("file_name", "expected_counts"),
    [
        ("metrics.yaml", (2, 0, 0)),
        ("dimensions.yaml", (0, 1, 0)),
    ],
)
def test_loads_each_supported_file_type(
    file_name: str,
    expected_counts: tuple[int, int, int],
) -> None:
    catalog = SemanticCatalogLoader(FIXTURE_DIRECTORY / file_name).load()

    assert (
        len(catalog.metrics),
        len(catalog.dimensions),
        len(catalog.glossary),
    ) == expected_counts


def test_loads_valid_standalone_glossary_file(tmp_path: Path) -> None:
    path = _write_document(
        tmp_path,
        "glossary.yaml",
        definition_type="glossary",
        definitions=_glossary_definition(related_metrics=""),
    )

    catalog = SemanticCatalogLoader(path).load()

    assert [term.term_id for term in catalog.glossary] == ["revenue"]


def test_empty_catalog_requires_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(SemanticConfigurationError, match="No semantic YAML"):
        SemanticCatalogLoader(tmp_path).load()

    catalog = SemanticCatalogLoader(tmp_path).load(allow_empty=True)

    assert catalog.metrics == ()
    assert catalog.dimensions == ()
    assert catalog.glossary == ()


def test_lookup_by_id_canonical_name_synonym_and_normalized_case() -> None:
    catalog = SemanticCatalogLoader(FIXTURE_DIRECTORY).load()

    metric = catalog.get_metric("completed_revenue")
    assert catalog.get_metric("completed revenue") is metric
    assert catalog.get_metric("  FULFILLED REVENUE ") is metric

    dimension = catalog.get_dimension("REGION")
    assert catalog.get_dimension("customer region") is dimension

    term = catalog.get_glossary_term("revenue")
    assert catalog.get_glossary_term(" SALES VALUE ") is term


@pytest.mark.parametrize(
    ("lookup", "value"),
    [
        ("get_metric", "missing"),
        ("get_dimension", "missing"),
        ("get_glossary_term", "missing"),
        ("get_metric", "   "),
    ],
)
def test_missing_lookup_fails_closed(lookup: str, value: str) -> None:
    catalog = SemanticCatalogLoader(FIXTURE_DIRECTORY).load()

    with pytest.raises(SemanticNotFoundError, match="not found"):
        getattr(catalog, lookup)(value)


@pytest.mark.parametrize(
    ("definition_type", "definition_factory", "duplicate_id"),
    [
        ("metrics", _metric_definition, "completed_revenue"),
        ("dimensions", _dimension_definition, "region"),
        ("glossary", _glossary_definition, "revenue"),
    ],
)
def test_duplicate_ids_fail_closed(
    tmp_path: Path,
    definition_type: str,
    definition_factory: object,
    duplicate_id: str,
) -> None:
    factory = definition_factory
    first = factory()  # type: ignore[operator]
    second = factory()  # type: ignore[operator]
    _write_document(
        tmp_path,
        f"{definition_type}.yaml",
        definition_type=definition_type,
        definitions=first + second,
    )

    with pytest.raises(SemanticConfigurationError, match="Duplicate"):
        SemanticCatalogLoader(tmp_path).load()


def test_conflicting_synonym_and_canonical_name_is_ambiguous(tmp_path: Path) -> None:
    definitions = _metric_definition() + _metric_definition(
        metric_id="fulfilled_revenue",
        name="fulfilled revenue",
        synonyms="      - settled revenue\n",
    )
    _write_document(
        tmp_path,
        "metrics.yaml",
        definition_type="metrics",
        definitions=definitions,
    )

    with pytest.raises(SemanticAmbiguityError, match="Ambiguous"):
        SemanticCatalogLoader(tmp_path).load()


def test_duplicate_canonical_names_are_ambiguous(tmp_path: Path) -> None:
    definitions = _metric_definition() + _metric_definition(
        metric_id="other_revenue",
        name="Completed Revenue",
        synonyms="      - other sales\n",
    )
    _write_document(
        tmp_path,
        "metrics.yaml",
        definition_type="metrics",
        definitions=definitions,
    )

    with pytest.raises(SemanticAmbiguityError):
        SemanticCatalogLoader(tmp_path).load()


@pytest.mark.parametrize(
    ("related_metrics", "related_dimensions"),
    [
        ("      - missing_metric\n", ""),
        ("", "      - missing_dimension\n"),
    ],
)
def test_invalid_glossary_references_fail_closed(
    tmp_path: Path,
    related_metrics: str,
    related_dimensions: str,
) -> None:
    glossary = _glossary_definition(
        related_metrics=related_metrics,
        related_dimensions=related_dimensions,
    )
    _write_document(
        tmp_path,
        "glossary.yaml",
        definition_type="glossary",
        definitions=glossary,
    )

    with pytest.raises(SemanticReferenceError, match="unknown"):
        SemanticCatalogLoader(tmp_path).load()


def test_invalid_required_field_reference_fails_closed(tmp_path: Path) -> None:
    _write_document(
        tmp_path,
        "metrics.yaml",
        definition_type="metrics",
        definitions=_metric_definition(required_field="orders.amount"),
    )

    with pytest.raises(SemanticConfigurationError, match="invalid"):
        SemanticCatalogLoader(tmp_path).load()


def test_empty_business_definition_fails_closed(tmp_path: Path) -> None:
    _write_document(
        tmp_path,
        "metrics.yaml",
        definition_type="metrics",
        definitions=_metric_definition(business_definition='""'),
    )

    with pytest.raises(SemanticConfigurationError, match="invalid"):
        SemanticCatalogLoader(tmp_path).load()


def test_missing_required_field_is_reported_without_input_value(tmp_path: Path) -> None:
    definition = _metric_definition().replace(
        "    business_definition: Revenue from completed orders.\n",
        "",
    )
    _write_document(
        tmp_path,
        "metrics.yaml",
        definition_type="metrics",
        definitions=definition,
    )

    with pytest.raises(SemanticConfigurationError, match="required field is missing"):
        SemanticCatalogLoader(tmp_path).load()


def test_malformed_yaml_fails_with_safe_source_identifier(tmp_path: Path) -> None:
    path = tmp_path / "metrics.yaml"
    path.write_text("version: [\n", encoding="utf-8")

    with pytest.raises(SemanticConfigurationError) as raised:
        SemanticCatalogLoader(path).load()

    assert "metrics.yaml" in str(raised.value)
    assert str(tmp_path) not in str(raised.value)


def test_unsupported_definition_type_fails_closed(tmp_path: Path) -> None:
    _write_document(
        tmp_path,
        "measures.yaml",
        definition_type="measures",
        definitions="  []\n",
    )

    with pytest.raises(SemanticConfigurationError, match="unsupported"):
        SemanticCatalogLoader(tmp_path).load()


def test_provenance_is_program_managed_and_path_safe() -> None:
    catalog = SemanticCatalogLoader(FIXTURE_DIRECTORY.resolve()).load()
    metric = catalog.get_metric("completed_revenue")

    assert metric.provenance.source == "metrics.yaml"
    assert metric.provenance.definition_id == metric.metric_id
    assert not Path(metric.provenance.source).is_absolute()
    assert str(FIXTURE_DIRECTORY.resolve()) not in repr(metric.provenance)


def test_yaml_cannot_supply_provenance_or_executable_sql(tmp_path: Path) -> None:
    for field in (
        "    provenance:\n      source: fake.yaml\n      definition_id: completed_revenue\n",
        "    sql: SELECT * FROM commerce.orders\n",
    ):
        path = _write_document(
            tmp_path,
            "metrics.yaml",
            definition_type="metrics",
            definitions=_metric_definition(extra=field),
        )
        with pytest.raises(SemanticConfigurationError):
            SemanticCatalogLoader(path).load()


def test_loading_does_not_use_recursive_scan_or_runtime_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openai
    import psycopg

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("runtime service or recursive scan was used")

    monkeypatch.setattr(Path, "rglob", forbidden)
    monkeypatch.setattr(openai, "OpenAI", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)

    catalog = SemanticCatalogLoader(FIXTURE_DIRECTORY).load()

    assert catalog.get_metric("order_count").metric_id == "order_count"


def test_semantic_import_is_isolated_from_agents_and_database_runtime() -> None:
    project_root = Path(__file__).parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import data_copilot.semantics; "
            "assert 'data_copilot.agent' not in sys.modules; "
            "assert 'data_copilot.database_agent' not in sys.modules; "
            "assert 'psycopg' not in sys.modules; "
            "assert 'openai' not in sys.modules",
        ],
        cwd=project_root,
        env={"PYTHONPATH": str(project_root / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
