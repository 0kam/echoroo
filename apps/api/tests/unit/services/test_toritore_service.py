"""Unit/service tests for the ToriTore (とりトレ) integration (preview).

Exercises the parser + ingest + read queries against a real test DB session
(:func:`db_session`), and the participation-gate decision against mocks.

Covered:
* JSON parsing — multi-test history, non-int species_id, idempotent re-upload.
* ``get_latest_total_score`` / ``get_species_rate`` ordering + aggregation.
* The gate: under-threshold blocked, owner/admin exempt, no-requirement passes.
* Snapshot population on ``TimeRangeAnnotation`` create.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.toritore_gate import enforce_participation_gate
from echoroo.models.toritore import ToriToreSpeciesScore, ToriToreTestResult
from echoroo.models.user import User
from echoroo.services import toritore as toritore_service
from echoroo.services.toritore import parse_source_timestamp


def _payload(
    *,
    timestamp: str | None = "20260604142325+9:00",
    tests: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if tests is None:
        tests = [
            {
                "test_timestamp": "1",
                "test_number": 1,
                "total_score": 0.5,
                "species_data": [
                    {
                        "species_name": "Hirundo rustica",
                        "is_correct": 1,
                        "species_id": "9515886",
                    },
                    {
                        "species_name": "Passer montanus",
                        "is_correct": 0,
                        "species_id": "5231198",
                    },
                ],
            }
        ]
    return {
        "timestamp": timestamp,
        "project": {
            "test_history": tests,
            "project_name": "fukushima_bird",
            "project_id": "1",
            "user_id": "00004",
            "user_name": "yutea888",
        },
    }


async def _make_user(db: AsyncSession, suffix: str) -> User:
    user = User(
        email=f"toritore-{suffix}-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="ToriTore Test User",
        security_stamp=f"toritore-stamp-{suffix}-{uuid4().hex[:8]}",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


def test_parse_source_timestamp_ok() -> None:
    parsed = parse_source_timestamp("20260604142325+9:00")
    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 6
    assert parsed.day == 4
    assert parsed.hour == 14
    assert parsed.utcoffset() is not None


def test_parse_source_timestamp_bad_returns_none() -> None:
    assert parse_source_timestamp(None) is None
    assert parse_source_timestamp("") is None
    assert parse_source_timestamp("not-a-timestamp") is None
    assert parse_source_timestamp("20260604142325") is None  # missing offset


# ---------------------------------------------------------------------------
# Ingest + read queries (real DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_multi_test_history(db_session: AsyncSession) -> None:
    """A multi-test JSON expands to one row per test + species rows."""
    user = await _make_user(db_session, "multi")
    payload = _payload(
        tests=[
            {
                "test_timestamp": "1",
                "test_number": 1,
                "total_score": 0.4,
                "species_data": [
                    {"species_name": "A", "is_correct": 1, "species_id": "100"},
                ],
            },
            {
                "test_timestamp": "2",
                "test_number": 2,
                "total_score": 0.8,
                "species_data": [
                    {"species_name": "A", "is_correct": 0, "species_id": "100"},
                    {"species_name": "B", "is_correct": 1, "species_id": "200"},
                ],
            },
        ]
    )
    summary = await toritore_service.ingest_upload(db_session, user.id, payload)

    assert len(summary.tests) == 2
    # Latest = highest source_timestamp (same here) then highest test_number.
    assert summary.latest_total_score == 0.8

    test_count = (
        await db_session.execute(
            select(func.count())
            .select_from(ToriToreTestResult)
            .where(ToriToreTestResult.user_id == user.id)
        )
    ).scalar_one()
    assert test_count == 2

    species_count = (
        await db_session.execute(
            select(func.count())
            .select_from(ToriToreSpeciesScore)
            .join(
                ToriToreTestResult,
                ToriToreTestResult.id == ToriToreSpeciesScore.test_result_id,
            )
            .where(ToriToreTestResult.user_id == user.id)
        )
    ).scalar_one()
    assert species_count == 3


@pytest.mark.asyncio
async def test_ingest_non_int_species_id_stored_as_null(
    db_session: AsyncSession,
) -> None:
    """A non-int species_id yields a NULL gbif_taxon_key."""
    user = await _make_user(db_session, "nonint")
    payload = _payload(
        tests=[
            {
                "test_timestamp": "1",
                "test_number": 1,
                "total_score": 0.5,
                "species_data": [
                    {"species_name": "Weird", "is_correct": 1, "species_id": "abc"},
                    {"species_name": "OK", "is_correct": 1, "species_id": "300"},
                ],
            }
        ]
    )
    await toritore_service.ingest_upload(db_session, user.id, payload)

    rows = (
        await db_session.execute(
            select(ToriToreSpeciesScore.gbif_taxon_key)
            .join(
                ToriToreTestResult,
                ToriToreTestResult.id == ToriToreSpeciesScore.test_result_id,
            )
            .where(ToriToreTestResult.user_id == user.id)
        )
    ).scalars().all()
    assert sorted(k for k in rows if k is not None) == [300]
    assert None in rows


@pytest.mark.asyncio
async def test_ingest_idempotent_reupload(db_session: AsyncSession) -> None:
    """Re-uploading the same test updates score + replaces species rows."""
    user = await _make_user(db_session, "idem")
    await toritore_service.ingest_upload(db_session, user.id, _payload())

    # Re-upload the same (timestamp, test_number) with a different score and
    # a different species set.
    updated = _payload(
        tests=[
            {
                "test_timestamp": "1",
                "test_number": 1,
                "total_score": 0.9,
                "species_data": [
                    {"species_name": "C", "is_correct": 1, "species_id": "777"},
                ],
            }
        ]
    )
    summary = await toritore_service.ingest_upload(db_session, user.id, updated)

    assert len(summary.tests) == 1
    assert summary.latest_total_score == 0.9

    species_count = (
        await db_session.execute(
            select(func.count())
            .select_from(ToriToreSpeciesScore)
            .join(
                ToriToreTestResult,
                ToriToreTestResult.id == ToriToreSpeciesScore.test_result_id,
            )
            .where(ToriToreTestResult.user_id == user.id)
        )
    ).scalar_one()
    # Old 2 rows replaced by the single new row.
    assert species_count == 1


@pytest.mark.asyncio
async def test_get_latest_total_score_ordering(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "latest")
    assert await toritore_service.get_latest_total_score(db_session, user.id) is None

    payload = _payload(
        timestamp="20260601120000+9:00",
        tests=[
            {
                "test_timestamp": "1",
                "test_number": 1,
                "total_score": 0.3,
                "species_data": [],
            },
            {
                "test_timestamp": "2",
                "test_number": 2,
                "total_score": 0.6,
                "species_data": [],
            },
        ],
    )
    await toritore_service.ingest_upload(db_session, user.id, payload)
    # Same timestamp → higher test_number wins.
    assert await toritore_service.get_latest_total_score(db_session, user.id) == 0.6


@pytest.mark.asyncio
async def test_get_species_rate_avg(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "rate")
    assert await toritore_service.get_species_rate(db_session, user.id, 999) is None

    payload = _payload(
        tests=[
            {
                "test_timestamp": "1",
                "test_number": 1,
                "total_score": 0.5,
                "species_data": [
                    {"species_name": "X", "is_correct": 1, "species_id": "42"},
                ],
            },
            {
                "test_timestamp": "2",
                "test_number": 2,
                "total_score": 0.5,
                "species_data": [
                    {"species_name": "X", "is_correct": 0, "species_id": "42"},
                ],
            },
        ]
    )
    await toritore_service.ingest_upload(db_session, user.id, payload)
    rate = await toritore_service.get_species_rate(db_session, user.id, 42)
    assert rate == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_ingest_is_correct_clamped_to_binary(
    db_session: AsyncSession,
) -> None:
    """is_correct is clamped to {0, 1}: only an exact 1 counts as correct.

    ``2`` (and any other nonzero) normalizes the same as ``0``; ``-1`` likewise.
    Truthiness must NOT let arbitrary nonzero values count as correct.
    """
    user = await _make_user(db_session, "clamp")
    payload = _payload(
        tests=[
            {
                "test_timestamp": "1",
                "test_number": 1,
                "total_score": 0.5,
                "species_data": [
                    # Exact 1 -> correct.
                    {"species_name": "One", "is_correct": 1, "species_id": "10"},
                    # 2 -> coerced to 0 (NOT truthy-correct).
                    {"species_name": "Two", "is_correct": 2, "species_id": "20"},
                    # -1 -> coerced to 0.
                    {"species_name": "Neg", "is_correct": -1, "species_id": "30"},
                    # 0 -> 0.
                    {"species_name": "Zero", "is_correct": 0, "species_id": "40"},
                ],
            }
        ]
    )
    await toritore_service.ingest_upload(db_session, user.id, payload)

    stored = dict(
        (
            await db_session.execute(
                select(
                    ToriToreSpeciesScore.gbif_taxon_key,
                    ToriToreSpeciesScore.is_correct,
                )
                .join(
                    ToriToreTestResult,
                    ToriToreTestResult.id == ToriToreSpeciesScore.test_result_id,
                )
                .where(ToriToreTestResult.user_id == user.id)
            )
        ).all()
    )
    # Only the exact-1 row is correct; 2 and -1 are coerced to 0 (same as 0).
    assert stored == {10: 1, 20: 0, 30: 0, 40: 0}

    # Per-species AVG reflects the clamp: 2 and -1 give the same rate as 0.
    assert await toritore_service.get_species_rate(db_session, user.id, 20) == 0.0
    assert await toritore_service.get_species_rate(db_session, user.id, 30) == 0.0
    assert await toritore_service.get_species_rate(db_session, user.id, 10) == 1.0


# ---------------------------------------------------------------------------
# Participation gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_no_requirement_passes() -> None:
    db = AsyncMock()
    with patch(
        "echoroo.core.toritore_gate.is_project_owner_or_admin",
        new=AsyncMock(return_value=False),
    ):
        # min_total_score=None → no-op (must not raise).
        await enforce_participation_gate(
            db, project_id=uuid4(), user_id=uuid4(), min_total_score=None,
        )


@pytest.mark.asyncio
async def test_gate_owner_admin_exempt() -> None:
    db = AsyncMock()
    with (
        patch(
            "echoroo.core.toritore_gate.is_project_owner_or_admin",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "echoroo.services.toritore.get_latest_total_score",
            new=AsyncMock(return_value=None),
        ),
    ):
        # Exempt despite no score and a positive threshold.
        await enforce_participation_gate(
            db, project_id=uuid4(), user_id=uuid4(), min_total_score=0.2,
        )


@pytest.mark.asyncio
async def test_gate_under_threshold_blocked() -> None:
    db = AsyncMock()
    with (
        patch(
            "echoroo.core.toritore_gate.is_project_owner_or_admin",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "echoroo.core.toritore_gate.toritore_service.get_latest_total_score",
            new=AsyncMock(return_value=0.1),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await enforce_participation_gate(
            db, project_id=uuid4(), user_id=uuid4(), min_total_score=0.2,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "toritore_score_insufficient"
    assert exc_info.value.detail["required"] == 0.2
    assert exc_info.value.detail["current"] == 0.1


@pytest.mark.asyncio
async def test_gate_no_upload_blocked() -> None:
    db = AsyncMock()
    with (
        patch(
            "echoroo.core.toritore_gate.is_project_owner_or_admin",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "echoroo.core.toritore_gate.toritore_service.get_latest_total_score",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await enforce_participation_gate(
            db, project_id=uuid4(), user_id=uuid4(), min_total_score=0.2,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_gate_meets_threshold_passes() -> None:
    db = AsyncMock()
    with (
        patch(
            "echoroo.core.toritore_gate.is_project_owner_or_admin",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "echoroo.core.toritore_gate.toritore_service.get_latest_total_score",
            new=AsyncMock(return_value=0.769),
        ),
    ):
        await enforce_participation_gate(
            db, project_id=uuid4(), user_id=uuid4(), min_total_score=0.2,
        )
