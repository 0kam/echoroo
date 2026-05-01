"""Step-up token service for destructive admin actions (Phase 16 Batch 6g-3).

Phase 15 Batch 5b R2 introduced a frontend-only WebAuthn UX gate
(``ensureHardwareKeyPresence``) for destructive superuser actions because
the backend admin endpoints did not yet require an assertion payload.
That left a real attacker path open: a stolen first-party session
cookie + CSRF token could still drive an admin mutation as long as the
browser never spoke to the user's hardware key.

Phase 16 Batch 6g-3 closes that gap by introducing a **step-up token**.
After a fresh WebAuthn assertion ceremony succeeds the API returns a
short-lived (5 min) JWT bound to the asserted user + assertion id +
operational scope.  Each destructive admin endpoint gates on
:func:`echoroo.middleware.step_up.require_step_up_token` which decodes
the token, asserts the scope matches, and refuses the request when the
header is missing / expired / for the wrong user.

Token shape
-----------
The token is a HS256 JWT signed with ``settings.web_session_secret``
(reusing the same secret that protects the interim 2FA tokens). The
payload is::

    {
      "sub": "<user_id uuid>",
      "type": "step_up",
      "scope": "admin_destructive",
      "ss":   "<security_stamp at issuance>",
      "aid":  "<assertion_id uuid issued by webauthn_service>",
      "jti":  "<random uuid>",
      "iat":  <unix_ts>,
      "exp":  <unix_ts + 300>
    }

Security stamp + assertion id keep the token tightly bound to the
ceremony that produced it: rotating ``security_stamp`` (e.g. on password
reset / 2FA reset) immediately invalidates outstanding step-up tokens,
matching the behaviour of session refresh tokens.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import jwt

from echoroo.core.settings import get_settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Token type discriminator for JWTs minted by this service.
STEP_UP_TOKEN_TYPE: Final[str] = "step_up"

#: Default scope used for every destructive superuser admin endpoint.
SCOPE_ADMIN_DESTRUCTIVE: Final[str] = "admin_destructive"

#: TTL for a freshly minted step-up token. 5 minutes mirrors the
#: ``webauthn_interim_token_ttl_seconds`` window used elsewhere in
#: the WebAuthn ceremony chain.
STEP_UP_TOKEN_TTL_SECONDS: Final[int] = 300


class StepUpTokenError(Exception):
    """Base class for step-up-token decode failures."""

    error_code: str = "step_up_token_invalid"


class StepUpTokenInvalidError(StepUpTokenError):
    """Signature / structural failures (bad type, missing claims, etc.)."""

    error_code = "step_up_token_invalid"


class StepUpTokenExpiredError(StepUpTokenError):
    """The token's ``exp`` claim is in the past."""

    error_code = "step_up_token_expired"


class StepUpTokenScopeMismatchError(StepUpTokenError):
    """The decoded scope does not match the gate's expected scope."""

    error_code = "step_up_token_scope_mismatch"


# ---------------------------------------------------------------------------
# Claims dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepUpTokenClaims:
    """Decoded claims surface for a successfully validated step-up token."""

    user_id: UUID
    scope: str
    security_stamp: str
    assertion_id: str
    jti: str
    issued_at: datetime
    expires_at: datetime


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def issue_step_up_token(
    *,
    user_id: UUID,
    security_stamp: str,
    assertion_id: str,
    scope: str = SCOPE_ADMIN_DESTRUCTIVE,
    ttl_seconds: int = STEP_UP_TOKEN_TTL_SECONDS,
) -> tuple[str, datetime]:
    """Mint a HS256 JWT bound to ``user_id`` + ``assertion_id`` + ``scope``.

    Returns a ``(token, expires_at)`` tuple. The expiry is exposed
    separately so the WebAuthn verify endpoint can advertise it on the
    response body without requiring callers to re-decode the JWT.

    Both ``user_id`` and ``assertion_id`` are coerced to ``str`` for the
    JWT payload because the underlying library does not accept ``UUID``
    natively.
    """
    settings = get_settings()
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=ttl_seconds)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": STEP_UP_TOKEN_TYPE,
        "scope": scope,
        "ss": security_stamp,
        "aid": assertion_id,
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(
        payload,
        settings.web_session_secret,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, expires_at


def verify_step_up_token(
    raw_token: str,
    *,
    expected_scope: str = SCOPE_ADMIN_DESTRUCTIVE,
) -> StepUpTokenClaims:
    """Decode + validate a step-up token.

    Raises:
        StepUpTokenInvalidError: signature / shape failures.
        StepUpTokenExpiredError: ``exp`` claim already passed.
        StepUpTokenScopeMismatchError: ``scope`` claim mismatch.
    """
    settings = get_settings()
    if not isinstance(raw_token, str) or not raw_token:
        raise StepUpTokenInvalidError("step_up token is missing")
    try:
        payload: dict[str, Any] = jwt.decode(
            raw_token,
            settings.web_session_secret,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise StepUpTokenExpiredError("step_up token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise StepUpTokenInvalidError("step_up token invalid") from exc

    if payload.get("type") != STEP_UP_TOKEN_TYPE:
        raise StepUpTokenInvalidError("step_up token type mismatch")

    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise StepUpTokenInvalidError("step_up token subject missing")
    try:
        user_id = UUID(sub)
    except ValueError as exc:
        raise StepUpTokenInvalidError("step_up token subject invalid") from exc

    scope = payload.get("scope")
    if not isinstance(scope, str) or not scope:
        raise StepUpTokenInvalidError("step_up token scope missing")
    # Use ``secrets.compare_digest`` so a malicious proxy that flips a
    # single byte cannot leak position via timing.
    if not secrets.compare_digest(scope, expected_scope):
        raise StepUpTokenScopeMismatchError(
            f"step_up token scope mismatch: got {scope!r}, expected {expected_scope!r}"
        )

    security_stamp = payload.get("ss")
    if not isinstance(security_stamp, str):
        raise StepUpTokenInvalidError("step_up token security stamp missing")

    assertion_id = payload.get("aid")
    if not isinstance(assertion_id, str) or not assertion_id:
        raise StepUpTokenInvalidError("step_up token assertion id missing")

    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise StepUpTokenInvalidError("step_up token jti missing")

    iat_raw = payload.get("iat")
    exp_raw = payload.get("exp")
    if not isinstance(iat_raw, int) or not isinstance(exp_raw, int):
        raise StepUpTokenInvalidError("step_up token timestamps missing")

    return StepUpTokenClaims(
        user_id=user_id,
        scope=scope,
        security_stamp=security_stamp,
        assertion_id=assertion_id,
        jti=jti,
        issued_at=datetime.fromtimestamp(iat_raw, tz=UTC),
        expires_at=datetime.fromtimestamp(exp_raw, tz=UTC),
    )


__all__ = [
    "SCOPE_ADMIN_DESTRUCTIVE",
    "STEP_UP_TOKEN_TTL_SECONDS",
    "STEP_UP_TOKEN_TYPE",
    "StepUpTokenClaims",
    "StepUpTokenError",
    "StepUpTokenExpiredError",
    "StepUpTokenInvalidError",
    "StepUpTokenScopeMismatchError",
    "issue_step_up_token",
    "verify_step_up_token",
]
