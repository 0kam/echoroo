"""Identity-journal behaviour of the resolvers (WS-A v2 slice 5).

Exercises the real database session with a STUBBED
:class:`~echoroo.services.col_xr.COLXRService`, mirroring
``tests/unit/services/test_col_xr_batch.py``, and locks the properties that
make ``taxon_identity_history`` trustworthy:

* a first resolution journals the identity fields it filled in;
* an IDENTICAL re-resolution journals nothing at all — a forced pass over an
  already-current catalogue must not manufacture history;
* a forced accepted -> rejected flip journals exactly the nulled fields, with
  ``new_value`` NULL;
* a release bump carries the release the change was pinned to;
* a Celery task id is threaded onto every row it wrote;
* the journal is committed with the identities that produced it — a mid-batch
  crash and an upstream-outage abort both keep the banked rows' history.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.exceptions import COLXRUnavailableError
from echoroo.models.taxon import Taxon
from echoroo.models.taxon_identity_history import TaxonIdentityHistory
from echoroo.services import taxon as taxon_service
from echoroo.services.col_xr import COLXRIndex, COLXRMatch
from echoroo.services.taxon import resolve_col_xr_batch
from echoroo.services.taxon_identity import (
    ACTOR_KIND_SYSTEM,
    ACTOR_KIND_TASK,
    ACTOR_KIND_USER,
    record_identity_change,
    resolve_actor_kind,
)

_INDEX = COLXRIndex(
    alias="COL26.6 XR", clb_dataset_key=315557, created="2026-08-01T00:00:00Z"
)
_NEXT_INDEX = COLXRIndex(
    alias="COL26.7 XR", clb_dataset_key=315999, created="2026-09-01T00:00:00Z"
)

#: The eight identity-bearing fields ``_apply_col_xr_match`` clears on a reject
#: (``col_xr_release`` is re-stamped, not cleared, so it is not in this set).
_CLEARED_ON_REJECT = {
    "col_xr_id",
    "col_xr_accepted_id",
    "col_xr_status",
    "accepted_scientific_name",
    "authorship",
    "accepted_authorship",
}


def _match(
    *,
    usage_key: str | None,
    match_type: str = "EXACT",
    confidence: int | None = 99,
    status: str | None = "ACCEPTED",
    accepted_key: str | None = None,
    accepted_name: str | None = None,
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
        synonym=status == "SYNONYM",
        match_type=match_type,
        confidence=confidence,
        classification={"CLASS": {"key": "V2", "name": "Aves"}},
        note=None,
    )


class _StubService:
    """Returns a scripted match (or raises) keyed by scientific name."""

    def __init__(
        self,
        by_name: dict[str, COLXRMatch | Exception | None],
        *,
        index: COLXRIndex = _INDEX,
    ) -> None:
        self._by_name = by_name
        self._index = index

    async def get_index_metadata(self) -> COLXRIndex:
        return self._index

    async def match(
        self, scientific_name: str, **_kwargs: object
    ) -> COLXRMatch | None:
        outcome = self._by_name[scientific_name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def aclose(self) -> None:  # pragma: no cover - injected services
        return None


async def _seed(db: AsyncSession, *taxa: Taxon) -> None:
    db.add_all(taxa)
    await db.commit()
    for taxon in taxa:
        await db.refresh(taxon)


async def _history(
    db: AsyncSession, taxon: Taxon | None = None
) -> list[TaxonIdentityHistory]:
    stmt = select(TaxonIdentityHistory).order_by(TaxonIdentityHistory.field)
    if taxon is not None:
        stmt = stmt.where(TaxonIdentityHistory.taxon_id == taxon.id)
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Actor resolution
# ---------------------------------------------------------------------------


def test_actor_kind_prefers_the_human_then_the_task_then_system() -> None:
    user_id = uuid4()
    assert (
        resolve_actor_kind(actor_user_id=user_id, actor_task_id="t-1")
        == ACTOR_KIND_USER
    )
    assert resolve_actor_kind(actor_user_id=None, actor_task_id="t-1") == ACTOR_KIND_TASK
    assert resolve_actor_kind(actor_user_id=None, actor_task_id=None) == ACTOR_KIND_SYSTEM


# ---------------------------------------------------------------------------
# COL XR resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_resolution_journals_the_identity_it_filled_in(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    await resolve_col_xr_batch(
        db_session,
        batch_size=10,
        service=_StubService({"Passer montanus": _match(usage_key="4DXY4")}),  # type: ignore[arg-type]
    )
    await db_session.commit()

    rows = await _history(db_session, taxon)
    by_field = {row.field: row for row in rows}

    assert by_field["col_xr_id"].old_value is None
    assert by_field["col_xr_id"].new_value == "4DXY4"
    assert by_field["col_xr_status"].new_value == "ACCEPTED"
    assert by_field["accepted_scientific_name"].new_value == "Canonical name"
    assert by_field["col_xr_release"].new_value == "COL26.6 XR"

    for row in rows:
        assert row.source == "col_xr"
        assert row.resolver == "resolve_col_xr_batch"
        assert row.release == "COL26.6 XR"
        # A direct service call has no dispatch id and no request user.
        assert row.actor_kind == ACTOR_KIND_SYSTEM
        assert row.actor_task_id is None
        assert row.actor_user_id is None
        assert row.detail is not None
        assert row.detail["decision"] == "accept"


@pytest.mark.asyncio
async def test_identical_re_resolution_journals_nothing(
    db_session: AsyncSession,
) -> None:
    """A forced pass over an already-current catalogue must add ZERO rows."""
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)
    service = _StubService({"Passer montanus": _match(usage_key="4DXY4")})

    await resolve_col_xr_batch(db_session, batch_size=10, service=service)  # type: ignore[arg-type]
    await db_session.commit()
    first_pass = len(await _history(db_session, taxon))
    assert first_pass > 0

    # Same release, same upstream answer: identical values are re-assigned.
    await resolve_col_xr_batch(
        db_session, batch_size=10, force=True, service=service  # type: ignore[arg-type]
    )
    await db_session.commit()

    assert len(await _history(db_session, taxon)) == first_pass


@pytest.mark.asyncio
async def test_forced_flip_to_rejected_journals_the_nulled_fields(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    await resolve_col_xr_batch(
        db_session,
        batch_size=10,
        service=_StubService({"Passer montanus": _match(usage_key="4DXY4")}),  # type: ignore[arg-type]
    )
    await db_session.commit()
    baseline = {row.id for row in await _history(db_session, taxon)}

    # A newer release no longer matches the name: every identity field is
    # cleared (the release pin is re-stamped, not cleared).
    await resolve_col_xr_batch(
        db_session,
        batch_size=10,
        force=True,
        service=_StubService(  # type: ignore[arg-type]
            {"Passer montanus": _match(usage_key=None, match_type="NONE")},
            index=_NEXT_INDEX,
        ),
    )
    await db_session.commit()

    new_rows = [row for row in await _history(db_session, taxon) if row.id not in baseline]
    cleared = {row.field for row in new_rows if row.new_value is None}
    assert cleared == _CLEARED_ON_REJECT
    for row in new_rows:
        if row.field in _CLEARED_ON_REJECT:
            assert row.new_value is None
            assert row.old_value is not None


@pytest.mark.asyncio
async def test_release_bump_is_journalled_and_carries_the_new_release(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)
    match = _match(usage_key="4DXY4")

    await resolve_col_xr_batch(
        db_session, batch_size=10, service=_StubService({"Passer montanus": match})  # type: ignore[arg-type]
    )
    await db_session.commit()

    await resolve_col_xr_batch(
        db_session,
        batch_size=10,
        force=True,
        service=_StubService({"Passer montanus": match}, index=_NEXT_INDEX),  # type: ignore[arg-type]
    )
    await db_session.commit()

    release_rows = [
        row for row in await _history(db_session, taxon) if row.field == "col_xr_release"
    ]
    assert len(release_rows) == 2
    bump = next(row for row in release_rows if row.old_value is not None)
    assert bump.old_value == "COL26.6 XR"
    assert bump.new_value == "COL26.7 XR"
    # The row is stamped with the release it moved TO.
    assert bump.release == "COL26.7 XR"


@pytest.mark.asyncio
async def test_task_id_is_recorded_as_the_actor(db_session: AsyncSession) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    await resolve_col_xr_batch(
        db_session,
        batch_size=10,
        service=_StubService({"Passer montanus": _match(usage_key="4DXY4")}),  # type: ignore[arg-type]
        task_id="celery-task-99",
    )
    await db_session.commit()

    rows = await _history(db_session, taxon)
    assert rows
    for row in rows:
        assert row.actor_kind == ACTOR_KIND_TASK
        assert row.actor_task_id == "celery-task-99"
        assert row.actor_user_id is None


# ---------------------------------------------------------------------------
# Durability: the journal is committed with the identity that produced it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_committed_chunks_keep_their_history_after_a_mid_batch_crash(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(taxon_service, "_COL_XR_COMMIT_CHUNK", 2)
    taxa = [
        Taxon(scientific_name=f"Genus histcrash{i:02d}", rank="SPECIES")
        for i in range(5)
    ]
    await _seed(db_session, *taxa)

    script: dict[str, COLXRMatch | Exception | None] = {
        t.scientific_name: _match(usage_key=f"K{i:03d}") for i, t in enumerate(taxa)
    }
    script["Genus histcrash04"] = SQLAlchemyError("connection reset")

    with pytest.raises(SQLAlchemyError):
        await resolve_col_xr_batch(
            db_session, batch_size=10, service=_StubService(script)  # type: ignore[arg-type]
        )
    await db_session.rollback()

    journalled = {
        row.taxon_id
        for row in await _history(db_session)
        if row.field == "col_xr_id"
    }
    # Rows 0-3 were banked in two chunks; row 4 never landed.
    assert journalled == {t.id for t in taxa[:4]}


@pytest.mark.asyncio
async def test_outage_abort_commits_the_partial_chunk_with_its_history(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(taxon_service, "_COL_XR_COMMIT_CHUNK", 100)
    good = [
        Taxon(scientific_name=f"Genus histgood{i:02d}", rank="SPECIES")
        for i in range(2)
    ]
    bad = [
        Taxon(scientific_name=f"Genus histdead{i:02d}", rank="SPECIES")
        for i in range(5)
    ]
    await _seed(db_session, *good, *bad)

    script: dict[str, COLXRMatch | Exception | None] = {
        t.scientific_name: _match(usage_key=f"G{i:03d}") for i, t in enumerate(good)
    }
    script.update({t.scientific_name: COLXRUnavailableError("down") for t in bad})

    with pytest.raises(COLXRUnavailableError):
        await resolve_col_xr_batch(
            db_session, batch_size=10, service=_StubService(script)  # type: ignore[arg-type]
        )
    await db_session.rollback()

    journalled = {
        row.taxon_id
        for row in await _history(db_session)
        if row.field == "col_xr_id"
    }
    assert journalled == {t.id for t in good}


# ---------------------------------------------------------------------------
# Database invariants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_op_rows_are_rejected_by_the_check(
    db_session: AsyncSession,
) -> None:
    """``ck_taxon_identity_history_actual_change`` is the last line of defence."""
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            sa.text(
                "INSERT INTO taxon_identity_history"
                " (id, created_at, updated_at, taxon_id, field, old_value,"
                "  new_value, source, actor_kind, changed_at)"
                " VALUES (gen_random_uuid(), now(), now(), :taxon_id,"
                "  'col_xr_id', 'SAME', 'SAME', 'col_xr', 'system', now())"
            ),
            {"taxon_id": taxon.id},
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_user_row_without_a_user_id_is_rejected(
    db_session: AsyncSession,
) -> None:
    """``ck_taxon_identity_history_actor_present`` makes attribution real."""
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            sa.text(
                "INSERT INTO taxon_identity_history"
                " (id, created_at, updated_at, taxon_id, field, old_value,"
                "  new_value, source, actor_kind, changed_at)"
                " VALUES (gen_random_uuid(), now(), now(), :taxon_id,"
                "  'col_xr_id', NULL, 'X', 'admin', 'user', now())"
            ),
            {"taxon_id": taxon.id},
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_record_identity_change_drops_a_no_op(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    row = record_identity_change(
        db_session,
        taxon,
        field="gbif_taxon_key",
        old_value=12345,
        new_value=12345,
        source="gbif",
        actor_kind=ACTOR_KIND_SYSTEM,
    )
    await db_session.commit()

    assert row is None
    assert await _history(db_session, taxon) == []


@pytest.mark.asyncio
async def test_record_identity_change_renders_non_string_values_as_text(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    record_identity_change(
        db_session,
        taxon,
        field="gbif_taxon_key",
        old_value=None,
        new_value=2492575,
        source="gbif",
        resolver="create_from_gbif",
        actor_kind=ACTOR_KIND_SYSTEM,
        changed_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await db_session.commit()

    rows = await _history(db_session, taxon)
    assert len(rows) == 1
    assert rows[0].old_value is None
    assert rows[0].new_value == "2492575"


# ---------------------------------------------------------------------------
# GBIF hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_from_gbif_journals_the_key_assignment_to_the_user(
    db_session: AsyncSession,
) -> None:
    """The Web UI route threads its request user; the row must name them."""
    from echoroo.models.user import User
    from echoroo.repositories.taxon import TaxonRepository
    from echoroo.services.taxon import TaxonService

    user = User(
        email="identity-actor@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Identity Actor",
        security_stamp="0" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    service = TaxonService(taxon_repo=TaxonRepository(db_session))
    result = await service.create_from_gbif(
        scientific_name="Turdus merula",
        gbif_taxon_key=2490719,
        actor_user_id=user.id,
    )
    await db_session.commit()

    rows = await _history(db_session)
    assert [row.field for row in rows] == ["gbif_taxon_key"]
    row = rows[0]
    assert row.taxon_id == result.id
    assert row.old_value is None
    assert row.new_value == "2490719"
    assert row.source == "gbif"
    assert row.resolver == "create_from_gbif"
    assert row.actor_kind == ACTOR_KIND_USER
    assert row.actor_user_id == user.id
    assert row.actor_task_id is None


@pytest.mark.asyncio
async def test_create_from_gbif_journals_nothing_when_the_key_is_owned(
    db_session: AsyncSession,
) -> None:
    """A key already owned elsewhere is never assigned — and never journalled."""
    from echoroo.repositories.taxon import TaxonRepository
    from echoroo.services.taxon import TaxonService

    owner = Taxon(scientific_name="Turdus merula", gbif_taxon_key=2490719)
    await _seed(db_session, owner)

    service = TaxonService(taxon_repo=TaxonRepository(db_session))
    await service.create_from_gbif(
        scientific_name="Turdus merula aterrimus", gbif_taxon_key=2490719
    )
    await db_session.commit()

    assert await _history(db_session) == []


@pytest.mark.asyncio
async def test_create_from_gbif_is_idempotent_in_the_journal_too(
    db_session: AsyncSession,
) -> None:
    """Re-materialising the same pick re-assigns nothing, so adds no history."""
    from echoroo.repositories.taxon import TaxonRepository
    from echoroo.services.taxon import TaxonService

    service = TaxonService(taxon_repo=TaxonRepository(db_session))
    await service.create_from_gbif(
        scientific_name="Turdus merula", gbif_taxon_key=2490719
    )
    await db_session.commit()
    assert len(await _history(db_session)) == 1

    await service.create_from_gbif(
        scientific_name="Turdus merula", gbif_taxon_key=2490719
    )
    await db_session.commit()
    assert len(await _history(db_session)) == 1


@pytest.mark.asyncio
async def test_gbif_batch_journals_the_resolved_key(
    db_session: AsyncSession,
) -> None:
    from unittest.mock import AsyncMock

    from echoroo.repositories.taxon import TaxonRepository
    from echoroo.services.gbif import GBIFResolveResult
    from echoroo.services.taxon import TaxonService

    taxon = Taxon(scientific_name="Turdus merula", is_non_biological=False)
    await _seed(db_session, taxon)

    gbif_service = AsyncMock()
    gbif_service.resolve_taxon = AsyncMock(
        return_value=GBIFResolveResult(
            taxon_key=2490719,
            scientific_name="Turdus merula",
            rank="SPECIES",
            metadata={"family": "Turdidae"},
        )
    )

    service = TaxonService(
        taxon_repo=TaxonRepository(db_session), gbif_service=gbif_service
    )
    result = await service.resolve_gbif_batch(limit=10, task_id="celery-gbif-1")
    await db_session.commit()

    assert result.resolved == 1
    rows = await _history(db_session, taxon)
    assert [row.field for row in rows] == ["gbif_taxon_key"]
    assert rows[0].new_value == "2490719"
    assert rows[0].source == "gbif"
    assert rows[0].resolver == "resolve_gbif_batch"
    assert rows[0].actor_kind == ACTOR_KIND_TASK
    assert rows[0].actor_task_id == "celery-gbif-1"
