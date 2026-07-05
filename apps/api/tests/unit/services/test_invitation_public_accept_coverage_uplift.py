"""W3-1 coverage uplift — ``echoroo.services.invitation.accept`` +
``echoroo.services.invitation.public`` (T996 per-module 85% gate).

PR #215 split ``invitation_service.py`` into the ``invitation/`` package.
Splitting the module exposed two previously-masked per-module coverage
gaps (the monolith's aggregate coverage hid them):

* ``invitation/accept.py`` (82.1% baseline) — the legacy
  ``accept_invitation`` happy-path branches (member REUSE, Trusted grant,
  IntegrityError-on-flush conflict) and two rare guard branches (row
  expired, signed-token/row expiry mismatch, SU-bootstrap-on-legacy-path
  refusal) were only exercised by the integration suite.
* ``invitation/public.py`` (64.3% baseline) — almost the entire success
  path of ``accept_invitation_via_public_token`` (Step 4 onward: the
  grant-application branches, the IntegrityError conflict, and the full
  FR-011-123 SAVEPOINT-nested ownership-transfer block) was unit-untested;
  only the early error-return branches had unit coverage
  (``test_invitation_service_spec011_uplift.py``).

This suite adds pure in-process unit tests (AsyncSession replaced by
scripted stubs, no real DB) for exactly those uncovered branches. Pure
addition — no production code is modified.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
    ProjectTrustedStatus,
)
from echoroo.models.project import ProjectMember
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.services.invitation.accept import accept_invitation
from echoroo.services.invitation.constants import (
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
    AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
    TRUSTED_MAX_DURATION_SECONDS,
)
from echoroo.services.invitation.emails import hash_email
from echoroo.services.invitation.errors import (
    InvitationConflictError,
    InvitationStateError,
    InvitationTokenInvalidError,
    InvitationValidationError,
)
from echoroo.services.invitation.public import accept_invitation_via_public_token
from echoroo.services.invitation.tokens import _b64u_encode, sign_invitation_token

HMAC_SECRET = "w3-1-coverage-uplift-hmac-secret-32!"
DEFAULT_EMAIL = "invited@example.com"

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared helpers / stubs
# ---------------------------------------------------------------------------


def _sign(*, expires_at: datetime) -> str:
    """Return a valid signed invitation-token envelope for ``expires_at``."""
    raw = _b64u_encode(secrets.token_bytes(32))
    return sign_invitation_token(raw_token_b64u=raw, expires_at=expires_at)


class _FakeRedis:
    """Minimal Redis fake supporting GET/SET for idempotency-record tests."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

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
        return True


class _NullResult:
    def scalar_one_or_none(self) -> Any:
        return None


class _MockInvitationLegacy:
    """Duck-typed ``ProjectInvitation`` stub for the legacy accept path.

    ``email_hash`` is computed via :func:`hash_email` so
    ``_email_matches_invitation`` (legacy HMAC branch) matches
    ``DEFAULT_EMAIL`` without requiring a real ORM row / DB round-trip.
    ``email_hash_v2`` is left ``None`` so the KMS branch is a no-op.
    """

    def __init__(
        self,
        *,
        email: str = DEFAULT_EMAIL,
        status: ProjectInvitationStatus = ProjectInvitationStatus.PENDING,
        expires_at: datetime | None = None,
        kind: ProjectInvitationKind = ProjectInvitationKind.MEMBER,
        role: ProjectMemberRole | None = ProjectMemberRole.MEMBER,
        ownership_transfer_on_accept: bool = False,
        granted_permissions: list[str] | None = None,
        trusted_duration_seconds: int | None = None,
        project_id: UUID | None = None,
        invited_by_id: UUID | None = None,
        id: UUID | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.project_id = project_id or uuid4()
        self.kind = kind
        self.status = status
        self.expires_at = expires_at or (datetime.now(UTC) + timedelta(days=7))
        self.role = role
        self.ownership_transfer_on_accept = ownership_transfer_on_accept
        self.granted_permissions = granted_permissions
        self.trusted_duration_seconds = trusted_duration_seconds
        self.invited_by_id = invited_by_id or uuid4()
        self.email_hash = hash_email(email, hmac_secret=HMAC_SECRET)
        self.email_hash_v2: str | None = None
        self.email: str | None = email
        self.accepted_at: datetime | None = None


class _ScriptedSession:
    """Returns canned results for consecutive ``session.execute()`` calls."""

    def __init__(self, responses: list[Any], *, raise_on_flush: BaseException | None = None) -> None:
        self._responses = list(responses)
        self.added: list[Any] = []
        self.flush_calls: int = 0
        self._raise_on_flush = raise_on_flush

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    async def flush(self) -> None:
        self.flush_calls += 1
        if self._raise_on_flush is not None:
            raise self._raise_on_flush

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        if not self._responses:
            raise AssertionError("_ScriptedSession: unexpected execute() call")
        return self._responses.pop(0)

    @asynccontextmanager
    async def begin_nested(self) -> AsyncGenerator[None, None]:
        yield


class _FakeScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def first(self) -> Any:
        return self._value

    def fetchone(self) -> Any:
        return self._value


class _FakeFirstResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row

    def scalar_one_or_none(self) -> Any:
        return self._row

    def fetchone(self) -> Any:
        return self._row


# ===========================================================================
# accept.py — legacy accept_invitation() happy-path + rare guard branches
# ===========================================================================


async def test_accept_invitation_row_expired_raises() -> None:
    """Row ``expires_at`` in the past (line 168) → InvitationTokenInvalidError.

    The signed token itself remains valid (future expiry) — only the DB
    row's own ``expires_at`` guard fires.
    """
    token = _sign(expires_at=datetime.now(UTC) + timedelta(days=1))
    inv = _MockInvitationLegacy(expires_at=datetime.now(UTC) - timedelta(hours=1))
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationTokenInvalidError, match="expired"):
        await accept_invitation(
            session,  # type: ignore[arg-type]
            signed_token=token,
            current_user_id=uuid4(),
            current_user_email=DEFAULT_EMAIL,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
        )


async def test_accept_invitation_signed_expiry_mismatch_raises() -> None:
    """Signed token expiry running well before the row's (line 218)."""
    row_expires_at = datetime.now(UTC) + timedelta(hours=2)
    token_expires_at = datetime.now(UTC) + timedelta(minutes=30)
    token = _sign(expires_at=token_expires_at)
    inv = _MockInvitationLegacy(expires_at=row_expires_at)
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationTokenInvalidError, match="expiry mismatch"):
        await accept_invitation(
            session,  # type: ignore[arg-type]
            signed_token=token,
            current_user_id=uuid4(),
            current_user_email=DEFAULT_EMAIL,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
        )


async def test_accept_invitation_ownership_transfer_must_use_public_path_raises() -> None:
    """Bootstrap invite (ownership_transfer_on_accept + MEMBER kind) on the
    legacy accept path (line 239) → InvitationStateError.
    """
    expires_at = datetime.now(UTC) + timedelta(days=1)
    token = _sign(expires_at=expires_at)
    inv = _MockInvitationLegacy(expires_at=expires_at, ownership_transfer_on_accept=True)
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationStateError, match="ownership_transfer_must_use_public_path"):
        await accept_invitation(
            session,  # type: ignore[arg-type]
            signed_token=token,
            current_user_id=uuid4(),
            current_user_email=DEFAULT_EMAIL,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
        )


async def test_accept_invitation_existing_member_no_idempotency_key_conflicts() -> None:
    """Existing active membership + no idempotency-key (line 280) → 409."""
    expires_at = datetime.now(UTC) + timedelta(days=1)
    token = _sign(expires_at=expires_at)
    inv = _MockInvitationLegacy(expires_at=expires_at)
    existing_member = MagicMock(spec=ProjectMember)
    existing_member.role = ProjectMemberRole.MEMBER
    session = _ScriptedSession(
        [_FakeScalarResult(inv), _FakeScalarResult(existing_member)],
    )
    with pytest.raises(InvitationConflictError, match="already has an active membership"):
        await accept_invitation(
            session,  # type: ignore[arg-type]
            signed_token=token,
            current_user_id=uuid4(),
            current_user_email=DEFAULT_EMAIL,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
        )


async def test_accept_invitation_existing_member_reuse_succeeds_with_matching_key() -> None:
    """Existing member + matching idempotency-key record (line 293) → REUSE.

    Exercises the ``member = existing_member`` reuse branch through to a
    successful ``flush()`` and outcome return.
    """
    expires_at = datetime.now(UTC) + timedelta(days=1)
    raw = _b64u_encode(secrets.token_bytes(32))
    token = sign_invitation_token(raw_token_b64u=raw, expires_at=expires_at)
    from echoroo.services.invitation.tokens import hash_token

    token_hash = hash_token(raw)

    inv = _MockInvitationLegacy(expires_at=expires_at)
    existing_member = MagicMock(spec=ProjectMember)
    existing_member.role = ProjectMemberRole.MEMBER
    existing_member.id = uuid4()

    redis = _FakeRedis()
    key = "reuse-key"
    from echoroo.services.invitation.idempotency import _idempotency_redis_key

    redis.values[_idempotency_redis_key(key)] = (
        '{"invitation_id": "'
        + str(inv.id)
        + '", "token_hash": "'
        + token_hash
        + '", "created_at": "2026-01-01T00:00:00+00:00"}'
    )

    session = _ScriptedSession(
        [_FakeScalarResult(inv), _FakeScalarResult(existing_member)],
    )

    outcome = await accept_invitation(
        session,  # type: ignore[arg-type]
        signed_token=token,
        current_user_id=uuid4(),
        current_user_email=DEFAULT_EMAIL,
        hmac_secret=HMAC_SECRET,
        redis=redis,  # type: ignore[arg-type]
        idempotency_key=key,
    )

    assert outcome.member is existing_member
    assert outcome.is_replay is False
    # No new ProjectMember was inserted — the existing row was reused.
    assert existing_member not in session.added
    assert session.flush_calls == 1


async def test_accept_invitation_trusted_kind_success() -> None:
    """Trusted-kind grant application (lines 315-336) end to end."""
    expires_at = datetime.now(UTC) + timedelta(days=1)
    token = _sign(expires_at=expires_at)
    inv = _MockInvitationLegacy(
        expires_at=expires_at,
        kind=ProjectInvitationKind.TRUSTED,
        role=None,
        granted_permissions=["view_media"],
        trusted_duration_seconds=3600,
    )
    session = _ScriptedSession([_FakeScalarResult(inv)])

    outcome = await accept_invitation(
        session,  # type: ignore[arg-type]
        signed_token=token,
        current_user_id=uuid4(),
        current_user_email=DEFAULT_EMAIL,
        hmac_secret=HMAC_SECRET,
        redis=_FakeRedis(),  # type: ignore[arg-type]
    )

    assert outcome.trusted_user is not None
    assert outcome.trusted_user.status == ProjectTrustedStatus.ACTIVE
    assert isinstance(outcome.trusted_user, ProjectTrustedUser)
    assert outcome.trusted_user in session.added
    assert inv.status == ProjectInvitationStatus.ACCEPTED


async def test_accept_invitation_trusted_duration_exceeds_cap_raises() -> None:
    """Trusted duration resolving past the FR-043 cap → InvitationValidationError."""
    expires_at = datetime.now(UTC) + timedelta(days=1)
    token = _sign(expires_at=expires_at)
    inv = _MockInvitationLegacy(
        expires_at=expires_at,
        kind=ProjectInvitationKind.TRUSTED,
        role=None,
        granted_permissions=["view_media"],
        trusted_duration_seconds=TRUSTED_MAX_DURATION_SECONDS + 3600,
    )
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationValidationError, match="FR-043 cap"):
        await accept_invitation(
            session,  # type: ignore[arg-type]
            signed_token=token,
            current_user_id=uuid4(),
            current_user_email=DEFAULT_EMAIL,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
        )


async def test_accept_invitation_new_member_integrity_error_on_flush_conflicts() -> None:
    """``session.flush()`` raising IntegrityError (lines 343-347) → 409."""
    expires_at = datetime.now(UTC) + timedelta(days=1)
    token = _sign(expires_at=expires_at)
    inv = _MockInvitationLegacy(expires_at=expires_at)
    session = _ScriptedSession(
        [_FakeScalarResult(inv), _NullResult()],
        raise_on_flush=IntegrityError("stmt", {}, Exception("dup")),
    )
    with pytest.raises(InvitationConflictError, match="concurrent grant"):
        await accept_invitation(
            session,  # type: ignore[arg-type]
            signed_token=token,
            current_user_id=uuid4(),
            current_user_email=DEFAULT_EMAIL,
            hmac_secret=HMAC_SECRET,
            redis=_FakeRedis(),  # type: ignore[arg-type]
        )


async def test_accept_invitation_new_member_success() -> None:
    """Baseline new-member happy path (already partially covered — kept as
    a stability anchor alongside the new branch tests above).
    """
    expires_at = datetime.now(UTC) + timedelta(days=1)
    token = _sign(expires_at=expires_at)
    inv = _MockInvitationLegacy(expires_at=expires_at)
    session = _ScriptedSession([_FakeScalarResult(inv), _NullResult()])

    outcome = await accept_invitation(
        session,  # type: ignore[arg-type]
        signed_token=token,
        current_user_id=uuid4(),
        current_user_email=DEFAULT_EMAIL,
        hmac_secret=HMAC_SECRET,
        redis=_FakeRedis(),  # type: ignore[arg-type]
    )

    assert outcome.member is not None
    assert outcome.member in session.added
    assert outcome.is_replay is False


# ===========================================================================
# public.py — accept_invitation_via_public_token() success-path branches
# ===========================================================================


def _make_public_token(*, expires_in: timedelta = timedelta(days=7)) -> str:
    raw = _b64u_encode(secrets.token_bytes(32))
    return sign_invitation_token(
        raw_token_b64u=raw,
        expires_at=datetime.now(UTC) + expires_in,
    )


class _MockInvitationPublic:
    """Duck-typed invitation stub for the public-token accept path.

    Unlike the legacy path, ``accept_invitation_via_public_token`` matches
    the caller's email via plain ``canonicalize_email`` comparison — no
    HMAC hash needed.
    """

    def __init__(
        self,
        *,
        email: str | None = DEFAULT_EMAIL,
        status: ProjectInvitationStatus = ProjectInvitationStatus.PENDING,
        expires_at: datetime | None = None,
        kind: ProjectInvitationKind = ProjectInvitationKind.MEMBER,
        role: ProjectMemberRole | None = ProjectMemberRole.MEMBER,
        ownership_transfer_on_accept: bool = False,
        granted_permissions: list[str] | None = None,
        trusted_duration_seconds: int | None = None,
        project_id: UUID | None = None,
        invited_by_id: UUID | None = None,
        id: UUID | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.project_id = project_id or uuid4()
        self.kind = kind
        self.status = status
        self.expires_at = expires_at or (datetime.now(UTC) + timedelta(days=7))
        self.email = email
        self.role = role
        self.ownership_transfer_on_accept = ownership_transfer_on_accept
        self.granted_permissions = granted_permissions
        self.trusted_duration_seconds = trusted_duration_seconds
        self.invited_by_id = invited_by_id or uuid4()
        self.email_hash: str | None = None
        self.accepted_at: datetime | None = None


async def test_resolve_authenticated_email_matches_true_branch() -> None:
    """Both emails present and matching (line 108) → matches=True."""
    from echoroo.services.invitation.public import resolve_invitation_for_public_token

    token = _make_public_token()
    inv = _MockInvitationPublic(email="Alice@Example.com")

    class _ProjectRow:
        def __getitem__(self, idx: int) -> Any:
            return "Test Project"

    session = _ScriptedSession(
        [_FakeScalarResult(inv), _FakeFirstResult(_ProjectRow())],
    )
    outcome = await resolve_invitation_for_public_token(
        session,  # type: ignore[arg-type]
        signed_token=token,
        authenticated_email="alice@example.com",
    )
    assert outcome.authenticated_email_matches is True


async def test_resolve_authenticated_email_matches_false_branch() -> None:
    """Both emails present but different (line 108) → matches=False."""
    from echoroo.services.invitation.public import resolve_invitation_for_public_token

    token = _make_public_token()
    inv = _MockInvitationPublic(email="bob@example.com")

    class _ProjectRow:
        def __getitem__(self, idx: int) -> Any:
            return "Test Project"

    session = _ScriptedSession(
        [_FakeScalarResult(inv), _FakeFirstResult(_ProjectRow())],
    )
    outcome = await resolve_invitation_for_public_token(
        session,  # type: ignore[arg-type]
        signed_token=token,
        authenticated_email="carol@example.com",
    )
    assert outcome.authenticated_email_matches is False


async def test_accept_public_token_new_member_success() -> None:
    """New-member grant application (Step 5, no ownership transfer)."""
    token = _make_public_token()
    inv = _MockInvitationPublic()
    session = _ScriptedSession(
        [
            _FakeScalarResult(inv),  # invitation SELECT
            _FakeFirstResult(("id",)),  # UPDATE ... RETURNING id
            _FakeScalarResult(None),  # existing ProjectMember SELECT → none
        ],
    )

    outcome = await accept_invitation_via_public_token(
        session,  # type: ignore[arg-type]
        signed_token=token,
        accepting_user_id=uuid4(),
        accepting_user_email=DEFAULT_EMAIL,
    )

    assert outcome.membership_created is True
    assert outcome.member is not None
    assert outcome.member in session.added
    assert outcome.audit_action == AUDIT_ACTION_MEMBER_INVITE_ACCEPTED
    assert outcome.ownership_transferred is False
    assert session.flush_calls == 1


async def test_accept_public_token_existing_lower_rank_member_upgraded() -> None:
    """Existing lower-rank member row is upgraded in place, not re-inserted."""
    token = _make_public_token()
    inv = _MockInvitationPublic(role=ProjectMemberRole.ADMIN)

    existing_member = MagicMock(spec=ProjectMember)
    existing_member.role = ProjectMemberRole.VIEWER
    existing_member.id = uuid4()

    session = _ScriptedSession(
        [
            _FakeScalarResult(inv),
            _FakeFirstResult(("id",)),
            _FakeScalarResult(existing_member),
        ],
    )

    outcome = await accept_invitation_via_public_token(
        session,  # type: ignore[arg-type]
        signed_token=token,
        accepting_user_id=uuid4(),
        accepting_user_email=DEFAULT_EMAIL,
    )

    assert outcome.member is existing_member
    assert existing_member.role == ProjectMemberRole.ADMIN
    assert outcome.membership_created is False
    assert existing_member not in session.added


async def test_accept_public_token_ownership_transfer_invalid_for_trusted_kind_raises() -> None:
    """Defence-in-depth: ``ownership_transfer_on_accept=True`` paired with
    a TRUSTED-kind row (should never happen given the DB CHECK) →
    InvitationStateError, before the atomic UPDATE runs.
    """
    token = _make_public_token()
    inv = _MockInvitationPublic(
        kind=ProjectInvitationKind.TRUSTED,
        role=None,
        ownership_transfer_on_accept=True,
    )
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(
        InvitationStateError, match="ownership_transfer_on_accept_invalid_for_kind"
    ):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email=DEFAULT_EMAIL,
        )


async def test_accept_public_token_trusted_duration_exceeds_cap_raises() -> None:
    """Trusted duration resolving past the FR-043 cap on the public-token
    path → InvitationValidationError.
    """
    token = _make_public_token()
    inv = _MockInvitationPublic(
        kind=ProjectInvitationKind.TRUSTED,
        role=None,
        granted_permissions=["view_media"],
        trusted_duration_seconds=TRUSTED_MAX_DURATION_SECONDS + 3600,
    )
    session = _ScriptedSession(
        [
            _FakeScalarResult(inv),
            _FakeFirstResult(("id",)),
        ],
    )
    with pytest.raises(InvitationValidationError, match="FR-043 cap"):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email=DEFAULT_EMAIL,
        )


async def test_accept_public_token_trusted_kind_success() -> None:
    """Trusted-kind grant application on the public-token path."""
    token = _make_public_token()
    inv = _MockInvitationPublic(
        kind=ProjectInvitationKind.TRUSTED,
        role=None,
        granted_permissions=["view_media"],
        trusted_duration_seconds=3600,
    )
    session = _ScriptedSession(
        [
            _FakeScalarResult(inv),
            _FakeFirstResult(("id",)),
        ],
    )

    outcome = await accept_invitation_via_public_token(
        session,  # type: ignore[arg-type]
        signed_token=token,
        accepting_user_id=uuid4(),
        accepting_user_email=DEFAULT_EMAIL,
    )

    assert outcome.trusted_user is not None
    assert outcome.trusted_user in session.added
    assert outcome.audit_action == AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED


async def test_accept_public_token_integrity_error_on_flush_conflicts() -> None:
    """Concurrent grant IntegrityError on flush() → InvitationConflictError."""
    token = _make_public_token()
    inv = _MockInvitationPublic()
    session = _ScriptedSession(
        [
            _FakeScalarResult(inv),
            _FakeFirstResult(("id",)),
            _FakeScalarResult(None),
        ],
        raise_on_flush=IntegrityError("stmt", {}, Exception("dup")),
    )
    with pytest.raises(InvitationConflictError, match="concurrent grant"):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email=DEFAULT_EMAIL,
        )


async def test_accept_public_token_ownership_transfer_project_missing_raises() -> None:
    """Ownership-transfer SAVEPOINT with the target project vanished →
    InvitationStateError (an unreachable-in-production defence-in-depth
    branch we still pin at the unit level).
    """
    token = _make_public_token()
    inv = _MockInvitationPublic(ownership_transfer_on_accept=True)
    session = _ScriptedSession(
        [
            _FakeScalarResult(inv),  # invitation SELECT
            _FakeFirstResult(("id",)),  # UPDATE ... RETURNING id
            _FakeScalarResult(None),  # existing ProjectMember SELECT → none
            _FakeFirstResult(None),  # project_row SELECT ... FOR UPDATE → none
        ],
    )
    with pytest.raises(InvitationStateError, match="ownership_transfer_target_project_missing"):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email=DEFAULT_EMAIL,
        )
    # The pre-savepoint flush already happened before the failure.
    assert session.flush_calls == 1


async def test_accept_public_token_ownership_transfer_success_new_prior_owner_member() -> None:
    """Full FR-011-123 SAVEPOINT transfer — prior owner gets a brand-new
    ProjectMember(role=ADMIN) row (no pre-existing active row).
    """
    prior_owner_id = uuid4()
    accepting_user_id = uuid4()
    project_created_at = datetime.now(UTC) - timedelta(days=30)

    token = _make_public_token()
    inv = _MockInvitationPublic(ownership_transfer_on_accept=True)

    session = _ScriptedSession(
        [
            _FakeScalarResult(inv),  # invitation SELECT
            _FakeFirstResult(("id",)),  # UPDATE ... RETURNING id
            _FakeScalarResult(None),  # existing ProjectMember SELECT → none (new member)
            _FakeFirstResult((prior_owner_id, project_created_at)),  # project_row FOR UPDATE
            _FakeScalarResult(None),  # UPDATE(Project) — result unused
            _FakeScalarResult(None),  # existing_prior_owner_member SELECT → none (insert)
        ],
    )

    async def _fake_summary(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"summary": []}

    with patch(
        "echoroo.services.invitation.public.build_pre_transfer_action_summary",
        side_effect=_fake_summary,
    ):
        outcome = await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=accepting_user_id,
            accepting_user_email=DEFAULT_EMAIL,
        )

    assert outcome.ownership_transferred is True
    assert outcome.prior_owner_id == prior_owner_id
    assert outcome.ownership_transfer_detail is not None
    assert outcome.ownership_transfer_detail["prior_owner"] == str(prior_owner_id)
    assert outcome.ownership_transfer_detail["new_owner"] == str(accepting_user_id)
    # A fresh ProjectMember(role=ADMIN) row was added for the prior owner
    # in addition to the accepting user's own new membership row.
    admin_rows = [
        obj
        for obj in session.added
        if isinstance(obj, ProjectMember) and obj.role == ProjectMemberRole.ADMIN
    ]
    assert len(admin_rows) == 1
    assert admin_rows[0].user_id == prior_owner_id
    # Savepoint flush happens in addition to the pre-savepoint flush.
    assert session.flush_calls == 2


async def test_accept_public_token_ownership_transfer_success_existing_prior_owner_member() -> None:
    """FR-011-123 SAVEPOINT transfer when the prior owner already has a
    (non-active-role) ProjectMember row — updated in place to ADMIN
    instead of inserted.
    """
    prior_owner_id = uuid4()
    project_created_at = datetime.now(UTC) - timedelta(days=30)

    token = _make_public_token()
    inv = _MockInvitationPublic(ownership_transfer_on_accept=True)

    existing_prior_owner_member = MagicMock(spec=ProjectMember)
    existing_prior_owner_member.role = ProjectMemberRole.VIEWER

    session = _ScriptedSession(
        [
            _FakeScalarResult(inv),
            _FakeFirstResult(("id",)),
            _FakeScalarResult(None),
            _FakeFirstResult((prior_owner_id, project_created_at)),
            _FakeScalarResult(None),
            _FakeScalarResult(existing_prior_owner_member),
        ],
    )

    async def _fake_summary(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"summary": []}

    with patch(
        "echoroo.services.invitation.public.build_pre_transfer_action_summary",
        side_effect=_fake_summary,
    ):
        outcome = await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email=DEFAULT_EMAIL,
        )

    assert outcome.ownership_transferred is True
    assert existing_prior_owner_member.role == ProjectMemberRole.ADMIN
    assert existing_prior_owner_member not in session.added
