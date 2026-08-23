"""Unit tests for the IUCN sync's taxon-resolution behaviour (WS-A v2 slice 4).

Migration 0034 re-keyed ``taxon_sensitivities.taxon_id`` onto ``taxa.id``.
The IUCN API's ``taxonid`` is an IUCN SIS identifier in an unrelated key-space,
so :func:`echoroo.workers.iucn_sync._apply_snapshot` now resolves each snapshot
row by ``scientific_name`` and **skips + counts** the ones with no local taxon.

These tests pin:

* snapshot rows resolve by scientific name, not by ``taxonid``;
* unresolvable rows are counted into ``unresolved`` and never upserted;
* skipped rows do not inflate ``synced``, and therefore cannot dilute the
  FR-036 "10 % loosened" sanity ratio;
* the ``taxa`` table is read exactly once per sync, not once per row.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import pytest

from echoroo.models.enums import TaxonSensitivitySource
from echoroo.workers import iucn_sync


class _StubSession:
    """Async-context session stub recording commit / rollback."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> _StubSession:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.fixture
def patched_sync(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the DB seams of ``_apply_snapshot`` and capture the upserts."""
    session = _StubSession()
    state: dict[str, Any] = {
        "session": session,
        "upserts": [],
        "resolve_calls": 0,
        "resolve_input": [],
        # scientific_name -> taxa.id
        "known": {},
        # taxon ids that should report "loosened"
        "loosened": set(),
    }

    monkeypatch.setattr(iucn_sync, "AsyncSessionLocal", lambda: session)

    async def _acquire(_session: Any) -> bool:
        return True

    monkeypatch.setattr(iucn_sync, "_try_acquire_lock", _acquire)

    async def _resolve(_session: Any, names: Any) -> dict[str, UUID]:
        state["resolve_calls"] += 1
        materialised = [n.strip() for n in names if n and n.strip()]
        state["resolve_input"] = materialised
        return {n: state["known"][n] for n in materialised if n in state["known"]}

    monkeypatch.setattr(
        iucn_sync, "resolve_taxon_ids_by_scientific_name", _resolve
    )

    async def _upsert(_session: Any, **kwargs: Any) -> tuple[bool, int | None]:
        state["upserts"].append(kwargs)
        loosened = kwargs["taxon_id"] in state["loosened"]
        return loosened, 9 if loosened else None

    monkeypatch.setattr(iucn_sync, "upsert_taxon_sensitivity", _upsert)
    return state


@pytest.mark.asyncio
async def test_rows_resolve_by_scientific_name_not_taxonid(
    patched_sync: dict[str, Any],
) -> None:
    taxon_uuid = uuid4()
    patched_sync["known"] = {"Nipponia nippon": taxon_uuid}

    synced, loosened, unresolved = await iucn_sync._apply_snapshot(
        [{"taxonid": 22697548, "scientific_name": "Nipponia nippon", "category": "EN"}]
    )

    assert (synced, loosened, unresolved) == (1, 0, 0)
    assert len(patched_sync["upserts"]) == 1
    upsert = patched_sync["upserts"][0]
    assert upsert["taxon_id"] == taxon_uuid
    assert upsert["source"] is TaxonSensitivitySource.IUCN
    assert upsert["sensitivity_h3_res"] == 5  # EN -> H3_RES_5
    assert upsert["category"] == "EN"


@pytest.mark.asyncio
async def test_unresolvable_rows_are_skipped_and_counted(
    patched_sync: dict[str, Any],
) -> None:
    known_uuid = uuid4()
    patched_sync["known"] = {"Nipponia nippon": known_uuid}

    synced, loosened, unresolved = await iucn_sync._apply_snapshot(
        [
            {"taxonid": 1, "scientific_name": "Nipponia nippon", "category": "EN"},
            {"taxonid": 2, "scientific_name": "Absolutely nonexistens", "category": "CR"},
            {"taxonid": 3, "scientific_name": "Also nonexistens", "category": "VU"},
        ]
    )

    assert unresolved == 2
    # Skipped rows are NOT synced — they must not dilute the 10 % ratio.
    assert synced == 1
    assert loosened == 0
    assert [u["taxon_id"] for u in patched_sync["upserts"]] == [known_uuid]
    assert patched_sync["session"].committed is True


@pytest.mark.asyncio
async def test_unmapped_category_still_skipped_without_counting_unresolved(
    patched_sync: dict[str, Any],
) -> None:
    """``DD`` / ``NE`` fall outside the H3 mapping and are not "unresolved"."""
    patched_sync["known"] = {"Nipponia nippon": uuid4()}

    synced, _loosened, unresolved = await iucn_sync._apply_snapshot(
        [{"taxonid": 1, "scientific_name": "Nipponia nippon", "category": "DD"}]
    )

    assert (synced, unresolved) == (0, 0)
    assert patched_sync["upserts"] == []


@pytest.mark.asyncio
async def test_blank_scientific_name_is_skipped(
    patched_sync: dict[str, Any],
) -> None:
    patched_sync["known"] = {}

    synced, _loosened, unresolved = await iucn_sync._apply_snapshot(
        [{"taxonid": 1, "scientific_name": "", "category": "EN"}]
    )

    assert (synced, unresolved) == (0, 0)
    assert patched_sync["upserts"] == []


@pytest.mark.asyncio
async def test_taxa_are_resolved_in_a_single_bulk_call(
    patched_sync: dict[str, Any],
) -> None:
    """NFR: one lookup per sync, not one per snapshot row."""
    patched_sync["known"] = {f"Genus species{i}": uuid4() for i in range(5)}

    await iucn_sync._apply_snapshot(
        [
            {"taxonid": i, "scientific_name": f"Genus species{i}", "category": "EN"}
            for i in range(5)
        ]
    )

    assert patched_sync["resolve_calls"] == 1
    assert len(patched_sync["resolve_input"]) == 5


@pytest.mark.asyncio
async def test_skipped_rows_cannot_trip_the_loosen_sanity_check(
    patched_sync: dict[str, Any],
) -> None:
    """One loosened row out of ten synced stays under the 10 % threshold.

    Nine additional unresolvable rows must not change that verdict — if they
    were counted as ``synced`` the ratio would silently look safer, and if the
    loosened row were counted against a smaller denominator the sync would
    abort spuriously.
    """
    ids = {f"Genus species{i}": uuid4() for i in range(10)}
    patched_sync["known"] = ids
    patched_sync["loosened"] = {ids["Genus species0"]}

    rows = [
        {"taxonid": i, "scientific_name": f"Genus species{i}", "category": "EN"}
        for i in range(10)
    ] + [
        {"taxonid": 100 + i, "scientific_name": f"Ghost species{i}", "category": "EN"}
        for i in range(9)
    ]

    synced, loosened, unresolved = await iucn_sync._apply_snapshot(rows)

    assert (synced, loosened, unresolved) == (10, 1, 9)
    assert patched_sync["session"].committed is True


@pytest.mark.asyncio
async def test_loosen_threshold_still_rolls_back(
    patched_sync: dict[str, Any],
) -> None:
    """FR-036 sanity rule survives the re-key: >10 % loosened aborts."""
    ids = {f"Genus species{i}": uuid4() for i in range(4)}
    patched_sync["known"] = ids
    patched_sync["loosened"] = set(ids.values())

    with pytest.raises(RuntimeError, match="sanity check failed"):
        await iucn_sync._apply_snapshot(
            [
                {"taxonid": i, "scientific_name": f"Genus species{i}", "category": "EN"}
                for i in range(4)
            ]
        )

    assert patched_sync["session"].rolled_back is True
    assert patched_sync["session"].committed is False


@pytest.mark.asyncio
async def test_lock_contention_is_a_noop(
    monkeypatch: pytest.MonkeyPatch, patched_sync: dict[str, Any]
) -> None:
    """A held advisory lock still short-circuits to the zero triple."""

    async def _no_lock(_session: Any) -> bool:
        return False

    monkeypatch.setattr(iucn_sync, "_try_acquire_lock", _no_lock)

    assert await iucn_sync._apply_snapshot(
        [{"taxonid": 1, "scientific_name": "Nipponia nippon", "category": "EN"}]
    ) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Coverage collapse gate (Codex finding 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_unresolved_snapshot_raises(
    patched_sync: dict[str, Any],
) -> None:
    """Zero resolved out of N candidates must FAIL the sync, not succeed.

    A "success, synced=0" run clears the FR-036 fail-safe flag on the strength
    of a sync that wrote nothing — exactly the stale-data scenario the
    fail-safe exists for. Raising keeps the flag armed.
    """
    patched_sync["known"] = {}

    with pytest.raises(RuntimeError, match="coverage check failed"):
        await iucn_sync._apply_snapshot(
            [
                {"taxonid": i, "scientific_name": f"Ghost species{i}", "category": "EN"}
                for i in range(3)
            ]
        )

    assert patched_sync["session"].rolled_back is True
    assert patched_sync["session"].committed is False
    assert patched_sync["upserts"] == []


@pytest.mark.asyncio
async def test_partial_coverage_succeeds(patched_sync: dict[str, Any]) -> None:
    """One resolved row out of many is enough — no ratio threshold.

    The IUCN Red List lists ~11k birds against ~6.5k local BirdNET taxa, so a
    large unresolved share is the expected steady state and must not fail.
    """
    known_id = uuid4()
    patched_sync["known"] = {"Nipponia nippon": known_id}

    synced, loosened, unresolved = await iucn_sync._apply_snapshot(
        [{"taxonid": 0, "scientific_name": "Nipponia nippon", "category": "EN"}]
        + [
            {"taxonid": i, "scientific_name": f"Ghost species{i}", "category": "EN"}
            for i in range(1, 40)
        ]
    )

    assert (synced, loosened, unresolved) == (1, 0, 39)
    assert patched_sync["session"].committed is True


@pytest.mark.asyncio
async def test_empty_snapshot_does_not_trip_the_coverage_gate(
    patched_sync: dict[str, Any],
) -> None:
    """No candidate rows at all is a vacuous no-op, not a failure."""
    patched_sync["known"] = {}

    assert await iucn_sync._apply_snapshot([]) == (0, 0, 0)
    assert patched_sync["session"].committed is True


@pytest.mark.asyncio
async def test_snapshot_of_only_unmapped_categories_is_not_a_failure(
    patched_sync: dict[str, Any],
) -> None:
    """``DD`` rows are never candidates, so they cannot trip the gate."""
    patched_sync["known"] = {}

    assert await iucn_sync._apply_snapshot(
        [{"taxonid": 1, "scientific_name": "Nipponia nippon", "category": "DD"}]
    ) == (0, 0, 0)
    assert patched_sync["session"].committed is True


@pytest.mark.asyncio
async def test_coverage_ratio_is_logged(
    patched_sync: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Operators need the trend; the ratio is observational, not a gate."""
    patched_sync["known"] = {"Nipponia nippon": uuid4()}

    with caplog.at_level(logging.INFO, logger=iucn_sync.logger.name):
        await iucn_sync._apply_snapshot(
            [
                {"taxonid": 0, "scientific_name": "Nipponia nippon", "category": "EN"},
                {"taxonid": 1, "scientific_name": "Ghost species", "category": "EN"},
                {"taxonid": 2, "scientific_name": "Ghost species2", "category": "EN"},
            ]
        )

    coverage = [r.getMessage() for r in caplog.records if "coverage" in r.getMessage()]
    assert coverage, caplog.records
    assert "unresolved_ratio=0.667" in coverage[0], coverage


# ---------------------------------------------------------------------------
# Strictest-wins collapse (Codex finding 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_taxon_collapses_to_strictest(
    patched_sync: dict[str, Any],
) -> None:
    """Two snapshot rows on one taxon -> ONE upsert at the strictest res."""
    taxon_uuid = uuid4()
    patched_sync["known"] = {
        "Accipiter gularis": taxon_uuid,
        "Tachyspiza gularis": taxon_uuid,
    }

    synced, _loosened, unresolved = await iucn_sync._apply_snapshot(
        [
            # EN -> 5 (strict), LC -> 9 (open)
            {"taxonid": 1, "scientific_name": "Accipiter gularis", "category": "EN"},
            {"taxonid": 2, "scientific_name": "Tachyspiza gularis", "category": "LC"},
        ]
    )

    assert (synced, unresolved) == (1, 0), "counts must be per unique taxon"
    assert len(patched_sync["upserts"]) == 1
    assert patched_sync["upserts"][0]["sensitivity_h3_res"] == 5
    assert patched_sync["upserts"][0]["category"] == "EN"


@pytest.mark.asyncio
async def test_duplicate_taxon_collapse_is_order_independent(
    patched_sync: dict[str, Any],
) -> None:
    """Reversing the payload must not relax masking."""
    taxon_uuid = uuid4()
    patched_sync["known"] = {
        "Accipiter gularis": taxon_uuid,
        "Tachyspiza gularis": taxon_uuid,
    }

    synced, _loosened, _unresolved = await iucn_sync._apply_snapshot(
        [
            {"taxonid": 2, "scientific_name": "Tachyspiza gularis", "category": "LC"},
            {"taxonid": 1, "scientific_name": "Accipiter gularis", "category": "EN"},
        ]
    )

    assert synced == 1
    assert len(patched_sync["upserts"]) == 1
    assert patched_sync["upserts"][0]["sensitivity_h3_res"] == 5
