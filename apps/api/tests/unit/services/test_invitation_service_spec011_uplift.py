"""spec/011 Step 7c coverage uplift — public-token paths in
``echoroo.services.invitation_service``.

spec/011 Step 7 PR #100 added ``resolve_invitation_for_public_token`` and
``accept_invitation_via_public_token``. Happy paths are covered by
``tests/integration/test_member_invitation_flow.py`` (13 integration cases).
This suite fills the unit-coverage gap by exercising the rare error branches
that are unreachable from the integration tests without session-level
control:

* ``resolve_invitation_for_public_token``:
  - invitation not found → InvitationTokenInvalidError
  - invitation not pending → InvitationTokenInvalidError
  - invitation expired → InvitationTokenInvalidError
  - target project missing → InvitationTokenInvalidError
  - authenticated_email present but invitation.email is None → matches=None fallback

* ``accept_invitation_via_public_token``:
  - invitation not found (token miss) → InvitationTokenInvalidError
  - project_id_scope mismatch → InvitationTokenInvalidError
  - invitation not pending → InvitationTokenInvalidError
  - invitation expired → InvitationTokenInvalidError
  - email mismatch (invitation.email is None) → InvitationEmailMismatchError
  - email mismatch (canonicalize mismatch) → InvitationEmailMismatchError
  - atomic UPDATE returns zero rows → InvitationTokenInvalidError
  - InvitationAlreadyMemberError when existing member at same role

* ``emit_public_invitation_accept_audit``:
  - ownership_transferred=True path (second audit row)
  - ownership_transferred=False / no prior_owner_id path (single audit row)

Pure unit tests; AsyncSession is replaced by in-process stubs.
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

from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
)
from echoroo.services import invitation_service as svc
from echoroo.services.invitation_service import (
    InvitationAlreadyMemberError,
    InvitationEmailMismatchError,
    InvitationPublicAcceptOutcome,
    InvitationTokenInvalidError,
    accept_invitation_via_public_token,
    emit_public_invitation_accept_audit,
    resolve_invitation_for_public_token,
    sign_invitation_token,
)

HMAC_SECRET = "step7c-spec011-uplift-hmac-secret-32!"

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


def _make_token(
    *,
    expires_in: timedelta = timedelta(days=7),
    now: datetime | None = None,
) -> str:
    """Return a valid signed invitation token for unit testing."""
    from echoroo.services.invitation_service import _b64u_encode

    tick = now or datetime.now(UTC)
    raw = _b64u_encode(secrets.token_bytes(32))
    expires_at = tick + expires_in
    return sign_invitation_token(
        raw_token_b64u=raw,
        expires_at=expires_at,
        hmac_secret=HMAC_SECRET,
    )


class _FakeFirstResult:
    """Wraps a single row for .first() calls."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row

    def scalar_one_or_none(self) -> Any:
        return self._row

    def fetchone(self) -> Any:
        return self._row


class _FakeScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def first(self) -> Any:
        return self._value

    def fetchone(self) -> Any:
        return self._value


class _MockInvitation:
    """Minimal invitation stub."""

    def __init__(
        self,
        *,
        token_hash: str = "hash",
        project_id: UUID | None = None,
        status: ProjectInvitationStatus = ProjectInvitationStatus.PENDING,
        expires_at: datetime | None = None,
        email: str | None = "invited@example.com",
        kind: ProjectInvitationKind = ProjectInvitationKind.MEMBER,
        role: ProjectMemberRole | None = ProjectMemberRole.MEMBER,
        ownership_transfer_on_accept: bool = False,
        granted_permissions: list[str] | None = None,
        trusted_duration_seconds: int | None = None,
        id: UUID | None = None,
        invited_by_id: UUID | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.token_hash = token_hash
        self.project_id = project_id or uuid4()
        self.status = status
        self.expires_at = expires_at or datetime.now(UTC) + timedelta(days=7)
        self.email = email
        self.kind = kind
        self.role = role
        self.ownership_transfer_on_accept = ownership_transfer_on_accept
        self.granted_permissions = granted_permissions
        self.trusted_duration_seconds = trusted_duration_seconds
        self.invited_by_id = invited_by_id or uuid4()
        self.email_hash: str | None = None
        self.accepted_at: datetime | None = None


class _ScriptedSession:
    """Returns canned results for consecutive session.execute() calls."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.added: list[Any] = []
        self.flush_calls: int = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    async def flush(self) -> None:
        self.flush_calls += 1

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        if not self._responses:
            raise AssertionError("_ScriptedSession: unexpected execute() call")
        return self._responses.pop(0)

    @asynccontextmanager
    async def begin_nested(self) -> AsyncGenerator[None, None]:
        yield


# ---------------------------------------------------------------------------
# resolve_invitation_for_public_token — unit error branches
# ---------------------------------------------------------------------------


async def test_resolve_invitation_not_found_raises() -> None:
    """Missing invitation row → InvitationTokenInvalidError."""
    token = _make_token()
    session = _ScriptedSession([_FakeScalarResult(None)])
    with pytest.raises(InvitationTokenInvalidError, match="not found"):
        await resolve_invitation_for_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            authenticated_email=None,
        )


async def test_resolve_invitation_not_pending_raises() -> None:
    """Terminal-status row → InvitationTokenInvalidError."""
    token = _make_token()
    inv = _MockInvitation(status=ProjectInvitationStatus.ACCEPTED)
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationTokenInvalidError, match="not pending"):
        await resolve_invitation_for_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            authenticated_email=None,
        )


async def test_resolve_invitation_expired_raises() -> None:
    """Expired invitation → InvitationTokenInvalidError.

    We sign a valid token (passes verify), but the invitation row's
    expires_at is in the past, so the DB-row expiry check fires.
    """
    past = datetime.now(UTC) - timedelta(hours=1)
    token = _make_token()  # token itself is valid (future expiry)
    inv = _MockInvitation(expires_at=past)  # but DB row is expired
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationTokenInvalidError, match="expired"):
        await resolve_invitation_for_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            authenticated_email=None,
        )


async def test_resolve_invitation_project_missing_raises() -> None:
    """Missing target project → InvitationTokenInvalidError."""
    token = _make_token()
    inv = _MockInvitation()
    # First execute → invitation row found; second execute → project query returns None
    session = _ScriptedSession([
        _FakeScalarResult(inv),
        _FakeFirstResult(None),  # project lookup
    ])
    with pytest.raises(InvitationTokenInvalidError, match="project missing"):
        await resolve_invitation_for_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            authenticated_email=None,
        )


async def test_resolve_invitation_authenticated_email_none_invitation_email_none() -> None:
    """When invitation.email is None and caller is logged in, matches=None."""
    token = _make_token()
    inv = _MockInvitation(email=None)

    class _ProjectRow:
        def __getitem__(self, idx: int) -> Any:
            return "Test Project"

    session = _ScriptedSession([
        _FakeScalarResult(inv),
        _FakeFirstResult(_ProjectRow()),
    ])
    outcome = await resolve_invitation_for_public_token(
        session,  # type: ignore[arg-type]
        signed_token=token,
        authenticated_email="caller@example.com",
    )
    # email is None on invitation → matches is False (logged in but no bound email)
    assert outcome.is_logged_in is True
    assert outcome.authenticated_email_matches is False


async def test_resolve_invitation_not_logged_in_returns_none_matches() -> None:
    """When caller is not logged in, authenticated_email_matches is None."""
    token = _make_token()
    inv = _MockInvitation()

    class _ProjectRow:
        def __getitem__(self, idx: int) -> Any:
            return "Test Project"

    session = _ScriptedSession([
        _FakeScalarResult(inv),
        _FakeFirstResult(_ProjectRow()),
    ])
    outcome = await resolve_invitation_for_public_token(
        session,  # type: ignore[arg-type]
        signed_token=token,
        authenticated_email=None,
    )
    assert outcome.is_logged_in is False
    assert outcome.authenticated_email_matches is None


# ---------------------------------------------------------------------------
# accept_invitation_via_public_token — unit error branches
# ---------------------------------------------------------------------------


async def test_accept_public_token_not_found_raises() -> None:
    """Missing row → InvitationTokenInvalidError."""
    token = _make_token()
    session = _ScriptedSession([_FakeScalarResult(None)])
    with pytest.raises(InvitationTokenInvalidError, match="not found"):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email="invited@example.com",
        )


async def test_accept_public_token_project_scope_mismatch_raises() -> None:
    """project_id_scope mismatch → InvitationTokenInvalidError."""
    token = _make_token()
    inv = _MockInvitation(project_id=uuid4())
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationTokenInvalidError, match="not found"):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email="invited@example.com",
            project_id_scope=uuid4(),  # different project
        )


async def test_accept_public_token_not_pending_raises() -> None:
    """Terminal-status row → InvitationTokenInvalidError."""
    token = _make_token()
    inv = _MockInvitation(status=ProjectInvitationStatus.DECLINED)
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationTokenInvalidError, match="not pending"):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email="invited@example.com",
        )


async def test_accept_public_token_expired_raises() -> None:
    """Expired row → InvitationTokenInvalidError."""
    token = _make_token()
    inv = _MockInvitation(expires_at=datetime.now(UTC) - timedelta(hours=1))
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationTokenInvalidError, match="expired"):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email="invited@example.com",
        )


async def test_accept_public_token_email_none_raises() -> None:
    """invitation.email is None → InvitationEmailMismatchError."""
    token = _make_token()
    inv = _MockInvitation(email=None)
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationEmailMismatchError, match="missing bound email"):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email="invited@example.com",
        )


async def test_accept_public_token_email_mismatch_raises() -> None:
    """Caller email canonically differs from bound email → InvitationEmailMismatchError."""
    token = _make_token()
    inv = _MockInvitation(email="invited@example.com")
    session = _ScriptedSession([_FakeScalarResult(inv)])
    with pytest.raises(InvitationEmailMismatchError):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email="different@example.com",  # mismatch
        )


async def test_accept_public_token_atomic_update_zero_rows_raises() -> None:
    """Concurrent accept loses race (UPDATE returns 0 rows) → InvitationTokenInvalidError."""
    token = _make_token()
    inv = _MockInvitation(email="invited@example.com")
    # First execute: invitation SELECT; second execute: UPDATE RETURNING → 0 rows
    session = _ScriptedSession([
        _FakeScalarResult(inv),
        _FakeFirstResult(None),  # UPDATE RETURNING returns None (zero rows)
    ])
    with pytest.raises(InvitationTokenInvalidError, match="not found"):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email="invited@example.com",
        )


async def test_accept_public_token_already_member_at_same_role_raises() -> None:
    """Existing member at same role → InvitationAlreadyMemberError."""
    from echoroo.models.project import ProjectMember

    token = _make_token()
    inv = _MockInvitation(email="invited@example.com", role=ProjectMemberRole.MEMBER)

    existing_member = MagicMock(spec=ProjectMember)
    existing_member.role = ProjectMemberRole.MEMBER
    existing_member.id = uuid4()

    # Scripted: invitation SELECT → inv; UPDATE RETURNING → row; member SELECT → existing
    session = _ScriptedSession([
        _FakeScalarResult(inv),
        _FakeFirstResult(("placeholder_row",)),  # UPDATE RETURNING → row present
        _FakeScalarResult(existing_member),         # existing member lookup
    ])

    with pytest.raises(InvitationAlreadyMemberError):
        await accept_invitation_via_public_token(
            session,  # type: ignore[arg-type]
            signed_token=token,
            accepting_user_id=uuid4(),
            accepting_user_email="invited@example.com",
        )


# ---------------------------------------------------------------------------
# emit_public_invitation_accept_audit — unit coverage
# ---------------------------------------------------------------------------


async def test_emit_public_invitation_accept_audit_no_ownership_transfer() -> None:
    """Single audit row emitted when ownership_transferred=False."""
    inv = _MockInvitation()
    inv.status = ProjectInvitationStatus.ACCEPTED

    outcome = InvitationPublicAcceptOutcome(
        invitation=inv,  # type: ignore[arg-type]
        accepting_user_id=uuid4(),
        member=None,
        trusted_user=None,
        membership_created=True,
        audit_action=svc.AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
        ownership_transferred=False,
        ownership_transfer_detail=None,
        prior_owner_id=None,
        request_id="req-1",
        ip="1.2.3.4",
        user_agent="pytest",
    )

    write_calls: list[Any] = []

    async def _fake_write(**kwargs: Any) -> None:
        write_calls.append(kwargs)

    with patch(
        "echoroo.services.invitation.side_effects._write_invitation_audit",
        side_effect=_fake_write,
    ):
        await emit_public_invitation_accept_audit(outcome)

    assert len(write_calls) == 1
    assert write_calls[0]["action"] == svc.AUDIT_ACTION_MEMBER_INVITE_ACCEPTED


async def test_emit_public_invitation_accept_audit_with_ownership_transfer() -> None:
    """Two audit rows emitted when ownership_transferred=True."""
    inv = _MockInvitation()
    inv.status = ProjectInvitationStatus.ACCEPTED
    prior_owner = uuid4()
    accepting_user = uuid4()

    from echoroo.models.project import ProjectMember

    mock_member = MagicMock(spec=ProjectMember)
    mock_member.id = uuid4()

    outcome = InvitationPublicAcceptOutcome(
        invitation=inv,  # type: ignore[arg-type]
        accepting_user_id=accepting_user,
        member=mock_member,
        trusted_user=None,
        membership_created=True,
        audit_action=svc.AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
        ownership_transferred=True,
        ownership_transfer_detail={"pre_transfer_summary": []},
        prior_owner_id=prior_owner,
        request_id="req-2",
        ip="1.2.3.4",
        user_agent="pytest",
    )

    write_calls: list[Any] = []

    async def _fake_write(**kwargs: Any) -> None:
        write_calls.append(kwargs)

    with patch(
        "echoroo.services.invitation.side_effects._write_invitation_audit",
        side_effect=_fake_write,
    ):
        await emit_public_invitation_accept_audit(outcome)

    assert len(write_calls) == 2
    actions = {c["action"] for c in write_calls}
    assert svc.AUDIT_ACTION_MEMBER_INVITE_ACCEPTED in actions
    assert svc.AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER in actions
