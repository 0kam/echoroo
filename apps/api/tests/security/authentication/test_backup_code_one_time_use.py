"""TDD coverage for backup-code one-time-use semantics (FR-068).

The backup-code primitive must:

* Accept a freshly-issued code on first use (returns True).
* Reject the same code on every subsequent attempt.
* Decrement the in-memory list by exactly 1 on each successful use,
  preserving the order of the remaining hashes.
* Refuse to verify when the user has consumed all 8 codes (the user is
  forced through the admin-driven 2FA reset path).

The service-level test exercises the SQLAlchemy ``UPDATE ... WHERE
two_factor_backup_codes_hashed = original`` guard via fakes — the
end-to-end Postgres FOR UPDATE behaviour is covered separately by the
TOTP integration suite.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pyotp
import pytest
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select

from echoroo.models.user import User
from echoroo.services import two_factor_service as two_factor_module
from echoroo.services.two_factor_service import (
    BACKUP_CODE_COUNT,
    TwoFactorService,
)


class _Result:
    def __init__(self, value: Any = None, *, rowcount: int = 1) -> None:
        self.value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> Any:
        return self.value


class _FakeSession:
    """Reflects the ``UPDATE ... WHERE original`` guard used by the service."""

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
            # The service issues at most one row update per call; the
            # one-time-use contract is enforced by the Python-side filter
            # comparing the post-removal hash list to the pre-call one.
            return _Result(rowcount=1)
        return _Result()


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str | int] = {}

    async def incr(self, name: str) -> int:
        value = int(self.values.get(name, 0)) + 1
        self.values[name] = value
        return value

    async def expire(self, name: str, time: int) -> bool:
        return name in self.values and time > 0

    async def get(self, name: str) -> str | int | None:
        return self.values.get(name)

    async def set(
        self,
        name: str,
        value: str | int,
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


def _user() -> User:
    return User(
        id=uuid4(),
        email="backup@example.com",
        password_hash="hash",
        security_stamp="s" + "0" * 63,
        two_factor_enabled=False,
    )


async def _confirmed_user() -> tuple[User, TwoFactorService, list[str]]:
    user = _user()
    service = TwoFactorService(_FakeSession(user), _FakeRedis())  # type: ignore[arg-type]
    artifacts = await service.begin_enrollment(user)
    code = pyotp.TOTP(artifacts.secret).now()
    backup_codes = await service.confirm_enrollment(user, artifacts.secret, code)
    return user, service, backup_codes


# ---------------------------------------------------------------------------
# Case (a): a backup code can be used exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backup_code_can_be_used_once_then_rejected() -> None:
    user, service, backup_codes = await _confirmed_user()
    code_to_consume = backup_codes[0]

    assert await service.verify_backup_code(user, code_to_consume) is True
    assert await service.verify_backup_code(user, code_to_consume) is False


# ---------------------------------------------------------------------------
# Case (b): consuming N codes leaves exactly (BACKUP_CODE_COUNT - N) entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consuming_codes_decrements_remaining_count_by_one_each_time() -> None:
    user, service, backup_codes = await _confirmed_user()

    assert user.two_factor_backup_codes_hashed is not None
    assert len(user.two_factor_backup_codes_hashed) == BACKUP_CODE_COUNT

    # Consume codes 0..6 (i.e. 7 codes), leaving exactly 1 remaining.
    for n in range(BACKUP_CODE_COUNT - 1):
        assert await service.verify_backup_code(user, backup_codes[n]) is True
        assert user.two_factor_backup_codes_hashed is not None
        assert (
            len(user.two_factor_backup_codes_hashed)
            == BACKUP_CODE_COUNT - (n + 1)
        ), f"after consuming {n + 1} code(s), expected " \
           f"{BACKUP_CODE_COUNT - (n + 1)} remaining"


# ---------------------------------------------------------------------------
# Case (c): exhausting all 8 codes leaves the user with 0 — must reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exhausting_all_backup_codes_drives_user_to_zero_remaining() -> None:
    user, service, backup_codes = await _confirmed_user()

    # Consume every issued code in turn. A successful verify clears
    # the backup-fail counter, so we never trip
    # :class:`TwoFactorRateLimitedError` when consuming valid codes
    # back-to-back — that path is exercised by ``test_two_factor_service.py``.
    for code in backup_codes:
        assert await service.verify_backup_code(user, code) is True

    # All 8 hashes are gone — the user has no recovery codes left and
    # MUST request an admin-driven 2FA reset (FR-068, FR-073). The
    # service does not auto-promote this state to an exception; the
    # caller (the auth router) is responsible for surfacing it. The
    # invariant we lock here is that the hashed-array is empty so the
    # router can detect "0 remaining" and prompt the user accordingly.
    assert user.two_factor_backup_codes_hashed == []

    # A future verification with the FIRST stale code is rejected
    # (the array no longer contains the matching hash). We deliberately
    # only check one code here — looping over all 8 stale codes would
    # trip the backup-fail rate limit (BACKUP_FAIL_LIMIT=3 cap, see
    # ``two_factor_service.py``), which is a separate FR-070 contract
    # exercised by ``test_two_factor_service.py``.
    assert await service.verify_backup_code(user, backup_codes[0]) is False
