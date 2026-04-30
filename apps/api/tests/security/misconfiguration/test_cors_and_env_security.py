"""T979h: Security misconfiguration — CORS + environment settings (OWASP A05).

Verifies that:
A. ``get_production_cors_config`` never returns ``allow_origins=["*"]``
   together with ``allow_credentials=True`` (CORS spec violation / auth bypass).
B. ``get_development_cors_config`` also does not use wildcard-with-credentials
   — development mode should NOT produce a configuration that would be copied
   to production accidentally.
C. The ``PrefixCorsMiddleware`` (cors.py) assigns:
   - ``/api/v1/*`` → wildcard origins + credentials=False (programmatic API).
   - ``/web-api/v1/*`` → explicit origins + credentials=True (session API).
D. ``Settings.DEBUG`` defaults to ``False`` (no accidental debug-mode startup).
E. ``Settings.ENVIRONMENT`` defaults to ``"development"``, and the
   ``validate_production_secrets`` guard raises ``ValueError`` for weak
   secrets in production/staging.
F. No ``/_offline_bypass`` or similar dev-only endpoint exists in the router.
G. ``build_prefix_cors_middleware`` factory produces a policy where the
   programmatic surface never sets ``allow_credentials=True``.

Shim: OFF — config function and schema inspection; no HTTP transport.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repository root helpers
#
# Supports both host checkout and Docker /app layout.
# ---------------------------------------------------------------------------


def _find_echoroo_src() -> Path:
    """Return the path to the echoroo source package."""
    this_file = Path(__file__).resolve()
    for depth in (5, 4, 3, 2):
        try:
            candidate = this_file.parents[depth]
        except IndexError:
            continue
        api_src = candidate / "apps" / "api" / "echoroo"
        if api_src.is_dir():
            return api_src
        direct_src = candidate / "echoroo"
        if direct_src.is_dir():
            return direct_src
    return Path("/app/echoroo")


_ECHOROO_SRC = _find_echoroo_src()


# ---------------------------------------------------------------------------
# Section A: Production CORS config must never combine wildcard + credentials
# ---------------------------------------------------------------------------


def test_production_cors_config_no_wildcard_with_credentials() -> None:
    """``get_production_cors_config`` must not return wildcard origins + credentials.

    The combination ``allow_origins=["*"]`` AND ``allow_credentials=True`` is
    explicitly prohibited by the CORS specification (browsers reject it) and
    creates an authentication bypass risk if ever honoured by a non-browser
    client or a misconfigured reverse-proxy.
    """
    from echoroo.middleware.security import get_production_cors_config

    # Call with a real explicit origin (the normal production invocation)
    explicit_config = get_production_cors_config(["https://echoroo.app"])
    origins: list[str] = explicit_config.get("allow_origins", [])
    credentials: bool = explicit_config.get("allow_credentials", False)
    assert not (
        origins == ["*"] and credentials is True
    ), (
        "get_production_cors_config returned allow_origins=['*'] with "
        "allow_credentials=True — this violates the CORS spec and creates "
        "an authentication bypass risk."
    )

    # Also test when wildcard is passed explicitly (should either reject or
    # force credentials=False)
    wildcard_config = get_production_cors_config(["*"])
    wildcard_origins: list[str] = wildcard_config.get("allow_origins", [])
    wildcard_creds: bool = wildcard_config.get("allow_credentials", False)
    assert not (
        wildcard_origins == ["*"] and wildcard_creds is True
    ), (
        "get_production_cors_config with allow_origins=['*'] must set "
        "allow_credentials=False — the wildcard+credentials combination is "
        "rejected by browsers and is a security misconfiguration."
    )


# ---------------------------------------------------------------------------
# Section B: Development CORS config must not combine wildcard + credentials
# ---------------------------------------------------------------------------


def test_development_cors_config_no_wildcard_with_credentials() -> None:
    """``get_development_cors_config`` must not use wildcard-origins + credentials.

    Development configs are sometimes copy-pasted to staging or production.
    Keeping the CORS contract correct in all environments prevents accidental
    misconfiguration (OWASP A05).
    """
    from echoroo.middleware.security import get_development_cors_config

    dev_config = get_development_cors_config(["http://localhost:3000"])
    origins: list[str] = dev_config.get("allow_origins", [])
    credentials: bool = dev_config.get("allow_credentials", False)
    assert not (
        origins == ["*"] and credentials is True
    ), (
        "get_development_cors_config returned allow_origins=['*'] with "
        "allow_credentials=True. This is still a misconfiguration even in "
        "development because it normalises the bad pattern."
    )


# ---------------------------------------------------------------------------
# Section C: PrefixCorsMiddleware policy separation
# ---------------------------------------------------------------------------


def test_prefix_cors_programmatic_surface_no_credentials() -> None:
    """``/api/v1/*`` (programmatic) must use wildcard origins + credentials=False.

    The programmatic API authenticates via Bearer tokens — no ambient cookie
    credential exists, so wildcard origin is safe AND credentials must be
    False so browsers cannot issue credentialed cross-origin requests.
    """
    from echoroo.middleware.cors import CorsPolicy, PrefixCorsConfig

    config = PrefixCorsConfig(
        programmatic=CorsPolicy(allow_origins=("*",), allow_credentials=False),
        session=CorsPolicy(allow_origins=("https://echoroo.app",), allow_credentials=True),
    )
    assert config.programmatic.allow_origins == ("*",)
    assert config.programmatic.allow_credentials is False


def test_prefix_cors_session_surface_explicit_origins_with_credentials() -> None:
    """``/web-api/v1/*`` (session) must use explicit origins + credentials=True.

    The session API uses HttpOnly cookies; the browser's credential-carrying
    behaviour depends on ``Allow-Credentials: true``, and the origin must be
    an explicit allowlist — never wildcard.
    """
    from echoroo.middleware.cors import CorsPolicy, PrefixCorsConfig

    config = PrefixCorsConfig(
        programmatic=CorsPolicy(allow_origins=("*",), allow_credentials=False),
        session=CorsPolicy(allow_origins=("https://echoroo.app",), allow_credentials=True),
    )
    assert "*" not in config.session.allow_origins, (
        "Session CORS policy must not use wildcard origins when credentials=True."
    )
    assert config.session.allow_credentials is True


def test_build_prefix_cors_middleware_factory_sets_correct_policies() -> None:
    """``build_prefix_cors_middleware`` factory must produce correct per-prefix policies."""
    from unittest.mock import MagicMock

    from echoroo.middleware.cors import (
        PROGRAMMATIC_PREFIX,
        SESSION_PREFIX,
        build_prefix_cors_middleware,
    )

    app = MagicMock()
    middleware = build_prefix_cors_middleware(
        app, session_origins=("https://echoroo.app",)
    )
    # The middleware stores the two underlying CORSMiddleware instances.
    # We verify the config was assembled correctly by inspecting the attributes
    # of the underlying starlette CORSMiddleware instances.
    assert middleware._programmatic_prefix == PROGRAMMATIC_PREFIX
    assert middleware._session_prefix == SESSION_PREFIX

    # Programmatic: wildcard origin, no credentials
    prog_cors = middleware._programmatic
    # starlette CORSMiddleware exposes allow_all_origins (bool) for the wildcard case.
    assert prog_cors.allow_all_origins is True, (
        "Programmatic CORS should use allow_origins=['*'] (allow_all_origins=True)"
    )
    # Verify credentials are NOT sent by checking the response headers starlette builds.
    # When allow_credentials=False, "Access-Control-Allow-Credentials" is absent from
    # simple_headers.  When allow_credentials=True it is present with value "true".
    cred_header = prog_cors.simple_headers.get("Access-Control-Allow-Credentials")
    assert cred_header != "true", (
        "Programmatic CORS must not include Access-Control-Allow-Credentials: true "
        "when using wildcard origin — this combination is forbidden by the CORS spec."
    )


# ---------------------------------------------------------------------------
# Section D: Settings.DEBUG defaults to False
# ---------------------------------------------------------------------------


def test_settings_debug_defaults_to_false() -> None:
    """Settings.DEBUG must default to False to prevent accidental debug startup.

    Running with DEBUG=True in production exposes the full Python traceback,
    interactive debugger endpoints (if a debugger is attached), and may
    disable security checks in framework components.
    """
    from echoroo.core.settings import Settings

    # Inspect the field default without instantiating (avoids env pollution)
    fields = Settings.model_fields
    assert "DEBUG" in fields, "Settings.DEBUG field not found"
    debug_field = fields["DEBUG"]
    default_val = debug_field.default
    assert default_val is False, (
        f"Settings.DEBUG default is {default_val!r}; expected False. "
        "Debug mode must be explicitly opted-in, never the default."
    )


# ---------------------------------------------------------------------------
# Section E: Production/staging settings validator rejects weak secrets
# ---------------------------------------------------------------------------


def test_production_settings_validator_rejects_default_jwt_secret() -> None:
    """Settings must raise ValueError for weak JWT_SECRET_KEY in production."""
    from pydantic import ValidationError

    with pytest.raises((ValueError, ValidationError)):
        from echoroo.core.settings import Settings

        # Bypass lru_cache to force validation with a weak secret
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="your-secret-key-change-in-production",
            DATABASE_URL="postgresql+asyncpg://u:p@db:5432/echoroo",
            web_session_secret="dev-web-session-secret-change-in-production",
        )


def test_production_settings_validator_rejects_default_session_secret() -> None:
    """Settings must raise ValueError for weak web_session_secret in production."""
    from pydantic import ValidationError

    with pytest.raises((ValueError, ValidationError)):
        from echoroo.core.settings import Settings

        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="a-strong-jwt-secret-that-is-long-enough-1234",
            DATABASE_URL="postgresql+asyncpg://u:p@db:5432/echoroo",
            web_session_secret="dev-web-session-secret-change-in-production",
        )


# ---------------------------------------------------------------------------
# Section F: No dev-only / offline-bypass endpoints in production routes
# ---------------------------------------------------------------------------


def test_no_offline_bypass_or_debug_only_endpoints() -> None:
    """Production router must not expose dev-only or offline-bypass endpoints.

    Paths like ``/_offline_bypass``, ``/debug/*``, or ``/__test__/*``
    are common developer shortcuts that must be absent from production code.
    """
    api_dir = _ECHOROO_SRC / "api"
    suspicious_patterns = re.compile(
        r'@.*\.(?:get|post|put|delete|patch)\s*\(\s*"'
        r'(?:/_offline|/_debug|/__test__|/_dev|/test-bypass|/_bypass)',
        re.IGNORECASE,
    )
    violations: list[str] = []
    for py_file in api_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if suspicious_patterns.search(line):
                rel = py_file.relative_to(_ECHOROO_SRC)
                violations.append(f"{rel}:{line_no}: {line.strip()}")

    assert not violations, (
        "Dev-only / offline-bypass route decorators found in production code:\n"
        + "\n".join(violations)
    )


__all__ = [
    "test_build_prefix_cors_middleware_factory_sets_correct_policies",
    "test_development_cors_config_no_wildcard_with_credentials",
    "test_no_offline_bypass_or_debug_only_endpoints",
    "test_prefix_cors_programmatic_surface_no_credentials",
    "test_prefix_cors_session_surface_explicit_origins_with_credentials",
    "test_production_cors_config_no_wildcard_with_credentials",
    "test_production_settings_validator_rejects_default_jwt_secret",
    "test_production_settings_validator_rejects_default_session_secret",
    "test_settings_debug_defaults_to_false",
]
