"""Phase 17 §C PR-D coverage uplift — ``echoroo.services.invitation_service``.

The existing ``test_invitation_service.py`` suite covers the four
Round 2 致命 fixes (FR-051 plain-text envelope, FR-056 fail-closed
Redis, FR-052 7-day TTL cap, FR-053 idempotency-key conflict). This
uplift fills the residual defensive branches:

* Token + base64 helpers — :func:`_b64u_decode` re-padding,
  :func:`verify_invitation_token` malformed parts / bad expiry / bad
  MAC / expired / valid round-trip.
* :func:`_email_matches_invitation` KMS-fail fallback to legacy hash
  match (drives the Round 2 R1-I3 OR-combine).
* :func:`coerce_granted_permissions` — empty input + unknown name +
  not-in-allowlist + Permission instance pass-through.
* :func:`check_rate_limits` — project-key Redis fault → fail-closed,
  project-cap exceeded → :class:`InvitationRateLimitError`.
* :func:`create_invitation` — kind/payload validation matrix:
  member-without-role, member-with-trusted-fields, trusted-with-role,
  trusted-without-permissions, trusted-with-bad-duration.
* :func:`_get_idempotent_outcome` — invalid JSON in cache returns
  ``None`` (line 831-832).
* :func:`accept_invitation` — invitation not found path.
* :func:`decline_invitation_by_recipient` — replay (already declined)
  + state-error (terminal accepted state).
* Post-commit side effects — ``_write_invitation_audit`` outer +
  inner failure, ``_enqueue_invitation_email`` outbox failure.

Pure unit tests; the AsyncSession is replaced by an in-process stub.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from echoroo.core.permissions import Permission
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
)
from echoroo.services import invitation_service as svc
from echoroo.services.invitation_service import (
    RATE_LIMIT_PROJECT_PER_HOUR,
    InvitationAcceptOutcome,
    InvitationCreateOutcome,
    InvitationDeclineOutcome,
    InvitationInfraUnavailableError,
    InvitationRateLimitError,
    InvitationStateError,
    InvitationTokenInvalidError,
    InvitationValidationError,
    _b64u_decode,
    _b64u_encode,
    _email_matches_invitation,
    _get_idempotent_outcome,
    _write_invitation_audit,
    accept_invitation,
    check_rate_limits,
    coerce_granted_permissions,
    create_invitation,
    decline_invitation_by_recipient,
    sign_invitation_token,
    trigger_post_commit_side_effects,
    verify_invitation_token,
)

HMAC_SECRET = "phase17-prd-coverage-uplift-secret-32!"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.fail_on_incr_actor: bool = False
        self.fail_on_incr_project: bool = False
        self.actor_initial: int = 0
        self.project_initial: int = 0

    async def incr(self, name: str) -> int:
        if "actor:" in name and self.fail_on_incr_actor:
            raise ConnectionError("redis actor incr down")
        if "project:" in name and self.fail_on_incr_project:
            raise ConnectionError("redis project incr down")
        if name not in self.values:
            base = (
                self.project_initial if "project:" in name else self.actor_initial
            )
            self.values[name] = base
        self.values[name] = int(self.values[name]) + 1
        return int(self.values[name])

    async def expire(self, name: str, time: int) -> bool:
        del time
        return name in self.values

    async def get(self, name: str) -> Any:
        return self.values.get(name)


class _FakeSession:
    """Capturing AsyncSession stub."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_calls: int = 0
        self.execute_responses: list[Any] = []
        self.execute_calls: int = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    async def flush(self) -> None:
        self.flush_calls += 1

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        self.execute_calls += 1
        if self.execute_responses:
            return self.execute_responses.pop(0)
        # Default — empty result.
        return _FakeResult(scalar_value=None)


class _FakeResult:
    def __init__(
        self,
        *,
        scalar_value: Any = None,
    ) -> None:
        self._scalar = scalar_value

    def scalar_one_or_none(self) -> Any:
        return self._scalar


# ---------------------------------------------------------------------------
# _b64u_decode — padding tolerance (line 307-308)
# ---------------------------------------------------------------------------


def test_b64u_decode_repads_unpadded_input() -> None:
    """Round-trip an unpadded base64url value through encode + decode."""
    raw = b"\x00\x01\x02\x03\x04"
    encoded = _b64u_encode(raw)
    # The encoder strips ``=`` padding; the decoder must re-pad.
    assert "=" not in encoded
    assert _b64u_decode(encoded) == raw


# ---------------------------------------------------------------------------
# verify_invitation_token — malformed / expired / valid (lines 480-481, 489)
# ---------------------------------------------------------------------------


def test_verify_invitation_token_rejects_wrong_part_count() -> None:
    with pytest.raises(InvitationTokenInvalidError, match="malformed"):
        verify_invitation_token("only.two", hmac_secret=HMAC_SECRET)


def test_verify_invitation_token_rejects_non_integer_expiry() -> None:
    # spec/011 Step 6 (T050/T051): the verifier now treats 3-part inputs
    # as legacy envelopes (NFR-011-010 path (b)). To exercise the
    # ``invalid expiry`` branch we use the 4-part shape with a bad
    # expiry token; the kid slot is irrelevant since the integer parse
    # happens before the kid lookup.
    with pytest.raises(InvitationTokenInvalidError, match="invalid expiry"):
        verify_invitation_token("rawtoken.notanint.kid.macblob")


def test_verify_invitation_token_rejects_bad_signature() -> None:
    """A correctly-shaped token with a forged MAC must fail."""
    raw = _b64u_encode(b"\x42" * 32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    valid = sign_invitation_token(
        raw_token_b64u=raw, expires_at=expires_at,
    )
    parts = valid.split(".")
    # spec/011 step 6: 4-part envelope — swap the last (MAC) component.
    forged = ".".join([parts[0], parts[1], parts[2], "AAAAAAAA"])
    with pytest.raises(InvitationTokenInvalidError, match="signature"):
        verify_invitation_token(forged)


def test_verify_invitation_token_round_trip_succeeds() -> None:
    raw = _b64u_encode(b"\x01" * 32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw, expires_at=expires_at, hmac_secret=HMAC_SECRET
    )
    decoded_raw, decoded_expiry = verify_invitation_token(
        signed, hmac_secret=HMAC_SECRET
    )
    assert decoded_raw == raw
    # Round-trip drops sub-second precision (expires_at_unix is int).
    assert int(decoded_expiry.timestamp()) == int(expires_at.timestamp())


# ---------------------------------------------------------------------------
# _email_matches_invitation — KMS path fallback (lines 382-389)
# ---------------------------------------------------------------------------


def test_email_matches_invitation_falls_back_to_legacy_when_kms_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``verify_pii_hash`` raises, the legacy HMAC compare still wins."""
    email = "alice@example.com"

    class _Invitation:
        # email_hash_v2 must be truthy to exercise the KMS branch.
        email_hash_v2 = "kms-v2-hash-deadbeef"
        email_hash = svc.hash_email(email, hmac_secret=HMAC_SECRET)

    def _boom(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("KMS unavailable")

    monkeypatch.setattr("echoroo.core.kms.verify_pii_hash", _boom)

    assert _email_matches_invitation(
        email, _Invitation(), hmac_secret=HMAC_SECRET  # type: ignore[arg-type]
    ) is True


def test_email_matches_invitation_returns_false_when_neither_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither KMS nor legacy match → ``False`` (the deny branch)."""

    class _Invitation:
        email_hash_v2 = None
        email_hash = "0" * 64  # nothing matches

    assert _email_matches_invitation(
        "alice@example.com", _Invitation(), hmac_secret=HMAC_SECRET  # type: ignore[arg-type]
    ) is False


# ---------------------------------------------------------------------------
# coerce_granted_permissions (lines 519, 533)
# ---------------------------------------------------------------------------


def test_coerce_granted_permissions_accepts_permission_instance() -> None:
    """A Permission instance passes straight through (line 519 branch)."""
    out = coerce_granted_permissions([Permission.VIEW_DETECTION])
    assert Permission.VIEW_DETECTION in out


def test_coerce_granted_permissions_rejects_unknown_name() -> None:
    with pytest.raises(InvitationValidationError, match="unknown permission"):
        coerce_granted_permissions(["this:is:not:a:permission"])


def test_coerce_granted_permissions_rejects_non_trusted_permission() -> None:
    """A real permission name that is not in TRUSTED_ALLOWED_PERMISSIONS."""
    # Pick a Permission that exists but is NOT in the allowlist; we
    # filter by exclusion to remain robust to allowlist edits.
    forbidden = [
        p for p in Permission if p not in svc.TRUSTED_ALLOWED_PERMISSIONS
    ]
    if not forbidden:
        pytest.skip("every Permission is currently allowlisted for Trusted")
    with pytest.raises(InvitationValidationError, match="not in TRUSTED_ALLOWED"):
        coerce_granted_permissions([forbidden[0]])


def test_coerce_granted_permissions_rejects_empty_input() -> None:
    """Empty post-validation set → ``granted_permissions must be non-empty``."""
    with pytest.raises(InvitationValidationError, match="non-empty"):
        coerce_granted_permissions([])


# ---------------------------------------------------------------------------
# check_rate_limits — project-key path (lines 581-589)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_rate_limits_fails_closed_when_project_incr_raises() -> None:
    redis = _FakeRedis()
    redis.fail_on_incr_project = True
    with pytest.raises(InvitationInfraUnavailableError):
        await check_rate_limits(
            redis,  # type: ignore[arg-type]
            actor_user_id=uuid4(),
            project_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_check_rate_limits_raises_when_project_cap_exceeded() -> None:
    redis = _FakeRedis()
    project_id = uuid4()
    # Pre-load so the project counter passes its cap on first incr.
    redis.values[f"invitation_rate:project:{project_id}"] = (
        RATE_LIMIT_PROJECT_PER_HOUR
    )
    with pytest.raises(InvitationRateLimitError, match="project"):
        await check_rate_limits(
            redis,  # type: ignore[arg-type]
            actor_user_id=uuid4(),
            project_id=project_id,
        )


# ---------------------------------------------------------------------------
# create_invitation — kind/payload validation matrix (lines 682-709)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invitation_member_requires_role() -> None:
    redis = _FakeRedis()
    session = _FakeSession()
    with pytest.raises(InvitationValidationError, match="role is required"):
        await create_invitation(
            session,  # type: ignore[arg-type]
            project_id=uuid4(),
            kind=ProjectInvitationKind.MEMBER,
            email="alice@example.com",
            invited_by_id=uuid4(),
            hmac_secret=HMAC_SECRET,
            redis=redis,  # type: ignore[arg-type]
            role=None,
        )


@pytest.mark.asyncio
async def test_create_invitation_member_rejects_trusted_fields() -> None:
    redis = _FakeRedis()
    session = _FakeSession()
    with pytest.raises(InvitationValidationError, match="must be NULL"):
        await create_invitation(
            session,  # type: ignore[arg-type]
            project_id=uuid4(),
            kind=ProjectInvitationKind.MEMBER,
            email="alice@example.com",
            invited_by_id=uuid4(),
            hmac_secret=HMAC_SECRET,
            redis=redis,  # type: ignore[arg-type]
            role=ProjectMemberRole.MEMBER,
            granted_permissions=["api:project:detection:view"],
        )


@pytest.mark.asyncio
async def test_create_invitation_trusted_rejects_role() -> None:
    redis = _FakeRedis()
    session = _FakeSession()
    with pytest.raises(InvitationValidationError, match="role must be NULL"):
        await create_invitation(
            session,  # type: ignore[arg-type]
            project_id=uuid4(),
            kind=ProjectInvitationKind.TRUSTED,
            email="alice@example.com",
            invited_by_id=uuid4(),
            hmac_secret=HMAC_SECRET,
            redis=redis,  # type: ignore[arg-type]
            role=ProjectMemberRole.MEMBER,
        )


@pytest.mark.asyncio
async def test_create_invitation_trusted_requires_granted_permissions() -> None:
    redis = _FakeRedis()
    session = _FakeSession()
    with pytest.raises(InvitationValidationError, match="granted_permissions is required"):
        await create_invitation(
            session,  # type: ignore[arg-type]
            project_id=uuid4(),
            kind=ProjectInvitationKind.TRUSTED,
            email="alice@example.com",
            invited_by_id=uuid4(),
            hmac_secret=HMAC_SECRET,
            redis=redis,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_create_invitation_trusted_rejects_bad_duration() -> None:
    redis = _FakeRedis()
    session = _FakeSession()
    with pytest.raises(InvitationValidationError, match="trusted_duration_seconds"):
        await create_invitation(
            session,  # type: ignore[arg-type]
            project_id=uuid4(),
            kind=ProjectInvitationKind.TRUSTED,
            email="alice@example.com",
            invited_by_id=uuid4(),
            hmac_secret=HMAC_SECRET,
            redis=redis,  # type: ignore[arg-type]
            granted_permissions=[Permission.VIEW_DETECTION],
            # 100 years — well past the FR-043 cap.
            trusted_duration_seconds=100 * 365 * 24 * 3600,
        )


# ---------------------------------------------------------------------------
# _get_idempotent_outcome — invalid JSON returns None (line 831-832)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_idempotent_outcome_returns_none_for_invalid_json() -> None:
    redis = _FakeRedis()
    redis.values[svc._idempotency_redis_key("k1")] = "not json {"
    out = await _get_idempotent_outcome(redis, "k1")  # type: ignore[arg-type]
    assert out is None


# ---------------------------------------------------------------------------
# accept_invitation — invitation not found (line 977)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_invitation_raises_when_token_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token verifies but no row matches the hash → ``InvitationTokenInvalidError``."""
    raw = _b64u_encode(b"\x07" * 32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw, expires_at=expires_at, hmac_secret=HMAC_SECRET
    )

    redis = _FakeRedis()
    session = _FakeSession()
    # The first execute (SELECT FOR UPDATE) returns no row.
    session.execute_responses = [_FakeResult(scalar_value=None)]

    with pytest.raises(InvitationTokenInvalidError, match="not found"):
        await accept_invitation(
            session,  # type: ignore[arg-type]
            signed_token=signed,
            current_user_id=uuid4(),
            current_user_email="alice@example.com",
            hmac_secret=HMAC_SECRET,
            redis=redis,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# decline_invitation_by_recipient — replay + terminal-state paths
# (lines 1222, 1227, 1240-1247, 1249)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_returns_replay_outcome_when_already_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second decline of the same row returns ``is_replay=True``."""
    raw = _b64u_encode(b"\x09" * 32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw, expires_at=expires_at, hmac_secret=HMAC_SECRET
    )

    inv_id_local = uuid4()
    project_id_local = uuid4()

    class _Invitation:
        id = inv_id_local
        token_hash = svc.hash_token(raw)
        project_id = project_id_local
        status = ProjectInvitationStatus.DECLINED
        kind = ProjectInvitationKind.MEMBER
        email_hash_v2 = None
        email_hash = svc.hash_email("alice@example.com", hmac_secret=HMAC_SECRET)
        declined_at: Any = None

    session = _FakeSession()
    session.execute_responses = [_FakeResult(scalar_value=_Invitation())]

    out = await decline_invitation_by_recipient(
        session,  # type: ignore[arg-type]
        signed_token=signed,
        current_user_id=uuid4(),
        current_user_email="alice@example.com",
        hmac_secret=HMAC_SECRET,
    )
    assert isinstance(out, InvitationDeclineOutcome)
    assert out.is_replay is True


@pytest.mark.asyncio
async def test_decline_raises_state_error_for_terminal_accepted_state() -> None:
    """An accepted invitation cannot be declined → :class:`InvitationStateError`."""
    raw = _b64u_encode(b"\x0a" * 32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw, expires_at=expires_at, hmac_secret=HMAC_SECRET
    )

    class _Invitation:
        id = uuid4()
        token_hash = svc.hash_token(raw)
        project_id = uuid4()
        status = ProjectInvitationStatus.ACCEPTED
        kind = ProjectInvitationKind.MEMBER
        email_hash_v2 = None
        email_hash = svc.hash_email("alice@example.com", hmac_secret=HMAC_SECRET)

    session = _FakeSession()
    session.execute_responses = [_FakeResult(scalar_value=_Invitation())]

    with pytest.raises(InvitationStateError, match="terminal state"):
        await decline_invitation_by_recipient(
            session,  # type: ignore[arg-type]
            signed_token=signed,
            current_user_id=uuid4(),
            current_user_email="alice@example.com",
            hmac_secret=HMAC_SECRET,
        )


@pytest.mark.asyncio
async def test_decline_raises_token_invalid_for_unknown_row() -> None:
    raw = _b64u_encode(b"\x0b" * 32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw, expires_at=expires_at, hmac_secret=HMAC_SECRET
    )

    session = _FakeSession()
    session.execute_responses = [_FakeResult(scalar_value=None)]

    with pytest.raises(InvitationTokenInvalidError, match="not found"):
        await decline_invitation_by_recipient(
            session,  # type: ignore[arg-type]
            signed_token=signed,
            current_user_id=uuid4(),
            current_user_email="alice@example.com",
            hmac_secret=HMAC_SECRET,
        )


@pytest.mark.asyncio
async def test_decline_raises_token_invalid_for_project_id_mismatch() -> None:
    """``project_id_scope`` mismatch collapses into the generic 404."""
    raw = _b64u_encode(b"\x0c" * 32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw, expires_at=expires_at, hmac_secret=HMAC_SECRET
    )

    real_project = uuid4()
    different = uuid4()
    assert real_project != different

    class _Invitation:
        id = uuid4()
        token_hash = svc.hash_token(raw)
        project_id = real_project
        status = ProjectInvitationStatus.PENDING
        kind = ProjectInvitationKind.MEMBER
        email_hash_v2 = None
        email_hash = svc.hash_email("alice@example.com", hmac_secret=HMAC_SECRET)

    session = _FakeSession()
    session.execute_responses = [_FakeResult(scalar_value=_Invitation())]

    with pytest.raises(InvitationTokenInvalidError, match="not found"):
        await decline_invitation_by_recipient(
            session,  # type: ignore[arg-type]
            signed_token=signed,
            current_user_id=uuid4(),
            current_user_email="alice@example.com",
            hmac_secret=HMAC_SECRET,
            project_id_scope=different,
        )


# ---------------------------------------------------------------------------
# Post-commit side effects — soft-alert paths
# ---------------------------------------------------------------------------


class _FailingSessionFactory:
    """Stand-in for ``AsyncSessionLocal`` whose context entry raises.

    Production code does ``async with AsyncSessionLocal() as session:``;
    the factory call returns an async context manager whose ``__aenter__``
    raises here, exercising the outer ``except Exception`` soft-alert
    branch in ``_write_invitation_audit`` / ``_enqueue_invitation_email``.
    """

    def __init__(self, error: Exception) -> None:
        self._error = error

    def __call__(self) -> _FailingSessionFactory:
        return self

    async def __aenter__(self) -> Any:
        raise self._error

    async def __aexit__(self, *_a: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_write_invitation_audit_swallows_open_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failing_factory = _FailingSessionFactory(RuntimeError("audit DB unreachable"))

    with patch(
        "echoroo.services.invitation.side_effects.AsyncSessionLocal",
        failing_factory,
    ), caplog.at_level("WARNING"):
        await _write_invitation_audit(
            action="project.invitation.create",
            actor_user_id=uuid4(),
            project_id=uuid4(),
            request_id="req-1",
            ip="1.2.3.4",
            user_agent="agent/1.0",
            detail={"invitation_id": str(uuid4())},
            before=None,
            after={"status": "pending"},
        )

    assert any(
        "audit write failed" in record.getMessage() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_write_invitation_audit_swallows_inner_failure_via_rollback() -> None:
    rollbacks: list[None] = []

    class _BoomSession:
        async def commit(self) -> None:  # pragma: no cover
            return None

        async def rollback(self) -> None:
            rollbacks.append(None)

        async def __aenter__(self) -> _BoomSession:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

    class _BoomFactory:
        """Stand-in for ``AsyncSessionLocal`` that yields a ``_BoomSession``.

        Mirrors the production ``async with AsyncSessionLocal() as s:``
        contract: the factory call returns an async context manager
        (the session itself) and ``__aenter__`` returns the session.
        """

        def __call__(self) -> _BoomSession:
            return _BoomSession()

    _factory = _BoomFactory()

    class _BoomService:
        def __init__(self, session: Any) -> None:
            self._session = session

        async def write_project_event(self, **_kwargs: Any) -> None:
            raise RuntimeError("hash chain broken")

    with (
        patch("echoroo.services.invitation.side_effects.AsyncSessionLocal", _factory),
        patch("echoroo.services.invitation.side_effects.AuditLogService", _BoomService),
    ):
        await _write_invitation_audit(
            action="project.invitation.create",
            actor_user_id=uuid4(),
            project_id=uuid4(),
            request_id="req-2",
            ip="",
            user_agent="",
            detail={"invitation_id": str(uuid4())},
            before=None,
            after=None,
        )

    assert rollbacks == [None]


# spec/011 Step 6 (T054): the legacy
# ``test_enqueue_invitation_email_swallows_outbox_failure`` case is gone
# along with ``_enqueue_invitation_email``. The outbox path is removed;
# the plain-text envelope is now surfaced once on the issue endpoint's
# HTTP response (FR-011-103) and never persisted past that turn. The
# audit-write soft-alert behaviour is still covered by the two
# ``test_write_invitation_audit_swallows_*`` cases above.


# ---------------------------------------------------------------------------
# trigger_post_commit_side_effects — accept + decline dispatch branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_post_commit_dispatches_to_decline_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    async def _fake_audit(
        *,
        action: str,
        **_kwargs: Any,
    ) -> None:
        captured.append(action)

    monkeypatch.setattr(
        "echoroo.services.invitation.side_effects._write_invitation_audit",
        _fake_audit,
    )

    class _StubInvitation:
        id = uuid4()
        project_id = uuid4()
        kind = ProjectInvitationKind.MEMBER
        status = ProjectInvitationStatus.DECLINED

    outcome = InvitationDeclineOutcome(
        invitation=_StubInvitation(),  # type: ignore[arg-type]
        actor_user_id=uuid4(),
        is_replay=False,
    )

    await trigger_post_commit_side_effects(outcome)

    assert captured == ["project.invitation.decline"]


@pytest.mark.asyncio
async def test_trigger_post_commit_dispatches_to_accept_branch_with_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    async def _fake_audit(*, action: str, **kwargs: Any) -> None:
        captured.append({"action": action, **kwargs})

    monkeypatch.setattr(
        "echoroo.services.invitation.side_effects._write_invitation_audit",
        _fake_audit,
    )

    class _StubInvitation:
        id = uuid4()
        project_id = uuid4()
        kind = ProjectInvitationKind.MEMBER
        status = ProjectInvitationStatus.ACCEPTED

    class _Member:
        id = uuid4()

    outcome = InvitationAcceptOutcome(
        invitation=_StubInvitation(),  # type: ignore[arg-type]
        member=_Member(),  # type: ignore[arg-type]
        trusted_user=None,
        actor_user_id=uuid4(),
        is_replay=False,
    )

    await trigger_post_commit_side_effects(outcome)

    assert len(captured) == 1
    assert captured[0]["action"] == "project.invitation.accept"
    assert "member_id" in captured[0]["detail"]


@pytest.mark.asyncio
async def test_trigger_post_commit_dispatches_to_create_branch_audit_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec/011 Step 6 (T054): create branch emits audit only.

    The outbox-email enqueue is removed (``_enqueue_invitation_email``
    no longer exists). Both ``is_new=True`` and ``is_new=False`` paths
    now perform the same audit write — the legacy ``is_new`` gate that
    suppressed the email side effect on replay is irrelevant since
    there is no email side effect to suppress.
    """
    captured: list[str] = []

    async def _fake_audit(*, action: str, **_kwargs: Any) -> None:
        captured.append(action)

    monkeypatch.setattr(
        "echoroo.services.invitation.side_effects._write_invitation_audit",
        _fake_audit,
    )

    inv_id_local = uuid4()
    proj_id_local = uuid4()

    class _StubInvitation:
        id = inv_id_local
        kind = ProjectInvitationKind.MEMBER
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        status = ProjectInvitationStatus.PENDING
        project_id = proj_id_local

    outcome = InvitationCreateOutcome(
        invitation=_StubInvitation(),  # type: ignore[arg-type]
        actor_user_id=uuid4(),
        signed_token_envelope="raw.1700000000.kid1.sig",
        is_new=False,
    )

    await trigger_post_commit_side_effects(outcome)

    assert captured == ["project.invitation.create"]
