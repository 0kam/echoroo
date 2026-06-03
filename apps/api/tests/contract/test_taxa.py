"""Contract tests for the Web UI taxa search endpoint (WS7 Phase 3).

The first-party species autocomplete surface calls
``GET /web-api/v1/taxa/search``. This module pins its response *shape*: the
endpoint returns a bare JSON list of :class:`TaxonSearchResult` rows, and it
MUST degrade gracefully to an empty list when no taxon matches the query (an
empty taxa table is the common state on a fresh test database).

The endpoint lives on the BFF surface, which requires a first-party session
(not a bare programmatic Bearer). The session is bootstrapped with the same
refresh-token pattern used by ``tests/integration/test_member_invitation_flow``
and ``tests/contract/test_invitations`` so the caller resolves to a real
authenticated user.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.core.settings import get_settings
from echoroo.models.user import User


async def _create_user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"ws7-taxa-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        display_name="WS7 taxa user",
        security_stamp="ws7taxa" + uuid.uuid4().hex,
        two_factor_enabled=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _bff_session_headers(
    client: AsyncClient,
    db: AsyncSession,
    user: User,
) -> dict[str, str]:
    """Authenticate ``user`` on the BFF surface; return Bearer + CSRF headers.

    Mirrors ``tests/integration/test_member_invitation_flow._bff_session_headers``:
    the ``/web-api/v1/auth/refresh`` call also sets the session cookies on
    ``client.cookies`` so subsequent BFF requests resolve the session.
    """
    from uuid import UUID

    from echoroo.api.web_v1.auth import _issue_web_refresh_token

    client.cookies.clear()
    token, record = _issue_web_refresh_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
    )
    await db.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, :created_at)"
        ),
        {
            "family_id": UUID(record.family_id),
            "user_id": record.user_id,
            "created_at": record.issued_at,
        },
    )
    await db.execute(
        sa.text(
            "INSERT INTO refresh_tokens "
            "(jti, user_id, family_id, issued_at, expires_at) "
            "VALUES (:jti, :user_id, :family_id, :issued_at, :expires_at)"
        ),
        {
            "jti": UUID(record.jti),
            "user_id": record.user_id,
            "family_id": UUID(record.family_id),
            "issued_at": record.issued_at,
            "expires_at": record.expires_at,
        },
    )
    await db.commit()

    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: token},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "X-CSRF-Token": response.headers["X-CSRF-Token"],
    }


@pytest.mark.asyncio
class TestTaxaSearchEndpoint:
    """Test the Web UI taxa search response shape."""

    async def test_taxa_search_returns_list_shape(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """WS7 Phase 3 (B): taxa search returns a graceful bare-list shape.

        ``GET /web-api/v1/taxa/search`` returns a JSON LIST (not an object
        wrapper). On an empty taxa table the list is ``[]`` (graceful). If
        rows exist, each MUST carry at least the ``id`` and
        ``scientific_name`` keys from :class:`TaxonSearchResult`.
        """
        user = await _create_user(db_session)
        headers = await _bff_session_headers(client, db_session, user)

        response = await client.get(
            "/web-api/v1/taxa/search",
            headers=headers,
            params={"q": "parus", "limit": 20},
        )

        assert response.status_code == 200, response.text
        body = response.json()

        # The response is a bare list, never an object wrapper.
        assert isinstance(body, list)

        # Do NOT assume non-empty — an empty taxa table yields [].
        for item in body:
            assert "id" in item
            assert "scientific_name" in item

    async def test_taxa_search_requires_authentication(
        self,
        client: AsyncClient,
    ) -> None:
        """The taxa search endpoint rejects unauthenticated callers (401)."""
        client.cookies.clear()
        response = await client.get(
            "/web-api/v1/taxa/search",
            params={"q": "parus", "limit": 20},
        )

        assert response.status_code == 401
