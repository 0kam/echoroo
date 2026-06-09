"""Unit tests for ``SpeciesSummaryItem`` vernacular_name serialization.

i18n fix: ``SpeciesSummaryItem`` mirrors ``TagResponse`` by exposing a
locale-resolved ``vernacular_name`` distinct from the English-legacy
``common_name``. The species-summary detail page prefers ``vernacular_name``
(falling back to ``common_name``) to render the Japanese 和名 under ``/ja``.

The full ``DetectionService.get_species_summary`` path cannot be exercised
here because it reads the Phase 14+ deferred ``recording_annotations`` table
(see ``echoroo/services/detection.py`` module docstring), so these tests pin
the schema contract directly. The ja→en resolution that fills the field is
covered by ``tests/unit/services/test_vernacular_locale_fallback.py``.
"""

from __future__ import annotations

from uuid import uuid4

from echoroo.schemas.detection import SpeciesSummaryItem


def test_vernacular_name_defaults_to_none() -> None:
    """``vernacular_name`` is optional and defaults to ``None``."""
    item = SpeciesSummaryItem(
        tag_id=uuid4(),
        tag_name="Turdus merula",
        scientific_name="Turdus merula",
        common_name="Common blackbird",
        taxon_id=uuid4(),
        total_count=3,
        unreviewed_count=1,
        confirmed_count=1,
        rejected_count=1,
        avg_confidence=0.85,
    )

    assert item.vernacular_name is None
    dumped = item.model_dump()
    assert "vernacular_name" in dumped
    assert dumped["vernacular_name"] is None


def test_vernacular_name_kept_distinct_from_common_name() -> None:
    """The locale-resolved 和名 lives in ``vernacular_name``; ``common_name``
    stays the English legacy value (no overwrite)."""
    item = SpeciesSummaryItem(
        tag_id=uuid4(),
        tag_name="Turdus merula",
        scientific_name="Turdus merula",
        common_name="Common blackbird",
        vernacular_name="クロウタドリ",
        taxon_id=uuid4(),
        total_count=3,
        unreviewed_count=1,
        confirmed_count=1,
        rejected_count=1,
        avg_confidence=0.85,
    )

    dumped = item.model_dump()
    assert dumped["vernacular_name"] == "クロウタドリ"
    assert dumped["common_name"] == "Common blackbird"
