"""Bounded conversion of typed Tool Results into compact factual evidence."""

from data_copilot.evidence.builder import EvidenceBuilder
from data_copilot.evidence.formatter import EvidenceFormatter
from data_copilot.evidence.models import (
    Evidence,
    EvidenceMetadata,
    EvidenceOperation,
)

__all__ = [
    "Evidence",
    "EvidenceBuilder",
    "EvidenceFormatter",
    "EvidenceMetadata",
    "EvidenceOperation",
]
