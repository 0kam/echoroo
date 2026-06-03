"""Contract test for the Member-invitation issue envelope shape (WS7 Phase 3).

Resolves the WS7 handoff caveat: the issue endpoint
``POST /web-api/v1/projects/{project_id}/invitations`` returns a SIGNED
TOKEN ENVELOPE under ``invitation_url`` — NOT a full URL. The envelope is a
4-part dot-separated string ``{raw_token_b64u}.{expires_at_unix}.{kid}.
{mac_b64u}`` (see
``echoroo.services.invitation_service.sign_invitation_token``). The frontend
builds the final URL from this envelope; the backend must never emit a path
or ``http(s)://`` value here.

The test issues a real invitation through the production BFF routing +
dependency chain. It mirrors the established
``tests/integration/test_member_invitation_flow.py`` harness:

* ``get_redis_connection`` is patched to a process-local ``fakeredis`` so the
  rate-limit / idempotency paths run without a live Redis container.
* The issuer authenticates via the BFF refresh bootstrap
  (``/web-api/v1/auth/refresh``) to obtain a Bearer access token + CSRF token.
* The owner is seeded as an ADMIN ``ProjectMember`` so the
  ``MANAGE_MEMBERS`` gate on the issue endpoint passes.
"""

from __future__ import annotations

import uuid
from typing import Any

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.core.settings import get_settings
from echoroo.models.enums import (
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User

_RESTRICTED_CONFIG: dict[str, Any] = {
    "allow_media_playback": False,
    "allow_detection_view": False,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 3,
    "allow_precise_location_to_viewer": False,
}


# ---------------------------------------------------------------------------
# Fixtures — Redis + timing patches (mirror the integration harness).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fake_redis_for_invitation_service(
    monkeypatch: pytest.MonkeyPatch,
) -> fakeredis.aioredis.FakeRedis:
    """Patch ``get_redis_connection`` to a process-local FakeRedis.

    The issue endpoint's rate-limit + idempotency paths require a live async
    Redis client; the contract test stack does not boot a real Redis
    container, so we substitute fakeredis at the import surfaces the issuer
    (``_members.py``) and the shared singleton use.
    """
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_fake() -> fakeredis.aioredis.FakeRedis:
        return fake

    from echoroo.api.web_v1.projects import _members as members_module

    monkeypatch.setattr(members_module, "get_redis_connection", _get_fake)

    from echoroo.core import redis as redis_module

    monkeypatch.setattr(redis_module, "get_redis_connection", _get_fake)
    return fake


# ---------------------------------------------------------------------------
# Helpers — seed actors / project / BFF session.
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession, *, email: str | None = None) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"ws7-inv-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        display_name="WS7 invitation user",
        security_stamp="ws7inv" + uuid.uuid4().hex,
        two_factor_enabled=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_project(db: AsyncSession, owner: User) -> Project:
    """Create a RESTRICTED project + seed the owner as an ADMIN member."""
    project = Project(
        name=f"WS7 INV {uuid.uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner.id,
        restricted_config=dict(_RESTRICTED_CONFIG),
    )
    db.add(project)
    await db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            role=ProjectMemberRole.ADMIN,
            invited_by_id=owner.id,
        )
    )
    await db.commit()
    await db.refresh(project)
    return project


async def _bff_session_headers(
    client: AsyncClient,
    db: AsyncSession,
    user: User,
) -> dict[str, str]:
    """Authenticate ``user`` on the BFF surface; return Bearer + CSRF headers.

    Mirrors ``tests/integration/test_member_invitation_flow._bff_session_headers``:
    seed a refresh-token + family row, then exchange it at
    ``/web-api/v1/auth/refresh`` for an access token + CSRF token.
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


# ---------------------------------------------------------------------------
# Test — envelope shape contract.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInvitationIssueEnvelopeShape:
    """``POST /projects/{id}/invitations`` returns a signed envelope, not a URL."""

    async def test_issue_invitation_returns_signed_envelope_not_url(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """WS7 Phase 3 (C): ``invitation_url`` is a 4-part signed envelope.

        The value MUST be a non-empty string that splits on ``.`` into
        exactly 4 parts, whose 2nd part is the unix expiry (all digits), and
        which is NOT a full URL/path (no ``http`` prefix, no ``/``).
        """
        owner = await _create_user(db_session, email="ws7-inv-owner@example.com")
        project = await _create_project(db_session, owner)

        owner_headers = await _bff_session_headers(client, db_session, owner)

        response = await client.post(
            f"/web-api/v1/projects/{project.id}/invitations",
            headers=owner_headers,
            json={"email": "ws7-inv-recipient@example.com", "role": "member"},
        )

        assert response.status_code == 201, response.text
        body = response.json()

        assert "invitation_url" in body
        envelope = body["invitation_url"]
        assert isinstance(envelope, str)
        assert envelope, "invitation_url must be a non-empty string"

        # 4-part signed envelope: raw_token.expires_unix.kid.mac
        parts = envelope.split(".")
        assert len(parts) == 4, (
            f"Expected a 4-part signed envelope, got {len(parts)} parts: "
            f"{envelope!r}"
        )

        # The 2nd part is the unix expiry — all digits.
        assert parts[1].isdigit(), (
            f"Envelope expiry segment must be all digits; got {parts[1]!r}"
        )

        # It is NOT a full URL / path — the frontend builds the URL.
        assert not envelope.startswith("http"), (
            f"invitation_url must not be a full URL; got {envelope!r}"
        )
        assert "/" not in envelope, (
            f"invitation_url must not contain a path separator; got {envelope!r}"
        )
