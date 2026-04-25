from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    BACKUP_CODE_LENGTH,
    TOTP_SECRET_LENGTH,
    TwoFactorEnrollmentArtifacts,
    TwoFactorInvalidCodeError,
    TwoFactorRateLimitedError,
    TwoFactorService,
)


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
        self.values: dict[str, str | int] = {}

    async def incr(self, name: str) -> int:
        value = int(self.values.get(name, 0)) + 1
        self.values[name] = value
        return value

    async def expire(self, name: str, time: int) -> bool:
        return name in self.values and time > 0

    async def get(self, name: str) -> str | int | None:
        return self.values.get(name)

    async def set(self, name: str, value: str | int, ex: int | None = None) -> bool:
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
def _mock_slow_or_external_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_audit(self: TwoFactorService, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        two_factor_module.kms,
        "wrap_dek",
        lambda plaintext: bytes(plaintext),
    )
    monkeypatch.setattr(two_factor_module.kms, "unwrap_dek", lambda wrapped: bytes(wrapped))
    monkeypatch.setattr(TwoFactorService, "_record_audit_event", no_audit)
    monkeypatch.setattr(two_factor_module, "_backup_code_hasher", _FastBackupHasher())


def _user() -> User:
    return User(
        id=uuid4(),
        email="alice@example.com",
        password_hash="hash",
        security_stamp="old-stamp",
        two_factor_enabled=False,
    )


def _service(user: User) -> TwoFactorService:
    return TwoFactorService(_FakeSession(user), _FakeRedis())  # type: ignore[arg-type]


async def _confirmed_user(user: User) -> tuple[TwoFactorService, list[str]]:
    service = _service(user)
    artifacts = await service.begin_enrollment(user)
    code = pyotp.TOTP(artifacts.secret).now()
    backup_codes = await service.confirm_enrollment(user, artifacts.secret, code)
    return service, backup_codes


@pytest.mark.asyncio
async def test_totp_enrollment_generates_32_char_base32_secret() -> None:
    user = _user()
    service = _service(user)

    artifacts = await service.begin_enrollment(user)

    assert isinstance(artifacts, TwoFactorEnrollmentArtifacts)
    assert len(artifacts.secret) == TOTP_SECRET_LENGTH
    assert set(artifacts.secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    assert "issuer=Echoroo" in artifacts.provisioning_uri
    assert "alice%40example.com" in artifacts.provisioning_uri


@pytest.mark.asyncio
async def test_confirm_enrollment_rejects_wrong_code_and_accepts_correct_code() -> None:
    user = _user()
    service = _service(user)
    artifacts = await service.begin_enrollment(user)

    with pytest.raises(TwoFactorInvalidCodeError):
        await service.confirm_enrollment(user, artifacts.secret, "000000")

    backup_codes = await service.confirm_enrollment(
        user,
        artifacts.secret,
        pyotp.TOTP(artifacts.secret).now(),
    )

    assert len(backup_codes) == BACKUP_CODE_COUNT
    assert all(len(code) == BACKUP_CODE_LENGTH for code in backup_codes)
    assert user.two_factor_secret_encrypted
    assert user.two_factor_enabled is True
    assert user.two_factor_backup_codes_hashed is not None
    assert len(user.two_factor_backup_codes_hashed) == BACKUP_CODE_COUNT


@pytest.mark.asyncio
async def test_totp_verify_accepts_valid_code_and_rejects_invalid_code() -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)
    assert user.two_factor_secret_encrypted is not None

    assert await service.verify_totp(user, pyotp.TOTP(two_factor_module._decrypt_totp_secret(user.two_factor_secret_encrypted)).now())
    assert await service.verify_totp(user, "not-a-code") is False


@pytest.mark.asyncio
async def test_backup_code_verify_and_consume_rejects_second_use() -> None:
    user = _user()
    service, backup_codes = await _confirmed_user(user)
    first_code = backup_codes[0]

    assert await service.verify_backup_code(user, first_code) is True
    assert user.two_factor_backup_codes_hashed is not None
    assert len(user.two_factor_backup_codes_hashed) == BACKUP_CODE_COUNT - 1
    assert await service.verify_backup_code(user, first_code) is False


@pytest.mark.asyncio
async def test_totp_rate_limit_raises_on_sixth_failure() -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)

    for _ in range(5):
        assert await service.verify_totp(user, "not-a-code") is False

    with pytest.raises(TwoFactorRateLimitedError):
        await service.verify_totp(user, "not-a-code")


@pytest.mark.asyncio
async def test_security_stamp_changes_on_enrollment_confirm_and_reset() -> None:
    user = _user()
    original_stamp = user.security_stamp
    service, _backup_codes = await _confirmed_user(user)
    enrolled_stamp = user.security_stamp

    await service.reset_user_two_factor(
        user,
        actor_id=uuid4(),
        reason="admin recovery",
    )

    assert enrolled_stamp != original_stamp
    assert user.security_stamp != enrolled_stamp
    assert user.two_factor_enabled is False
    assert user.two_factor_secret_encrypted is None
    assert user.two_factor_backup_codes_hashed is None
    assert user.two_factor_reset_cooldown_until is not None
    expected = datetime.now(UTC) + timedelta(hours=72)
    assert expected - timedelta(seconds=5) <= user.two_factor_reset_cooldown_until <= expected
