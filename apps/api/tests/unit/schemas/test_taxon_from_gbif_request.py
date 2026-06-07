"""Unit tests for ``TaxonFromGBIFRequest`` blank-vernacular tolerance.

Regression: GBIF/iNat search payloads can include a vernacular entry with a
null/empty ``language`` (or, rarely, ``name``). The frontend forwards
``vernacular_names`` verbatim into the from-GBIF body, and a single junk entry
used to trip ``VernacularNameInput``'s ``min_length=1`` constraint and 422 the
whole add. The request now drops blank entries BEFORE per-item validation so the
add succeeds and the good names (incl. the ja 和名) still persist.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from echoroo.schemas.taxon import TaxonFromGBIFRequest


def test_blank_language_entry_is_dropped_and_request_validates() -> None:
    """A stray empty-language vernacular entry is filtered, not a 422."""
    req = TaxonFromGBIFRequest(
        scientific_name="Hirundo rustica",
        gbif_taxon_key=9515886,
        common_name="Barn Swallow",
        vernacular_names=[
            {"name": "Barn Swallow", "language": "en", "source": "gbif"},
            {"name": "No Language", "language": ""},  # junk: empty language
        ],
    )
    assert req.vernacular_names is not None
    names = {(vn.name, vn.language) for vn in req.vernacular_names}
    assert ("Barn Swallow", "en") in names
    assert all(vn.language for vn in req.vernacular_names)
    assert len(req.vernacular_names) == 1


def test_blank_name_entry_is_dropped() -> None:
    """An empty-name vernacular entry is filtered out, others survive."""
    req = TaxonFromGBIFRequest(
        scientific_name="Passer montanus",
        vernacular_names=[
            {"name": "", "language": "en"},  # junk: empty name
            {"name": "Eurasian Tree Sparrow", "language": "en"},
        ],
    )
    assert req.vernacular_names is not None
    assert len(req.vernacular_names) == 1
    assert req.vernacular_names[0].name == "Eurasian Tree Sparrow"


def test_regression_ja_entry_survives_blank_language_entry() -> None:
    """Mirror the real failure: a ja entry + a blank-language entry.

    Adding the species must succeed (no 422) and the ja 和名 must be kept.
    """
    req = TaxonFromGBIFRequest(
        scientific_name="Cyanopica cyanus",
        gbif_taxon_key=2482552,
        common_name="オナガ",
        vernacular_names=[
            {"name": "オナガ", "language": "jpn", "source": "inaturalist"},
            {"name": "Azure-winged Magpie", "language": "en", "source": "gbif"},
            {"name": "junk", "language": ""},  # blank-language entry from GBIF
        ],
    )
    assert req.vernacular_names is not None
    surviving = {(vn.name, vn.language) for vn in req.vernacular_names}
    assert ("オナガ", "jpn") in surviving
    assert ("Azure-winged Magpie", "en") in surviving
    assert all(vn.language and vn.name for vn in req.vernacular_names)
    assert len(req.vernacular_names) == 2


def test_whitespace_only_entries_are_dropped() -> None:
    """Whitespace-only name/language entries are treated as blank and dropped."""
    req = TaxonFromGBIFRequest(
        scientific_name="Corvus corone",
        vernacular_names=[
            {"name": "   ", "language": "en"},  # whitespace-only name
            {"name": "Crow", "language": "  "},  # whitespace-only language
            {"name": "Carrion Crow", "language": "en"},
        ],
    )
    assert req.vernacular_names is not None
    assert len(req.vernacular_names) == 1
    assert req.vernacular_names[0].name == "Carrion Crow"


def test_none_vernacular_names_is_unchanged() -> None:
    """A ``None`` vernacular list passes through untouched."""
    req = TaxonFromGBIFRequest(scientific_name="Turdus merula")
    assert req.vernacular_names is None


def test_malformed_non_dict_entry_still_raises() -> None:
    """A genuinely malformed (non-dict, non-blank) shape still surfaces a 422.

    The filter only drops blank entries; it must not silently swallow shapes
    that should fail validation.
    """
    with pytest.raises(ValidationError):
        TaxonFromGBIFRequest(
            scientific_name="Sturnus vulgaris",
            vernacular_names=["not-a-dict"],
        )
