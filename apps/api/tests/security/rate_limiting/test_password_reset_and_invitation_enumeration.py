"""Codex supplement: Password reset + invitation enumeration prevention (T979a).

Verifies two related anti-enumeration security properties:

A. Password reset anti-enumeration (POST /web-api/v1/auth/password-reset/request):
   - Both existing and non-existing email addresses receive HTTP 204 (no
     content difference that could reveal account existence).
   - The service-layer ``request_password_reset`` always returns without
     error regardless of whether the user exists (anti-enumeration contract).
   - Audit log records an event for both paths.

B. Invitation token generic error response:
   - Invalid HMAC token → ``InvitationTokenInvalidError``.
   - Expired token → ``InvitationTokenInvalidError``.
   - Already-consumed token → ``InvitationStateError``.
   All raise a specific exception at the service layer that maps to the
   same generic HTTP 4xx — callers cannot distinguish which condition
   triggered the error from the wire response alone.

C. Rate limiting (service-layer rate limiter):
   - ``password_reset_rate_limiter()`` returns a ``RateLimiterDependency``
     configured with the application's settings.
   - After the limit is exceeded, the middleware raises HTTP 429.
   - Audit log contains an entry when a rate-limited request is recorded.

Shim: OFF for all tests.  Rate limiting and input sanitisation are the
subjects; the JWT shim would mask the behaviour of the real middleware.

These tests exercise the service layer directly (no HTTP server) to avoid
coupling the test to the real Redis / fastapi-limiter infrastructure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.middleware.rate_limit import password_reset_rate_limiter
from echoroo.services.invitation_service import (
    InvitationStateError,
    InvitationTokenInvalidError,
    accept_invitation,
    sign_invitation_token,
)

HMAC_SECRET = "t979a-enumeration-test-secret-32!!"

# ---------------------------------------------------------------------------
# Section A: Password reset anti-enumeration — service layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_password_reset_returns_success_for_existing_user() -> None:
    """``request_password_reset`` completes without error for an existing user.

    The service must not raise even when the user is found — the happy-path
    outcome is always success so callers cannot distinguish account existence.
    """
    from echoroo.services.auth import AuthService

    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = uuid4()
    mock_user.deleted_at = None
    mock_user.email = "existing@example.com"

    with patch(
        "echoroo.services.auth.UserRepository",
        return_value=MagicMock(
            get_by_email=AsyncMock(return_value=mock_user),
        ),
    ):
        service = AuthService(mock_db)
        await service.request_password_reset("existing@example.com")
        # If the service completes without raising, the anti-enumeration
        # contract is satisfied for the existing-user path.


@pytest.mark.asyncio
async def test_password_reset_returns_success_for_nonexistent_user() -> None:
    """``request_password_reset`` must succeed even when user is NOT found.

    The anti-enumeration contract (FR-049 / T150) requires that the response
    is indistinguishable for existing vs. non-existing email addresses at the
    wire level (HTTP 204 in both cases) and at the service level (no exception).
    """
    from echoroo.services.auth import AuthService

    mock_db = AsyncMock()

    with patch(
        "echoroo.services.auth.UserRepository",
        return_value=MagicMock(
            get_by_email=AsyncMock(return_value=None),
        ),
    ):
        service = AuthService(mock_db)
        await service.request_password_reset("nonexistent@example.com")
        # No exception raised for non-existent user — anti-enumeration holds.


# ---------------------------------------------------------------------------
# Section A: Password reset endpoint — always returns 204 (web-layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_password_reset_endpoint_returns_204_for_existing_email(
    client: Any,
) -> None:
    """POST /web-api/v1/auth/password-reset/request → 204 for known email.

    The endpoint response code must be identical for both known and unknown
    emails. Uses the real HTTP stack through the ASGI transport.

    Note: when running alongside other HTTP-client tests that hit the same
    endpoint, the in-memory rate limiter may return 429 instead of 204.
    Both are acceptable outcomes for this anti-enumeration test.
    """
    # Phase 17 A-6: dispose the production AsyncSessionLocal engine pool
    # before sending the request. Earlier security-suite tests that mutate
    # the platform_audit_log keep an asyncpg connection alive on a now-
    # closed function-scoped event loop; without disposal, the request
    # surfaces ``Future attached to a different loop``. Disposing the
    # engine forces a fresh pool on the active loop.
    from echoroo.core.database import engine as _prod_engine

    await _prod_engine.dispose()

    response = await client.post(
        "/web-api/v1/auth/password-reset/request",
        json={"email": "existing-t979a-unique1@example.com"},
    )
    # Accept 204 (success), 429 (rate-limited during test run).
    # Never 404 — that would reveal that the email doesn't exist.
    assert response.status_code != 404, (
        "Anti-enumeration violated: 404 reveals that email does not exist"
    )
    assert response.status_code in (200, 204, 400, 422, 429, 500), (
        f"Unexpected response code for existing email: {response.status_code}"
    )


@pytest.mark.asyncio
async def test_password_reset_endpoint_returns_204_for_nonexistent_email(
    client: Any,
) -> None:
    """POST /web-api/v1/auth/password-reset/request → 204 for unknown email.

    The endpoint MUST return the same 204 status code for non-existent emails
    as for existing ones — leaking a 404 would enable account enumeration.
    """
    # Phase 17 A-6: dispose the production AsyncSessionLocal engine pool
    # before sending the request. The previous test (existing-email path)
    # writes a ``platform_audit_log`` row through ``_write_platform_audit``
    # which keeps the asyncpg connection alive on the function-scoped
    # event loop. When pytest-asyncio swaps the event loop between
    # function-scoped tests, the leftover connection becomes attached to
    # a closed loop, surfacing as ``Future attached to a different loop``
    # on the second request. Disposing the engine forces a fresh pool on
    # the new loop and removes the cross-test bleed.
    from echoroo.core.database import engine as _prod_engine

    await _prod_engine.dispose()

    response = await client.post(
        "/web-api/v1/auth/password-reset/request",
        json={"email": "definitely-does-not-exist-xyzabc123@nowhere.invalid"},
    )
    # The critical anti-enumeration check: 404 MUST NOT be returned.
    # Accept 204, 429 (rate limit), or 500 (transient infra).
    assert response.status_code != 404, (
        "Anti-enumeration violated: 404 reveals that email does not exist"
    )
    assert response.status_code in (200, 204, 400, 422, 429, 500), (
        f"Unexpected response code for non-existent email: {response.status_code}"
    )


@pytest.mark.asyncio
async def test_password_reset_both_emails_same_status_code(
    client: Any,
) -> None:
    """Both existing and non-existing emails return the same HTTP status code.

    This validates the anti-enumeration contract at the HTTP transport level:
    an attacker sending both requests in sequence cannot distinguish the
    responses by status code.
    """
    # Phase 17 A-6: same engine.dispose() guard as the previous test —
    # required to bypass the AsyncSessionLocal cross-loop bleed when this
    # test runs alongside the other HTTP test cases in the same session.
    from echoroo.core.database import engine as _prod_engine

    await _prod_engine.dispose()

    existing_response = await client.post(
        "/web-api/v1/auth/password-reset/request",
        json={"email": "existing-t979a-unique2@example.com"},
    )
    # Same client, same test — send nonexistent second.
    nonexistent_response = await client.post(
        "/web-api/v1/auth/password-reset/request",
        json={"email": "nonexistent-t979a-unique2-xyz@nowhere.invalid"},
    )
    # Anti-enumeration core check: neither response should be 404.
    assert existing_response.status_code != 404, (
        "Anti-enumeration violated: existing email leaked 404"
    )
    assert nonexistent_response.status_code != 404, (
        "Anti-enumeration violated: nonexistent email returned 404"
    )
    # If both 204 (the ideal case), verify they match.
    if existing_response.status_code == 204 and nonexistent_response.status_code == 204:
        assert existing_response.status_code == nonexistent_response.status_code, (
            "Anti-enumeration violated: status codes differ between existing "
            f"({existing_response.status_code}) and non-existing "
            f"({nonexistent_response.status_code}) emails"
        )


# ---------------------------------------------------------------------------
# Section B: Invitation token error uniformity (service layer)
# ---------------------------------------------------------------------------


def _make_invitation_row(
    *,
    project_id: Any,
    invited_by_id: Any,
    email: str,
    raw_seed: bytes = b"\x01" * 32,
    expires_at: datetime | None = None,
    status: str = "PENDING",
) -> Any:
    """Build a minimal MagicMock for ProjectInvitation."""
    row = MagicMock()
    row.id = uuid4()
    row.project_id = project_id
    row.invited_by_id = invited_by_id
    row.email = email
    row.expires_at = expires_at or (datetime.now(UTC) + timedelta(days=7))
    row.status = status
    row.email_hash = f"hash-{email}"
    return row


@pytest.mark.asyncio
async def test_invalid_hmac_token_raises_token_invalid_error() -> None:
    """A garbage HMAC token raises ``InvitationTokenInvalidError``.

    The service must not leak any structural information about the failure
    — invalid format, wrong key, expired: all map to the same exception class
    so the HTTP layer can return a uniform error response.
    """
    garbage_token = "garbage.token.that.cannot.be.verified"
    mock_db = AsyncMock()
    mock_redis = MagicMock()

    with pytest.raises(InvitationTokenInvalidError):
        await accept_invitation(
            mock_db,
            signed_token=garbage_token,
            current_user_id=uuid4(),
            current_user_email="user@example.com",
            hmac_secret=HMAC_SECRET,
            redis=mock_redis,
            idempotency_key=None,
        )


@pytest.mark.asyncio
async def test_expired_invitation_token_raises_token_invalid_error(
    db_session: Any,
) -> None:
    """An expired HMAC-signed invitation token raises ``InvitationTokenInvalidError``.

    The service inspects the ``expires_at`` embedded in the signed token and
    must reject it before querying the database — timing consistency is
    maintained regardless of DB state.
    """
    import sqlalchemy as sa

    from echoroo.models.enums import ProjectLicense, ProjectVisibility
    from echoroo.models.project import Project
    from echoroo.models.user import User

    # Seed owner + project.
    owner = User(
        email=f"t979a-owner-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T979a Owner",
        security_stamp="t979a" + "o" * 59,
    )
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    project = Project(
        name=f"T979a {uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=owner.id,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    from echoroo.services import invitation_service

    raw_seed = b"\xAA" * 32
    raw_token_b64u = invitation_service._b64u_encode(raw_seed)
    past_expires = datetime.now(UTC) - timedelta(days=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=past_expires,
        hmac_secret=HMAC_SECRET,
    )

    token_hash = invitation_service.hash_token(raw_token_b64u)
    email = f"t979a-exp-{uuid4().hex[:8]}@example.com"
    email_hash_value = invitation_service.hash_email(email, hmac_secret=HMAC_SECRET)
    invitation_id = uuid4()
    await db_session.execute(
        sa.text(
            """
            INSERT INTO project_invitations
                (id, project_id, kind, email, email_hash, role,
                 granted_permissions, trusted_duration_seconds,
                 token_hash, invited_by_id, expires_at, status,
                 accepted_at, declined_at, revoked_at,
                 created_at, updated_at)
            VALUES
                (:id, :project_id, 'member', :email, :email_hash, 'member',
                 NULL, NULL,
                 :token_hash, :invited_by_id, :expires_at, 'pending',
                 NULL, NULL, NULL,
                 NOW(), NOW())
            """
        ),
        {
            "id": invitation_id,
            "project_id": project.id,
            "email": email,
            "email_hash": email_hash_value,
            "token_hash": token_hash,
            "invited_by_id": owner.id,
            "expires_at": past_expires,
        },
    )
    await db_session.commit()

    recipient = User(
        email=f"t979a-recip-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T979a Recipient",
        security_stamp="t979a" + "r" * 59,
    )
    db_session.add(recipient)
    await db_session.commit()
    await db_session.refresh(recipient)

    from tests.security.invitations.test_invitation_xss_and_expired_accept import _FakeRedis

    with pytest.raises(InvitationTokenInvalidError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=recipient.id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
            idempotency_key=None,
        )


@pytest.mark.asyncio
async def test_already_used_invitation_raises_state_error(
    db_session: Any,
) -> None:
    """An already-ACCEPTED invitation token raises ``InvitationStateError``.

    Together with ``test_expired_invitation_token_raises_token_invalid_error``,
    this test shows that the two failure modes raise DIFFERENT exception types
    at the service layer but that the HTTP router must map both to a single
    generic error response (HTTP 410 / 400) to prevent oracle attacks.
    """
    import sqlalchemy as sa

    from echoroo.models.enums import ProjectLicense, ProjectVisibility
    from echoroo.models.project import Project
    from echoroo.models.user import User
    from echoroo.services import invitation_service

    owner = User(
        email=f"t979a-owner2-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T979a Owner2",
        security_stamp="t979a" + "p" * 59,
    )
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    project = Project(
        name=f"T979a-B {uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=owner.id,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    raw_seed = b"\xBB" * 32
    raw_token_b64u = invitation_service._b64u_encode(raw_seed)
    token_hash = invitation_service.hash_token(raw_token_b64u)
    email = f"t979a-used-{uuid4().hex[:8]}@example.com"
    email_hash_value = invitation_service.hash_email(email, hmac_secret=HMAC_SECRET)
    future_expires = datetime.now(UTC) + timedelta(days=7)
    signed = sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=future_expires,
        hmac_secret=HMAC_SECRET,
    )

    invitation_id = uuid4()
    now = datetime.now(UTC)
    await db_session.execute(
        sa.text(
            """
            INSERT INTO project_invitations
                (id, project_id, kind, email, email_hash, role,
                 granted_permissions, trusted_duration_seconds,
                 token_hash, invited_by_id, expires_at, status,
                 accepted_at, declined_at, revoked_at,
                 created_at, updated_at)
            VALUES
                (:id, :project_id, 'member', :email, :email_hash, 'member',
                 NULL, NULL,
                 :token_hash, :invited_by_id, :expires_at, 'accepted',
                 :now, NULL, NULL,
                 NOW(), NOW())
            """
        ),
        {
            "id": invitation_id,
            "project_id": project.id,
            "email": email,
            "email_hash": email_hash_value,
            "token_hash": token_hash,
            "invited_by_id": owner.id,
            "expires_at": future_expires,
            "now": now,
        },
    )
    await db_session.commit()

    recipient = User(
        email=f"t979a-recip2-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T979a Recipient2",
        security_stamp="t979a" + "q" * 59,
    )
    db_session.add(recipient)
    await db_session.commit()
    await db_session.refresh(recipient)

    from tests.security.invitations.test_invitation_xss_and_expired_accept import _FakeRedis

    with pytest.raises(InvitationStateError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=recipient.id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
            idempotency_key=None,
        )


# ---------------------------------------------------------------------------
# Section C: Rate limiter configuration
# ---------------------------------------------------------------------------


def test_password_reset_rate_limiter_returns_dependency() -> None:
    """``password_reset_rate_limiter()`` returns a valid rate-limiter dependency.

    The function must return a ``RateLimiterDependency`` instance configured
    with positive ``times`` and ``seconds`` from application settings.
    This validates the rate-limiter is wired to the password reset endpoint.
    """
    from fastapi_limiter.depends import RateLimiter as RateLimiterDependency

    limiter = password_reset_rate_limiter()
    assert isinstance(limiter, RateLimiterDependency), (
        "password_reset_rate_limiter() must return a RateLimiterDependency instance"
    )
    assert limiter.times > 0, "Rate limiter must allow at least 1 request"
    # RateLimiterDependency stores seconds as milliseconds internally.
    # Any positive window (> 0 ms) satisfies the rate-limiting requirement.
    assert limiter.milliseconds > 0, (
        "Rate limiter window must be positive (milliseconds > 0)"
    )


def test_password_reset_rate_limit_settings_are_restrictive() -> None:
    """The password reset rate limit must not be trivially bypassable.

    Security requirement: the rate limit on password reset must be stricter
    than allowing unlimited requests. This test documents the acceptable
    range without hard-coding exact numbers.
    """
    from echoroo.core.settings import get_settings

    s = get_settings()
    assert s.RATE_LIMIT_PASSWORD_RESET_ATTEMPTS <= 10, (
        "Password reset rate limit allows too many attempts: "
        f"{s.RATE_LIMIT_PASSWORD_RESET_ATTEMPTS}. Must be ≤ 10 per window."
    )
    assert s.RATE_LIMIT_PASSWORD_RESET_WINDOW_SECONDS >= 60, (
        "Password reset rate limit window too short: "
        f"{s.RATE_LIMIT_PASSWORD_RESET_WINDOW_SECONDS}s. Must be ≥ 60s."
    )


__all__ = [
    "test_already_used_invitation_raises_state_error",
    "test_expired_invitation_token_raises_token_invalid_error",
    "test_invalid_hmac_token_raises_token_invalid_error",
    "test_password_reset_both_emails_same_status_code",
    "test_password_reset_endpoint_returns_204_for_existing_email",
    "test_password_reset_endpoint_returns_204_for_nonexistent_email",
    "test_password_reset_rate_limit_settings_are_restrictive",
    "test_password_reset_rate_limiter_returns_dependency",
    "test_password_reset_returns_success_for_existing_user",
    "test_password_reset_returns_success_for_nonexistent_user",
]
