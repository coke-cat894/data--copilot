"""Conservative exact semantic mentions from one original user message."""

from dataclasses import dataclass

from data_copilot.errors import SemanticResolutionLimitError
from data_copilot.semantics.catalog import SemanticCatalog
from data_copilot.semantics.constants import MAX_SEMANTIC_QUERY_TERMS
from data_copilot.semantics.models import normalize_semantic_alias


@dataclass(frozen=True)
class _Mention:
    start: int
    end: int
    alias: str


class SemanticMentionExtractor:
    """Find only configured IDs, names, and synonyms in current user text."""

    def __init__(
        self,
        catalog: SemanticCatalog,
        *,
        max_terms: int = MAX_SEMANTIC_QUERY_TERMS,
    ) -> None:
        if not isinstance(catalog, SemanticCatalog):
            raise TypeError("SemanticMentionExtractor requires a SemanticCatalog.")
        if isinstance(max_terms, bool) or not isinstance(max_terms, int) or max_terms < 1:
            raise SemanticResolutionLimitError(
                "max_terms must be a positive integer."
            )
        self._max_terms = max_terms
        self._aliases = _configured_aliases(catalog)

    def extract(self, user_message: str) -> tuple[str, ...]:
        """Return longest non-overlapping exact configured phrases in text order."""

        if not isinstance(user_message, str):
            raise TypeError("user_message must be a string.")
        normalized_message = user_message.casefold()
        matches: list[_Mention] = []
        for alias, normalized_alias in self._aliases:
            start = 0
            while True:
                start = normalized_message.find(normalized_alias, start)
                if start < 0:
                    break
                end = start + len(normalized_alias)
                if _has_exact_boundaries(
                    normalized_message,
                    normalized_alias,
                    start,
                    end,
                ):
                    matches.append(_Mention(start=start, end=end, alias=alias))
                start += 1

        matches.sort(
            key=lambda mention: (
                -(mention.end - mention.start),
                mention.start,
                normalize_semantic_alias(mention.alias),
            )
        )
        selected: list[_Mention] = []
        for mention in matches:
            if any(
                mention.start < existing.end and existing.start < mention.end
                for existing in selected
            ):
                continue
            selected.append(mention)
        selected.sort(key=lambda mention: mention.start)

        terms: list[str] = []
        seen: set[str] = set()
        for mention in selected:
            normalized = normalize_semantic_alias(mention.alias)
            if normalized not in seen:
                seen.add(normalized)
                terms.append(mention.alias)
        if len(terms) > self._max_terms:
            raise SemanticResolutionLimitError(
                "User message contains too many exact semantic mentions."
            )
        return tuple(terms)


def _configured_aliases(
    catalog: SemanticCatalog,
) -> tuple[tuple[str, str], ...]:
    aliases: dict[str, str] = {}
    for metric in catalog.metrics:
        for alias in (metric.metric_id, metric.name, *metric.synonyms):
            aliases.setdefault(normalize_semantic_alias(alias), alias)
    for dimension in catalog.dimensions:
        for alias in (dimension.dimension_id, dimension.name, *dimension.synonyms):
            aliases.setdefault(normalize_semantic_alias(alias), alias)
    for term in catalog.glossary:
        for alias in (term.term_id, term.term, *term.synonyms):
            aliases.setdefault(normalize_semantic_alias(alias), alias)
    return tuple(
        (alias, normalized)
        for normalized, alias in sorted(
            aliases.items(),
            key=lambda item: (-len(item[0]), item[0]),
        )
    )


def _has_exact_boundaries(
    message: str,
    alias: str,
    start: int,
    end: int,
) -> bool:
    if not any(
        character.isascii() and _is_identifier_character(character)
        for character in alias
    ):
        return True
    before = message[start - 1] if start > 0 else None
    after = message[end] if end < len(message) else None
    return not (
        before is not None
        and before.isascii()
        and _is_identifier_character(before)
    ) and not (
        after is not None
        and after.isascii()
        and _is_identifier_character(after)
    )


def _is_identifier_character(character: str) -> bool:
    return character.isalnum() or character in {"_", "$"}
