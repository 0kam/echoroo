"""Settings contract tests for spec/011 NFR-011-010.

These tests pin the invitation-token kid + HMAC env vars and the
co-presence / strength validator that mirrors the Phase 17 A-12 pattern
on ``two_factor_reset_confirmation_hmac_*``.

The model validator MUST:

1. Require ``KID_NEW`` + ``HMAC_KEY`` to be non-empty in EVERY
   environment (dev + staging + prod) — spec is explicit that these
   are "required at every boot".
2. Accept either both ``_OLD`` slots set OR both unset (dev + prod).
3. Reject if only ONE of the ``_OLD`` slots is set (dev + prod).
4. Reject ``_OLD`` kid equal to ``_NEW`` kid in every environment.
5. Reject short ``_NEW`` and short ``_OLD`` HMAC keys in production /
   staging only (the 32-char minimum is the env-conditional bar).

Additionally the ``mode="before"`` field validators MUST:

* Reject any kid that does not match ``^[A-Za-z0-9_-]+$`` — the
  envelope ``{token}.{exp}.{kid}.{mac}`` parses by splitting on ``.``
  so a dot inside the kid would silently break verification.
* Normalise whitespace-only kids to "unset" (None for ``_OLD``, empty
  string for ``_NEW`` so the env-aware non-empty guard fires).
* Normalise empty / whitespace ``HMAC_KEY_OLD`` to ``None``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from echoroo.core.settings import Settings, get_settings

# A 32+ char strong secret used wherever we need a passing key value.
_STRONG_KEY = "x" * 48
_STRONG_KEY_ALT = "y" * 48
_STRONG_JWT_KEY = "j" * 48
_STRONG_WEB_SESSION = "w" * 48
_STRONG_TWOFA = "t" * 48

# Every spec/011 env var the validator looks at — plus the existing
# production-secret guards that fire together when ENVIRONMENT is
# "production" or "staging". The tests below populate this dictionary
# and then patch each key into the env.
_INVITATION_ENV_VARS = (
    "INVITATION_TOKEN_KID_NEW",
    "INVITATION_TOKEN_KID_OLD",
    "INVITATION_TOKEN_KID_GRACE_HOURS",
    "INVITATION_TOKEN_HMAC_KEY",
    "INVITATION_TOKEN_HMAC_KEY_OLD",
)

# Production-secret guards that share the same ``model_validator`` —
# without these set to strong values the validator trips on the older
# ``JWT_SECRET_KEY`` / ``web_session_secret`` / ``S3_SECRET_KEY`` / 2FA
# HMAC key checks before reaching the invitation-token block.
_PROD_PREREQ_ENV_VARS = {
    "JWT_SECRET_KEY": _STRONG_JWT_KEY,
    # Plain lowercase env var, no validation_alias on the field — must
    # match the case-sensitive Pydantic Settings binding exactly.
    "web_session_secret": _STRONG_WEB_SESSION,
    "S3_SECRET_KEY": "totally-strong-s3-secret",
    "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY": _STRONG_TWOFA,
}


@pytest.fixture(autouse=True)
def _clear_invitation_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset cached settings and any pre-existing env for each test."""
    for name in _INVITATION_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name in _PROD_PREREQ_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_prod_prerequisites(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply strong defaults for every non-spec/011 production guard."""
    for key, value in _PROD_PREREQ_ENV_VARS.items():
        monkeypatch.setenv(key, value)


def _set_dev_minimums(
    monkeypatch: pytest.MonkeyPatch,
    *,
    kid_new: str = "spec011-v2",
    hmac_key: str = _STRONG_KEY,
) -> None:
    """Apply the minimum spec/011 envs required for a dev boot.

    The model validator now requires ``KID_NEW`` + ``HMAC_KEY`` in
    every environment (NFR-011-010 "required at every boot"), so
    co-presence / distinct-kid tests that previously relied on the
    default empty string must seed both slots first.
    """
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", kid_new)
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", hmac_key)


# ---------------------------------------------------------------------------
# Field defaults + presence
# ---------------------------------------------------------------------------


def test_invitation_token_settings_have_expected_defaults() -> None:
    """Raw field defaults (no env, no model validator run)."""
    # We can't instantiate Settings() at dev environment without
    # KID_NEW + HMAC_KEY anymore (validator rejects the empty default),
    # so check the class-level defaults instead.
    fields = Settings.model_fields
    assert fields["invitation_token_kid_new"].default == ""
    assert fields["invitation_token_kid_old"].default is None
    assert fields["invitation_token_kid_grace_hours"].default == 24
    assert fields["invitation_token_hmac_key"].default == ""
    assert fields["invitation_token_hmac_key_old"].default is None


def test_invitation_token_env_vars_bind_via_validation_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "spec011-v2")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)
    monkeypatch.setenv("INVITATION_TOKEN_KID_GRACE_HOURS", "48")

    settings = Settings(ENVIRONMENT="development")

    assert settings.invitation_token_kid_new == "spec011-v2"
    assert settings.invitation_token_hmac_key == _STRONG_KEY
    assert settings.invitation_token_kid_grace_hours == 48


# ---------------------------------------------------------------------------
# Non-empty guards (active in every environment)
# ---------------------------------------------------------------------------


def test_empty_kid_new_rejects_boot_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)
    # KID_NEW intentionally left empty (default).

    with pytest.raises(ValueError, match="INVITATION_TOKEN_KID_NEW"):
        Settings(ENVIRONMENT="development")


def test_empty_hmac_key_rejects_boot_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "spec011-v2")
    # HMAC_KEY intentionally left empty (default).

    with pytest.raises(ValueError, match="INVITATION_TOKEN_HMAC_KEY"):
        Settings(ENVIRONMENT="development")


# ---------------------------------------------------------------------------
# Co-presence validator (active in every environment)
# ---------------------------------------------------------------------------


def test_old_kid_without_old_hmac_raises_co_presence_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dev_minimums(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_KID_OLD", "spec011-v0")
    # HMAC_KEY_OLD intentionally unset.

    with pytest.raises(ValueError, match="must be set together"):
        Settings(ENVIRONMENT="development")


def test_old_hmac_without_old_kid_raises_co_presence_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dev_minimums(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY_OLD", _STRONG_KEY)
    # KID_OLD intentionally unset.

    with pytest.raises(ValueError, match="must be set together"):
        Settings(ENVIRONMENT="development")


def test_both_old_unset_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dev_minimums(monkeypatch)
    # No rotation in progress.
    Settings(ENVIRONMENT="development")


def test_both_old_set_with_distinct_kids_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "spec011-v2")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)
    monkeypatch.setenv("INVITATION_TOKEN_KID_OLD", "spec011-v1")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY_OLD", _STRONG_KEY_ALT)

    settings = Settings(ENVIRONMENT="development")

    assert settings.invitation_token_kid_new == "spec011-v2"
    assert settings.invitation_token_kid_old == "spec011-v1"


def test_old_kid_equal_to_new_kid_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "spec011-v1")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)
    monkeypatch.setenv("INVITATION_TOKEN_KID_OLD", "spec011-v1")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY_OLD", _STRONG_KEY_ALT)

    with pytest.raises(ValueError, match="must differ from"):
        Settings(ENVIRONMENT="development")


# ---------------------------------------------------------------------------
# kid format validator (mode="before")
# ---------------------------------------------------------------------------


def test_whitespace_only_kid_new_normalises_to_empty_and_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only KID_NEW collapses to "" and trips the non-empty guard."""
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "   ")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)

    with pytest.raises(ValueError, match="INVITATION_TOKEN_KID_NEW"):
        Settings(ENVIRONMENT="development")


def test_dot_in_kid_new_rejected_as_invalid_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dot inside the kid would break the 4-part envelope rsplit."""
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "v.1")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)

    with pytest.raises(ValueError, match=r"\[A-Za-z0-9_-\]\+"):
        Settings(ENVIRONMENT="development")


def test_url_safe_underscore_and_hyphen_in_kid_new_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Underscore and hyphen are inside the allowed character class."""
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "spec_011-v2")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)

    settings = Settings(ENVIRONMENT="development")
    assert settings.invitation_token_kid_new == "spec_011-v2"


def test_whitespace_only_kid_old_normalises_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only KID_OLD collapses to None (no rotation)."""
    _set_dev_minimums(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_KID_OLD", "   ")
    # HMAC_KEY_OLD unset — co-presence guard should NOT fire because
    # KID_OLD normalised to None.

    settings = Settings(ENVIRONMENT="development")
    assert settings.invitation_token_kid_old is None


def test_dot_in_kid_old_rejected_as_invalid_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dev_minimums(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_KID_OLD", "spec.011")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY_OLD", _STRONG_KEY_ALT)

    with pytest.raises(ValueError, match=r"\[A-Za-z0-9_-\]\+"):
        Settings(ENVIRONMENT="development")


def test_empty_hmac_key_old_normalises_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty HMAC_KEY_OLD (e.g. .env stub) normalises to None."""
    _set_dev_minimums(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY_OLD", "")
    # KID_OLD unset — co-presence should NOT fire because the empty
    # HMAC slot normalised to None.

    settings = Settings(ENVIRONMENT="development")
    assert settings.invitation_token_hmac_key_old is None


# ---------------------------------------------------------------------------
# Production / staging strength + presence guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env_name", ["production", "staging"])
def test_empty_kid_new_rejects_boot_in_prod_staging(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    _set_prod_prerequisites(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)
    # KID_NEW intentionally left empty (default).

    with pytest.raises(ValueError, match="INVITATION_TOKEN_KID_NEW"):
        Settings(ENVIRONMENT=env_name)


@pytest.mark.parametrize("env_name", ["production", "staging"])
def test_empty_hmac_key_rejects_boot_in_prod_staging(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    _set_prod_prerequisites(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "spec011-v1")
    # HMAC_KEY intentionally left empty (default).

    with pytest.raises(ValueError, match="INVITATION_TOKEN_HMAC_KEY"):
        Settings(ENVIRONMENT=env_name)


@pytest.mark.parametrize("env_name", ["production", "staging"])
def test_short_hmac_key_rejects_boot_in_prod_staging(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    _set_prod_prerequisites(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "spec011-v1")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", "tooshort")

    with pytest.raises(ValueError, match="INVITATION_TOKEN_HMAC_KEY"):
        Settings(ENVIRONMENT=env_name)


@pytest.mark.parametrize("env_name", ["production", "staging"])
def test_short_old_hmac_key_rejects_boot_in_prod_staging(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    _set_prod_prerequisites(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "spec011-v2")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)
    monkeypatch.setenv("INVITATION_TOKEN_KID_OLD", "spec011-v1")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY_OLD", "tooshort")

    with pytest.raises(ValueError, match="INVITATION_TOKEN_HMAC_KEY_OLD"):
        Settings(ENVIRONMENT=env_name)


@pytest.mark.parametrize("env_name", ["production", "staging"])
def test_strong_keys_pass_prod_staging_boot(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    _set_prod_prerequisites(monkeypatch)
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "spec011-v2")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)
    monkeypatch.setenv("INVITATION_TOKEN_KID_OLD", "spec011-v1")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY_OLD", _STRONG_KEY_ALT)

    settings = Settings(ENVIRONMENT=env_name)

    assert settings.invitation_token_kid_new == "spec011-v2"
    assert settings.invitation_token_kid_old == "spec011-v1"
    assert settings.invitation_token_hmac_key == _STRONG_KEY
    assert settings.invitation_token_hmac_key_old == _STRONG_KEY_ALT


# ---------------------------------------------------------------------------
# Dev-only relaxation: 32-char minimum HMAC strength is prod/staging-gated.
# ---------------------------------------------------------------------------


def test_dev_accepts_short_hmac_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev / test env allows short HMAC fixtures (<32 chars).

    The 32-char minimum is the only env-conditional bar (NFR-011-010);
    dev / test workflows are explicitly permitted weaker fixtures so
    pytest collection does not require operator-grade secrets. Co-presence
    + non-empty + distinct-kid guards still run in every environment
    (covered by the other tests in this module).
    """
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "dev-kid")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", "short")  # <32 chars

    settings = Settings(ENVIRONMENT="development")

    assert settings.invitation_token_hmac_key == "short"
    assert settings.invitation_token_kid_new == "dev-kid"


def test_dev_accepts_short_hmac_key_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev / test env also accepts a short HMAC_KEY_OLD during a rotation.

    Mirrors ``test_dev_accepts_short_hmac_key`` for the ``_OLD`` rotation
    slot — the 32-char strength bar is prod/staging-only; co-presence
    (KID_OLD + HMAC_KEY_OLD set together) is still enforced in dev.
    """
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "dev-kid-v2")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)
    monkeypatch.setenv("INVITATION_TOKEN_KID_OLD", "dev-kid-v1")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY_OLD", "short-old")  # <32 chars

    settings = Settings(ENVIRONMENT="development")

    assert settings.invitation_token_hmac_key_old == "short-old"
    assert settings.invitation_token_kid_old == "dev-kid-v1"
