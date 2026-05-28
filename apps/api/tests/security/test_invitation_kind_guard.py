"""spec/011 R5 — ``ownership_transfer_on_accept`` is MEMBER-kind only.

Three defence layers MUST refuse to let an attacker (or a careless
operator) ride a Trusted-overlay invitation to a project ownership
transfer:

1. **DB CHECK** ``ck_project_invitations_ownership_transfer_kind_member``
   added by migration ``0021_zero_email_additive`` (spec/011 Step 1).
   A direct INSERT bypassing the service layer (raw psql, future
   ETL pipeline, restore-from-backup) MUST raise ``IntegrityError``.
2. **Service-layer issue guard** — ``create_invitation`` raises
   :class:`InvitationStateError` BEFORE the INSERT so callers get a
   typed error instead of a bare IntegrityError. This is the path the
   admin / SU API actually hits.
3. **Service-layer accept guard** — ``accept_invitation`` raises the
   same typed error if a row somehow exists with
   ``ownership_transfer_on_accept=True`` AND ``kind != member`` (e.g.
   data corruption, a CHECK-bypassing migration shim, a backup
   restored from a deployment that pre-dates the CHECK). Defence in
   depth so the ownership transfer pathway in Step 9 never silently
   activates on a misclassified row.

Together these guarantee FR-011-122..125: the SU bootstrap ownership
transfer ONLY fires for the explicitly-allowlisted Admin-role Member
invitation. A Trusted overlay (which is an ephemeral capability layer,
NOT a project ownership grant) cannot be wired to the transfer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectLicense,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectInvitation
from echoroo.models.user import User
from echoroo.services import invitation_service
from echoroo.services.invitation_service import (
    InvitationStateError,
    accept_invitation,
    create_invitation,
    hash_email,
    hash_token,
    sign_invitation_token,
)

HMAC_SECRET = "spec011-step6-kind-guard-hmac-32chars!"

# ---------------------------------------------------------------------------
# In-memory Redis fake (mirrors test_double_accept_idempotency.py)
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Async Redis fake used by ``create_invitation`` rate-limit + idempotency."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def incr(self, name: str) -> int:
        value = int(self.values.get(name, 0)) + 1
        self.values[name] = value
        return value

    async def expire(self, name: str, time: int) -> bool:
        del time
        return name in self.values

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
        del ex
        self.values[name] = value
        return True


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def issuer_user(db_session: AsyncSession) -> User:
    """Owner / issuer who creates the invitation under test."""
    user = User(
        email=f"r5-issuer-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="R5 Issuer",
        security_stamp="r5issuer" + "x" * 56,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def restricted_project(
    db_session: AsyncSession, issuer_user: User
) -> Project:
    """A Restricted project the issuer can issue invitations against."""
    project = Project(
        name=f"R5 {uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=issuer_user.id,
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
    return project


@pytest_asyncio.fixture
async def recipient_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"r5-recip-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="R5 Recipient",
        security_stamp="r5recipient" + "z" * 53,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[_FakeRedis]:
    yield _FakeRedis()


# ---------------------------------------------------------------------------
# Layer 1 — DB CHECK constraint refuses a raw INSERT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_insert_with_transfer_on_trusted_row_rejected_by_check(
    db_session: AsyncSession,
    issuer_user: User,
    restricted_project: Project,
) -> None:
    """The DB CHECK rejects ``ownership_transfer_on_accept=True`` on TRUSTED."""
    raw_token = "raw-direct-insert-stub"
    token_hash_value = hash_token(raw_token)
    email = "trusted-direct@example.com"
    email_hash_value = hash_email(email, hmac_secret=HMAC_SECRET)
    expires_at = datetime.now(UTC) + timedelta(days=1)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            sa.text(
                """
                INSERT INTO project_invitations (
                    id, project_id, kind, email, email_hash,
                    role, granted_permissions, trusted_duration_seconds,
                    token_hash, invited_by_id, expires_at, status,
                    ownership_transfer_on_accept,
                    created_at, updated_at
                ) VALUES (
                    :id, :project_id, 'trusted', :email, :email_hash,
                    NULL,
                    CAST(:granted_permissions AS JSONB), 86400,
                    :token_hash, :invited_by_id, :expires_at, 'pending',
                    TRUE,
                    NOW(), NOW()
                )
                """
            ),
            {
                "id": uuid4(),
                "project_id": restricted_project.id,
                "email": email,
                "email_hash": email_hash_value,
                "granted_permissions": '["view_media"]',
                "token_hash": token_hash_value,
                "invited_by_id": issuer_user.id,
                "expires_at": expires_at,
            },
        )
    await db_session.rollback()


# ---------------------------------------------------------------------------
# Layer 2 — ``create_invitation`` raises BEFORE the INSERT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invitation_raises_state_error_for_trusted_with_transfer(
    db_session: AsyncSession,
    issuer_user: User,
    restricted_project: Project,
    fake_redis: _FakeRedis,
) -> None:
    """The service guard surfaces a typed error before any DB round-trip."""
    with pytest.raises(InvitationStateError) as exc_info:
        await create_invitation(
            db_session,
            project_id=restricted_project.id,
            kind=ProjectInvitationKind.TRUSTED,
            email="r5-svc-trusted@example.com",
            invited_by_id=issuer_user.id,
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            granted_permissions=["view_media"],
            trusted_duration_seconds=86400,
            ownership_transfer_on_accept=True,
        )
    assert "ownership_transfer_on_accept_invalid_for_kind" in str(exc_info.value)
    # Sanity: no row was inserted (rate-limit consumption is acceptable —
    # the guard runs before ``check_rate_limits`` per the implementation).
    row_count = (
        await db_session.execute(
            sa.select(sa.func.count()).select_from(ProjectInvitation).where(
                ProjectInvitation.project_id == restricted_project.id
            )
        )
    ).scalar_one()
    assert row_count == 0


@pytest.mark.asyncio
async def test_create_invitation_allows_member_with_transfer(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity / regression: MEMBER + transfer is the SU bootstrap happy path.

    We use a fake in-memory session here so the assertion focuses on the
    service-layer outcome shape (kind + ownership_transfer_on_accept on
    the returned ``InvitationCreateOutcome``). The DB-level CHECK
    coverage lives in
    :func:`test_direct_insert_with_transfer_on_trusted_row_rejected_by_check`
    above; this case is purely "happy path: service does NOT raise".
    """

    class _StubSession:
        added: list[Any]
        flush_calls: int

        def __init__(self) -> None:
            self.added = []
            self.flush_calls = 0

        def add(self, obj: Any) -> None:
            self.added.append(obj)
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()

        async def flush(self) -> None:
            self.flush_calls += 1

    monkeypatch.setattr(
        invitation_service,
        "hash_email_dual",
        lambda _email: {"v1": "0" * 64},
    )
    session = _StubSession()
    outcome = await create_invitation(
        session,  # type: ignore[arg-type]
        project_id=uuid4(),
        kind=ProjectInvitationKind.MEMBER,
        email="r5-member-happy@example.com",
        invited_by_id=uuid4(),
        hmac_secret=HMAC_SECRET,
        redis=fake_redis,  # type: ignore[arg-type]
        role=ProjectMemberRole.ADMIN,
        ownership_transfer_on_accept=True,
    )
    assert outcome.invitation.ownership_transfer_on_accept is True
    assert outcome.invitation.kind is ProjectInvitationKind.MEMBER


# ---------------------------------------------------------------------------
# Layer 3 — ``accept_invitation`` raises if the row is somehow corrupt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_invitation_raises_state_error_on_corrupted_row(
    db_session: AsyncSession,
    issuer_user: User,
    restricted_project: Project,
    recipient_user: User,
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupted row (TRUSTED + transfer=True) is rejected at accept time.

    We can't reproduce the corruption via the live DB because the CHECK
    constraint protects against it. Instead we monkeypatch the
    ``ProjectInvitation`` instance attribute after a clean fetch so the
    in-memory copy carries the impossible combination. This exercises
    the **defence-in-depth** path inside ``accept_invitation`` — the
    only sanity guarantee we have if the CHECK constraint were ever
    accidentally dropped during a migration or a backup restore.
    """
    # Seed a clean MEMBER-kind row WITHOUT transfer set (a normal
    # invitation), then mutate the in-memory instance.
    raw_token = "raw-accept-corruption-stub"
    raw_token_b64u = invitation_service._b64u_encode(b"\x88" * 32)
    token_hash_value = hash_token(raw_token_b64u)
    email = "r5-accept-corrupt@example.com"
    # Use the recipient's email for the email-match guard.
    email = recipient_user.email or email
    email_hash_value = hash_email(email, hmac_secret=HMAC_SECRET)
    expires_at = datetime.now(UTC) + timedelta(days=1)
    # spec/011 step 6 also requires a kid env to be active for signing.
    # The test DB env already provides ``INVITATION_TOKEN_KID_NEW`` +
    # ``INVITATION_TOKEN_HMAC_KEY`` (compose dev defaults). The signed
    # envelope is consumed by the verifier under those settings.
    signed = sign_invitation_token(
        raw_token_b64u=raw_token_b64u, expires_at=expires_at,
    )

    invitation_id = uuid4()
    await db_session.execute(
        sa.text(
            """
            INSERT INTO project_invitations (
                id, project_id, kind, email, email_hash,
                role, granted_permissions, trusted_duration_seconds,
                token_hash, invited_by_id, expires_at, status,
                ownership_transfer_on_accept,
                created_at, updated_at
            ) VALUES (
                :id, :project_id, 'member', :email, :email_hash,
                'admin', NULL, NULL,
                :token_hash, :invited_by_id, :expires_at, 'pending',
                FALSE,
                NOW(), NOW()
            )
            """
        ),
        {
            "id": invitation_id,
            "project_id": restricted_project.id,
            "email": email,
            "email_hash": email_hash_value,
            "token_hash": token_hash_value,
            "invited_by_id": issuer_user.id,
            "expires_at": expires_at,
        },
    )
    await db_session.commit()

    # Patch the SQLAlchemy ORM lookup so the instance returned by
    # ``accept_invitation`` carries the impossible TRUSTED + transfer
    # combo. The real DB row is untouched; we are simulating a
    # CHECK-bypass that would otherwise be invisible to the service.
    _original_execute = db_session.execute

    async def _corrupting_execute(*args: Any, **kwargs: Any) -> Any:
        result = await _original_execute(*args, **kwargs)
        # Only mutate the very first SELECT FOR UPDATE on
        # project_invitations; the post-flush calls leave the result
        # alone.
        try:
            scalar = result.scalar_one_or_none()
        except Exception:
            return result
        if isinstance(scalar, ProjectInvitation):
            # Rebuild a result wrapper that returns the corrupted row.
            scalar.kind = ProjectInvitationKind.TRUSTED
            scalar.ownership_transfer_on_accept = True

            class _OneShotResult:
                def __init__(self, value: Any) -> None:
                    self._value = value

                def scalar_one_or_none(self) -> Any:
                    return self._value

            # Restore normal execute for downstream calls so the rest
            # of accept_invitation does not get further surgery.
            db_session.execute = _original_execute  # type: ignore[method-assign]
            return _OneShotResult(scalar)
        return result

    monkeypatch.setattr(db_session, "execute", _corrupting_execute)

    with pytest.raises(InvitationStateError) as exc_info:
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=recipient_user.id,
            current_user_email=recipient_user.email or email,
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key=None,
        )
    assert "ownership_transfer_on_accept_invalid_for_kind" in str(
        exc_info.value
    )
