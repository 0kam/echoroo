"""Phase 10 Batch 1 Round 2 polish — security-critical regressions.

These tests pin the behaviour fixed during Round 2 (致命 1..4 + Major 1..5):

* Plain-text token confidentiality (FR-051)         — outcome surface check.
* Rate-limit fail-closed when Redis is unreachable  — FR-056.
* Hard TTL cap = 7 days                              — FR-052.
* Idempotency-key conflict / replay matching        — FR-053.

Pure unit tests; the database round-trip (FR-049 partial unique, FOR UPDATE
serialisation) is exercised by the integration suite.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
)
from echoroo.models.project import ProjectInvitation, ProjectMember
from echoroo.services import invitation_service
from echoroo.services.invitation_service import (
    INVITATION_MAX_TTL_SECONDS,
    RATE_LIMIT_ACTOR_PER_HOUR,
    InvitationConflictError,
    InvitationCreateOutcome,
    InvitationInfraUnavailableError,
    InvitationRateLimitError,
    InvitationValidationError,
    accept_invitation,
    check_rate_limits,
    create_invitation,
)

HMAC_SECRET = "test-hmac-secret-32-bytes-long!!!"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeRedis:
    """In-memory Redis fake supporting INCR/EXPIRE/GET/SET-NX with TTL bookkeeping."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.fail_on_incr: bool = False
        self.fail_on_get: bool = False
        self.fail_on_set: bool = False

    async def incr(self, name: str) -> int:
        if self.fail_on_incr:
            raise ConnectionError("redis unreachable")
        value = int(self.values.get(name, 0)) + 1
        self.values[name] = value
        return value

    async def expire(self, name: str, time: int) -> bool:
        if name in self.values:
            self.ttls[name] = time
            return True
        return False

    async def get(self, name: str) -> Any:
        if self.fail_on_get:
            raise ConnectionError("redis unreachable")
        return self.values.get(name)

    async def set(
        self,
        name: str,
        value: Any,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if self.fail_on_set:
            raise ConnectionError("redis unreachable")
        if nx and name in self.values:
            return None
        self.values[name] = value
        if ex is not None:
            self.ttls[name] = ex
        return True


class _NullResult:
    """Stub SQLAlchemy result whose ``scalar_one_or_none`` is always ``None``."""

    def scalar_one_or_none(self) -> Any:
        return None


class _FakeSession:
    """Minimal AsyncSession stub that captures ``add`` / ``flush`` calls.

    ``execute`` is stubbed to return an empty result (``scalar_one_or_none``
    → ``None``). This models the unit-scope assumption that the recipient
    email does NOT resolve to any registered user, so the preview issue #4
    existing-active-member guard in ``create_invitation`` is a no-op and the
    happy-path INSERT proceeds — exactly what these outcome-surface tests
    exercise. Tests that need a hydrated membership row use a dedicated
    stub session further down (see the REUSE-branch tests).
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_calls: int = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        # Mirror what SQLAlchemy will do: stamp an id so downstream
        # outcome dataclasses can serialise it.
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    async def execute(self, *_a: Any, **_k: Any) -> _NullResult:
        return _NullResult()

    async def flush(self) -> None:
        self.flush_calls += 1


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


# ---------------------------------------------------------------------------
# 致命 4 / Major 3 — fail-closed Redis + 7-day TTL hard cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_rate_limits_fail_closed_when_redis_raises(
    fake_redis: _FakeRedis,
) -> None:
    fake_redis.fail_on_incr = True
    with pytest.raises(InvitationInfraUnavailableError):
        await check_rate_limits(
            fake_redis,  # type: ignore[arg-type]
            actor_user_id=uuid4(),
            project_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_check_rate_limits_raises_when_actor_cap_exceeded(
    fake_redis: _FakeRedis,
) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    # Pre-load the actor counter past the cap.
    fake_redis.values[f"invitation_rate:actor:{actor_id}"] = RATE_LIMIT_ACTOR_PER_HOUR
    with pytest.raises(InvitationRateLimitError):
        await check_rate_limits(
            fake_redis,  # type: ignore[arg-type]
            actor_user_id=actor_id,
            project_id=project_id,
        )


@pytest.mark.asyncio
async def test_create_invitation_rejects_ttl_above_seven_days(
    fake_redis: _FakeRedis,
) -> None:
    session = _FakeSession()
    with pytest.raises(InvitationValidationError):
        await create_invitation(
            session,  # type: ignore[arg-type]
            project_id=uuid4(),
            kind=ProjectInvitationKind.MEMBER,
            email="alice@example.com",
            invited_by_id=uuid4(),
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            role=ProjectMemberRole.MEMBER,
            invitation_ttl_seconds=INVITATION_MAX_TTL_SECONDS + 1,
        )


# ---------------------------------------------------------------------------
# 致命 1 — plain-text token confidentiality (FR-051)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invitation_outcome_does_not_expose_plain_token_at_top_level(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Phase 17 §C PR-A: this unit test exercises the outcome surface
    # only — the KMS-backed PII dual-write helper invoked transitively
    # by ``create_invitation`` is incidental machinery here. Stubbing
    # ``hash_email_dual`` to a deterministic single-key result keeps the
    # test purely unit-scoped (no moto roundtrip, no AWS env wiring) and
    # mirrors the explicit-stub culture of the rest of ``tests/unit/``.
    monkeypatch.setattr(
        "echoroo.services.invitation.create.hash_email_dual",
        lambda _email: {"v1": "0" * 64},
    )
    session = _FakeSession()
    outcome = await create_invitation(
        session,  # type: ignore[arg-type]
        project_id=uuid4(),
        kind=ProjectInvitationKind.MEMBER,
        email="alice@example.com",
        invited_by_id=uuid4(),
        hmac_secret=HMAC_SECRET,
        redis=fake_redis,  # type: ignore[arg-type]
        role=ProjectMemberRole.MEMBER,
    )

    assert isinstance(outcome, InvitationCreateOutcome)
    # spec/011 Step 6 (T053): the plain-text envelope lives on a single
    # ``signed_token_envelope`` slot — the legacy split between the
    # outcome surface and an internal ``mail_payload`` carrier is gone.
    # Confidentiality is now enforced at the API layer (FR-011-102..104)
    # rather than by hiding the value inside a nested dataclass.
    field_names = set(outcome.__dataclass_fields__)
    assert "raw_token_b64u" not in field_names
    assert "signed_token" not in field_names
    assert "mail_payload" not in field_names

    assert isinstance(outcome.signed_token_envelope, str)
    # 4-part envelope: {raw}.{exp}.{kid}.{mac}
    assert outcome.signed_token_envelope.count(".") == 3


# ---------------------------------------------------------------------------
# Major 1 / FR-053 — idempotency-key conflict semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_invitation_reuses_idempotency_record_for_same_token(
    fake_redis: _FakeRedis,
) -> None:
    """Same idempotency-key + same token should not raise during the
    pre-flight conflict check.
    """
    key = "client-idem-1"
    record_payload = (
        '{"invitation_id": "'
        + str(uuid4())
        + '", "token_hash": "deadbeef", "created_at": "2026-01-01T00:00:00+00:00"}'
    )
    fake_redis.values[invitation_service._idempotency_redis_key(key)] = record_payload
    cached = await invitation_service._get_idempotent_outcome(
        fake_redis,  # type: ignore[arg-type]
        key,
    )
    assert cached is not None
    assert cached.token_hash == "deadbeef"


@pytest.mark.asyncio
async def test_accept_invitation_reuse_idempotency_key_with_different_token_409(
    fake_redis: _FakeRedis,
) -> None:
    """Different token under same idempotency-key must raise 409 conflict.

    We exercise only the pre-flight short-circuit branch — the full DB
    round-trip is covered by the integration suite. Here we seed Redis
    with a stale record that points at a *different* token_hash and
    confirm the token+key mismatch is rejected immediately.
    """
    key = "client-idem-2"
    fake_redis.values[invitation_service._idempotency_redis_key(key)] = (
        '{"invitation_id": "'
        + str(uuid4())
        + '", "token_hash": "previous-token-hash", "created_at": "2026-01-01T00:00:00+00:00"}'
    )

    # Forge a *valid* signed token so verify_invitation_token succeeds —
    # the conflict must surface from the idempotency check, not from
    # signature verification.
    raw_token_b64u = invitation_service._b64u_encode(b"\x01" * 32)
    from datetime import UTC, datetime, timedelta

    expires_at = datetime.now(UTC) + timedelta(hours=1)
    signed_token = invitation_service.sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=expires_at,
        hmac_secret=HMAC_SECRET,
    )

    class _NoSession:
        async def execute(self, *_a: Any, **_k: Any) -> Any:  # pragma: no cover
            raise AssertionError(
                "accept_invitation must raise before issuing any SQL "
                "when the idempotency-key short-circuit fires",
            )

    with pytest.raises(InvitationConflictError):
        await accept_invitation(
            _NoSession(),  # type: ignore[arg-type]
            signed_token=signed_token,
            current_user_id=uuid4(),
            current_user_email="alice@example.com",
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key=key,
        )


# ---------------------------------------------------------------------------
# Round 3 Major 1 / 2 / 3 — fail-closed Redis + Member REUSE token-match
# ---------------------------------------------------------------------------


def _signed_token_for_test(
    raw_bytes: bytes = b"\x02" * 32,
    *,
    ttl_hours: int = 1,
) -> tuple[str, str, datetime]:
    """Return ``(raw_token_b64u, signed_token, expires_at)`` for tests."""
    raw_token_b64u = invitation_service._b64u_encode(raw_bytes)
    expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)
    signed_token = invitation_service.sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=expires_at,
        hmac_secret=HMAC_SECRET,
    )
    return raw_token_b64u, signed_token, expires_at


@pytest.mark.asyncio
async def test_accept_invitation_rejects_redis_get_fault_fail_closed(
    fake_redis: _FakeRedis,
) -> None:
    """Round 3 Major 2: a Redis GET fault during the idempotency-key
    short-circuit must surface as :class:`InvitationInfraUnavailableError`
    (HTTP 503 fail-closed) — silently treating the cache miss as ``None``
    would let an attacker reuse the same key with a different token while
    Redis is partially down.
    """
    fake_redis.fail_on_get = True

    _, signed_token, _ = _signed_token_for_test()

    class _NoSession:
        async def execute(self, *_a: Any, **_k: Any) -> Any:  # pragma: no cover
            raise AssertionError(
                "accept_invitation must raise the infra error before any SQL "
                "when the idempotency cache is unreachable",
            )

    with pytest.raises(InvitationInfraUnavailableError):
        await accept_invitation(
            _NoSession(),  # type: ignore[arg-type]
            signed_token=signed_token,
            current_user_id=uuid4(),
            current_user_email="alice@example.com",
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key="any-key",
        )


@pytest.mark.asyncio
async def test_set_idempotent_outcome_fails_closed_on_redis_set_fault(
    fake_redis: _FakeRedis,
) -> None:
    """Round 3 Major 2: a Redis SET fault during the post-success pin
    must raise :class:`InvitationInfraUnavailableError`. A silently
    skipped write would break the 24 h dedupe contract (a subsequent
    retry would hit a cold cache and we would have no record to detect
    a different-token replay).
    """
    fake_redis.fail_on_set = True

    record = invitation_service._IdempotencyRecord(
        invitation_id=str(uuid4()),
        token_hash="abc123",
        is_replay=True,
    )

    with pytest.raises(InvitationInfraUnavailableError):
        await invitation_service._set_idempotent_outcome(
            fake_redis,  # type: ignore[arg-type]
            "client-idem-set-fault",
            record,
        )


@pytest.mark.asyncio
async def test_accept_invitation_member_reuse_requires_token_match(
    fake_redis: _FakeRedis,
) -> None:
    """Round 3 Major 3: when an unrelated active membership row already
    exists for ``(project_id, user_id)``, REUSE must NOT proceed even if
    the caller supplied an idempotency-key — unless the cached record
    under that key was bound to the *same* invitation token. Otherwise
    an attacker could use a stolen / unrelated key to silently flip an
    arbitrary pending invitation to ``accepted``.
    """
    project_id = uuid4()
    invited_by_id = uuid4()
    user_id = uuid4()
    email = "alice@example.com"

    raw_token_b64u, signed_token, expires_at = _signed_token_for_test(
        raw_bytes=b"\x03" * 32,
    )
    token_hash = invitation_service.hash_token(raw_token_b64u)
    email_hash = invitation_service.hash_email(email, hmac_secret=HMAC_SECRET)

    # Build a transient pending invitation row (not added to any session
    # — we hand it to the stub session's ``execute`` mock directly).
    invitation = ProjectInvitation(
        project_id=project_id,
        kind=ProjectInvitationKind.MEMBER,
        email=email,
        email_hash=email_hash,
        role=ProjectMemberRole.MEMBER,
        token_hash=token_hash,
        invited_by_id=invited_by_id,
        expires_at=expires_at,
        status=ProjectInvitationStatus.PENDING,
    )
    invitation.id = uuid4()

    # An *unrelated* existing active membership (e.g. created via a
    # different prior invitation or a direct admin-add). The current
    # invitation's token does NOT match this row.
    existing_member = ProjectMember(
        project_id=project_id,
        user_id=user_id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=invited_by_id,
    )
    existing_member.id = uuid4()

    class _StubResult:
        def __init__(self, value: Any) -> None:
            self._value = value

        def scalar_one_or_none(self) -> Any:
            return self._value

    class _StubSession:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, *_a: Any, **_k: Any) -> _StubResult:
            self.calls += 1
            if self.calls == 1:
                return _StubResult(invitation)
            if self.calls == 2:
                return _StubResult(existing_member)
            raise AssertionError("unexpected extra execute() call")

        def add(self, _obj: Any) -> None:  # pragma: no cover - REUSE branch
            raise AssertionError(
                "Member REUSE must never insert a new ProjectMember row",
            )

        async def flush(self) -> None:  # pragma: no cover - REUSE branch
            raise AssertionError(
                "REUSE conflict must raise before flush()",
            )

    # Caller supplies an idempotency-key, but Redis has NO record under
    # it (or, equivalently, a record bound to a different token). Either
    # way, REUSE must be denied with 409.
    key = "stolen-or-unrelated-key"
    # Seed a stale record under the key, but with a *different*
    # token_hash — this matches the real-world stolen-key threat.
    fake_redis.values[invitation_service._idempotency_redis_key(key)] = (
        '{"invitation_id": "'
        + str(uuid4())
        + '", "token_hash": "different-token-hash", '
        '"created_at": "2026-01-01T00:00:00+00:00"}'
    )

    # The pre-flight idempotency check (step 2) sees a different-token
    # record under the same key and raises 409 immediately. This *also*
    # demonstrates that a stolen key can never silently REUSE the
    # unrelated existing member row. To exercise the REUSE branch
    # specifically (cached record absent), we re-run with an empty key.
    with pytest.raises(InvitationConflictError):
        await accept_invitation(
            _StubSession(),  # type: ignore[arg-type]
            signed_token=signed_token,
            current_user_id=user_id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key=key,
        )

    # Now the REUSE-specific path: idempotency-key is supplied but the
    # cache has no record under it (Redis evicted, or first attempt for
    # this key). REUSE must still be denied because we cannot prove the
    # existing member row originated from this invitation.
    fresh_redis = _FakeRedis()
    with pytest.raises(InvitationConflictError):
        await accept_invitation(
            _StubSession(),  # type: ignore[arg-type]
            signed_token=signed_token,
            current_user_id=user_id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=fresh_redis,  # type: ignore[arg-type]
            idempotency_key="another-fresh-key",
        )


# ---------------------------------------------------------------------------
# Minor 2 — datetime aware UTC normalisation
# ---------------------------------------------------------------------------


def test_ensure_utc_preserves_absolute_instant_for_non_utc_aware_value() -> None:
    from datetime import datetime, timedelta, timezone

    jst = timezone(timedelta(hours=9))
    jst_value = datetime(2026, 4, 27, 12, 0, 0, tzinfo=jst)
    utc_value = invitation_service._ensure_utc(jst_value)
    # If we had used .replace(tzinfo=UTC) the resulting timestamp would be
    # 9 hours in the future. astimezone(UTC) preserves the instant.
    assert utc_value == jst_value
    assert utc_value.tzinfo is not None
    assert utc_value.utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def _drain(it: AsyncIterator[Any]) -> list[Any]:  # pragma: no cover
    return [v async for v in it]
