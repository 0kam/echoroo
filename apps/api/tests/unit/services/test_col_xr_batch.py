"""Tests for ``resolve_col_xr_batch`` (WS-A v2 slice 3).

Exercises the real database session with a STUBBED
:class:`~echoroo.services.col_xr.COLXRService`, so the write rules are locked
without touching the network:

* accepted / review rows store the full identity plus the pinned release;
* rejected rows store only ``col_xr_match_type`` + ``col_xr_resolved_at`` and
  keep ``col_xr_id`` NULL — a HIGHERRANK genus hit is not an identity;
* EVERY processed row is stamped, so a rerun does not reprocess it;
* ``force=True`` re-resolves already-stamped rows;
* non-biological labels (Engine, Noise, ...) are never resolved;
* an upstream outage counts as ``unavailable`` and leaves the row unresolved,
  and a sustained outage aborts the batch.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.exceptions import COLXRMetadataError, COLXRUnavailableError
from echoroo.models.taxon import Taxon
from echoroo.repositories.taxon import TaxonRepository
from echoroo.services import taxon as taxon_service
from echoroo.services.col_xr import COLXRIndex, COLXRMatch
from echoroo.services.taxon import COL_XR_MAX_BATCH_SIZE, resolve_col_xr_batch

_INDEX = COLXRIndex(
    alias="COL26.6 XR", clb_dataset_key=315557, created="2026-08-01T00:00:00Z"
)


def _match(
    *,
    usage_key: str | None,
    match_type: str,
    confidence: int | None,
    status: str | None = "ACCEPTED",
    accepted_key: str | None = None,
    accepted_name: str | None = None,
    synonym: bool = False,
) -> COLXRMatch:
    return COLXRMatch(
        usage_key=usage_key,
        canonical_name="Canonical name",
        authorship="(Linnaeus, 1758)",
        rank="SPECIES",
        status=status,
        accepted_key=accepted_key or usage_key,
        accepted_canonical_name=accepted_name or "Canonical name",
        accepted_authorship="(Linnaeus, 1758)",
        accepted_rank="SPECIES",
        synonym=synonym,
        match_type=match_type,
        confidence=confidence,
        classification={"CLASS": {"key": "V2", "name": "Aves"}},
        note=None,
    )


class _StubService:
    """Returns a scripted match (or raises) keyed by scientific name."""

    def __init__(
        self,
        by_name: dict[str, COLXRMatch | Exception],
        *,
        index: COLXRIndex = _INDEX,
    ) -> None:
        self._by_name = by_name
        self._index = index
        self.matched: list[str] = []
        self.closed = False

    async def get_index_metadata(self) -> COLXRIndex:
        return self._index

    async def match(
        self, scientific_name: str, **_kwargs: object
    ) -> COLXRMatch | None:
        self.matched.append(scientific_name)
        outcome = self._by_name[scientific_name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def aclose(self) -> None:  # pragma: no cover - injected services
        self.closed = True


async def _seed(db: AsyncSession, *taxa: Taxon) -> None:
    db.add_all(taxa)
    await db.commit()
    for taxon in taxa:
        await db.refresh(taxon)


@pytest.mark.asyncio
async def test_accepted_row_stores_full_identity_and_release(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)
    service = _StubService(
        {
            "Passer montanus": _match(
                usage_key="4DXY4", match_type="EXACT", confidence=99
            )
        }
    )

    result = await resolve_col_xr_batch(
        db_session, batch_size=10, service=service  # type: ignore[arg-type]
    )
    await db_session.commit()
    await db_session.refresh(taxon)

    assert result["processed"] == 1
    assert result["accepted"] == 1
    assert result["review"] == 0
    assert result["rejected"] == 0
    assert result["unavailable"] == 0
    assert result["release"] == "COL26.6 XR"
    assert result["clb_dataset_key"] == 315557

    assert taxon.col_xr_id == "4DXY4"
    assert taxon.col_xr_accepted_id == "4DXY4"
    assert taxon.col_xr_accepted_rank == "SPECIES"
    assert taxon.col_xr_status == "ACCEPTED"
    assert taxon.col_xr_match_type == "EXACT"
    assert taxon.col_xr_match_confidence == 99
    assert taxon.col_xr_release == "COL26.6 XR"
    assert taxon.col_xr_clb_dataset_key == 315557
    assert taxon.authorship == "(Linnaeus, 1758)"
    assert taxon.accepted_authorship == "(Linnaeus, 1758)"
    assert taxon.accepted_scientific_name == "Canonical name"
    assert taxon.col_xr_classification == {"CLASS": {"key": "V2", "name": "Aves"}}
    assert taxon.col_xr_resolved_at is not None


@pytest.mark.asyncio
async def test_synonym_accepted_fields_come_from_accepted_usage(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Accipiter gularis", rank="SPECIES")
    await _seed(db_session, taxon)
    service = _StubService(
        {
            "Accipiter gularis": _match(
                usage_key="93V8",
                match_type="EXACT",
                confidence=98,
                status="SYNONYM",
                accepted_key="CVWBS",
                accepted_name="Tachyspiza gularis",
                synonym=True,
            )
        }
    )

    await resolve_col_xr_batch(
        db_session, batch_size=10, service=service  # type: ignore[arg-type]
    )
    await db_session.commit()
    await db_session.refresh(taxon)

    assert taxon.col_xr_id == "93V8"
    assert taxon.col_xr_accepted_id == "CVWBS"
    assert taxon.col_xr_status == "SYNONYM"
    assert taxon.accepted_scientific_name == "Tachyspiza gularis"
    # The stored scientific_name is NEVER rewritten — the local identity and
    # the display name are owned elsewhere (AviList/IOC bundle).
    assert taxon.scientific_name == "Accipiter gularis"


@pytest.mark.asyncio
async def test_review_row_stores_identity_and_counts_separately(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanuss", rank="SPECIES")
    await _seed(db_session, taxon)
    service = _StubService(
        {
            "Passer montanuss": _match(
                usage_key="4DXY4", match_type="VARIANT", confidence=93
            )
        }
    )

    result = await resolve_col_xr_batch(
        db_session, batch_size=10, service=service  # type: ignore[arg-type]
    )
    await db_session.commit()
    await db_session.refresh(taxon)

    assert result["review"] == 1
    assert result["accepted"] == 0
    assert taxon.col_xr_id == "4DXY4"
    assert taxon.col_xr_match_type == "VARIANT"
    assert taxon.col_xr_match_confidence == 93


@pytest.mark.asyncio
async def test_rejected_rows_are_stamped_but_keep_no_identity(
    db_session: AsyncSession,
) -> None:
    higher = Taxon(scientific_name="Zzzz qqqq", rank="SPECIES")
    nomatch = Taxon(scientific_name="Not a name", rank="SPECIES")
    await _seed(db_session, higher, nomatch)
    service = _StubService(
        {
            "Zzzz qqqq": _match(
                usage_key="N", match_type="HIGHERRANK", confidence=99
            ),
            "Not a name": _match(
                usage_key=None, match_type="NONE", confidence=None, status=None
            ),
        }
    )

    result = await resolve_col_xr_batch(
        db_session, batch_size=10, service=service  # type: ignore[arg-type]
    )
    await db_session.commit()
    for taxon in (higher, nomatch):
        await db_session.refresh(taxon)

    assert result["processed"] == 2
    assert result["rejected"] == 2

    assert higher.col_xr_match_type == "HIGHERRANK"
    assert nomatch.col_xr_match_type == "NONE"
    for taxon in (higher, nomatch):
        # Stamped (so a rerun skips it) but carrying no identity.
        assert taxon.col_xr_resolved_at is not None
        assert taxon.col_xr_id is None
        assert taxon.col_xr_accepted_id is None
        assert taxon.col_xr_status is None
        assert taxon.col_xr_match_confidence is None
        assert taxon.accepted_scientific_name is None
        # A reject IS a result of this release: the pin is stamped so the row
        # drops out of the next forced pass but becomes eligible again on a
        # release bump.
        assert taxon.col_xr_release == "COL26.6 XR"
        assert taxon.col_xr_clb_dataset_key == 315557


@pytest.mark.asyncio
async def test_rerun_skips_stamped_rows_and_force_reresolves(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)
    script = {
        "Passer montanus": _match(
            usage_key="4DXY4", match_type="EXACT", confidence=99
        )
    }

    first = _StubService(script)
    await resolve_col_xr_batch(
        db_session, batch_size=10, service=first  # type: ignore[arg-type]
    )
    await db_session.commit()

    # Second pass without ``force``: nothing left to do.
    second = _StubService(script)
    again = await resolve_col_xr_batch(
        db_session, batch_size=10, service=second  # type: ignore[arg-type]
    )
    assert again["processed"] == 0
    assert second.matched == []

    # ``force`` re-resolves after a release bump.
    third = _StubService(
        script,
        index=COLXRIndex(alias="COL27.1 XR", clb_dataset_key=999, created=None),
    )
    forced = await resolve_col_xr_batch(
        db_session, batch_size=10, force=True, service=third  # type: ignore[arg-type]
    )
    await db_session.commit()
    await db_session.refresh(taxon)

    assert forced["processed"] == 1
    assert third.matched == ["Passer montanus"]
    assert taxon.col_xr_release == "COL27.1 XR"
    assert taxon.col_xr_clb_dataset_key == 999


@pytest.mark.asyncio
async def test_force_reresolution_clears_a_stale_identity(
    db_session: AsyncSession,
) -> None:
    """A previously accepted taxon that now rejects must not keep old data."""
    taxon = Taxon(
        scientific_name="Passer montanus",
        rank="SPECIES",
        col_xr_id="4DXY4",
        col_xr_accepted_id="4DXY4",
        col_xr_status="ACCEPTED",
        col_xr_match_type="EXACT",
        col_xr_match_confidence=99,
        # An OLDER release pin, so the forced pass selects this row.
        col_xr_release="COL25.1 XR",
        col_xr_clb_dataset_key=1,
        authorship="(Linnaeus, 1758)",
        accepted_scientific_name="Passer montanus",
        col_xr_resolved_at=datetime.now(UTC),
    )
    await _seed(db_session, taxon)
    service = _StubService(
        {
            "Passer montanus": _match(
                usage_key=None, match_type="NONE", confidence=None, status=None
            )
        }
    )

    await resolve_col_xr_batch(
        db_session, batch_size=10, force=True, service=service  # type: ignore[arg-type]
    )
    await db_session.commit()
    await db_session.refresh(taxon)

    assert taxon.col_xr_id is None
    assert taxon.col_xr_accepted_id is None
    assert taxon.col_xr_status is None
    assert taxon.authorship is None
    assert taxon.accepted_scientific_name is None
    assert taxon.col_xr_match_type == "NONE"
    # Re-pinned to the release that produced the rejection.
    assert taxon.col_xr_release == "COL26.6 XR"
    assert taxon.col_xr_clb_dataset_key == 315557


@pytest.mark.asyncio
async def test_non_biological_labels_are_never_resolved(
    db_session: AsyncSession,
) -> None:
    noise = Taxon(scientific_name="Engine", is_non_biological=True)
    bird = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, noise, bird)
    service = _StubService(
        {
            "Passer montanus": _match(
                usage_key="4DXY4", match_type="EXACT", confidence=99
            )
        }
    )

    result = await resolve_col_xr_batch(
        db_session, batch_size=10, service=service  # type: ignore[arg-type]
    )
    await db_session.commit()
    await db_session.refresh(noise)

    assert result["processed"] == 1
    assert service.matched == ["Passer montanus"]
    assert noise.col_xr_resolved_at is None


@pytest.mark.asyncio
async def test_batch_size_bounds_the_pass(db_session: AsyncSession) -> None:
    taxa = [Taxon(scientific_name=f"Genus species{i}", rank="SPECIES") for i in range(5)]
    await _seed(db_session, *taxa)
    service = _StubService(
        {
            t.scientific_name: _match(
                usage_key="4DXY4", match_type="EXACT", confidence=99
            )
            for t in taxa
        }
    )

    result = await resolve_col_xr_batch(
        db_session, batch_size=2, service=service  # type: ignore[arg-type]
    )

    assert result["processed"] == 2
    assert len(service.matched) == 2


@pytest.mark.asyncio
async def test_single_outage_counts_unavailable_and_leaves_row_unresolved(
    db_session: AsyncSession,
) -> None:
    broken = Taxon(scientific_name="Aaa broken", rank="SPECIES")
    ok = Taxon(scientific_name="Bbb fine", rank="SPECIES")
    await _seed(db_session, broken, ok)
    service = _StubService(
        {
            "Aaa broken": COLXRUnavailableError("down"),
            "Bbb fine": _match(
                usage_key="4DXY4", match_type="EXACT", confidence=99
            ),
        }
    )

    result = await resolve_col_xr_batch(
        db_session, batch_size=10, service=service  # type: ignore[arg-type]
    )
    await db_session.commit()
    await db_session.refresh(broken)

    assert result["unavailable"] == 1
    assert result["processed"] == 1
    assert result["accepted"] == 1
    # Left unresolved on purpose so the next run retries it.
    assert broken.col_xr_resolved_at is None


@pytest.mark.asyncio
async def test_sustained_outage_aborts_the_batch(db_session: AsyncSession) -> None:
    taxa = [Taxon(scientific_name=f"Genus down{i}", rank="SPECIES") for i in range(8)]
    await _seed(db_session, *taxa)
    service = _StubService(
        {t.scientific_name: COLXRUnavailableError("down") for t in taxa}
    )

    with pytest.raises(COLXRUnavailableError):
        await resolve_col_xr_batch(
            db_session, batch_size=10, service=service  # type: ignore[arg-type]
        )

    # Aborted at the threshold rather than burning through the whole batch.
    assert len(service.matched) == 5


@pytest.mark.asyncio
async def test_metadata_failure_aborts_before_writing_anything(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    class _NoMetadata(_StubService):
        async def get_index_metadata(self) -> COLXRIndex:
            raise COLXRUnavailableError("metadata down")

    service = _NoMetadata({})

    with pytest.raises(COLXRUnavailableError):
        await resolve_col_xr_batch(
            db_session, batch_size=10, service=service  # type: ignore[arg-type]
        )

    await db_session.refresh(taxon)
    assert service.matched == []
    assert taxon.col_xr_resolved_at is None


@pytest.mark.asyncio
async def test_rows_are_read_in_seed_order(db_session: AsyncSession) -> None:
    """The pass walks ``created_at`` ascending so batches are deterministic."""
    first = Taxon(scientific_name="Aaa first", rank="SPECIES")
    await _seed(db_session, first)
    second = Taxon(scientific_name="Zzz second", rank="SPECIES")
    await _seed(db_session, second)

    service = _StubService(
        {
            "Aaa first": _match(usage_key="A", match_type="EXACT", confidence=99),
            "Zzz second": _match(usage_key="Z", match_type="EXACT", confidence=99),
        }
    )
    await resolve_col_xr_batch(
        db_session, batch_size=10, service=service  # type: ignore[arg-type]
    )

    assert service.matched == ["Aaa first", "Zzz second"]


@pytest.mark.asyncio
async def test_repository_helper_honours_force(db_session: AsyncSession) -> None:
    resolved = Taxon(
        scientific_name="Already done",
        rank="SPECIES",
        col_xr_resolved_at=datetime.now(UTC),
    )
    pending = Taxon(scientific_name="Still pending", rank="SPECIES")
    await _seed(db_session, resolved, pending)

    repo = TaxonRepository(db_session)
    assert [t.scientific_name for t in await repo.get_col_xr_unresolved(limit=10)] == [
        "Still pending"
    ]
    forced = await repo.get_col_xr_unresolved(
        limit=10, force=True, release="COL26.6 XR", clb_dataset_key=315557
    )
    assert {t.scientific_name for t in forced} == {"Already done", "Still pending"}

    # Refusing force without a pin is deliberate: it would silently degrade to
    # the non-resumable "re-resolve everything from the top" behaviour.
    with pytest.raises(ValueError, match="release"):
        await repo.get_col_xr_unresolved(limit=10, force=True)

    # The ORM mapping must agree with the migrated schema.
    stored = (
        await db_session.execute(
            select(Taxon).where(Taxon.scientific_name == "Already done")
        )
    ).scalar_one()
    assert stored.col_xr_id is None


# ---------------------------------------------------------------------------
# Release-aware ``force`` batching (must be resumable)
# ---------------------------------------------------------------------------


def _all_exact(taxa: list[Taxon]) -> dict[str, COLXRMatch | Exception]:
    return {
        t.scientific_name: _match(
            usage_key="4DXY4", match_type="EXACT", confidence=99
        )
        for t in taxa
    }


@pytest.mark.asyncio
async def test_force_batching_advances_instead_of_looping(
    db_session: AsyncSession,
) -> None:
    """The regression this guards: ``force`` used to just drop the
    ``resolved_at`` filter, so every dispatch re-resolved the same first
    ``batch_size`` rows and the catalogue never finished."""
    taxa = [
        Taxon(scientific_name=f"Genus species{i:02d}", rank="SPECIES")
        for i in range(5)
    ]
    await _seed(db_session, *taxa)
    script = _all_exact(taxa)

    first_service = _StubService(script)
    first = await resolve_col_xr_batch(
        db_session, batch_size=2, force=True, service=first_service  # type: ignore[arg-type]
    )
    await db_session.commit()

    second_service = _StubService(script)
    second = await resolve_col_xr_batch(
        db_session, batch_size=2, force=True, service=second_service  # type: ignore[arg-type]
    )
    await db_session.commit()

    third_service = _StubService(script)
    third = await resolve_col_xr_batch(
        db_session, batch_size=2, force=True, service=third_service  # type: ignore[arg-type]
    )
    await db_session.commit()

    fourth_service = _StubService(script)
    fourth = await resolve_col_xr_batch(
        db_session, batch_size=2, force=True, service=fourth_service  # type: ignore[arg-type]
    )
    await db_session.commit()

    assert first["processed"] == 2
    assert second["processed"] == 2
    assert third["processed"] == 1
    # Everything now carries the current pin, so there is nothing left.
    assert fourth["processed"] == 0
    assert fourth_service.matched == []

    # Each pass saw DIFFERENT rows — no overlap at all.
    assert first_service.matched == ["Genus species00", "Genus species01"]
    assert second_service.matched == ["Genus species02", "Genus species03"]
    assert third_service.matched == ["Genus species04"]


@pytest.mark.asyncio
async def test_release_bump_makes_every_row_eligible_again(
    db_session: AsyncSession,
) -> None:
    taxa = [
        Taxon(scientific_name=f"Genus species{i:02d}", rank="SPECIES")
        for i in range(3)
    ]
    await _seed(db_session, *taxa)
    script = _all_exact(taxa)

    await resolve_col_xr_batch(
        db_session, batch_size=10, service=_StubService(script)  # type: ignore[arg-type]
    )
    await db_session.commit()

    # Same release: nothing to do.
    same = _StubService(script)
    assert (
        await resolve_col_xr_batch(
            db_session, batch_size=10, force=True, service=same  # type: ignore[arg-type]
        )
    )["processed"] == 0

    # New COL release: all three become eligible again and get the new pin.
    bumped = _StubService(
        script,
        index=COLXRIndex(alias="COL27.1 XR", clb_dataset_key=999, created=None),
    )
    result = await resolve_col_xr_batch(
        db_session, batch_size=10, force=True, service=bumped  # type: ignore[arg-type]
    )
    await db_session.commit()

    assert result["processed"] == 3
    assert result["release"] == "COL27.1 XR"
    for taxon in taxa:
        await db_session.refresh(taxon)
        assert taxon.col_xr_release == "COL27.1 XR"
        assert taxon.col_xr_clb_dataset_key == 999


@pytest.mark.asyncio
async def test_force_pass_also_advances_past_rejected_rows(
    db_session: AsyncSession,
) -> None:
    """Rejects carry the pin too, so they cannot wedge a forced pass."""
    taxa = [
        Taxon(scientific_name=f"Genus reject{i:02d}", rank="SPECIES")
        for i in range(3)
    ]
    await _seed(db_session, *taxa)
    script: dict[str, COLXRMatch | Exception] = {
        t.scientific_name: _match(
            usage_key="N", match_type="HIGHERRANK", confidence=99
        )
        for t in taxa
    }

    first = _StubService(script)
    assert (
        await resolve_col_xr_batch(
            db_session, batch_size=2, force=True, service=first  # type: ignore[arg-type]
        )
    )["rejected"] == 2
    await db_session.commit()

    second = _StubService(script)
    result = await resolve_col_xr_batch(
        db_session, batch_size=2, force=True, service=second  # type: ignore[arg-type]
    )
    await db_session.commit()

    assert result["rejected"] == 1
    assert second.matched == ["Genus reject02"]


@pytest.mark.asyncio
async def test_batch_size_is_clamped_to_the_time_limit_ceiling(
    db_session: AsyncSession,
) -> None:
    taxa = [
        Taxon(scientific_name=f"Genus clamp{i:02d}", rank="SPECIES")
        for i in range(3)
    ]
    await _seed(db_session, *taxa)
    service = _StubService(_all_exact(taxa))

    captured: list[int] = []
    original = TaxonRepository.get_col_xr_unresolved

    async def _spy(self: TaxonRepository, limit: int = 500, **kwargs: object) -> list[Taxon]:
        captured.append(limit)
        return await original(self, limit, **kwargs)  # type: ignore[arg-type]

    TaxonRepository.get_col_xr_unresolved = _spy  # type: ignore[method-assign]
    try:
        await resolve_col_xr_batch(
            db_session, batch_size=999_999, service=service  # type: ignore[arg-type]
        )
    finally:
        TaxonRepository.get_col_xr_unresolved = original  # type: ignore[method-assign]

    assert captured == [COL_XR_MAX_BATCH_SIZE]


# ---------------------------------------------------------------------------
# Durable progress (chunked commits)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_is_committed_every_chunk(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(taxon_service, "_COL_XR_COMMIT_CHUNK", 2)
    taxa = [
        Taxon(scientific_name=f"Genus chunk{i:02d}", rank="SPECIES")
        for i in range(5)
    ]
    await _seed(db_session, *taxa)

    commits = 0
    original_commit = db_session.commit

    async def _counting_commit() -> None:
        nonlocal commits
        commits += 1
        await original_commit()

    monkeypatch.setattr(db_session, "commit", _counting_commit)

    await resolve_col_xr_batch(
        db_session, batch_size=10, service=_StubService(_all_exact(taxa))  # type: ignore[arg-type]
    )

    # 5 rows / chunk of 2 => commits after rows 2 and 4. The trailing row is
    # left for the caller's commit.
    assert commits == 2


@pytest.mark.asyncio
async def test_committed_chunks_survive_a_mid_batch_crash(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hard failure must not roll back the chunks already banked."""
    monkeypatch.setattr(taxon_service, "_COL_XR_COMMIT_CHUNK", 2)
    taxa = [
        Taxon(scientific_name=f"Genus crash{i:02d}", rank="SPECIES")
        for i in range(5)
    ]
    await _seed(db_session, *taxa)

    script: dict[str, COLXRMatch | Exception] = _all_exact(taxa)
    # Blow up on the 5th row, i.e. after two full chunks were committed.
    script["Genus crash04"] = SQLAlchemyError("connection reset")

    with pytest.raises(SQLAlchemyError):
        await resolve_col_xr_batch(
            db_session, batch_size=10, service=_StubService(script)  # type: ignore[arg-type]
        )

    await db_session.rollback()
    resolved = (
        await db_session.execute(
            select(Taxon.scientific_name)
            .where(Taxon.col_xr_resolved_at.isnot(None))
            .order_by(Taxon.scientific_name)
        )
    ).scalars().all()

    # Rows 0-3 were committed in two chunks; row 4 never landed.
    assert list(resolved) == [
        "Genus crash00",
        "Genus crash01",
        "Genus crash02",
        "Genus crash03",
    ]


@pytest.mark.asyncio
async def test_outage_abort_commits_the_partial_chunk(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hard outage abort must not throw away already-resolved rows."""
    monkeypatch.setattr(taxon_service, "_COL_XR_COMMIT_CHUNK", 100)
    good = [
        Taxon(scientific_name=f"Genus good{i:02d}", rank="SPECIES") for i in range(2)
    ]
    bad = [
        Taxon(scientific_name=f"Genus dead{i:02d}", rank="SPECIES") for i in range(5)
    ]
    await _seed(db_session, *good, *bad)

    script: dict[str, COLXRMatch | Exception] = _all_exact(good)
    script.update({t.scientific_name: COLXRUnavailableError("down") for t in bad})

    with pytest.raises(COLXRUnavailableError):
        await resolve_col_xr_batch(
            db_session, batch_size=10, service=_StubService(script)  # type: ignore[arg-type]
        )

    await db_session.rollback()
    resolved = (
        await db_session.execute(
            select(Taxon.scientific_name).where(Taxon.col_xr_resolved_at.isnot(None))
        )
    ).scalars().all()
    assert sorted(resolved) == ["Genus good00", "Genus good01"]


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_errors_propagate_instead_of_counting_unavailable(
    db_session: AsyncSession,
) -> None:
    """A SQLAlchemyError is a bug, not weather: it must fail the batch."""
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)
    service = _StubService({"Passer montanus": SQLAlchemyError("deadlock")})

    with pytest.raises(SQLAlchemyError):
        await resolve_col_xr_batch(
            db_session, batch_size=10, service=service  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_programming_errors_propagate(db_session: AsyncSession) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)
    service = _StubService({"Passer montanus": AttributeError("typo")})

    with pytest.raises(AttributeError):
        await resolve_col_xr_batch(
            db_session, batch_size=10, service=service  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_raw_httpx_errors_are_treated_as_unavailable(
    db_session: AsyncSession,
) -> None:
    """Defence in depth: the service normally converts these, but a leak must
    still count as an outage rather than crash the batch."""
    broken = Taxon(scientific_name="Aaa broken", rank="SPECIES")
    ok = Taxon(scientific_name="Bbb fine", rank="SPECIES")
    await _seed(db_session, broken, ok)
    service = _StubService(
        {
            "Aaa broken": httpx.ConnectError("boom"),
            "Bbb fine": _match(
                usage_key="4DXY4", match_type="EXACT", confidence=99
            ),
        }
    )

    result = await resolve_col_xr_batch(
        db_session, batch_size=10, service=service  # type: ignore[arg-type]
    )

    assert result["unavailable"] == 1
    assert result["accepted"] == 1


@pytest.mark.asyncio
async def test_metadata_error_aborts_before_any_write(
    db_session: AsyncSession,
) -> None:
    """An incomplete release pin must abort the run with zero writes."""
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    class _BadMetadata(_StubService):
        async def get_index_metadata(self) -> COLXRIndex:
            raise COLXRMetadataError("no release pin")

    service = _BadMetadata({})

    with pytest.raises(COLXRMetadataError):
        await resolve_col_xr_batch(
            db_session, batch_size=10, service=service  # type: ignore[arg-type]
        )

    await db_session.rollback()
    await db_session.refresh(taxon)
    assert service.matched == []
    assert taxon.col_xr_resolved_at is None
    assert taxon.col_xr_release is None
