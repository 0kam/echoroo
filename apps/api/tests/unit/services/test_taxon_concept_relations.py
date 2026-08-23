"""Concept-relation seeding and relinking (WS-A v2 slice 5).

``taxon_concept_relations`` answers "where did this concept GO" after a COL XR
resolution overwrote ``col_xr_accepted_id``. The primary real-data case drives
the design: on the dev catalogue all 302 SYNONYM taxa point at accepted COL
usages that are NOT local taxa (``Accipiter badius`` -> ``CVWCS Tachyspiza
badia``), so the edge must survive with ``to_taxon_id`` NULL and only
``to_col_xr_id`` set.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_concept_relation import TaxonConceptRelation
from echoroo.services.col_xr import COLXRIndex, COLXRMatch
from echoroo.services.taxon import resolve_col_xr_batch
from echoroo.services.taxon_identity import (
    relink_concept_relations,
    seed_concept_relations,
)

_INDEX = COLXRIndex(
    alias="COL26.6 XR", clb_dataset_key=315557, created="2026-08-01T00:00:00Z"
)


def _synonym_match(*, usage_key: str, accepted_key: str, accepted_name: str) -> COLXRMatch:
    return COLXRMatch(
        usage_key=usage_key,
        canonical_name="Accipiter badius",
        authorship="(Gmelin, 1788)",
        rank="SPECIES",
        status="SYNONYM",
        accepted_key=accepted_key,
        accepted_canonical_name=accepted_name,
        accepted_authorship="(Gmelin, 1788)",
        accepted_rank="SPECIES",
        synonym=True,
        match_type="EXACT",
        confidence=99,
        classification={"CLASS": {"key": "V2", "name": "Aves"}},
        note=None,
    )


class _StubService:
    def __init__(self, by_name: dict[str, COLXRMatch | None]) -> None:
        self._by_name = by_name

    async def get_index_metadata(self) -> COLXRIndex:
        return _INDEX

    async def match(
        self, scientific_name: str, **_kwargs: object
    ) -> COLXRMatch | None:
        return self._by_name[scientific_name]

    async def aclose(self) -> None:  # pragma: no cover - injected services
        return None


async def _seed(db: AsyncSession, *taxa: Taxon) -> None:
    db.add_all(taxa)
    await db.commit()
    for taxon in taxa:
        await db.refresh(taxon)


async def _relations(db: AsyncSession) -> list[TaxonConceptRelation]:
    return list(
        (
            await db.execute(
                select(TaxonConceptRelation).order_by(TaxonConceptRelation.to_col_xr_id)
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Auto-seed from a COL XR pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_local_target_keeps_to_taxon_id_null(
    db_session: AsyncSession,
) -> None:
    """The primary real-data case: the accepted usage is not a local taxon."""
    taxon = Taxon(scientific_name="Accipiter badius", rank="SPECIES")
    await _seed(db_session, taxon)

    await resolve_col_xr_batch(
        db_session,
        batch_size=10,
        service=_StubService(  # type: ignore[arg-type]
            {
                "Accipiter badius": _synonym_match(
                    usage_key="3XYZ1",
                    accepted_key="CVWCS",
                    accepted_name="Tachyspiza badia",
                )
            }
        ),
    )
    await db_session.commit()

    relations = await _relations(db_session)
    assert len(relations) == 1
    edge = relations[0]
    assert edge.from_taxon_id == taxon.id
    # No local taxon carries COL usage CVWCS, so the local FK stays NULL and
    # the durable key is the COL id.
    assert edge.to_taxon_id is None
    assert edge.to_col_xr_id == "CVWCS"
    assert edge.to_scientific_name == "Tachyspiza badia"
    assert edge.relation == "synonym_of"
    assert edge.source == "col_xr_auto"
    assert edge.release == "COL26.6 XR"
    assert edge.authority == "COL26.6 XR"


@pytest.mark.asyncio
async def test_auto_seed_is_idempotent(db_session: AsyncSession) -> None:
    """A forced re-resolution must not duplicate the edge."""
    taxon = Taxon(scientific_name="Accipiter badius", rank="SPECIES")
    await _seed(db_session, taxon)
    service = _StubService(
        {
            "Accipiter badius": _synonym_match(
                usage_key="3XYZ1",
                accepted_key="CVWCS",
                accepted_name="Tachyspiza badia",
            )
        }
    )

    await resolve_col_xr_batch(db_session, batch_size=10, service=service)  # type: ignore[arg-type]
    await db_session.commit()
    assert len(await _relations(db_session)) == 1

    await resolve_col_xr_batch(
        db_session, batch_size=10, force=True, service=service  # type: ignore[arg-type]
    )
    await db_session.commit()
    assert len(await _relations(db_session)) == 1

    # And a direct catalogue-wide seed is equally a no-op.
    assert await seed_concept_relations(db_session) == 0
    await db_session.commit()
    assert len(await _relations(db_session)) == 1


@pytest.mark.asyncio
async def test_accepted_taxa_produce_no_edge(db_session: AsyncSession) -> None:
    taxon = Taxon(
        scientific_name="Passer montanus",
        rank="SPECIES",
        col_xr_id="4DXY4",
        col_xr_accepted_id="4DXY4",
        col_xr_status="ACCEPTED",
    )
    await _seed(db_session, taxon)

    assert await seed_concept_relations(db_session) == 0
    await db_session.commit()
    assert await _relations(db_session) == []


@pytest.mark.asyncio
async def test_seed_scoped_to_ids_ignores_other_taxa(
    db_session: AsyncSession,
) -> None:
    scoped = Taxon(
        scientific_name="Accipiter gularis",
        rank="SPECIES",
        col_xr_id="AAA11",
        col_xr_accepted_id="BBB22",
        col_xr_status="SYNONYM",
        accepted_scientific_name="Tachyspiza gularis",
    )
    other = Taxon(
        scientific_name="Parus minor",
        rank="SPECIES",
        col_xr_id="CCC33",
        col_xr_accepted_id="VC6HB",
        col_xr_status="SYNONYM",
        accepted_scientific_name="Parus cinereus minor",
    )
    await _seed(db_session, scoped, other)

    assert await seed_concept_relations(db_session, [scoped.id]) == 1
    await db_session.commit()

    relations = await _relations(db_session)
    assert [edge.from_taxon_id for edge in relations] == [scoped.id]

    # An empty scope is an explicit no-op, not "everything".
    assert await seed_concept_relations(db_session, []) == 0


# ---------------------------------------------------------------------------
# Relinking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relink_fills_to_taxon_id_when_the_target_appears(
    db_session: AsyncSession,
) -> None:
    synonym = Taxon(
        scientific_name="Accipiter badius",
        rank="SPECIES",
        col_xr_id="3XYZ1",
        col_xr_accepted_id="CVWCS",
        col_xr_status="SYNONYM",
        accepted_scientific_name="Tachyspiza badia",
    )
    await _seed(db_session, synonym)
    await seed_concept_relations(db_session)
    await db_session.commit()

    edge = (await _relations(db_session))[0]
    assert edge.to_taxon_id is None

    # Nothing to do until the accepted concept exists locally.
    assert await relink_concept_relations(db_session) == 0

    accepted = Taxon(
        scientific_name="Tachyspiza badia", rank="SPECIES", col_xr_id="CVWCS"
    )
    await _seed(db_session, accepted)

    assert await relink_concept_relations(db_session) == 1
    await db_session.commit()

    refreshed = (await _relations(db_session))[0]
    assert refreshed.to_taxon_id == accepted.id
    # The COL key stays: it is the assertion the edge was derived from.
    assert refreshed.to_col_xr_id == "CVWCS"

    # Idempotent: a second relink changes nothing.
    assert await relink_concept_relations(db_session) == 0


@pytest.mark.asyncio
async def test_relink_never_creates_a_self_edge(db_session: AsyncSession) -> None:
    """A taxon whose own col_xr_id equals the edge target must be skipped."""
    taxon = Taxon(
        scientific_name="Parus minor",
        rank="SPECIES",
        col_xr_id="VC6HB",
        col_xr_accepted_id="VC6HB",
        col_xr_status="SYNONYM",
        accepted_scientific_name="Parus cinereus minor",
    )
    await _seed(db_session, taxon)

    # The seeder itself refuses the self-edge outright.
    assert await seed_concept_relations(db_session) == 0
    await db_session.commit()
    assert await _relations(db_session) == []


# ---------------------------------------------------------------------------
# Database invariants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_edge_is_rejected_by_the_check(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            sa.text(
                "INSERT INTO taxon_concept_relations"
                " (id, created_at, updated_at, from_taxon_id, to_taxon_id,"
                "  relation, source)"
                " VALUES (gen_random_uuid(), now(), now(), :taxon_id, :taxon_id,"
                "  'synonym_of', 'operator')"
            ),
            {"taxon_id": taxon.id},
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_edge_without_a_target_is_rejected_by_the_check(
    db_session: AsyncSession,
) -> None:
    taxon = Taxon(scientific_name="Passer montanus", rank="SPECIES")
    await _seed(db_session, taxon)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            sa.text(
                "INSERT INTO taxon_concept_relations"
                " (id, created_at, updated_at, from_taxon_id, relation, source)"
                " VALUES (gen_random_uuid(), now(), now(), :taxon_id,"
                "  'synonym_of', 'operator')"
            ),
            {"taxon_id": taxon.id},
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_duplicate_local_edges_are_rejected_by_the_partial_unique(
    db_session: AsyncSession,
) -> None:
    """NULL ``to_col_xr_id`` edges still get exactly-once semantics."""
    source = Taxon(scientific_name="Accipiter badius", rank="SPECIES")
    target = Taxon(scientific_name="Tachyspiza badia", rank="SPECIES")
    await _seed(db_session, source, target)

    insert = sa.text(
        "INSERT INTO taxon_concept_relations"
        " (id, created_at, updated_at, from_taxon_id, to_taxon_id, relation,"
        "  source)"
        " VALUES (gen_random_uuid(), now(), now(), :from_id, :to_id,"
        "  'synonym_of', 'operator')"
    )
    params = {"from_id": source.id, "to_id": target.id}
    await db_session.execute(insert, params)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(insert, params)
    await db_session.rollback()
