"""WS-A PR3a: materialise a GBIF search pick into a local taxon (preview #2).

Covers ``POST /web-api/v1/taxa/from-gbif`` (and, via the shared service, the
legacy ``POST /api/v1/taxa/from-gbif`` mirror). The endpoint is a get-or-create
over the ``taxa`` table keyed by ``scientific_name``: it must be idempotent and
must honour the partial-unique ``ix_taxa_gbif_taxon_key`` index when
backfilling a GBIF key.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.models.user import User
from tests.integration.api.web_v1._helpers import (
    assert_api_key_cross_rejected,
    assert_rate_limit_bucket_web,
)
from tests.integration.api.web_v1.test_projects_read_smoke import (
    _create_user,
    _seed_refresh_token,
)


async def _bff_session_headers(
    client: AsyncClient,
    db: AsyncSession,
    user: User,
) -> dict[str, str]:
    client.cookies.clear()
    refresh_token = await _seed_refresh_token(db, user)
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "X-CSRF-Token": response.headers["X-CSRF-Token"],
    }


async def _taxon_count(db: AsyncSession, scientific_name: str) -> int:
    result = await db.execute(
        sa.select(sa.func.count())
        .select_from(Taxon)
        .where(Taxon.scientific_name == scientific_name)
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_from_gbif_creates_new_taxon(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A previously unknown scientific name creates a taxon and returns it."""
    user = await _create_user(db_session, email="wsa-from-gbif-new@example.com")
    headers = await _bff_session_headers(client, db_session, user)

    response = await client.post(
        "/web-api/v1/taxa/from-gbif",
        headers=headers,
        json={
            "scientific_name": "Wsa Newus testus",
            "gbif_taxon_key": 91000001,
            "common_name": "Test Warbler",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"]
    assert body["scientific_name"] == "Wsa Newus testus"
    assert body["gbif_taxon_key"] == 91000001
    # common_name seeded as an English vernacular and resolved back.
    assert body["common_name"] == "Test Warbler"
    assert_rate_limit_bucket_web(response)

    assert await _taxon_count(db_session, "Wsa Newus testus") == 1


@pytest.mark.asyncio
async def test_from_gbif_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A second identical POST returns the SAME taxon with no duplicate row."""
    user = await _create_user(db_session, email="wsa-from-gbif-idem@example.com")
    headers = await _bff_session_headers(client, db_session, user)

    payload = {
        "scientific_name": "Wsa Idemus testus",
        "gbif_taxon_key": 91000002,
        "common_name": "Idempotent Tit",
    }
    first = await client.post(
        "/web-api/v1/taxa/from-gbif", headers=headers, json=payload
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        "/web-api/v1/taxa/from-gbif", headers=headers, json=payload
    )
    assert second.status_code == 200, second.text

    assert first.json()["id"] == second.json()["id"]
    assert await _taxon_count(db_session, "Wsa Idemus testus") == 1


@pytest.mark.asyncio
async def test_from_gbif_backfills_null_key(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A pre-existing taxon with a NULL key gets the supplied key backfilled."""
    taxon = Taxon(scientific_name="Wsa Backfill testus", gbif_taxon_key=None)
    db_session.add(taxon)
    await db_session.commit()
    await db_session.refresh(taxon)

    user = await _create_user(
        db_session, email="wsa-from-gbif-backfill@example.com"
    )
    headers = await _bff_session_headers(client, db_session, user)

    response = await client.post(
        "/web-api/v1/taxa/from-gbif",
        headers=headers,
        json={
            "scientific_name": "Wsa Backfill testus",
            "gbif_taxon_key": 91000003,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(taxon.id)
    assert body["gbif_taxon_key"] == 91000003

    await db_session.refresh(taxon)
    assert taxon.gbif_taxon_key == 91000003


@pytest.mark.asyncio
async def test_from_gbif_skips_key_owned_by_another_taxon(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """When the GBIF key is owned by ANOTHER taxon, it is left unset (no 500)."""
    owner = Taxon(scientific_name="Wsa Owner testus", gbif_taxon_key=91000004)
    target = Taxon(scientific_name="Wsa Target testus", gbif_taxon_key=None)
    db_session.add_all([owner, target])
    await db_session.commit()
    await db_session.refresh(target)

    user = await _create_user(
        db_session, email="wsa-from-gbif-conflict@example.com"
    )
    headers = await _bff_session_headers(client, db_session, user)

    response = await client.post(
        "/web-api/v1/taxa/from-gbif",
        headers=headers,
        json={
            "scientific_name": "Wsa Target testus",
            # Same key already owned by ``owner`` — must NOT be assigned.
            "gbif_taxon_key": 91000004,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(target.id)
    # Key left unset rather than raising on the partial-unique constraint.
    assert body["gbif_taxon_key"] is None

    await db_session.refresh(target)
    assert target.gbif_taxon_key is None


@pytest.mark.asyncio
async def test_from_gbif_new_taxon_with_key_conflict_persists_taxon(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """New scientific_name + a key already owned by ANOTHER taxon.

    Regression for the HIGH finding: the new taxon must still be persisted
    (its row exists after the call), the returned ``id`` must match the
    actually-persisted row, and ``gbif_taxon_key`` must be left NULL rather
    than discarding the freshly created taxon via a transaction-wide rollback.

    The pre-check (``get_by_gbif_taxon_key``) normally skips the assignment
    when the key is owned, so to drive the IntegrityError fallback we patch it
    to report "no owner" and let the partial-unique index raise on flush — the
    exact concurrent-race shape the SAVEPOINT scoping must survive.
    """
    owner = Taxon(scientific_name="Wsa Conflictowner testus", gbif_taxon_key=92000001)
    db_session.add(owner)
    await db_session.commit()

    user = await _create_user(
        db_session, email="wsa-from-gbif-newconflict@example.com"
    )
    headers = await _bff_session_headers(client, db_session, user)

    sci_name = "Wsa Newconflict testus"

    # Force the IntegrityError path: make the pre-check claim the key is free
    # so the service attempts the (doomed) flush against the partial-unique
    # index, mirroring a concurrent insert that races past the pre-check.
    from echoroo.repositories.taxon import TaxonRepository

    original = TaxonRepository.get_by_gbif_taxon_key

    async def _no_owner(self: TaxonRepository, gbif_taxon_key: int) -> Taxon | None:
        return None

    TaxonRepository.get_by_gbif_taxon_key = _no_owner  # type: ignore[assignment]
    try:
        response = await client.post(
            "/web-api/v1/taxa/from-gbif",
            headers=headers,
            json={
                "scientific_name": sci_name,
                "gbif_taxon_key": 92000001,
                "common_name": "New Conflict Warbler",
            },
        )
    finally:
        TaxonRepository.get_by_gbif_taxon_key = original  # type: ignore[assignment]

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scientific_name"] == sci_name
    # Key conflict resolved by leaving it NULL, NOT by discarding the taxon.
    assert body["gbif_taxon_key"] is None
    # The seeded en vernacular survived the scoped rollback.
    assert body["common_name"] == "New Conflict Warbler"

    # The new taxon row exists after commit and the returned id is real
    # (not a phantom id pointing at a rolled-back row).
    persisted = await db_session.execute(
        sa.select(Taxon).where(Taxon.scientific_name == sci_name)
    )
    row = persisted.scalar_one()
    assert str(row.id) == body["id"]
    assert row.gbif_taxon_key is None
    assert await _taxon_count(db_session, sci_name) == 1


@pytest.mark.asyncio
async def test_from_gbif_locale_returns_ja_vernacular(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """``?locale=ja`` returns the ja vernacular when present (A3 fallback)."""
    taxon = Taxon(scientific_name="Wsa Localus testus", gbif_taxon_key=None)
    db_session.add(taxon)
    await db_session.flush()
    db_session.add_all(
        [
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale="en",
                name="Local Tit",
                source="gbif",
                is_primary=True,
            ),
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale="ja",
                name="ローカルガラ",
                source="gbif",
                is_primary=True,
            ),
        ]
    )
    await db_session.commit()

    user = await _create_user(
        db_session, email="wsa-from-gbif-locale@example.com"
    )
    headers = await _bff_session_headers(client, db_session, user)

    ja = await client.post(
        "/web-api/v1/taxa/from-gbif?locale=ja",
        headers=headers,
        json={"scientific_name": "Wsa Localus testus"},
    )
    assert ja.status_code == 200, ja.text
    assert ja.json()["common_name"] == "ローカルガラ"

    en = await client.post(
        "/web-api/v1/taxa/from-gbif?locale=en",
        headers=headers,
        json={"scientific_name": "Wsa Localus testus"},
    )
    assert en.status_code == 200, en.text
    assert en.json()["common_name"] == "Local Tit"


@pytest.mark.asyncio
async def test_from_gbif_locale_falls_back_to_en(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """``?locale=ja`` falls back to the en vernacular when no ja row exists."""
    taxon = Taxon(scientific_name="Wsa Fallbackus testus", gbif_taxon_key=None)
    db_session.add(taxon)
    await db_session.flush()
    db_session.add(
        TaxonVernacularName(
            taxon_id=taxon.id,
            locale="en",
            name="Fallback Tit",
            source="gbif",
            is_primary=True,
        )
    )
    await db_session.commit()

    user = await _create_user(
        db_session, email="wsa-from-gbif-fallback@example.com"
    )
    headers = await _bff_session_headers(client, db_session, user)

    response = await client.post(
        "/web-api/v1/taxa/from-gbif?locale=ja",
        headers=headers,
        json={"scientific_name": "Wsa Fallbackus testus"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["common_name"] == "Fallback Tit"


@pytest.mark.asyncio
async def test_from_gbif_requires_authentication(
    client: AsyncClient,
) -> None:
    """The endpoint rejects unauthenticated callers (401)."""
    client.cookies.clear()
    response = await client.post(
        "/web-api/v1/taxa/from-gbif",
        json={"scientific_name": "Wsa Unauthed testus"},
    )
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_from_gbif_rejects_blank_scientific_name(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """An empty scientific name is rejected by request validation (422)."""
    user = await _create_user(
        db_session, email="wsa-from-gbif-blank@example.com"
    )
    headers = await _bff_session_headers(client, db_session, user)

    response = await client.post(
        "/web-api/v1/taxa/from-gbif",
        headers=headers,
        json={"scientific_name": ""},
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_from_gbif_cross_credential_rejected(
    client: AsyncClient,
) -> None:
    """A programmatic API key must not authenticate the BFF endpoint."""
    await assert_api_key_cross_rejected(
        client,
        "POST",
        "/web-api/v1/taxa/from-gbif",
        body={"scientific_name": "Wsa Crosscred testus"},
    )
