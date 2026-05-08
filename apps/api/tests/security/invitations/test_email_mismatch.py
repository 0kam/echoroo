"""FR-054 email-mismatch security tests (T530).

The invitation accept / decline flow MUST authenticate the recipient
against the invitation's stored ``email_hash`` using NFKC + casefold
on both sides. This module pins:

1. Plain mismatch (``alice`` vs ``bob``) on accept → ``InvitationEmailMismatchError``.
2. Plain mismatch on decline                       → same exception.
3. Case-only difference (``Alice@`` vs ``alice@``) → no exception (matches).
4. NFKC-equivalent unicode (full-width vs half-width) → matches.
5. Stripped whitespace (``  alice@ ``) → matches the canonical row.
6. Match path on accept returns the invitation row (no error).
7. Match path on decline returns the DECLINED outcome (no error).

The HTTP-layer mapping (403 on accept, 404 on decline) is covered by
``tests/contract/test_invitation_recipient_self_delete.py`` and the
license-style accept harness (future task). Here we focus on the
service-layer guarantees so a regression that loosens the canonical
match surfaces immediately.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectInvitationStatus
from echoroo.models.project import ProjectInvitation
from echoroo.services import invitation_service
from echoroo.services.invitation_service import (
    InvitationEmailMismatchError,
    accept_invitation,
    decline_invitation_by_recipient,
    sign_invitation_token,
)

HMAC_SECRET = "t530-email-mismatch-secret-32-bytes-of-entropy!!"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal Redis fake — only ``get`` / ``set`` / ``incr`` / ``expire``."""

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
# Fixture: build a pending invitation row directly in the DB.
# ---------------------------------------------------------------------------


async def _seed_pending_invitation(
    db: AsyncSession,
    *,
    canonical_email: str,
    project_owner_id: Any,
    project_id: Any,
) -> tuple[ProjectInvitation, str]:
    """Insert a pending Member invitation row + return the signed URL token.

    We seed via raw SQL so we can pass SQL ``NULL`` (not JSONB ``'null'``)
    for the optional Trusted-only columns — the
    ``ck_project_invitations_kind_fields`` CHECK requires
    ``granted_permissions IS NULL`` for ``kind='member'`` and a JSONB null
    literal does not satisfy ``IS NULL``.
    """
    raw_bytes = b"\x42" * 32
    raw_token_b64u = invitation_service._b64u_encode(raw_bytes)
    token_hash = invitation_service.hash_token(raw_token_b64u)
    expires_at = datetime.now(UTC) + timedelta(days=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=expires_at,
        hmac_secret=HMAC_SECRET,
    )
    email_hash_value = invitation_service.hash_email(
        canonical_email, hmac_secret=HMAC_SECRET
    )
    invitation_id = uuid4()
    await db.execute(
        sa.text(
            """
            INSERT INTO project_invitations
                (id, project_id, kind, email, email_hash, role,
                 granted_permissions, trusted_duration_seconds,
                 token_hash, invited_by_id, expires_at, status,
                 created_at, updated_at)
            VALUES
                (:id, :project_id, 'member', :email, :email_hash, 'member',
                 NULL, NULL,
                 :token_hash, :invited_by_id, :expires_at, 'pending',
                 NOW(), NOW())
            """
        ),
        {
            "id": invitation_id,
            "project_id": project_id,
            "email": canonical_email,
            "email_hash": email_hash_value,
            "token_hash": token_hash,
            "invited_by_id": project_owner_id,
            "expires_at": expires_at,
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


@pytest_asyncio.fixture
async def t530_owner_id(db_session: AsyncSession) -> Any:
    """Insert a stand-in user row to satisfy the FK on ``invited_by_id``."""
    from echoroo.models.user import User

    user = User(
        email=f"t530-owner-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T530 Owner",
        security_stamp="t530" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    return user.id


async def _seed_recipient(db: AsyncSession) -> Any:
    """Create a real user row so ``project_members.user_id`` FK holds."""
    from echoroo.models.user import User

    user = User(
        email=f"t530-recipient-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T530 Recipient",
        security_stamp="t530" + "r" * 60,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def _seed_project(db: AsyncSession, owner_id: Any) -> Any:
    """Insert a parent Project row (FK source for invitation.project_id)."""
    from echoroo.models.enums import ProjectLicense, ProjectVisibility
    from echoroo.models.project import Project

    project = Project(
        name=f"T530 {uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
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


# ---------------------------------------------------------------------------
# Helpers — clear table state so individual tests cannot collide on the
# partial-unique pending index. Each test uses a unique email anyway, but
# the helper keeps the suite robust against shared canonical emails.
# ---------------------------------------------------------------------------


async def _purge_invitations(db: AsyncSession) -> None:
    await db.execute(sa.text("DELETE FROM project_invitations"))
    await db.commit()


# ---------------------------------------------------------------------------
# 1. Plain mismatch on accept → exception.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_plain_email_mismatch_raises(
    db_session: AsyncSession,
    t530_owner_id: Any,
) -> None:
    canonical = "alice@example.com"
    await _purge_invitations(db_session)
    project_id = await _seed_project(db_session, t530_owner_id)
    _, signed = await _seed_pending_invitation(
        db_session,
        canonical_email=canonical,
        project_owner_id=t530_owner_id,
        project_id=project_id,
    )

    with pytest.raises(InvitationEmailMismatchError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=uuid4(),
            current_user_email="bob@example.com",
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# 2. Plain mismatch on decline → exception.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_plain_email_mismatch_raises(
    db_session: AsyncSession,
    t530_owner_id: Any,
) -> None:
    canonical = "alice2@example.com"
    await _purge_invitations(db_session)
    project_id = await _seed_project(db_session, t530_owner_id)
    _, signed = await _seed_pending_invitation(
        db_session,
        canonical_email=canonical,
        project_owner_id=t530_owner_id,
        project_id=project_id,
    )

    with pytest.raises(InvitationEmailMismatchError):
        await decline_invitation_by_recipient(
            db_session,
            signed_token=signed,
            current_user_id=uuid4(),
            current_user_email="charlie@example.com",
            hmac_secret=HMAC_SECRET,
        )


# ---------------------------------------------------------------------------
# 3. Case-only difference → matches (NFKC + casefold).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_case_only_difference_matches(
    db_session: AsyncSession,
    t530_owner_id: Any,
) -> None:
    canonical = "alice3@example.com"
    await _purge_invitations(db_session)
    project_id = await _seed_project(db_session, t530_owner_id)
    _, signed = await _seed_pending_invitation(
        db_session,
        canonical_email=canonical,
        project_owner_id=t530_owner_id,
        project_id=project_id,
    )

    # Caller-supplied email differs only in case — hash_email NFKC +
    # casefolds both sides so they collide.
    outcome = await accept_invitation(
        db_session,
        signed_token=signed,
        current_user_id=await _seed_recipient(db_session),
        current_user_email="ALICE3@Example.com",
        hmac_secret=HMAC_SECRET,
        redis=_FakeRedis(),  # type: ignore[arg-type]
    )
    assert outcome.invitation.status is ProjectInvitationStatus.ACCEPTED


# ---------------------------------------------------------------------------
# 4. NFKC-equivalent unicode → matches.
#
# Full-width ASCII (U+FF21..) NFKC-normalises to half-width ASCII so a
# user typing their address with an IME mid-flow still resolves to the
# same canonical hash.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_nfkc_full_width_matches(
    db_session: AsyncSession,
    t530_owner_id: Any,
) -> None:
    canonical = "alice4@example.com"
    full_width = "Ａｌｉｃｅ４@example.com"  # "Alice4"
    # Sanity: NFKC normalisation collapses the full-width variant.
    import unicodedata

    assert (
        unicodedata.normalize("NFKC", full_width).casefold()
        == unicodedata.normalize("NFKC", canonical).casefold()
    )

    await _purge_invitations(db_session)
    project_id = await _seed_project(db_session, t530_owner_id)
    _, signed = await _seed_pending_invitation(
        db_session,
        canonical_email=canonical,
        project_owner_id=t530_owner_id,
        project_id=project_id,
    )

    outcome = await accept_invitation(
        db_session,
        signed_token=signed,
        current_user_id=await _seed_recipient(db_session),
        current_user_email=full_width,
        hmac_secret=HMAC_SECRET,
        redis=_FakeRedis(),  # type: ignore[arg-type]
    )
    assert outcome.invitation.status is ProjectInvitationStatus.ACCEPTED


# ---------------------------------------------------------------------------
# 5. Stripped surrounding whitespace matches the canonical row.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_stripped_whitespace_matches(
    db_session: AsyncSession,
    t530_owner_id: Any,
) -> None:
    canonical = "alice5@example.com"
    await _purge_invitations(db_session)
    project_id = await _seed_project(db_session, t530_owner_id)
    _, signed = await _seed_pending_invitation(
        db_session,
        canonical_email=canonical,
        project_owner_id=t530_owner_id,
        project_id=project_id,
    )

    outcome = await accept_invitation(
        db_session,
        signed_token=signed,
        current_user_id=await _seed_recipient(db_session),
        current_user_email="   alice5@example.com   ",
        hmac_secret=HMAC_SECRET,
        redis=_FakeRedis(),  # type: ignore[arg-type]
    )
    assert outcome.invitation.status is ProjectInvitationStatus.ACCEPTED


# ---------------------------------------------------------------------------
# 6. Hash function — direct unit on hash_email so a regression in NFKC
#    canonicalisation surfaces even without a DB roundtrip.
# ---------------------------------------------------------------------------


def test_hash_email_canonicalises_case_unicode_and_whitespace() -> None:
    """Three visually-different inputs MUST produce the same digest."""
    h1 = invitation_service.hash_email(
        "alice6@example.com", hmac_secret=HMAC_SECRET
    )
    h2 = invitation_service.hash_email(
        "ALICE6@Example.com", hmac_secret=HMAC_SECRET
    )
    h3 = invitation_service.hash_email(
        "  alice6@example.com  ", hmac_secret=HMAC_SECRET
    )
    h4 = invitation_service.hash_email(
        "Ａｌｉｃｅ６@example.com",
        hmac_secret=HMAC_SECRET,
    )  # "Alice6" full-width
    assert h1 == h2 == h3 == h4

    # Different mailbox → different digest.
    h_other = invitation_service.hash_email(
        "alice6+tag@example.com", hmac_secret=HMAC_SECRET
    )
    assert h_other != h1


# ---------------------------------------------------------------------------
# 7. Decline match path → invitation row transitions to DECLINED.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_email_match_transitions_to_declined(
    db_session: AsyncSession,
    t530_owner_id: Any,
) -> None:
    canonical = "alice7@example.com"
    await _purge_invitations(db_session)
    project_id = await _seed_project(db_session, t530_owner_id)
    invitation, signed = await _seed_pending_invitation(
        db_session,
        canonical_email=canonical,
        project_owner_id=t530_owner_id,
        project_id=project_id,
    )

    outcome = await decline_invitation_by_recipient(
        db_session,
        signed_token=signed,
        current_user_id=uuid4(),
        current_user_email=canonical,
        hmac_secret=HMAC_SECRET,
    )
    assert outcome.invitation.status is ProjectInvitationStatus.DECLINED
    assert outcome.is_replay is False
    # The row in the same session reflects the new state.
    assert invitation.status is ProjectInvitationStatus.DECLINED


__all__ = [
    "test_accept_case_only_difference_matches",
    "test_accept_nfkc_full_width_matches",
    "test_accept_plain_email_mismatch_raises",
    "test_accept_stripped_whitespace_matches",
    "test_decline_email_match_transitions_to_declined",
    "test_decline_plain_email_mismatch_raises",
    "test_hash_email_canonicalises_case_unicode_and_whitespace",
]
