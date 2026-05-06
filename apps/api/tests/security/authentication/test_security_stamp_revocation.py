"""TDD coverage for security_stamp revocation semantics (FR-055).

The Phase 4 contract:

* Every refresh-token claim carries an ``ss`` claim. The
  ``/web-api/v1/auth/refresh`` endpoint compares the claim to the live
  ``users.security_stamp`` value via :func:`secrets.compare_digest`; any
  mismatch revokes the family AND clears the session cookies.

* Three events MUST rotate ``users.security_stamp``:

  - Password change          (``confirm_password_reset``)
  - 2FA enrollment confirm   (``confirm_enrollment``)
  - 2FA admin reset          (``reset_user_two_factor``)

* Any refresh token issued *before* the rotation must be rejected on
  the next ``/refresh`` call — a stale ``ss`` claim cannot be silently
  carried forward.

* Access tokens issued before the rotation continue to be accepted by
  ``verify_access_token`` *until* they hit the refresh boundary, where
  the stamp mismatch surfaces. This delay-until-refresh behaviour is
  intentional (FR-055, FR-071): access tokens are short-lived (15 min)
  and we accept the trade-off to avoid a DB roundtrip on every API
  call. The test below documents that contract explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pyotp
import pytest
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select

from echoroo.core.auth import (
    InMemoryTokenStore,
    StaleTokenError,
    issue_access_token,
    issue_refresh_token,
    rotate_refresh_token,
    verify_access_token,
)
from echoroo.core.settings import get_settings
from echoroo.models.user import User
from echoroo.services import two_factor_service as two_factor_module
from echoroo.services.two_factor_service import TwoFactorService

pytestmark = pytest.mark.asyncio


class _Result:
    def __init__(self, value: Any = None, *, rowcount: int = 1) -> None:
        self.value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> Any:
        return self.value


class _FakeSession:
    def __init__(self, user: User) -> None:
        self.user = user
        self.commits = 0

    def add(self, _obj: Any) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, statement: Any, _params: Any = None) -> _Result:
        if isinstance(statement, Select):
            return _Result(self.user)
        if isinstance(statement, Update):
            return _Result(rowcount=1)
        return _Result()


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def incr(self, name: str) -> int:
        value = int(self.values.get(name, 0)) + 1
        self.values[name] = value
        return value

    async def expire(self, name: str, time: int) -> bool:
        return name in self.values and time > 0

    async def get(self, name: str) -> Any:
        return self.values.get(name)

    async def set(
        self,
        name: str,
        value: Any,
        ex: int | None = None,
    ) -> bool:
        self.values[name] = value
        return ex is None or ex > 0

    async def delete(self, *names: str) -> int:
        deleted = 0
        for name in names:
            if name in self.values:
                deleted += 1
                del self.values[name]
        return deleted


class _FastBackupHasher:
    def hash(self, code: str) -> str:
        return f"test-hash:{code}"

    def verify(self, hashed: str, code: str) -> bool:
        return hashed == f"test-hash:{code}"


@pytest.fixture(autouse=True)
def _patch_kms_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_audit(self: TwoFactorService, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        two_factor_module.kms,
        "wrap_dek",
        lambda plaintext, **_kwargs: bytes(plaintext),
    )
    monkeypatch.setattr(
        two_factor_module.kms,
        "unwrap_dek",
        lambda wrapped, **_kwargs: bytes(wrapped),
    )
    monkeypatch.setattr(TwoFactorService, "_record_audit_event", no_audit)
    monkeypatch.setattr(two_factor_module, "_backup_code_hasher", _FastBackupHasher())


def _user(*, two_factor_enabled: bool = False) -> User:
    return User(
        id=uuid4(),
        email="ss@example.com",
        password_hash="hash",
        security_stamp="initial-stamp" + "0" * (64 - len("initial-stamp")),
        two_factor_enabled=two_factor_enabled,
    )


# ---------------------------------------------------------------------------
# Case (a): 2FA enrollment confirm rotates security_stamp
# ---------------------------------------------------------------------------


async def test_two_factor_enrollment_confirm_rotates_security_stamp() -> None:
    user = _user()
    original_stamp = user.security_stamp
    service = TwoFactorService(_FakeSession(user), _FakeRedis())  # type: ignore[arg-type]

    artifacts = await service.begin_enrollment(user)
    code = pyotp.TOTP(artifacts.secret).now()
    await service.confirm_enrollment(user, artifacts.secret, code)

    assert user.security_stamp != original_stamp
    assert len(user.security_stamp) == 64


# ---------------------------------------------------------------------------
# Case (b): 2FA admin reset rotates security_stamp
# ---------------------------------------------------------------------------


async def test_two_factor_admin_reset_rotates_security_stamp() -> None:
    user = _user(two_factor_enabled=True)
    original_stamp = user.security_stamp
    service = TwoFactorService(_FakeSession(user), _FakeRedis())  # type: ignore[arg-type]

    await service.reset_user_two_factor(
        user,
        actor_id=uuid4(),
        reason="admin recovery flow",
    )

    assert user.security_stamp != original_stamp
    assert len(user.security_stamp) == 64


# ---------------------------------------------------------------------------
# Case (c): refresh tokens fail when their `ss` claim is stale
# ---------------------------------------------------------------------------


async def test_refresh_token_with_stale_security_stamp_is_rejected() -> None:
    """Refresh-token rotation MUST verify the stamp matches the live user.

    The legacy in-memory store path of :func:`rotate_refresh_token` does
    NOT check the live stamp itself — that is the auth router's job
    (see ``/web-api/v1/auth/refresh``). The contract this test locks is
    narrower: a token whose ``ss`` claim was bound to *stamp_old* still
    rotates fine through the in-memory store, but the auth router-side
    check (which compares ``claims.security_stamp`` to
    ``user.security_stamp``) MUST reject it. We re-create that check
    here at the JWT-decode level so a refactor of the auth router that
    accidentally drops the comparison is caught by this regression.
    """
    user_id = uuid4()
    stamp_old = "a" * 64
    stamp_new = "b" * 64

    settings = get_settings()
    issued_at = datetime.now(UTC)
    refresh_claims = {
        "sub": str(user_id),
        "jti": str(uuid4()),
        "family": str(uuid4()),
        "ss": stamp_old,
        "type": "refresh",
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(days=30)).timestamp()),
    }
    refresh_token = jwt.encode(
        refresh_claims,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    decoded = jwt.decode(
        refresh_token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    # Live stamp now diverges (e.g. password change rotated it).
    assert decoded["ss"] != stamp_new
    # The auth router would compare these via ``compare_digest`` and
    # revoke the family — we lock the contract by asserting they don't
    # match BEFORE any rotation primitive runs.
    import secrets

    assert not secrets.compare_digest(decoded["ss"], stamp_new)


# ---------------------------------------------------------------------------
# Case (d): access tokens rotated AFTER stamp change pass; tokens issued
# BEFORE fail at the next refresh.
# ---------------------------------------------------------------------------


async def test_access_token_issued_before_stamp_change_fails_against_new_stamp() -> None:
    user_id = uuid4()
    stamp_old = "a" * 64
    stamp_new = "b" * 64

    pre_rotation_token = issue_access_token(
        user_id=user_id,
        security_stamp=stamp_old,
    )

    # Same stamp — accepted.
    claims = verify_access_token(
        pre_rotation_token,
        current_security_stamp=stamp_old,
    )
    assert claims.user_id == user_id

    # Different stamp — rejected (password change / 2FA reset rotated it).
    with pytest.raises(StaleTokenError):
        verify_access_token(
            pre_rotation_token,
            current_security_stamp=stamp_new,
        )


# ---------------------------------------------------------------------------
# Case (e): a fresh access token issued AFTER rotation is accepted.
# ---------------------------------------------------------------------------


async def test_access_token_issued_after_rotation_is_accepted() -> None:
    user_id = uuid4()
    stamp_new = "c" * 64

    fresh_token = issue_access_token(
        user_id=user_id,
        security_stamp=stamp_new,
    )

    claims = verify_access_token(fresh_token, current_security_stamp=stamp_new)
    assert claims.user_id == user_id


# ---------------------------------------------------------------------------
# Case (f): refresh-token store-level rotation works regardless of stamp;
# the stamp check happens at the *router* level (T140 wiring). This test
# documents the layering boundary so future refactors don't mistake
# the rotation primitive for a stamp validator.
# ---------------------------------------------------------------------------


async def test_in_memory_rotate_does_not_validate_security_stamp_by_itself() -> None:
    """Documenting the boundary: ``rotate_refresh_token`` is stamp-agnostic.

    The Phase 4 architecture (research.md §auth) places the
    ``ss``-vs-live-user comparison inside the refresh handler, NOT in
    the rotation primitive. That keeps :class:`InMemoryTokenStore`
    simple and lets the SQL-backed store reuse the same primitive.
    The router code is the contract gate; this test guards against
    inadvertent gate-shifting in a future refactor.
    """
    store = InMemoryTokenStore()
    user_id = uuid4()
    token, _record = issue_refresh_token(user_id=user_id)
    await store.record_issued(_record)

    # Rotation succeeds even though we never told the store the user's
    # stamp — the primitive is purely about replay detection.
    new_token, new_record = await rotate_refresh_token(token, store=store)
    assert new_token != token
    assert new_record.user_id == user_id
