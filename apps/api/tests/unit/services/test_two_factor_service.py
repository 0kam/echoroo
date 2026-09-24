from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pyotp
import pytest
from pydantic import ValidationError
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select

from echoroo.core.keyring import KeyringAuthError
from echoroo.core.settings import Settings
from echoroo.models.user import User
from echoroo.services import two_factor_service as two_factor_module
from echoroo.services.two_factor_service import (
    BACKUP_CODE_COUNT,
    BACKUP_CODE_LENGTH,
    TOTP_SECRET_LENGTH,
    TwoFactorEnrollmentArtifacts,
    TwoFactorError,
    TwoFactorInvalidCodeError,
    TwoFactorLockedError,
    TwoFactorRateLimitedError,
    TwoFactorService,
)

SHARED_TEST_TOTP_SECRET = "JBSWY3DPEHPK3PXP"


def _stub_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    test_mode: bool = False,
    test_totp_secret_base32: str | None = None,
    environment: str = "development",
) -> None:
    """Patch the non-keyring settings used by verification tests."""

    class _StubSettings:
        TEST_MODE = test_mode
        TEST_TOTP_SECRET_BASE32 = test_totp_secret_base32
        ENVIRONMENT = environment

    monkeypatch.setattr(two_factor_module, "get_settings", lambda: _StubSettings())


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
        self.committed_two_factor_enabled = user.two_factor_enabled

    def add(self, _obj: Any) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1
        self.committed_two_factor_enabled = self.user.two_factor_enabled

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


def _strong_production_settings(**overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "ENVIRONMENT": "production",
        "JWT_SECRET_KEY": "strong-jwt-secret-that-is-long-enough-1234",
        "web_session_secret": "strong-web-session-secret-that-is-long-enough-1234",
        "S3_SECRET_KEY": "strong-s3-secret",
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY": ("strong-two-factor-reset-hmac-secret-1234"),
    }
    settings.update(overrides)
    return settings


def _decrypt_user_totp_secret(user: User) -> str:
    assert user.two_factor_secret_encrypted is not None
    return two_factor_module._decrypt_totp_secret(
        user.two_factor_secret_encrypted,
        dek_version=user.two_factor_secret_dek_version,
    )


def _shared_secret_code_not_matching_enrolled(enrolled_secret: str) -> tuple[str, str]:
    candidate_secrets = [
        SHARED_TEST_TOTP_SECRET,
        "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
    ]
    enrolled_totp = pyotp.TOTP(enrolled_secret)
    for shared_secret in candidate_secrets:
        code = pyotp.TOTP(shared_secret).now()
        if not enrolled_totp.verify(code, valid_window=two_factor_module.TOTP_VALID_WINDOW):
            return shared_secret, code
    raise AssertionError("could not find shared TOTP code distinct from enrolled secret")


def _totp_code_matching_no_secret(*secrets: str) -> str:
    totps = [pyotp.TOTP(secret) for secret in secrets]
    for value in range(1_000_000):
        code = f"{value:06d}"
        if all(
            not totp.verify(code, valid_window=two_factor_module.TOTP_VALID_WINDOW)
            for totp in totps
        ):
            return code
    raise AssertionError("could not find non-matching TOTP code")


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
async def test_enrollment_fails_closed_on_keyring_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    service = _service(user)
    artifacts = await service.begin_enrollment(user)

    def fail_wrap(*_args: Any, **_kwargs: Any) -> bytes:
        raise KeyringAuthError("test authentication failure")

    monkeypatch.setattr(two_factor_module.kms, "wrap_dek", fail_wrap)
    with pytest.raises(KeyringAuthError):
        await service.confirm_enrollment(
            user,
            artifacts.secret,
            pyotp.TOTP(artifacts.secret).now(),
        )
    assert user.two_factor_enabled is False


@pytest.mark.asyncio
async def test_verification_fails_closed_on_keyring_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)

    def fail_unwrap(*_args: Any, **_kwargs: Any) -> bytearray:
        raise KeyringAuthError("test authentication failure")

    monkeypatch.setattr(two_factor_module.kms, "unwrap_dek", fail_unwrap)
    with pytest.raises(KeyringAuthError):
        await service.verify_totp(user, "123456")


@pytest.mark.asyncio
async def test_totp_verify_accepts_valid_code_and_rejects_invalid_code() -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)
    assert user.two_factor_secret_encrypted is not None

    assert await service.verify_totp(
        user,
        pyotp.TOTP(two_factor_module._decrypt_totp_secret(user.two_factor_secret_encrypted)).now(),
    )
    assert await service.verify_totp(user, "not-a-code") is False


def test_test_mode_in_production_refuses_startup() -> None:
    with pytest.raises((ValueError, ValidationError), match="TEST_MODE"):
        Settings(
            **_strong_production_settings(
                TEST_MODE=True,
                TEST_TOTP_SECRET_BASE32=SHARED_TEST_TOTP_SECRET,
            )
        )


def test_test_mode_without_shared_secret_refuses_startup() -> None:
    with pytest.raises((ValueError, ValidationError), match="TEST_TOTP_SECRET_BASE32"):
        Settings(TEST_MODE=True, TEST_TOTP_SECRET_BASE32=None)


@pytest.mark.asyncio
async def test_test_mode_bypass_accepts_shared_secret_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)
    enrolled_secret = _decrypt_user_totp_secret(user)
    shared_secret, shared_code = _shared_secret_code_not_matching_enrolled(enrolled_secret)
    _stub_settings(
        monkeypatch,
        test_mode=True,
        test_totp_secret_base32=shared_secret,
        environment="development",
    )
    audit = AsyncMock()
    monkeypatch.setattr(service, "_record_audit_event", audit)

    assert await service.verify_totp(user, shared_code) is True

    audit.assert_awaited_once()
    assert audit.call_args.kwargs["action"] == "two_factor.test_mode_bypass"
    assert audit.call_args.kwargs["detail"] == {
        "reason": "shared_secret_match",
        "environment": "development",
    }


@pytest.mark.asyncio
async def test_test_mode_bypass_rejects_wrong_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)
    enrolled_secret = _decrypt_user_totp_secret(user)
    wrong_code = _totp_code_matching_no_secret(
        enrolled_secret,
        SHARED_TEST_TOTP_SECRET,
    )
    _stub_settings(
        monkeypatch,
        test_mode=True,
        test_totp_secret_base32=SHARED_TEST_TOTP_SECRET,
    )

    assert await service.verify_totp(user, wrong_code) is False


@pytest.mark.asyncio
async def test_test_mode_off_rejects_shared_secret_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)
    enrolled_secret = _decrypt_user_totp_secret(user)
    shared_secret, shared_code = _shared_secret_code_not_matching_enrolled(enrolled_secret)
    _stub_settings(
        monkeypatch,
        test_mode=False,
        test_totp_secret_base32=shared_secret,
    )

    assert await service.verify_totp(user, shared_code) is False


@pytest.mark.asyncio
async def test_enrolled_secret_still_works_with_test_mode_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)
    enrolled_secret = _decrypt_user_totp_secret(user)
    _stub_settings(
        monkeypatch,
        test_mode=True,
        test_totp_secret_base32=SHARED_TEST_TOTP_SECRET,
    )
    audit = AsyncMock()
    monkeypatch.setattr(service, "_record_audit_event", audit)

    assert await service.verify_totp(user, pyotp.TOTP(enrolled_secret).now()) is True

    audit.assert_not_awaited()


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
async def test_backup_code_rate_limit_raises_on_fourth_failure() -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)

    for _ in range(3):
        assert await service.verify_backup_code(user, "not-a-backup-code") is False

    with pytest.raises(TwoFactorRateLimitedError):
        await service.verify_backup_code(user, "not-a-backup-code")


@pytest.mark.asyncio
async def test_totp_consecutive_lockout_raises_after_ten_failures() -> None:
    user = _user()
    service, _backup_codes = await _confirmed_user(user)

    for _ in range(5):
        assert await service.verify_totp(user, "not-a-code") is False

    for _ in range(4):
        with pytest.raises(TwoFactorRateLimitedError):
            await service.verify_totp(user, "not-a-code")

    with pytest.raises(TwoFactorLockedError):
        await service.verify_totp(user, "not-a-code")

    redis = service.redis
    assert redis is not None
    assert await redis.get(service._totp_lock_key(user.id)) == "1"


def test_decrypt_totp_secret_rejects_malformed_payloads() -> None:
    malformed_payloads = [
        b"",
        b"x" * 15,
        struct.pack("<I", 0) + b"x" * 13,
        struct.pack("<I", 1) + b"x" * 13,
    ]

    for payload in malformed_payloads:
        with pytest.raises(TwoFactorError, match="malformed"):
            two_factor_module._decrypt_totp_secret(payload)


@pytest.mark.asyncio
async def test_audit_event_written_only_after_commit_for_confirm_enrollment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    fake_session = _FakeSession(user)
    service = TwoFactorService(fake_session, _FakeRedis())  # type: ignore[arg-type]
    artifacts = await service.begin_enrollment(user)

    async def audit_side_effect(*_args: Any, **_kwargs: Any) -> None:
        assert fake_session.commits == 1
        assert fake_session.committed_two_factor_enabled is True

    audit = AsyncMock(side_effect=audit_side_effect)
    monkeypatch.setattr(service, "_record_audit_event", audit)

    await service.confirm_enrollment(user, artifacts.secret, pyotp.TOTP(artifacts.secret).now())

    assert fake_session.commits == 1
    assert [call.kwargs["action"] for call in audit.call_args_list] == [
        "two_factor.backup_code_remaining",
        "two_factor.enroll_confirmed",
    ]


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


# ---------------------------------------------------------------------------
# T170 carry-over (FR-050, FR-052, FR-068) — additional edge-case TDD coverage
#
# The block above (T145) already covers the canonical enrollment, verification,
# rate-limit, and reset-cooldown flows. The cases below close gaps the Codex
# review surfaced after Phase 4 polish landed:
#
# * Malformed TOTP codes (non-numeric / wrong length) MUST raise
#   ``TwoFactorInvalidCodeError`` rather than silently returning False from
#   :meth:`TwoFactorService.confirm_enrollment` — pyotp's ``verify`` is
#   permissive about non-digit input and we want the explicit error.
# * Backup-code consumption preserves the *order* of the remaining codes.
#   The hashed-array contract that callers depend on (``len() == BACKUP_CODE_COUNT - n``
#   plus identity of the first hash) breaks if we accidentally rotate the
#   list during consumption.
# * :meth:`reset_user_two_factor` MUST clear ``two_factor_secret_dek_version``
#   to ``None`` so a stale rotation hint cannot point at a no-longer-
#   present secret. The original test only asserted that the secret bytes
#   are cleared.
# * AES-GCM nonces are randomised per encryption call. Two encryptions of
#   the same plaintext MUST produce distinct ciphertexts — without this
#   guarantee a passive observer of ``two_factor_secret_encrypted`` could
#   spot users who share a TOTP secret. ``_encrypt_totp_secret`` uses
#   ``os.urandom(12)`` for the nonce (FR-051) so the regression check is
#   essentially "did anyone refactor this into a fixed nonce?".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_code",
    [
        "",
        "abcdef",
        "12345",  # too short
        "1234567",  # too long
        "12 34 56",  # space-padded but still invalid digits-after-strip
        "00000a",
    ],
)
async def test_confirm_enrollment_rejects_malformed_totp_codes(
    malformed_code: str,
) -> None:
    user = _user()
    service = _service(user)
    artifacts = await service.begin_enrollment(user)

    with pytest.raises(TwoFactorInvalidCodeError):
        await service.confirm_enrollment(user, artifacts.secret, malformed_code)


@pytest.mark.asyncio
async def test_backup_code_consumption_preserves_order_of_remaining_codes() -> None:
    user = _user()
    service, backup_codes = await _confirmed_user(user)

    assert user.two_factor_backup_codes_hashed is not None
    original_hashes = list(user.two_factor_backup_codes_hashed)
    # Sanity-check: hashes are issued in the same order as the plaintext
    # codes returned to the user.
    assert [f"test-hash:{code}" for code in backup_codes] == original_hashes

    # Consume the *third* code and verify the remaining hashes preserve
    # their original ordering (i.e. we drop element 2 only — we do not
    # rotate or reverse the list during consumption).
    consumed_index = 2
    assert await service.verify_backup_code(user, backup_codes[consumed_index]) is True

    expected_remaining = original_hashes[:consumed_index] + original_hashes[consumed_index + 1 :]
    assert user.two_factor_backup_codes_hashed == expected_remaining


@pytest.mark.asyncio
async def test_reset_clears_two_factor_secret_dek_version_to_none() -> None:
    user = _user()
    # Pre-condition: a confirmed enrollment populates the dek_version
    # column.
    _service_, _backup = await _confirmed_user(user)
    assert user.two_factor_secret_dek_version is not None

    service = _service(user)
    await service.reset_user_two_factor(
        user,
        actor_id=uuid4(),
        reason="admin recovery",
    )

    # FR-068 contract: the dek_version slot is cleared so a future
    # rotation reader does not mis-route the (now-empty) secret bytes.
    assert user.two_factor_secret_dek_version is None
    assert user.two_factor_secret_encrypted is None
    assert user.two_factor_backup_codes_hashed is None


def test_encrypt_totp_secret_produces_distinct_ciphertexts_for_same_plaintext() -> None:
    # Two encryptions of an identical plaintext must produce distinct
    # ciphertext blobs — a fresh 12-byte nonce per call (and a fresh DEK
    # per call) guarantees unlinkability across users that happen to share
    # a TOTP secret. Failure here would indicate someone refactored the
    # encrypt path to use a deterministic nonce.
    plaintext_secret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
    blob_a = two_factor_module._encrypt_totp_secret(plaintext_secret)
    blob_b = two_factor_module._encrypt_totp_secret(plaintext_secret)

    assert blob_a != blob_b
    # Both blobs must independently round-trip back to the original
    # plaintext — distinctness without correctness is not enough.
    assert two_factor_module._decrypt_totp_secret(blob_a) == plaintext_secret
    assert two_factor_module._decrypt_totp_secret(blob_b) == plaintext_secret
