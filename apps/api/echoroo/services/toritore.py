"""Service layer for the ToriTore (とりトレ) integration (preview).

Handles ingest of an uploaded ToriTore JSON export, idempotent upsert of
the per-test / per-species rows, and the read queries that power the
participation gate (Part A) and the per-species snapshot (Part B):

* :func:`ingest_upload` — validate + expand + upsert (idempotent on
  ``(user_id, source_timestamp, test_number)``).
* :func:`get_latest_total_score` — most-recent test's ``total_score``.
* :func:`get_species_rate` — AVG(is_correct) for a GBIF key across all of
  the user's tests.
* :func:`get_summary` — combined summary for the ``/me`` endpoint.
* :func:`get_latest_test_reference` — snapshot reference string.

The decimal scores ToriTore exports (e.g. ``0.769230769230769``) are stored
verbatim as floats; no rounding is applied so the gate comparison is exact.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.toritore import ToriToreSpeciesScore, ToriToreTestResult
from echoroo.repositories.taxon import TaxonRepository
from echoroo.schemas.toritore import (
    ToriToreSummary,
    ToriToreTestSummary,
    ToriToreUpload,
)

logger = logging.getLogger(__name__)


# ``YYYYMMDDHHMMSS±H:MM`` (or ``±HH:MM``) — the ToriTore top-level timestamp.
_TIMESTAMP_RE = re.compile(
    r"^(?P<base>\d{14})(?P<sign>[+-])(?P<h>\d{1,2}):(?P<m>\d{2})$"
)


def parse_source_timestamp(raw: str | None) -> datetime | None:
    """Best-effort parse of the ToriTore top-level ``timestamp``.

    Accepts ``YYYYMMDDHHMMSS±H:MM`` / ``±HH:MM`` and returns a tz-aware
    :class:`datetime`. Returns ``None`` on any parse failure so the caller
    stores a NULL ``source_timestamp`` and falls back to ``uploaded_at`` for
    ordering.
    """
    if not raw:
        return None
    match = _TIMESTAMP_RE.match(raw.strip())
    if match is None:
        logger.warning("ToriTore: unparseable timestamp %r", raw)
        return None
    try:
        sign = match.group("sign")
        hours = int(match.group("h"))
        minutes = int(match.group("m"))
        offset = f"{sign}{hours:02d}:{minutes:02d}"
        # ISO 8601: YYYY-MM-DDTHH:MM:SS±HH:MM
        base = match.group("base")
        iso = (
            f"{base[0:4]}-{base[4:6]}-{base[6:8]}T"
            f"{base[8:10]}:{base[10:12]}:{base[12:14]}{offset}"
        )
        return datetime.fromisoformat(iso)
    except ValueError:
        logger.warning("ToriTore: unparseable timestamp %r", raw)
        return None


def _coerce_gbif_key(species_id: str | None) -> int | None:
    """Convert a numeric-string ``species_id`` to a GBIF key int, else None."""
    if species_id is None:
        return None
    text = species_id.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _test_reference(
    test_number: int, source_timestamp: datetime | None, uploaded_at: datetime
) -> str:
    """Build the human-readable snapshot reference for a test."""
    stamp = source_timestamp if source_timestamp is not None else uploaded_at
    return f"test#{test_number}@{stamp.isoformat()}"


async def ingest_upload(
    db: AsyncSession, user_id: UUID, payload: dict[str, object]
) -> ToriToreSummary:
    """Validate, expand and idempotently upsert an uploaded ToriTore export.

    Expands ``project.test_history[]`` into one :class:`ToriToreTestResult`
    per test and each ``species_data[]`` into a :class:`ToriToreSpeciesScore`.
    Re-upload is idempotent on ``(user_id, source_timestamp, test_number)``:
    an existing test has its ``total_score`` / metadata updated and its
    species rows deleted-and-reinserted within the same transaction.

    Returns the refreshed :func:`get_summary` for the user.
    """
    upload = ToriToreUpload.model_validate(payload)
    source_timestamp = parse_source_timestamp(upload.timestamp)
    project = upload.project
    taxon_repo = TaxonRepository(db)

    for entry in project.test_history:
        # Locate an existing test for idempotent upsert. NULL source_timestamp
        # rows are matched explicitly (IS NULL) because SQL ``= NULL`` never
        # matches.
        existing_stmt = select(ToriToreTestResult).where(
            ToriToreTestResult.user_id == user_id,
            ToriToreTestResult.test_number == entry.test_number,
        )
        if source_timestamp is None:
            existing_stmt = existing_stmt.where(
                ToriToreTestResult.source_timestamp.is_(None)
            )
        else:
            existing_stmt = existing_stmt.where(
                ToriToreTestResult.source_timestamp == source_timestamp
            )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing is None:
            test_result = ToriToreTestResult(
                user_id=user_id,
                toritore_user_id=project.user_id,
                toritore_user_name=project.user_name,
                toritore_project_id=project.project_id,
                toritore_project_name=project.project_name,
                source_timestamp=source_timestamp,
                test_number=entry.test_number,
                test_timestamp=entry.test_timestamp,
                total_score=entry.total_score,
                raw_json=entry.model_dump(),
            )
            db.add(test_result)
            await db.flush()
        else:
            existing.toritore_user_id = project.user_id
            existing.toritore_user_name = project.user_name
            existing.toritore_project_id = project.project_id
            existing.toritore_project_name = project.project_name
            existing.test_timestamp = entry.test_timestamp
            existing.total_score = entry.total_score
            existing.raw_json = entry.model_dump()
            # Replace this test's species rows.
            await db.execute(
                delete(ToriToreSpeciesScore).where(
                    ToriToreSpeciesScore.test_result_id == existing.id
                )
            )
            await db.flush()
            test_result = existing

        for species in entry.species_data:
            gbif_key = _coerce_gbif_key(species.species_id)
            taxon_id: UUID | None = None
            if gbif_key is not None:
                taxon = await taxon_repo.get_by_gbif_taxon_key(gbif_key)
                if taxon is not None:
                    taxon_id = taxon.id
            db.add(
                ToriToreSpeciesScore(
                    test_result_id=test_result.id,
                    gbif_taxon_key=gbif_key,
                    species_name=species.species_name,
                    # Only an exact ``1`` counts as correct; anything else
                    # (2, -1, 0, ...) is coerced to 0. The schema validator
                    # already normalizes this at the boundary; this is a
                    # defensive clamp at the persistence layer.
                    is_correct=1 if species.is_correct == 1 else 0,
                    taxon_id=taxon_id,
                )
            )

    # Flush so the freshly-upserted rows are visible to ``get_summary`` below.
    # No explicit ``commit()`` here: the request-scoped session commits at the
    # end of the request (the re-read after upload happens in a later request,
    # by which time the data is committed).
    await db.flush()
    return await get_summary(db, user_id)


async def get_latest_total_score(
    db: AsyncSession, user_id: UUID
) -> float | None:
    """Return the user's most-recent test ``total_score``.

    Ordered by ``COALESCE(source_timestamp, uploaded_at)`` desc then
    ``test_number`` desc. ``None`` when the user has no uploads.
    """
    stmt = (
        select(ToriToreTestResult.total_score)
        .where(ToriToreTestResult.user_id == user_id)
        .order_by(
            func.coalesce(
                ToriToreTestResult.source_timestamp,
                ToriToreTestResult.uploaded_at,
            ).desc(),
            ToriToreTestResult.test_number.desc(),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def get_latest_test_reference(
    db: AsyncSession, user_id: UUID
) -> str | None:
    """Return the snapshot reference for the user's most-recent test.

    ``None`` when the user has no uploads.
    """
    stmt = (
        select(
            ToriToreTestResult.test_number,
            ToriToreTestResult.source_timestamp,
            ToriToreTestResult.uploaded_at,
        )
        .where(ToriToreTestResult.user_id == user_id)
        .order_by(
            func.coalesce(
                ToriToreTestResult.source_timestamp,
                ToriToreTestResult.uploaded_at,
            ).desc(),
            ToriToreTestResult.test_number.desc(),
        )
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    test_number, source_timestamp, uploaded_at = row
    return _test_reference(test_number, source_timestamp, uploaded_at)


async def get_species_rate(
    db: AsyncSession, user_id: UUID, gbif_taxon_key: int
) -> float | None:
    """Return AVG(is_correct) for a GBIF key across all of the user's tests.

    ``None`` when the user has no scored rows for that species.
    """
    stmt = (
        select(func.avg(ToriToreSpeciesScore.is_correct))
        .join(
            ToriToreTestResult,
            ToriToreTestResult.id == ToriToreSpeciesScore.test_result_id,
        )
        .where(
            ToriToreTestResult.user_id == user_id,
            ToriToreSpeciesScore.gbif_taxon_key == gbif_taxon_key,
        )
    )
    value = (await db.execute(stmt)).scalar_one_or_none()
    return float(value) if value is not None else None


async def get_summary(db: AsyncSession, user_id: UUID) -> ToriToreSummary:
    """Return the proficiency summary for the user.

    Includes the latest total score, every stored test (newest first) and a
    ``{gbif_key: rate}`` map of per-species correct rates.
    """
    # Tests, newest first.
    tests_stmt = (
        select(ToriToreTestResult)
        .where(ToriToreTestResult.user_id == user_id)
        .order_by(
            func.coalesce(
                ToriToreTestResult.source_timestamp,
                ToriToreTestResult.uploaded_at,
            ).desc(),
            ToriToreTestResult.test_number.desc(),
        )
    )
    test_rows = list((await db.execute(tests_stmt)).scalars().all())

    tests = [
        ToriToreTestSummary(
            id=row.id,
            test_number=row.test_number,
            total_score=row.total_score,
            source_timestamp=row.source_timestamp,
            uploaded_at=row.uploaded_at,
            test_reference=_test_reference(
                row.test_number, row.source_timestamp, row.uploaded_at
            ),
        )
        for row in test_rows
    ]
    latest_total_score = tests[0].total_score if tests else None

    # Per-species rates (single grouped query).
    rates_stmt = (
        select(
            ToriToreSpeciesScore.gbif_taxon_key,
            func.avg(ToriToreSpeciesScore.is_correct),
        )
        .join(
            ToriToreTestResult,
            ToriToreTestResult.id == ToriToreSpeciesScore.test_result_id,
        )
        .where(
            ToriToreTestResult.user_id == user_id,
            ToriToreSpeciesScore.gbif_taxon_key.isnot(None),
        )
        .group_by(ToriToreSpeciesScore.gbif_taxon_key)
    )
    per_species_rates: dict[int, float] = {}
    for gbif_key, avg in (await db.execute(rates_stmt)).all():
        if gbif_key is not None and avg is not None:
            per_species_rates[int(gbif_key)] = float(avg)

    return ToriToreSummary(
        latest_total_score=latest_total_score,
        tests=tests,
        per_species_rates=per_species_rates,
    )
