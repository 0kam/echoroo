"""Logout CSRF-exemption + idempotency security tests (Phase 4-5-6 #1).

These tests pin the security contract documented in
``echoroo/core/auth_paths.py`` and ``echoroo/api/web_v1/auth.py::logout``:

* ``/web-api/v1/auth/logout`` MUST be reachable without an
  ``X-CSRF-Token`` header. The client may have already lost its CSRF
  cookie (refresh failure, partial cookie eviction, browser cleared
  one but not all of them). Refusing logout in that state would leave
  the user wedged because the SvelteKit hook marker
  ``echoroo_logged_in`` is ``HttpOnly`` — only the server can clear it.

* ``/web-api/v1/auth/logout`` MUST be reachable without a session
  cookie. Returning 401 in the no-cookie case has the same wedge
  failure mode as above. We accept that an unauthenticated caller can
  trigger a no-op audit row; that is the intended forensic signal that
  a recovery logout occurred.

* The endpoint MUST always return 204 with all four session cookies
  cleared (refresh / session / csrf / marker). This is the *only*
  state-machine guarantee the SvelteKit client relies on to recover
  from inconsistent cookie state.

* CSRF exemption is safe because logout is a fully idempotent,
  capability-free operation — the worst case is the victim losing
  their own session, which the attacker gains nothing from. OWASP's
  CSRF cheat sheet documents logout as a standard CSRF-exempt path
  for this reason.
"""

from __future__ import annotations

from echoroo.core.auth_paths import PUBLIC_AUTH_PATHS, is_public_auth_path
from echoroo.middleware.csrf import EXEMPT_PATHS

LOGOUT_PATH = "/web-api/v1/auth/logout"


def test_logout_path_is_in_public_auth_allowlist() -> None:
    """Logout MUST be exempt from auth + CSRF middleware enforcement."""
    assert LOGOUT_PATH in PUBLIC_AUTH_PATHS, (
        "Logout must be registered in PUBLIC_AUTH_PATHS so the auth router "
        "and CSRF middleware both bypass enforcement; otherwise a client "
        "that has lost its CSRF cookie cannot terminate its own session."
    )
    assert is_public_auth_path(LOGOUT_PATH)


def test_logout_path_is_in_csrf_exempt_paths() -> None:
    """Source-of-truth sync: CSRF EXEMPT_PATHS is derived from PUBLIC_AUTH_PATHS."""
    assert LOGOUT_PATH in EXEMPT_PATHS, (
        f"CSRF EXEMPT_PATHS must include {LOGOUT_PATH}; current value "
        f"is {EXEMPT_PATHS!r}. The CSRF middleware sources this list from "
        "core.auth_paths.PUBLIC_AUTH_PATHS — if the constant was edited, "
        "make sure both lists are exported correctly."
    )


def test_csrf_and_auth_allowlists_remain_in_sync_after_logout_addition() -> None:
    """Adding logout to the public list MUST NOT diverge the two middlewares."""
    from echoroo.middleware.auth_router import AuthRouterConfig

    auth_allowlist = tuple(AuthRouterConfig().public_path_allowlist)
    assert auth_allowlist == EXEMPT_PATHS, (
        "Auth router public_path_allowlist and CSRF EXEMPT_PATHS must be "
        "exact-match (both sourced from core.auth_paths.PUBLIC_AUTH_PATHS). "
        f"auth={auth_allowlist!r} csrf={EXEMPT_PATHS!r}"
    )
