"""Unit tests for :mod:`echoroo.services.taxon_resolution` (WS-A v2 slice 4).

The resolver is the single seam that turns an upstream scientific name (IUCN
Red List, Japanese MoE Red Data Book) into a local ``taxa.id`` UUID, which
migration 0034 made the key of the sensitive-species masking tables. A wrong
match here would mask the wrong species — or, worse, leave a sensitive one
unmasked — so each of the three matching paths is pinned:

1. exact ``taxa.scientific_name``
2. bundled BirdNET -> AviList crosswalk, forward
3. the same crosswalk, reverse (AviList -> BirdNET), which is the path that
   actually matters for IUCN/IOC-aligned upstreams

plus the "no match at all" path, which must be silently absent from the result
so callers can count and skip it.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import pytest

from echoroo.services import taxon_resolution
from echoroo.services.taxon_resolution import (
    build_reverse_crosswalk,
    collapse_strictest,
    log_unresolved_sample,
    resolve_taxon_ids_by_scientific_name,
)


class _StubResult:
    """Mirror of the SQLAlchemy ``Result`` surface the resolver touches."""

    def __init__(self, rows: list[tuple[UUID, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[UUID, str]]:
        return self._rows


class _StubSession:
    """Counts ``execute`` calls so the one-query guarantee is testable."""

    def __init__(self, rows: list[tuple[UUID, str]]) -> None:
        self._rows = rows
        self.execute_calls = 0

    async def execute(self, _stmt: Any) -> _StubResult:
        self.execute_calls += 1
        return _StubResult(self._rows)


#: BirdNET (eBird/Clements) name -> AviList name, as the bundled crosswalk
#: ships it. ``Accipiter gularis`` -> ``Tachyspiza gularis`` is a real pair.
_CROSSWALK = {"Accipiter gularis": "Tachyspiza gularis"}


@pytest.fixture
def bundled_crosswalk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the bundled crosswalk so the test does not depend on the data file."""
    monkeypatch.setattr(
        taxon_resolution, "read_bundled_birdnet_crosswalk", lambda: dict(_CROSSWALK)
    )


@pytest.mark.asyncio
async def test_exact_scientific_name_match(bundled_crosswalk: None) -> None:
    taxon_id = uuid4()
    session = _StubSession([(taxon_id, "Nipponia nippon")])

    resolved = await resolve_taxon_ids_by_scientific_name(
        session, ["Nipponia nippon"]
    )

    assert resolved == {"Nipponia nippon": taxon_id}
    assert session.execute_calls == 1, "the taxa table must be read exactly once"


@pytest.mark.asyncio
async def test_crosswalk_forward_match(bundled_crosswalk: None) -> None:
    """Upstream supplies the BirdNET name; ``taxa`` stores the AviList one."""
    taxon_id = uuid4()
    session = _StubSession([(taxon_id, "Tachyspiza gularis")])

    resolved = await resolve_taxon_ids_by_scientific_name(
        session, ["Accipiter gularis"]
    )

    assert resolved == {"Accipiter gularis": taxon_id}


@pytest.mark.asyncio
async def test_crosswalk_reverse_match(bundled_crosswalk: None) -> None:
    """Upstream supplies the AviList name; ``taxa`` stores the BirdNET one.

    This is the common case: local taxa are seeded from BirdNET V2.4 labels
    while IUCN / IOC-aligned lists publish the AviList concept.
    """
    taxon_id = uuid4()
    session = _StubSession([(taxon_id, "Accipiter gularis")])

    resolved = await resolve_taxon_ids_by_scientific_name(
        session, ["Tachyspiza gularis"]
    )

    assert resolved == {"Tachyspiza gularis": taxon_id}


@pytest.mark.asyncio
async def test_unresolved_names_are_absent(bundled_crosswalk: None) -> None:
    """No match through any of the three paths → simply not in the result."""
    session = _StubSession([(uuid4(), "Nipponia nippon")])

    resolved = await resolve_taxon_ids_by_scientific_name(
        session, ["Absolutely nonexistens"]
    )

    assert resolved == {}


@pytest.mark.asyncio
async def test_mixed_batch_resolves_independently(bundled_crosswalk: None) -> None:
    exact_id = uuid4()
    crosswalk_id = uuid4()
    session = _StubSession(
        [(exact_id, "Nipponia nippon"), (crosswalk_id, "Accipiter gularis")]
    )

    resolved = await resolve_taxon_ids_by_scientific_name(
        session,
        ["Nipponia nippon", "Tachyspiza gularis", "Absolutely nonexistens"],
    )

    assert resolved == {
        "Nipponia nippon": exact_id,
        "Tachyspiza gularis": crosswalk_id,
    }


@pytest.mark.asyncio
async def test_blank_and_duplicate_names_are_tolerated(
    bundled_crosswalk: None,
) -> None:
    """Blanks are dropped; whitespace is trimmed; duplicates collapse."""
    taxon_id = uuid4()
    session = _StubSession([(taxon_id, "Nipponia nippon")])

    resolved = await resolve_taxon_ids_by_scientific_name(
        session, ["  Nipponia nippon ", "Nipponia nippon", "", "   "]
    )

    assert resolved == {"Nipponia nippon": taxon_id}
    assert session.execute_calls == 1


@pytest.mark.asyncio
async def test_empty_input_short_circuits() -> None:
    """No names → no query at all."""
    session = _StubSession([(uuid4(), "Nipponia nippon")])

    assert await resolve_taxon_ids_by_scientific_name(session, []) == {}
    assert session.execute_calls == 0


@pytest.mark.asyncio
async def test_missing_bundle_degrades_to_exact_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken/absent bundle must not abort the sync — exact matching stays."""

    def _boom() -> dict[str, str]:
        raise FileNotFoundError("bundle missing")

    monkeypatch.setattr(taxon_resolution, "read_bundled_birdnet_crosswalk", _boom)
    taxon_id = uuid4()
    session = _StubSession([(taxon_id, "Nipponia nippon")])

    resolved = await resolve_taxon_ids_by_scientific_name(
        session, ["Nipponia nippon", "Tachyspiza gularis"]
    )

    assert resolved == {"Nipponia nippon": taxon_id}


def test_log_unresolved_sample_truncates(caplog: pytest.LogCaptureFixture) -> None:
    """At most ``UNRESOLVED_LOG_SAMPLE`` names reach the log line."""
    logger = logging.getLogger("test.taxon_resolution")
    names = [f"Genus species{i:03d}" for i in range(50)]

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_unresolved_sample(logger, "unit_test", names)

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "50" in message
    assert "Genus species000" in message
    assert "Genus species010" not in message


def test_log_unresolved_sample_is_silent_when_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.taxon_resolution.empty")

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_unresolved_sample(logger, "unit_test", [])

    assert caplog.records == []


# ---------------------------------------------------------------------------
# build_reverse_crosswalk — lumped-species ambiguity (Codex finding 4)
# ---------------------------------------------------------------------------


def test_reverse_crosswalk_keeps_unambiguous_pairs() -> None:
    forward = {"Accipiter gularis": "Tachyspiza gularis"}

    assert build_reverse_crosswalk(forward) == {
        "Tachyspiza gularis": "Accipiter gularis"
    }


def test_reverse_crosswalk_drops_lumped_targets() -> None:
    """Two BirdNET names -> one AviList name must NOT be reversible.

    AviList lumps species eBird/Clements splits. A naive dict inversion keeps
    whichever BirdNET label iterated last, so an IUCN row for the lumped
    species would mask one arbitrary member of the split and leave its
    siblings exposed. The ambiguous target is dropped instead.
    """
    forward = {
        "Zosterops japonicus": "Zosterops simplex",
        "Zosterops simplex": "Zosterops simplex",
        "Accipiter gularis": "Tachyspiza gularis",
    }

    reverse = build_reverse_crosswalk(forward)

    assert "Zosterops simplex" not in reverse
    # The unambiguous pair alongside it must survive.
    assert reverse == {"Tachyspiza gularis": "Accipiter gularis"}


def test_reverse_crosswalk_logs_ambiguous_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    forward = {"A a": "L l", "B b": "L l", "C c": "M m", "D d": "M m"}

    with caplog.at_level(logging.INFO, logger=taxon_resolution.logger.name):
        build_reverse_crosswalk(forward)

    assert any("2 AviList name" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_lumped_avilist_name_does_not_resolve_via_reverse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: the lumped AviList name is reported unresolved."""
    monkeypatch.setattr(
        taxon_resolution,
        "read_bundled_birdnet_crosswalk",
        lambda: {
            "Zosterops japonicus": "Zosterops simplex",
            "Zosterops simplex": "Zosterops simplex",
        },
    )
    japonicus_id = uuid4()
    session = _StubSession([(japonicus_id, "Zosterops japonicus")])

    resolved = await resolve_taxon_ids_by_scientific_name(
        session, ["Zosterops simplex"]
    )

    assert resolved == {}, (
        "a lumped AviList name must stay unresolved rather than binding to an "
        "arbitrary member of the split"
    )


@pytest.mark.asyncio
async def test_exact_match_still_wins_over_ambiguous_crosswalk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``taxa`` actually holds the lumped name, step 1 resolves it."""
    monkeypatch.setattr(
        taxon_resolution,
        "read_bundled_birdnet_crosswalk",
        lambda: {
            "Zosterops japonicus": "Zosterops simplex",
            "Zosterops simplex": "Zosterops simplex",
        },
    )
    simplex_id = uuid4()
    session = _StubSession([(simplex_id, "Zosterops simplex")])

    resolved = await resolve_taxon_ids_by_scientific_name(
        session, ["Zosterops simplex"]
    )

    assert resolved == {"Zosterops simplex": simplex_id}


# ---------------------------------------------------------------------------
# collapse_strictest (Codex finding 5)
# ---------------------------------------------------------------------------


def test_collapse_strictest_picks_lowest_h3_res() -> None:
    taxon_id = uuid4()

    collapsed = collapse_strictest(
        [(taxon_id, 5, "EN", "strict"), (taxon_id, 9, "LC", "loose")]
    )

    assert collapsed == {taxon_id: (5, "EN", "strict")}


def test_collapse_strictest_is_order_independent() -> None:
    """Reversing the input must not change which recommendation wins."""
    taxon_id = uuid4()

    forwards = collapse_strictest(
        [(taxon_id, 5, "EN", None), (taxon_id, 9, "LC", None)]
    )
    backwards = collapse_strictest(
        [(taxon_id, 9, "LC", None), (taxon_id, 5, "EN", None)]
    )

    assert forwards == backwards == {taxon_id: (5, "EN", None)}


def test_collapse_strictest_keeps_distinct_taxa_apart() -> None:
    a, b = uuid4(), uuid4()

    collapsed = collapse_strictest(
        [(a, 5, "EN", None), (b, 9, "LC", None), (a, 7, "VU", None)]
    )

    assert collapsed == {a: (5, "EN", None), b: (9, "LC", None)}


def test_collapse_strictest_handles_empty_input() -> None:
    assert collapse_strictest([]) == {}
