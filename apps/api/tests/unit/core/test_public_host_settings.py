"""Settings derivation tests for ``ECHOROO_PUBLIC_HOST``.

A single browser-facing host knob (``ECHOROO_PUBLIC_HOST``, a bare
hostname/IP, default ``localhost``) drives the *default* values of the
WebAuthn RP ID + origins and the CORS ``ALLOWED_ORIGINS`` list when those
are not explicitly overridden. These tests pin the contract:

1. Default (``localhost``): derived values are byte-identical to the
   historical hard-coded defaults (backward compatibility).
2. Explicit override always wins — an env value / constructor arg for
   ``ALLOWED_ORIGINS`` / ``ECHOROO_WEBAUTHN_RP_ID`` / ``ECHOROO_WEBAUTHN_ORIGINS``
   is never clobbered by the derivation.
3. A non-localhost host derives the bare-host RP ID and dual-origin
   (public host AND localhost) CORS + WebAuthn origin lists.
4. The CORS list de-dupes (order preserved) so a compose-appended
   duplicate collapses cleanly.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from echoroo.core.settings import Settings, get_settings

# Minimum env required for a dev boot (the invitation-token validator runs
# in every environment; see test_invitation_token_kid_settings.py).
_STRONG_KEY = "x" * 48

_PUBLIC_HOST_ENV_VARS = (
    "ECHOROO_PUBLIC_HOST",
    "ECHOROO_WEBAUTHN_RP_ID",
    "ECHOROO_WEBAUTHN_ORIGINS",
    "ALLOWED_ORIGINS",
)


@pytest.fixture(autouse=True)
def _clear_public_host_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset cached settings + any pre-existing env for each test."""
    for name in _PUBLIC_HOST_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    # spec/011 invitation-token validator runs at every boot.
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", "test-kid")
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", _STRONG_KEY)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Field default + binding
# ---------------------------------------------------------------------------


def test_public_host_field_default_is_localhost() -> None:
    assert Settings.model_fields["echoroo_public_host"].default == "localhost"


def test_public_host_binds_via_validation_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ECHOROO_PUBLIC_HOST", "192.0.2.10")

    settings = Settings(ENVIRONMENT="development")

    assert settings.echoroo_public_host == "192.0.2.10"


# ---------------------------------------------------------------------------
# Default (localhost) — backward compatibility
# ---------------------------------------------------------------------------


def test_default_localhost_derives_historical_defaults() -> None:
    """Unset PUBLIC_HOST → byte-identical to the pre-change defaults."""
    settings = Settings(ENVIRONMENT="development")

    assert settings.webauthn_rp_id == "localhost"
    assert settings.webauthn_origins == ["http://localhost:3000"]
    assert settings.ALLOWED_ORIGINS == [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


# ---------------------------------------------------------------------------
# Non-localhost host — derivation + dual-origin
# ---------------------------------------------------------------------------


def test_ip_host_derives_bare_rp_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RP ID is the BARE host (no scheme / port)."""
    monkeypatch.setenv("ECHOROO_PUBLIC_HOST", "192.0.2.10")

    settings = Settings(ENVIRONMENT="development")

    assert settings.webauthn_rp_id == "192.0.2.10"


def test_ip_host_derives_dual_webauthn_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WebAuthn origins keep localhost AND append the public host."""
    monkeypatch.setenv("ECHOROO_PUBLIC_HOST", "192.0.2.10")

    settings = Settings(ENVIRONMENT="development")

    assert settings.webauthn_origins == [
        "http://localhost:3000",
        "http://192.0.2.10:3000",
    ]


def test_ip_host_derives_dual_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORS origins keep both localhost ports AND append the public host."""
    monkeypatch.setenv("ECHOROO_PUBLIC_HOST", "192.0.2.10")

    settings = Settings(ENVIRONMENT="development")

    assert settings.ALLOWED_ORIGINS == [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://192.0.2.10:5173",
        "http://192.0.2.10:3000",
    ]
    # Dual-origin guarantee: localhost MUST still be present so SSH
    # port-forward users (who arrive as localhost) keep working.
    assert "http://localhost:5173" in settings.ALLOWED_ORIGINS
    assert "http://localhost:3000" in settings.ALLOWED_ORIGINS


def test_fqdn_host_derives_dual_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ECHOROO_PUBLIC_HOST", "echoroo.example.org")

    settings = Settings(ENVIRONMENT="development")

    assert settings.webauthn_rp_id == "echoroo.example.org"
    assert "http://echoroo.example.org:5173" in settings.ALLOWED_ORIGINS
    assert "http://localhost:5173" in settings.ALLOWED_ORIGINS


# ---------------------------------------------------------------------------
# Explicit override always wins
# ---------------------------------------------------------------------------


def test_explicit_allowed_origins_overrides_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ALLOWED_ORIGINS env value is never clobbered."""
    monkeypatch.setenv("ECHOROO_PUBLIC_HOST", "192.0.2.10")
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        '["http://localhost:5173","http://localhost:3000",'
        '"http://frontend:5173","http://192.0.2.10:5173"]',
    )

    settings = Settings(ENVIRONMENT="development")

    # The container-internal entry survives — derivation did NOT replace it.
    assert "http://frontend:5173" in settings.ALLOWED_ORIGINS
    assert settings.ALLOWED_ORIGINS == [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://frontend:5173",
        "http://192.0.2.10:5173",
    ]


def test_explicit_webauthn_rp_id_overrides_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ECHOROO_PUBLIC_HOST", "192.0.2.10")
    monkeypatch.setenv("ECHOROO_WEBAUTHN_RP_ID", "echoroo.app")

    settings = Settings(ENVIRONMENT="development")

    assert settings.webauthn_rp_id == "echoroo.app"


def test_explicit_webauthn_origins_overrides_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ECHOROO_PUBLIC_HOST", "192.0.2.10")
    monkeypatch.setenv(
        "ECHOROO_WEBAUTHN_ORIGINS", "https://echoroo.app,https://www.echoroo.app"
    )

    settings = Settings(ENVIRONMENT="development")

    assert settings.webauthn_origins == [
        "https://echoroo.app",
        "https://www.echoroo.app",
    ]


# ---------------------------------------------------------------------------
# Compose appends a duplicate localhost origin → de-dupe collapses it
# ---------------------------------------------------------------------------


def test_allowed_origins_dedupes_order_preserving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The compose-appended duplicate localhost origin collapses cleanly.

    ``compose.dev.yaml`` appends ``http://${ECHOROO_PUBLIC_HOST}:5173`` to
    the explicit list; when the host is the default localhost that equals an
    existing entry. The field validator de-dupes (first-seen order) so the
    effective allowlist is byte-identical to the pre-change default.
    """
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        '["http://localhost:5173","http://localhost:3000",'
        '"http://frontend:5173","http://localhost:5173"]',
    )

    settings = Settings(ENVIRONMENT="development")

    assert settings.ALLOWED_ORIGINS == [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://frontend:5173",
    ]
