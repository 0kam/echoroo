"""Unit tests for the `_generate_session_name` helper.

These pin the exact user-facing output format of auto-generated search
session names across single / 3-exact / 4+ truncated species, and the
"Unknown" fallback when both common_name and scientific_name are missing.
"""

import re

from echoroo.services.search_session import _generate_session_name

DATE_RE = r"\d{4}-\d{2}-\d{2}"


def test_single_species_uses_common_name() -> None:
    """One species with a common_name produces `<name> - YYYY-MM-DD`."""
    species_config: list[dict[str, object]] = [
        {"common_name": "Common Blackbird", "scientific_name": "Turdus merula"},
    ]
    result = _generate_session_name(species_config)
    assert re.fullmatch(rf"Common Blackbird - {DATE_RE}", result) is not None, result


def test_exactly_three_species_no_ellipsis() -> None:
    """Exactly 3 species are all joined with ', ' and no ellipsis."""
    species_config: list[dict[str, object]] = [
        {"common_name": "A"},
        {"common_name": "B"},
        {"common_name": "C"},
    ]
    result = _generate_session_name(species_config)
    assert re.fullmatch(rf"A, B, C - {DATE_RE}", result) is not None, result
    assert "..." not in result


def test_four_species_truncated_with_ellipsis() -> None:
    """4+ species: only the first 3 + '...' appear before ' - '."""
    species_config: list[dict[str, object]] = [
        {"common_name": "A"},
        {"common_name": "B"},
        {"common_name": "C"},
        {"common_name": "D"},
    ]
    result = _generate_session_name(species_config)
    assert re.fullmatch(rf"A, B, C\.\.\. - {DATE_RE}", result) is not None, result
    assert "D" not in result


def test_five_species_still_truncated_to_three() -> None:
    """More than 4 species still truncates to first 3 with a single '...'."""
    species_config: list[dict[str, object]] = [
        {"common_name": "A"},
        {"common_name": "B"},
        {"common_name": "C"},
        {"common_name": "D"},
        {"common_name": "E"},
    ]
    result = _generate_session_name(species_config)
    assert re.fullmatch(rf"A, B, C\.\.\. - {DATE_RE}", result) is not None, result


def test_missing_common_name_falls_back_to_scientific_name() -> None:
    """Species without common_name use scientific_name instead."""
    species_config: list[dict[str, object]] = [
        {"scientific_name": "Turdus merula"},
    ]
    result = _generate_session_name(species_config)
    assert re.fullmatch(rf"Turdus merula - {DATE_RE}", result) is not None, result


def test_missing_both_names_falls_back_to_unknown() -> None:
    """Species missing both common_name and scientific_name become 'Unknown'."""
    species_config: list[dict[str, object]] = [
        {},
    ]
    result = _generate_session_name(species_config)
    assert re.fullmatch(rf"Unknown - {DATE_RE}", result) is not None, result


def test_empty_common_name_falls_back_to_scientific_name() -> None:
    """An empty-string common_name (falsy) falls through to scientific_name."""
    species_config: list[dict[str, object]] = [
        {"common_name": "", "scientific_name": "Turdus merula"},
    ]
    result = _generate_session_name(species_config)
    assert re.fullmatch(rf"Turdus merula - {DATE_RE}", result) is not None, result
