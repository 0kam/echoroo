"""Contract tests for ``GET /web-api/v1/licenses`` (spec/012).

Locks the wire contract in
``specs/012-license-master-unification/contracts/web-licenses.yaml``:

* 200 with items ordered by ``short_name`` ASC.
* 200 with an empty ``items`` list when the master is empty.
* 401 when no session is present.
* 200 for a non-admin authenticated caller (FR-017 — read endpoint MUST
  NOT require admin privileges).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.user import User

WEB_LICENSES_ENDPOINT = "/web-api/v1/licenses"

# spec/012: the response keys MUST match the contract's License model:
# id, short_name, name, url, description. Timestamps are intentionally
# absent on this surface (admin /admin/licenses keeps them).
PUBLIC_LICENSE_KEYS = {"id", "short_name", "name", "url", "description"}


@pytest.fixture
async def regular_user(db_session: AsyncSession) -> User:
    """Non-admin authenticated user (FR-017 coverage)."""
    user = User(
        email="t012-regular@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T012 Regular",
        security_stamp="t012" + "r" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def regular_user_headers(regular_user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(regular_user.id)})}"
        )
    }


@pytest.mark.asyncio
class TestWebPublicLicenseList:
    """``GET /web-api/v1/licenses`` happy / empty / unauthenticated paths."""

    async def test_returns_200_with_canonical_licenses(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Default seed is the four canonical CC rows, ordered by short_name."""
        response = await client.get(
            WEB_LICENSES_ENDPOINT, headers=regular_user_headers
        )
        assert response.status_code == 200, response.text

        body = response.json()
        assert "items" in body
        items = body["items"]
        assert isinstance(items, list)
        assert len(items) == 4

        short_names = [row["short_name"] for row in items]
        assert short_names == sorted(short_names), (
            f"Items MUST be ordered by short_name ASC; got {short_names}"
        )
        # Canonical seed includes CC0 / CC-BY / CC-BY-NC / CC-BY-SA.
        assert set(short_names) == {"CC0", "CC-BY", "CC-BY-NC", "CC-BY-SA"}

        # Each row exposes the spec/012 public shape only — no timestamps.
        for row in items:
            assert set(row.keys()) == PUBLIC_LICENSE_KEYS, row

    async def test_returns_200_empty_items_when_master_is_empty(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Empty master → 200 with ``items: []`` (FR-017 actionable empty state)."""
        # Purge the canonical seed for THIS test only; FK ``ON DELETE
        # RESTRICT`` means we cannot delete licenses while projects /
        # datasets reference them. The contract fixture leaves both
        # tables clean at start, so a bare DELETE is safe.
        await db_session.execute(sa.text("DELETE FROM licenses"))
        await db_session.commit()

        response = await client.get(
            WEB_LICENSES_ENDPOINT, headers=regular_user_headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"items": []}

    async def test_returns_401_without_session(
        self,
        client: AsyncClient,
    ) -> None:
        """No Authorization header → 401, no items leaked."""
        response = await client.get(WEB_LICENSES_ENDPOINT)
        assert response.status_code == 401, response.text

    async def test_non_admin_authenticated_user_receives_full_list(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """FR-017: read endpoint MUST NOT require admin privileges.

        A non-superuser authenticated user (e.g. ``e2e-member``) sees
        every row, not a truncated subset.
        """
        response = await client.get(
            WEB_LICENSES_ENDPOINT, headers=regular_user_headers
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 4, (
            "FR-017: non-admin caller must see the full master, not an "
            "admin-only filtered subset."
        )
