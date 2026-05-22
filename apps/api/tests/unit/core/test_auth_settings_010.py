"""Spec 010 settings contract tests for trusted devices.

spec/011 Step 10 (carry-over #4) removed the
``EMAIL_VERIFICATION_ENFORCEMENT_ENABLED`` /
``EMAIL_VERIFICATION_TOKEN_TTL_SECONDS`` /
``EMAIL_VERIFICATION_RESEND_ACTIVE_TOKEN_CAP`` settings alongside the
email-verification subsystem (FR-011-006). The trusted-device defaults
introduced by spec/010 (``TRUSTED_DEVICE_*``) survive the cut and remain
under contract here.
"""

from __future__ import annotations

import pytest

from echoroo.core.settings import Settings, get_settings

_NEW_SETTING_ENV_VARS = (
    "TRUSTED_DEVICE_REGISTRATION_ENABLED",
    "TRUSTED_DEVICE_BYPASS_ENABLED",
    "TRUSTED_DEVICE_COOKIE_NAME",
    "TRUSTED_DEVICE_COOKIE_TTL_SECONDS",
)


@pytest.fixture(autouse=True)
def _clear_spec_010_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _NEW_SETTING_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_spec_010_trusted_device_cookie_defaults_match_security_contract() -> None:
    settings = Settings()

    assert settings.TRUSTED_DEVICE_COOKIE_NAME == "echoroo_trusted_device"
    assert settings.TRUSTED_DEVICE_COOKIE_TTL_SECONDS == 30 * 24 * 3600
    assert settings.TRUSTED_DEVICE_COOKIE_TTL_SECONDS <= 30 * 24 * 3600


def test_spec_010_get_settings_exposes_new_defaults() -> None:
    """Trusted-device defaults survive spec/011 Step 10.

    The email-verification settings (``EMAIL_VERIFICATION_*``) were
    removed in spec/011 Step 10 (FR-011-006); only the trusted-device
    cookie defaults remain under this contract.
    """
    settings = get_settings()

    assert settings.TRUSTED_DEVICE_REGISTRATION_ENABLED is False
    assert settings.TRUSTED_DEVICE_BYPASS_ENABLED is False
    assert settings.TRUSTED_DEVICE_COOKIE_NAME == "echoroo_trusted_device"
