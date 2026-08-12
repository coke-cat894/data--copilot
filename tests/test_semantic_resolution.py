from pathlib import Path
import subprocess
import sys

import pytest

from data_copilot.errors import (
    SemanticAmbiguityError,
    SemanticNotFoundError,
    SemanticResolutionLimitError,
)
from data_copilot.semantics import (
    DimensionDefinition,
    GlossaryTerm,
    MetricDefinition,
    SemanticCatalog,
    SemanticCatalogLoader,
    SemanticMatchType,
    SemanticProvenance,
    SemanticResolver,
    SemanticType,
)


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "semantic"


@pytest.fixture
def resolver() -> SemanticResolver:
    return SemanticResolver(SemanticCatalogLoader(FIXTURE_DIRECTORY).load())


@pytest.mark.parametrize(
    ("term", "match_type"),
    [
        ("completed_revenue", SemanticMatchType.EXACT_ID),
        ("completed revenue", SemanticMatchType.CANONICAL_NAME),
        ("fulfilled revenue", SemanticMatchType.EXPLICIT_SYNONYM),
        ("  FULFILLED REVENUE  ", SemanticMatchType.EXPLICIT_SYNONYM),
    ],
)
def test_resolves_metric_by_deterministic_alias_class(
    resolver: SemanticResolver,
    term: str,
    match_type: SemanticMatchType,
) -> None:
    result = resolver.resolve(term)

    assert result.query_term == term.strip()
    assert result.semantic_type is SemanticType.METRIC
    assert result.definition_id == "completed_revenue"
    assert result.canonical_name == "completed revenue"
    assert result.match_type is match_type
    assert result.provenance.source == "metrics.yaml"


def test_resolves_dimension_by_id(resolver: SemanticResolver) -> None:
    result = resolver.resolve(" REGION ")

    assert result.semantic_type is SemanticType.DIMENSION
    assert result.definition_id == "region"
    assert result.match_type is SemanticMatchType.EXACT_ID


@pytest.mark.parametrize(
    ("term", "match_type"),
    [
        ("Sales Territory", SemanticMatchType.CANONICAL_NAME),
        ("market area", SemanticMatchType.EXPLICIT_SYNONYM),
    ],
)
def test_resolves_dimension_by_name_and_synonym(
    term: str,
    match_type: SemanticMatchType,
) -> None:
    dimension = DimensionDefinition(
        dimension_id="territory",
        name="Sales Territory",
        display_name="Sales Territory",
        description="Synthetic sales territory.",
        synonyms=("market area",),
        source_fields=("commerce.users.territory",),
        provenance=SemanticProvenance(
            source="dimensions.yaml",
            definition_id="territory",
        ),
    )

    result = SemanticResolver(SemanticCatalog(dimensions=(dimension,))).resolve(term)

    assert result.definition_id == "territory"
    assert result.match_type is match_type


@pytest.mark.parametrize(
    ("term", "match_type"),
    [
        ("completed_order", SemanticMatchType.EXACT_ID),
        ("Completed Order", SemanticMatchType.CANONICAL_NAME),
        ("FULFILLED ORDER", SemanticMatchType.EXPLICIT_SYNONYM),
    ],
)
def test_resolves_glossary_term(
    resolver: SemanticResolver,
    term: str,
    match_type: SemanticMatchType,
) -> None:
    result = resolver.resolve(term)

    assert result.semantic_type is SemanticType.GLOSSARY
    assert result.definition_id == "completed_order"
    assert result.match_type is match_type


@pytest.mark.parametrize("term", ["missing semantic", "", "   ", None])
def test_missing_or_empty_term_fails_closed(
    resolver: SemanticResolver,
    term: object,
) -> None:
    with pytest.raises(SemanticNotFoundError, match="not found"):
        resolver.resolve(term)  # type: ignore[arg-type]


def test_cross_type_ambiguity_fails_without_priority(
    resolver: SemanticResolver,
) -> None:
    # The dimension explicitly aliases this term and the glossary owns it canonically.
    with pytest.raises(SemanticAmbiguityError, match="ambiguous"):
        resolver.resolve("customer region")


def test_multi_term_resolution_preserves_order(resolver: SemanticResolver) -> None:
    results = resolver.resolve_many(["sales value", "region", "order_count"])

    assert tuple(result.definition_id for result in results) == (
        "revenue",
        "region",
        "order_count",
    )
    assert tuple(result.semantic_type for result in results) == (
        SemanticType.GLOSSARY,
        SemanticType.DIMENSION,
        SemanticType.METRIC,
    )


def test_empty_multi_term_request_is_valid(resolver: SemanticResolver) -> None:
    assert resolver.resolve_many([]) == ()


def test_multi_term_resolution_is_bounded(resolver: SemanticResolver) -> None:
    with pytest.raises(SemanticResolutionLimitError, match="too many"):
        resolver.resolve_many(["region"] * 21)


def test_resolver_does_not_fuzzy_match_or_parse_prose(
    resolver: SemanticResolver,
) -> None:
    for term in ("regions", "show me completed revenue", "completed-revenue"):
        with pytest.raises(SemanticNotFoundError):
            resolver.resolve(term)


def test_match_class_uses_exact_id_for_same_definition_alias() -> None:
    provenance = SemanticProvenance(source="metrics.yaml", definition_id="revenue")
    metric = MetricDefinition(
        metric_id="revenue",
        name="revenue",
        display_name="Revenue",
        description="Synthetic revenue.",
        synonyms=("Revenue",),
        business_definition="Synthetic revenue definition.",
        required_fields=("commerce.orders.amount",),
        provenance=provenance,
    )
    result = SemanticResolver(SemanticCatalog(metrics=(metric,))).resolve("Revenue")

    assert result.match_type is SemanticMatchType.EXACT_ID


def test_ambiguity_is_independent_of_catalog_insertion_order() -> None:
    metric = MetricDefinition(
        metric_id="sales",
        name="sales",
        display_name="Sales",
        description="Synthetic sales.",
        business_definition="Synthetic sales.",
        required_fields=("commerce.orders.amount",),
        provenance=SemanticProvenance(
            source="metrics.yaml",
            definition_id="sales",
        ),
    )
    term = GlossaryTerm(
        term_id="sales_term",
        term="Sales",
        definition="Synthetic sales concept.",
        provenance=SemanticProvenance(
            source="glossary.yaml",
            definition_id="sales_term",
        ),
    )
    catalogs = (
        SemanticCatalog(metrics=(metric,), glossary=(term,)),
        SemanticCatalog(glossary=(term,), metrics=(metric,)),
    )

    for catalog in catalogs:
        with pytest.raises(SemanticAmbiguityError):
            SemanticResolver(catalog).resolve("sales")


def test_resolution_import_has_no_agent_llm_database_or_sql_runtime_dependency() -> None:
    project_root = Path(__file__).parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from data_copilot.semantics import SemanticResolver; "
            "forbidden={'openai','psycopg','data_copilot.agent',"
            "'data_copilot.database_agent','data_copilot.sql.validator'}; "
            "assert forbidden.isdisjoint(sys.modules)",
        ],
        cwd=project_root,
        env={"PYTHONPATH": str(project_root / "src")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
