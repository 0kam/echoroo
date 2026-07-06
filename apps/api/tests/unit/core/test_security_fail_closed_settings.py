"""W4-2 — production guards for the two security fail-closed switches.

``ECHOROO_AUTH_REVOCATION_FAIL_CLOSED`` (SFR-2) and
``ECHOROO_HIBP_FAIL_OPEN`` (SFR-6) exist only as dev / offline escape
hatches. The settings ``model_validator`` MUST refuse the *insecure*
setting when ``ENVIRONMENT == "production"``:

* ``ECHOROO_AUTH_REVOCATION_FAIL_CLOSED=false`` -> rejected in production.
* ``ECHOROO_HIBP_FAIL_OPEN=true`` -> rejected in production.

Both settings retain their defaults (fail-closed) and are freely
overridable in development.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from echoroo.core.settings import Settings, get_settings

# Strong secrets so the pre-existing production-secret guards (which share
# the same model_validator) pass before we reach the W4-2 guards.
_STRONG = "x" * 48
_STRONG_ALT = "y" * 48

# Every production-guard prerequisite the model_validator inspects. Mirrors
# tests/unit/core/test_invitation_token_kid_settings.py so a bare
# ``Settings(ENVIRONMENT="production")`` boots cleanly.
_PROD_ENV_VARS = {
    "JWT_SECRET_KEY": "j" * 48,
    # Plain lowercase env var (no validation_alias on the field).
    "web_session_secret": "w" * 48,
    "S3_SECRET_KEY": "totally-strong-s3-secret",
    "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY": "t" * 48,
    "INVITATION_TOKEN_KID_NEW": "w4-2-kid",
    "INVITATION_TOKEN_HMAC_KEY": _STRONG,
}

_W4_2_ENV_VARS = (
    "ECHOROO_AUTH_REVOCATION_FAIL_CLOSED",
    "ECHOROO_HIBP_FAIL_OPEN",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (*_PROD_ENV_VARS, *_W4_2_ENV_VARS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_prod_prereqs(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _PROD_ENV_VARS.items():
        monkeypatch.setenv(key, value)


# ---------------------------------------------------------------------------
# Defaults are fail-closed
# ---------------------------------------------------------------------------


def test_defaults_are_fail_closed() -> None:
    fields = Settings.model_fields
    assert fields["ECHOROO_AUTH_REVOCATION_FAIL_CLOSED"].default is True
    assert fields["ECHOROO_HIBP_FAIL_OPEN"].default is False


def test_production_baseline_boots_with_secure_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_prod_prereqs(monkeypatch)

    settings = Settings(ENVIRONMENT="production")

    assert settings.ECHOROO_AUTH_REVOCATION_FAIL_CLOSED is True
    assert settings.ECHOROO_HIBP_FAIL_OPEN is False


# ---------------------------------------------------------------------------
# Production guards
# ---------------------------------------------------------------------------


def test_revocation_fail_open_rejected_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_prod_prereqs(monkeypatch)
    monkeypatch.setenv("ECHOROO_AUTH_REVOCATION_FAIL_CLOSED", "false")

    with pytest.raises(ValueError, match="ECHOROO_AUTH_REVOCATION_FAIL_CLOSED"):
        Settings(ENVIRONMENT="production")


def test_hibp_fail_open_rejected_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_prod_prereqs(monkeypatch)
    monkeypatch.setenv("ECHOROO_HIBP_FAIL_OPEN", "true")

    with pytest.raises(ValueError, match="ECHOROO_HIBP_FAIL_OPEN"):
        Settings(ENVIRONMENT="production")


# ---------------------------------------------------------------------------
# Dev escape hatch is permitted
# ---------------------------------------------------------------------------


def test_revocation_fail_open_allowed_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "dev-kid")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", "short")
    monkeypatch.setenv("ECHOROO_AUTH_REVOCATION_FAIL_CLOSED", "false")

    settings = Settings(ENVIRONMENT="development")

    assert settings.ECHOROO_AUTH_REVOCATION_FAIL_CLOSED is False


def test_hibp_fail_open_allowed_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "dev-kid")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", "short")
    monkeypatch.setenv("ECHOROO_HIBP_FAIL_OPEN", "true")

    settings = Settings(ENVIRONMENT="development")

    assert settings.ECHOROO_HIBP_FAIL_OPEN is True
