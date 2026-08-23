"""Tests for the admin taxon identity-provenance read endpoints (slice 5).

Covers ``GET /web-api/v1/admin/taxon/{taxon_id}/identity-history`` and
``GET /web-api/v1/admin/taxon/concept-relations``. Both are platform-scope,
superuser-only and READ-ONLY: a real superuser session reaches 200, a regular
user is rejected by the permission gate, the documented filters narrow the
result, the pagination bounds are enforced by FastAPI, and neither endpoint
writes a ``platform_audit_log`` row.

The gate itself (Step -1 api_key veto / Step 0a superuser branch) is exercised
separately in
``tests/security/authorization/test_taxon_maintenance_platform_scope.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.superuser import Superuser
from echoroo.models.taxon import Taxon
from echoroo.models.taxon_concept_relation import TaxonConceptRelation
from echoroo.models.taxon_identity_history import TaxonIdentityHistory
from echoroo.models.user import User
from tests.contract.conftest import bff_session_headers

pytestmark = pytest.mark.asyncio

_HISTORY_PATH = "/web-api/v1/admin/taxon/{taxon_id}/identity-history"
_RELATIONS_PATH = "/web-api/v1/admin/taxon/concept-relations"


@pytest.fixture
async def admin_superuser(db_session: AsyncSession) -> User:
    """Create a superuser (users row + active superusers entitlement)."""
    user = User(
        email="taxon-identity-su@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Identity Superuser",
        security_stamp="0" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(
        Superuser(
            user_id=user.id,
            added_by_id=None,
            added_at=datetime.now(UTC) - timedelta(days=1),
            webauthn_credentials=[],
            allowed_ip_cidrs=[],
            revoked_at=None,
        )
    )
    await db_session.commit()
    return user


@pytest.fixture
async def superuser_headers(
    client: AsyncClient, db_session: AsyncSession, admin_superuser: User
) -> dict[str, str]:
    return await bff_session_headers(client, db_session, admin_superuser)


@pytest.fixture
async def regular_user_headers(
    client: AsyncClient, db_session: AsyncSession
) -> dict[str, str]:
    user = User(
        email="taxon-identity-user@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Identity Regular User",
        security_stamp="0" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return await bff_session_headers(client, db_session, user)


async def _seed_journal(db_session: AsyncSession) -> Taxon:
    """Seed one taxon with three journal rows and one concept edge."""
    taxon = Taxon(scientific_name="Accipiter badius", rank="SPECIES")
    db_session.add(taxon)
    await db_session.commit()
    await db_session.refresh(taxon)

    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    db_session.add_all(
        [
            TaxonIdentityHistory(
                taxon_id=taxon.id,
                field="col_xr_id",
                old_value=None,
                new_value="3XYZ1",
                source="col_xr",
                resolver="resolve_col_xr_batch",
                release="COL26.6 XR",
                actor_kind="task",
                actor_task_id="celery-1",
                changed_at=base,
            ),
            TaxonIdentityHistory(
                taxon_id=taxon.id,
                field="col_xr_status",
                old_value="ACCEPTED",
                new_value="SYNONYM",
                source="col_xr",
                resolver="resolve_col_xr_batch",
                release="COL26.6 XR",
                actor_kind="task",
                actor_task_id="celery-1",
                changed_at=base + timedelta(days=1),
            ),
            TaxonIdentityHistory(
                taxon_id=taxon.id,
                field="gbif_taxon_key",
                old_value=None,
                new_value="2492575",
                source="gbif",
                resolver="create_from_gbif",
                actor_kind="system",
                changed_at=base + timedelta(days=2),
            ),
            TaxonConceptRelation(
                from_taxon_id=taxon.id,
                to_taxon_id=None,
                to_col_xr_id="CVWCS",
                to_scientific_name="Tachyspiza badia",
                relation="synonym_of",
                release="COL26.6 XR",
                authority="COL26.6 XR",
                source="col_xr_auto",
            ),
        ]
    )
    await db_session.commit()
    return taxon


async def _platform_audit_count(db_session: AsyncSession) -> int:
    return int(
        (
            await db_session.execute(sa.text("SELECT count(*) FROM platform_audit_log"))
        ).scalar_one()
    )


# ---------------------------------------------------------------------------
# GET /admin/taxon/{taxon_id}/identity-history
# ---------------------------------------------------------------------------


class TestIdentityHistory:
    async def test_superuser_gets_the_journal_newest_first(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
    ) -> None:
        taxon = await _seed_journal(db_session)

        response = await client.get(
            _HISTORY_PATH.format(taxon_id=taxon.id), headers=superuser_headers
        )

        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [item["field"] for item in items] == [
            "gbif_taxon_key",
            "col_xr_status",
            "col_xr_id",
        ]
        flip = items[1]
        assert flip["old_value"] == "ACCEPTED"
        assert flip["new_value"] == "SYNONYM"
        assert flip["source"] == "col_xr"
        assert flip["release"] == "COL26.6 XR"
        assert flip["actor_kind"] == "task"
        assert flip["actor_task_id"] == "celery-1"

    async def test_filters_narrow_the_journal(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
    ) -> None:
        taxon = await _seed_journal(db_session)
        url = _HISTORY_PATH.format(taxon_id=taxon.id)

        by_field = await client.get(
            f"{url}?field=col_xr_status", headers=superuser_headers
        )
        assert by_field.status_code == 200, by_field.text
        assert [i["field"] for i in by_field.json()["items"]] == ["col_xr_status"]

        by_source = await client.get(f"{url}?source=gbif", headers=superuser_headers)
        assert [i["field"] for i in by_source.json()["items"]] == ["gbif_taxon_key"]

        since = await client.get(
            f"{url}?since=2026-08-02T12:00:00%2B00:00", headers=superuser_headers
        )
        assert [i["field"] for i in since.json()["items"]] == [
            "gbif_taxon_key",
            "col_xr_status",
        ]

    async def test_pagination_works_and_is_stable(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
    ) -> None:
        taxon = await _seed_journal(db_session)
        url = _HISTORY_PATH.format(taxon_id=taxon.id)

        first = await client.get(f"{url}?limit=2", headers=superuser_headers)
        second = await client.get(
            f"{url}?limit=2&offset=2", headers=superuser_headers
        )

        assert [i["field"] for i in first.json()["items"]] == [
            "gbif_taxon_key",
            "col_xr_status",
        ]
        assert [i["field"] for i in second.json()["items"]] == ["col_xr_id"]

    @pytest.mark.parametrize(
        "query", ["limit=0", "limit=501", "limit=abc", "offset=-1"]
    )
    async def test_out_of_range_pagination_is_422(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
        query: str,
    ) -> None:
        taxon = await _seed_journal(db_session)

        response = await client.get(
            f"{_HISTORY_PATH.format(taxon_id=taxon.id)}?{query}",
            headers=superuser_headers,
        )
        assert response.status_code == 422, response.text

    async def test_naive_since_is_rejected(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
    ) -> None:
        """A naive ``since`` would be interpreted in the server zone → 422."""
        taxon = await _seed_journal(db_session)

        response = await client.get(
            f"{_HISTORY_PATH.format(taxon_id=taxon.id)}?since=2026-08-02T12:00:00",
            headers=superuser_headers,
        )
        assert response.status_code == 422, response.text
        assert "timezone-aware" in response.text

    async def test_unknown_taxon_returns_an_empty_page(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        from uuid import uuid4

        response = await client.get(
            _HISTORY_PATH.format(taxon_id=uuid4()), headers=superuser_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []

    async def test_non_superuser_is_forbidden(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        regular_user_headers: dict[str, str],
    ) -> None:
        taxon = await _seed_journal(db_session)

        response = await client.get(
            _HISTORY_PATH.format(taxon_id=taxon.id), headers=regular_user_headers
        )
        assert response.status_code == 403

    async def test_read_writes_no_platform_audit_row(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
    ) -> None:
        taxon = await _seed_journal(db_session)
        before = await _platform_audit_count(db_session)

        response = await client.get(
            _HISTORY_PATH.format(taxon_id=taxon.id), headers=superuser_headers
        )
        assert response.status_code == 200, response.text

        assert await _platform_audit_count(db_session) == before


# ---------------------------------------------------------------------------
# GET /admin/taxon/concept-relations
# ---------------------------------------------------------------------------


class TestConceptRelations:
    async def test_superuser_lists_the_edges(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
    ) -> None:
        taxon = await _seed_journal(db_session)

        response = await client.get(_RELATIONS_PATH, headers=superuser_headers)

        assert response.status_code == 200, response.text
        items = response.json()["items"]
        edge = next(i for i in items if i["from_taxon_id"] == str(taxon.id))
        assert edge["relation"] == "synonym_of"
        assert edge["to_col_xr_id"] == "CVWCS"
        assert edge["to_scientific_name"] == "Tachyspiza badia"
        # The accepted usage is not a local taxon — the whole reason the FK is
        # nullable and the COL key is the durable target.
        assert edge["to_taxon_id"] is None
        assert edge["source"] == "col_xr_auto"

    async def test_filters_narrow_the_edges(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
    ) -> None:
        taxon = await _seed_journal(db_session)

        matched = await client.get(
            f"{_RELATIONS_PATH}?relation=synonym_of&from_taxon_id={taxon.id}"
            "&release=COL26.6%20XR&unresolved_target=true",
            headers=superuser_headers,
        )
        assert matched.status_code == 200, matched.text
        assert len(matched.json()["items"]) == 1

        # Every filter is an AND: any mismatch empties the page.
        for query in (
            "relation=lumped_into",
            "release=COL99.9%20XR",
            "unresolved_target=false",
        ):
            response = await client.get(
                f"{_RELATIONS_PATH}?from_taxon_id={taxon.id}&{query}",
                headers=superuser_headers,
            )
            assert response.status_code == 200, response.text
            assert response.json()["items"] == [], query

    @pytest.mark.parametrize("query", ["limit=0", "limit=501", "offset=-1"])
    async def test_out_of_range_pagination_is_422(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        query: str,
    ) -> None:
        response = await client.get(
            f"{_RELATIONS_PATH}?{query}", headers=superuser_headers
        )
        assert response.status_code == 422, response.text

    async def test_non_superuser_is_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        response = await client.get(_RELATIONS_PATH, headers=regular_user_headers)
        assert response.status_code == 403

    async def test_read_writes_no_platform_audit_row(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        superuser_headers: dict[str, str],
    ) -> None:
        await _seed_journal(db_session)
        before = await _platform_audit_count(db_session)

        response = await client.get(_RELATIONS_PATH, headers=superuser_headers)
        assert response.status_code == 200, response.text

        assert await _platform_audit_count(db_session) == before
