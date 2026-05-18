"""Spec 010 settings contract tests for email verification and trusted devices.

These tests should fail until T014 adds the rollout and cookie/rate-limit
settings to ``echoroo.core.settings.Settings``.
"""

from __future__ import annotations

import pytest

from echoroo.core.settings import Settings, get_settings

_NEW_SETTING_ENV_VARS = (
    "EMAIL_VERIFICATION_ENFORCEMENT_ENABLED",
    "TRUSTED_DEVICE_REGISTRATION_ENABLED",
    "TRUSTED_DEVICE_BYPASS_ENABLED",
    "TRUSTED_DEVICE_COOKIE_NAME",
    "TRUSTED_DEVICE_COOKIE_TTL_SECONDS",
    "EMAIL_VERIFICATION_TOKEN_TTL_SECONDS",
    "EMAIL_VERIFICATION_RESEND_ACTIVE_TOKEN_CAP",
)


@pytest.fixture(autouse=True)
def _clear_spec_010_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _NEW_SETTING_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_spec_010_rollout_flags_default_to_disabled() -> None:
    settings = Settings()

    assert settings.EMAIL_VERIFICATION_ENFORCEMENT_ENABLED is False
    assert settings.TRUSTED_DEVICE_REGISTRATION_ENABLED is False
    assert settings.TRUSTED_DEVICE_BYPASS_ENABLED is False


def test_spec_010_rollout_flags_can_be_enabled_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_VERIFICATION_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("TRUSTED_DEVICE_REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("TRUSTED_DEVICE_BYPASS_ENABLED", "false")

    settings = Settings()

    assert settings.EMAIL_VERIFICATION_ENFORCEMENT_ENABLED is True
    assert settings.TRUSTED_DEVICE_REGISTRATION_ENABLED is True
    assert settings.TRUSTED_DEVICE_BYPASS_ENABLED is False


def test_spec_010_trusted_device_cookie_defaults_match_security_contract() -> None:
    settings = Settings()

    assert settings.TRUSTED_DEVICE_COOKIE_NAME == "echoroo_trusted_device"
    assert settings.TRUSTED_DEVICE_COOKIE_TTL_SECONDS == 30 * 24 * 3600
    assert settings.TRUSTED_DEVICE_COOKIE_TTL_SECONDS <= 30 * 24 * 3600


def test_spec_010_email_verification_ttl_and_resend_cap_defaults() -> None:
    settings = Settings()

    assert settings.EMAIL_VERIFICATION_TOKEN_TTL_SECONDS == 24 * 3600
    assert settings.EMAIL_VERIFICATION_RESEND_ACTIVE_TOKEN_CAP == 1


def test_spec_010_get_settings_exposes_new_defaults() -> None:
    settings = get_settings()

    assert settings.EMAIL_VERIFICATION_ENFORCEMENT_ENABLED is False
    assert settings.TRUSTED_DEVICE_REGISTRATION_ENABLED is False
    assert settings.TRUSTED_DEVICE_BYPASS_ENABLED is False
    assert settings.TRUSTED_DEVICE_COOKIE_NAME == "echoroo_trusted_device"
