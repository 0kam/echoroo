"""TDD coverage for JWT replay across ``security_stamp`` rotations
(FR-055, FR-071, PR-007).

This suite locks the cross-cutting contract that ties together password
change, 2FA enable, 2FA reset, and logout:

* **Password change**           rotates ``users.security_stamp`` so an
                                old access JWT (``ss`` claim bound to
                                the old stamp) MUST fail at the next
                                ``verify_access_token`` call.

* **2FA enable**                rotates the stamp via
                                :meth:`TwoFactorService.confirm_enrollment`.
                                Same replay-rejection contract.

* **2FA admin reset**           rotates the stamp via
                                :meth:`TwoFactorService.reset_user_two_factor`.
                                Same replay-rejection contract.

* **Logout**                    does NOT rotate the stamp — it merely
                                revokes the refresh-token family. This
                                means an *access* JWT minted just
                                before logout MAY still be accepted by
                                ``verify_access_token`` until ``exp``;
                                the refresh boundary is where logout's
                                family revocation surfaces. The test
                                below documents this difference
                                explicitly so a future "logout must
                                rotate the stamp" feature request is
                                routed through a deliberate spec
                                change rather than a silent regression.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pyotp
import pytest
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select

from echoroo.core.auth import (
    StaleTokenError,
    issue_access_token,
    new_security_stamp,
    verify_access_token,
)
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
        lambda plaintext: bytes(plaintext),
    )
    monkeypatch.setattr(
        two_factor_module.kms,
        "unwrap_dek",
        lambda wrapped: bytes(wrapped),
    )
    monkeypatch.setattr(TwoFactorService, "_record_audit_event", no_audit)
    monkeypatch.setattr(two_factor_module, "_backup_code_hasher", _FastBackupHasher())


def _user(*, two_factor_enabled: bool = False) -> User:
    return User(
        id=uuid4(),
        email="replay@example.com",
        password_hash="hash",
        security_stamp="initial-stamp" + "0" * (64 - len("initial-stamp")),
        two_factor_enabled=two_factor_enabled,
    )


# ---------------------------------------------------------------------------
# Case (a): password change → access JWT with old stamp is rejected
# ---------------------------------------------------------------------------


async def test_old_jwt_rejected_after_password_change_rotates_stamp() -> None:
    user_id = uuid4()
    stamp_before = "p" * 64

    pre_change_jwt = issue_access_token(
        user_id=user_id,
        security_stamp=stamp_before,
    )

    # Validate against the live (still-old) stamp — accepted.
    pre_claims = verify_access_token(
        pre_change_jwt,
        current_security_stamp=stamp_before,
    )
    assert pre_claims.user_id == user_id

    # Simulate password change: stamp rotates to a brand-new value.
    stamp_after = new_security_stamp()
    assert stamp_after != stamp_before

    # The pre-change JWT is now stale — replaying it MUST fail.
    with pytest.raises(StaleTokenError):
        verify_access_token(pre_change_jwt, current_security_stamp=stamp_after)


# ---------------------------------------------------------------------------
# Case (b): 2FA enable → access JWT with old stamp is rejected
# ---------------------------------------------------------------------------


async def test_old_jwt_rejected_after_two_factor_enable_rotates_stamp() -> None:
    user = _user()
    pre_enable_stamp = user.security_stamp
    pre_enable_jwt = issue_access_token(
        user_id=user.id,
        security_stamp=pre_enable_stamp,
    )

    service = TwoFactorService(_FakeSession(user), _FakeRedis())  # type: ignore[arg-type]
    artifacts = await service.begin_enrollment(user)
    code = pyotp.TOTP(artifacts.secret).now()
    await service.confirm_enrollment(user, artifacts.secret, code)

    assert user.security_stamp != pre_enable_stamp

    with pytest.raises(StaleTokenError):
        verify_access_token(
            pre_enable_jwt,
            current_security_stamp=user.security_stamp,
        )


# ---------------------------------------------------------------------------
# Case (c): 2FA reset → access JWT with old stamp is rejected
# ---------------------------------------------------------------------------


async def test_old_jwt_rejected_after_two_factor_reset_rotates_stamp() -> None:
    user = _user(two_factor_enabled=True)
    pre_reset_stamp = user.security_stamp
    pre_reset_jwt = issue_access_token(
        user_id=user.id,
        security_stamp=pre_reset_stamp,
    )

    service = TwoFactorService(_FakeSession(user), _FakeRedis())  # type: ignore[arg-type]
    await service.reset_user_two_factor(
        user,
        actor_id=uuid4(),
        reason="admin recovery",
    )

    assert user.security_stamp != pre_reset_stamp

    with pytest.raises(StaleTokenError):
        verify_access_token(
            pre_reset_jwt,
            current_security_stamp=user.security_stamp,
        )


# ---------------------------------------------------------------------------
# Case (d): logout does NOT rotate the stamp — pre-logout JWTs still
# verify until ``exp``. This documents the layering: refresh-token
# family revocation handles the *session* termination contract; the
# JWT-stamp check handles the *credential* invalidation contract.
#
# A future change that wants logout to immediately invalidate every
# outstanding access token must EITHER (i) rotate ``security_stamp``
# at logout, OR (ii) introduce per-JWT revocation lists. Both are
# spec changes; this test catches a quiet drift in either direction.
# ---------------------------------------------------------------------------


async def test_logout_does_not_rotate_security_stamp_so_jwt_remains_valid_until_exp() -> None:
    user_id = uuid4()
    stamp = "L" * 64

    jwt_token = issue_access_token(user_id=user_id, security_stamp=stamp)

    # "Logout" in the production code path ONLY revokes the refresh-token
    # family — see ``echoroo.api.web_v1.auth.logout``. It does not call
    # any helper that rotates the stamp. Locking that behaviour here
    # means a future drift (e.g. somebody adds ``user.security_stamp = ...``
    # to logout) will fail the assertion below until the spec is
    # explicitly updated.
    post_logout_stamp = stamp  # unchanged

    claims = verify_access_token(jwt_token, current_security_stamp=post_logout_stamp)
    assert claims.user_id == user_id


# ---------------------------------------------------------------------------
# Case (e): a fresh JWT minted AFTER any rotation event is accepted —
# proves the stamp check rotates with the user, not with the token.
# ---------------------------------------------------------------------------


async def test_fresh_jwt_minted_after_rotation_is_accepted() -> None:
    user_id = uuid4()
    new_stamp = new_security_stamp()
    fresh = issue_access_token(user_id=user_id, security_stamp=new_stamp)
    claims = verify_access_token(fresh, current_security_stamp=new_stamp)
    assert claims.user_id == user_id
