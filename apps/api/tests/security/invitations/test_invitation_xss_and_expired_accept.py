"""Codex追補: Invitation XSS sanitisation + expired/revoked token acceptance (T979c).

Verifies two security properties of the invitation flow:

A. XSS prevention:
   - ``display_name`` / ``email`` payloads with ``<script>`` / SVG / HTML
     tags in request schemas are either rejected (Pydantic ValidationError)
     or stored as plain text (no HTML interpretation at the JSON-API level).
   - spec/011 Step 6 (T052/T053): the legacy ``InvitationMailPayload``
     dataclass is removed. The plain-text envelope now lives on
     ``InvitationCreateOutcome.signed_token_envelope`` as a flat ``str``
     and is surfaced once on the issue endpoint's HTTP response
     (FR-011-103). The envelope is inert at the dataclass boundary.

B. Expired / already-consumed token acceptance:
   - Expired HMAC-signed token (``expires_at`` in the past) → raises
     ``InvitationTokenInvalidError`` at the service level.
   - Already-accepted token (``status=ACCEPTED``) without matching
     idempotency key → raises ``InvitationStateError``.
   - Already-declined token → raises ``InvitationStateError``.
   - Revoked token (``status=REVOKED``) → raises ``InvitationStateError``.

All tests work at the service / schema layer — no HTTP server is needed.
DB tests use the shared ``db_session`` fixture and follow the same
seeding pattern as ``test_double_accept_idempotency.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectInvitationStatus
from echoroo.models.project import ProjectInvitation
from echoroo.services import invitation_service
from echoroo.services.invitation_service import (
    InvitationStateError,
    InvitationTokenInvalidError,
    accept_invitation,
    sign_invitation_token,
)

HMAC_SECRET = "t979c-xss-expired-secret-32-bytes-!!!"

# XSS payload candidates
_XSS_PAYLOADS: list[str] = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(1)",
    "<svg onload=alert(1)>",
    "data:text/html,<h1>inject</h1>",
]


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal Redis fake with controllable state."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, name: str) -> int:
        v = int(self.values.get(name, 0)) + 1
        self.values[name] = v
        return v

    async def expire(self, name: str, time: int) -> bool:
        if name in self.values:
            self.ttls[name] = time
            return True
        return False

    async def get(self, name: str) -> Any:
        return self.values.get(name)

    async def set(
        self,
        name: str,
        value: Any,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if nx and name in self.values:
            return None
        self.values[name] = value
        if ex is not None:
            self.ttls[name] = ex
        return True


# ---------------------------------------------------------------------------
# DB-level helpers (mirrors test_double_accept_idempotency.py pattern)
# ---------------------------------------------------------------------------


async def _seed_owner(db: AsyncSession) -> Any:
    from echoroo.models.user import User

    user = User(
        email=f"t979c-owner-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T979c Owner",
        security_stamp="t979c" + "o" * 59,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def _seed_recipient(db: AsyncSession) -> Any:
    from echoroo.models.user import User

    user = User(
        email=f"t979c-recip-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T979c Recipient",
        security_stamp="t979c" + "r" * 59,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def _seed_project(db: AsyncSession, owner_id: Any) -> Any:
    from echoroo.models.enums import ProjectLicense, ProjectVisibility
    from echoroo.models.project import Project

    project = Project(
        name=f"T979c {uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner_id,
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
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project.id


async def _seed_invitation(
    db: AsyncSession,
    *,
    email: str,
    invited_by_id: Any,
    project_id: Any,
    raw_seed: bytes = b"\xAA" * 32,
    expires_at: datetime | None = None,
    status: ProjectInvitationStatus = ProjectInvitationStatus.PENDING,
) -> tuple[ProjectInvitation, str]:
    """Insert an invitation row and return the row + signed token.

    The DB CHECK constraint ``ck_project_invitations_status_timestamps``
    requires that terminal-status rows carry the matching timestamp:
    - ACCEPTED  → accepted_at IS NOT NULL
    - DECLINED  → declined_at IS NOT NULL
    - REVOKED   → revoked_at IS NOT NULL
    - PENDING / EXPIRED → all timestamp columns NULL
    """
    raw_token_b64u = invitation_service._b64u_encode(raw_seed)
    token_hash = invitation_service.hash_token(raw_token_b64u)
    eff_expires_at = expires_at or (datetime.now(UTC) + timedelta(days=7))
    signed = sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=eff_expires_at,
        hmac_secret=HMAC_SECRET,
    )
    email_hash_value = invitation_service.hash_email(email, hmac_secret=HMAC_SECRET)
    invitation_id = uuid4()

    # Determine terminal timestamps based on status to satisfy the DB constraint.
    now = datetime.now(UTC)
    accepted_at: datetime | None = now if status is ProjectInvitationStatus.ACCEPTED else None
    declined_at: datetime | None = now if status is ProjectInvitationStatus.DECLINED else None
    revoked_at: datetime | None = now if status is ProjectInvitationStatus.REVOKED else None

    await db.execute(
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
                 :token_hash, :invited_by_id, :expires_at, :status,
                 :accepted_at, :declined_at, :revoked_at,
                 NOW(), NOW())
            """
        ),
        {
            "id": invitation_id,
            "project_id": project_id,
            "email": email,
            "email_hash": email_hash_value,
            "token_hash": token_hash,
            "invited_by_id": invited_by_id,
            "expires_at": eff_expires_at,
            "status": status.value,
            "accepted_at": accepted_at,
            "declined_at": declined_at,
            "revoked_at": revoked_at,
        },
    )
    await db.commit()
    invitation = (
        await db.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id
            )
        )
    ).scalar_one()
    return invitation, signed


# ---------------------------------------------------------------------------
# Section A: XSS prevention at the schema layer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("xss_payload", _XSS_PAYLOADS)
def test_trusted_invite_request_rejects_xss_in_email(xss_payload: str) -> None:
    """XSS payloads in ``email`` MUST be rejected by Pydantic ``EmailStr``.

    ``pydantic.EmailStr`` delegates to ``email-validator`` which validates
    RFC 5322 syntax and refuses HTML/script special characters in email
    local-parts and domains. Any of the ``_XSS_PAYLOADS`` should raise
    ``ValidationError``.
    """
    from pydantic import ValidationError

    from echoroo.schemas.trusted import TrustedUserInviteRequest

    with pytest.raises(ValidationError) as exc_info:
        TrustedUserInviteRequest(
            email=xss_payload,
            granted_permissions=["view_media"],
            duration_seconds=86400,
        )

    errors = exc_info.value.errors()
    field_locs = {err["loc"][0] for err in errors}
    assert "email" in field_locs, (
        f"Expected ValidationError on 'email', got {field_locs}"
    )


def test_trusted_invite_request_no_display_name_field() -> None:
    """``TrustedUserInviteRequest`` has no ``display_name`` field — no XSS surface.

    If a ``display_name`` field is ever added, it MUST be validated to prevent
    XSS in email templates (FR-101b: user-generated strings must be HTML-escaped).
    This test documents the expected schema shape.
    """
    from echoroo.schemas.trusted import TrustedUserInviteRequest

    assert "display_name" not in TrustedUserInviteRequest.model_fields, (
        "display_name field was added to TrustedUserInviteRequest — "
        "ensure HTML escaping is applied before using it in email templates"
    )


def test_invitation_outcome_envelope_is_inert_string() -> None:
    """spec/011 Step 6 (T052/T053): the legacy ``InvitationMailPayload``
    carrier is removed. Plain-text token confidentiality is now enforced
    at the API layer (FR-011-102..104) — the value lives on
    ``InvitationCreateOutcome.signed_token_envelope`` as a plain ``str``,
    surfaced once on the issue endpoint's HTTP response and never
    persisted.

    This test documents the new shape and asserts the envelope is just
    a string (no Markup / SafeStr / nested dataclass that could subtly
    re-render).
    """
    from echoroo.services.invitation_service import InvitationCreateOutcome

    outcome = InvitationCreateOutcome(
        invitation=None,  # type: ignore[arg-type]
        actor_user_id=uuid4(),
        signed_token_envelope="rawb64.1700000000.kid_test.sigb64",
    )
    assert type(outcome.signed_token_envelope) is str
    assert "<script>" not in outcome.signed_token_envelope


# ---------------------------------------------------------------------------
# Section B: Expired token → InvitationTokenInvalidError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_token_raises_token_invalid_error(
    db_session: AsyncSession,
) -> None:
    """An HMAC-signed token whose ``expires_at`` is in the past MUST raise
    ``InvitationTokenInvalidError`` before the status check — the signature
    verification step rejects expired tokens independently of the DB row.
    """
    owner_id = await _seed_owner(db_session)
    project_id = await _seed_project(db_session, owner_id)
    email = f"expired-token-{uuid4().hex[:6]}@example.com"

    # Seed the row with a past expires_at.
    past_expires = datetime.now(UTC) - timedelta(days=31)
    _, signed = await _seed_invitation(
        db_session,
        email=email,
        invited_by_id=owner_id,
        project_id=project_id,
        raw_seed=b"\xB1" * 32,
        expires_at=past_expires,
    )
    user_id = await _seed_recipient(db_session)

    with pytest.raises(InvitationTokenInvalidError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=user_id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
            idempotency_key=None,
        )


# ---------------------------------------------------------------------------
# Section B: Already-accepted token (without idempotency key) → StateError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_already_accepted_token_without_key_raises_state_error(
    db_session: AsyncSession,
) -> None:
    """Re-accepting an already-ACCEPTED invitation without an idempotency key
    MUST raise ``InvitationStateError`` (maps to HTTP 410 Gone).
    """
    owner_id = await _seed_owner(db_session)
    project_id = await _seed_project(db_session, owner_id)
    email = f"already-accepted-{uuid4().hex[:6]}@example.com"

    _, signed = await _seed_invitation(
        db_session,
        email=email,
        invited_by_id=owner_id,
        project_id=project_id,
        raw_seed=b"\xB2" * 32,
        status=ProjectInvitationStatus.ACCEPTED,
    )
    user_id = await _seed_recipient(db_session)

    with pytest.raises(InvitationStateError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=user_id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
            idempotency_key=None,
        )


# ---------------------------------------------------------------------------
# Section B: Already-declined token → StateError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_declined_token_raises_state_error(
    db_session: AsyncSession,
) -> None:
    """Attempting to accept an already-DECLINED invitation MUST raise
    ``InvitationStateError`` (HTTP 410).
    """
    owner_id = await _seed_owner(db_session)
    project_id = await _seed_project(db_session, owner_id)
    email = f"declined-invite-{uuid4().hex[:6]}@example.com"

    _, signed = await _seed_invitation(
        db_session,
        email=email,
        invited_by_id=owner_id,
        project_id=project_id,
        raw_seed=b"\xB3" * 32,
        status=ProjectInvitationStatus.DECLINED,
    )
    user_id = await _seed_recipient(db_session)

    with pytest.raises(InvitationStateError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=user_id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
            idempotency_key=None,
        )


# ---------------------------------------------------------------------------
# Section B: Revoked token → StateError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoked_token_raises_state_error(
    db_session: AsyncSession,
) -> None:
    """Attempting to accept a REVOKED invitation MUST raise
    ``InvitationStateError`` (HTTP 410 / 403).
    """
    owner_id = await _seed_owner(db_session)
    project_id = await _seed_project(db_session, owner_id)
    email = f"revoked-invite-{uuid4().hex[:6]}@example.com"

    _, signed = await _seed_invitation(
        db_session,
        email=email,
        invited_by_id=owner_id,
        project_id=project_id,
        raw_seed=b"\xB4" * 32,
        status=ProjectInvitationStatus.REVOKED,
    )
    user_id = await _seed_recipient(db_session)

    with pytest.raises(InvitationStateError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=user_id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
            idempotency_key=None,
        )


__all__ = [
    "test_already_accepted_token_without_key_raises_state_error",
    "test_declined_token_raises_state_error",
    "test_expired_token_raises_token_invalid_error",
    "test_invitation_outcome_envelope_is_inert_string",
    "test_revoked_token_raises_state_error",
    "test_trusted_invite_request_no_display_name_field",
    "test_trusted_invite_request_rejects_xss_in_email",
]
