"""Contract tests for ``GET /api/v1/licenses`` (spec/012).

Locks the wire contract in
``specs/012-license-master-unification/contracts/licenses.yaml``. This
suite mirrors :mod:`tests.contract.test_licenses_web_public` against the
Bearer (programmatic) surface so the contract is enforced at both
customer touch-points. Cases:

* 200 with items ordered by ``short_name`` ASC.
* 200 with an empty ``items`` list when the master is empty.
* 401 when no Bearer token is present.
* 200 for a non-admin Bearer caller (FR-017 — read endpoint MUST NOT
  require admin privileges; the patched test ``client`` fixture
  synthesises a full-scope principal so the auth-router accepts the
  legacy JWT shape).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.user import User
from tests.conftest import seed_canonical_test_licenses

API_LICENSES_ENDPOINT = "/api/v1/licenses"

PUBLIC_LICENSE_KEYS = {"id", "short_name", "name", "url", "description"}


@pytest.fixture
async def t012_api_user(db_session: AsyncSession) -> User:
    """Plain authenticated user — no superuser row, no API key scopes."""
    user = User(
        email="t012-api-user@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T012 API User",
        security_stamp="t012" + "a" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t012_api_user_headers(t012_api_user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t012_api_user.id)})}"
        )
    }


@pytest.mark.asyncio
class TestApiPublicLicenseList:
    """``GET /api/v1/licenses`` programmatic-surface contract."""

    async def test_returns_200_with_canonical_licenses(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t012_api_user_headers: dict[str, str],
    ) -> None:
        """Default seed populates the four canonical CC rows."""
        await seed_canonical_test_licenses(db_session)

        response = await client.get(
            API_LICENSES_ENDPOINT, headers=t012_api_user_headers
        )
        assert response.status_code == 200, response.text

        body = response.json()
        items = body["items"]
        assert isinstance(items, list)
        assert len(items) == 4

        short_names = [row["short_name"] for row in items]
        assert short_names == ["CC0", "CC-BY", "CC-BY-NC", "CC-BY-SA"], (
            f"Items MUST be ordered by short_name ASC; got {short_names}"
        )
        assert set(short_names) == {"CC0", "CC-BY", "CC-BY-NC", "CC-BY-SA"}

        for row in items:
            assert set(row.keys()) == PUBLIC_LICENSE_KEYS, row

    async def test_returns_200_empty_when_master_is_empty(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t012_api_user_headers: dict[str, str],
    ) -> None:
        """Empty master → ``items: []`` (FR-017 actionable empty state)."""
        await db_session.execute(sa.text("DELETE FROM licenses"))
        await db_session.commit()

        response = await client.get(
            API_LICENSES_ENDPOINT, headers=t012_api_user_headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"items": []}

    async def test_returns_401_without_bearer(
        self,
        client: AsyncClient,
    ) -> None:
        """Missing Bearer header → 401 (auth-router veto)."""
        response = await client.get(API_LICENSES_ENDPOINT)
        assert response.status_code == 401, response.text

    async def test_non_admin_bearer_receives_full_list(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t012_api_user_headers: dict[str, str],
    ) -> None:
        """FR-017: a non-admin Bearer caller still receives every row.

        The patched test ``client`` fixture in
        :func:`tests.conftest.client` synthesises a full-scope principal
        for JWT-based auth, but the principal is NOT a superuser. If the
        endpoint accidentally gated to admins we would 403 here.
        """
        await seed_canonical_test_licenses(db_session)

        response = await client.get(
            API_LICENSES_ENDPOINT, headers=t012_api_user_headers
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 4, (
            "FR-017: non-admin Bearer caller must see the full master."
        )
