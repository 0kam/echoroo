"""Shared constants for unauthenticated / pre-session auth paths.

Both :class:`echoroo.middleware.auth_router.AuthRouterMiddleware` and
:class:`echoroo.middleware.csrf.CsrfMiddleware` need to know which
``/web-api/v1/auth/*`` endpoints are *public* (no session cookie or
CSRF token can possibly be presented yet — the very purpose of these
endpoints is to *create* a session). Keeping the list in one module
prevents the two middleware copies drifting and locking users out of
the login flow (Phase 2.10 #6).

Decision matrix
---------------

* ``/web-api/v1/auth/login``           — pre-session credential check.
* ``/web-api/v1/auth/register``        — pre-session account creation.
* ``/web-api/v1/auth/2fa/challenge``   — pre-session 2FA prompt.
* ``/web-api/v1/auth/2fa/setup/totp``  — pre-session first-login 2FA setup.
* ``/web-api/v1/auth/2fa/setup/totp/confirm`` — pre-session setup confirmation.
* ``/web-api/v1/auth/2fa/webauthn/register`` — pre-session hardware-key setup.
* ``/web-api/v1/auth/2fa/webauthn/challenge`` — pre-session hardware-key challenge.
* ``/web-api/v1/auth/2fa/verify``      — pre-session 2FA confirmation.
* ``/web-api/v1/auth/refresh``         — refresh-token rotation.
* ``/web-api/v1/auth/forgot-password`` — pre-session password reset.
* ``/web-api/v1/auth/reset-password``  — pre-session password reset.

Refresh CSRF decision
---------------------
The refresh endpoint is exempt from CSRF specifically because the
rotation token *itself* is the proof of the request — a CSRF token on
top would require a session cookie that does not yet exist (the user
just received the refresh token from the previous rotation, not a
session id). The cookie-bound CSRF design assumes a steady-state
session; the refresh leg is by construction *between* sessions.

Path matching
-------------
The list is matched **exactly** against ``request.url.path``. No
prefix wildcarding — if Phase 3 introduces sub-paths under
``/web-api/v1/auth/2fa`` (e.g. ``/web-api/v1/auth/2fa/setup``), each
new path MUST be reviewed and added to this list explicitly.
"""

from __future__ import annotations

from typing import Final

#: Tuple of fully-qualified ``request.url.path`` values that bypass
#: both authentication and CSRF enforcement. Order is informational
#: only; both middlewares iterate the tuple linearly.
PUBLIC_AUTH_PATHS: Final[tuple[str, ...]] = (
    "/web-api/v1/auth/login",
    "/web-api/v1/auth/register",
    "/web-api/v1/auth/2fa/challenge",
    "/web-api/v1/auth/2fa/setup/totp",
    "/web-api/v1/auth/2fa/setup/totp/confirm",
    "/web-api/v1/auth/2fa/webauthn/register",
    "/web-api/v1/auth/2fa/webauthn/challenge",
    "/web-api/v1/auth/2fa/verify",
    "/web-api/v1/auth/refresh",
    "/web-api/v1/auth/forgot-password",
    "/web-api/v1/auth/reset-password",
)


def is_public_auth_path(path: str) -> bool:
    """Return True if ``path`` matches a public auth endpoint exactly."""
    return path in PUBLIC_AUTH_PATHS


__all__ = [
    "PUBLIC_AUTH_PATHS",
    "is_public_auth_path",
]
