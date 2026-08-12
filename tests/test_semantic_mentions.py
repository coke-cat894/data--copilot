from pathlib import Path

import pytest

from data_copilot.errors import SemanticAmbiguityError
from data_copilot.semantics import (
    SemanticCatalogLoader,
    SemanticMentionExtractor,
)
from data_copilot.tools.semantic_context import SemanticResolutionTool


PROJECT_ROOT = Path(__file__).parents[1]
PHASE_3_SEMANTICS = PROJECT_ROOT / "evals/fixtures/phase_3_semantic"
TEST_SEMANTICS = Path(__file__).parent / "fixtures/semantic"


def test_exact_chinese_synonym_is_extracted_from_original_user_message() -> None:
    extractor = SemanticMentionExtractor(
        SemanticCatalogLoader(PHASE_3_SEMANTICS).load()
    )

    assert extractor.extract("销售额是怎么定义的？") == ("销售额",)


def test_multiple_metric_and_dimension_mentions_use_one_bounded_collection() -> None:
    catalog = SemanticCatalogLoader(PHASE_3_SEMANTICS).load()
    extractor = SemanticMentionExtractor(catalog)
    tool = SemanticResolutionTool(catalog)

    assert extractor.extract("哪个 region 的销售额最高？") == (
        "region",
        "销售额",
    )
    evidence = tool.invoke(
        '{"terms":["paraphrased business measure"]}',
        current_user_message="哪个 region 的销售额最高？",
    )

    assert {
        (definition.semantic_type, getattr(definition, "metric_id", None),
         getattr(definition, "dimension_id", None))
        for definition in evidence.definitions
    } == {
        ("metric", "completed_revenue", None),
        ("dimension", None, "region"),
    }


def test_longest_exact_phrase_wins_over_overlapping_alias() -> None:
    extractor = SemanticMentionExtractor(
        SemanticCatalogLoader(PHASE_3_SEMANTICS).load()
    )

    assert extractor.extract("Define completed revenue.") == (
        "completed revenue",
    )


def test_similar_unconfigured_word_does_not_fuzzy_match() -> None:
    extractor = SemanticMentionExtractor(
        SemanticCatalogLoader(PHASE_3_SEMANTICS).load()
    )

    assert extractor.extract("请定义销售这个词。") == ()
    assert extractor.extract("regionalized revenueful value") == ()


def test_exact_cross_type_ambiguity_still_fails_closed() -> None:
    catalog = SemanticCatalogLoader(TEST_SEMANTICS).load()
    tool = SemanticResolutionTool(catalog)

    with pytest.raises(SemanticAmbiguityError):
        tool.invoke(
            '{"terms":["unrelated paraphrase"]}',
            current_user_message="Explain customer region.",
        )
