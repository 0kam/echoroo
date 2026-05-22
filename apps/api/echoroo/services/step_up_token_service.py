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
      "scope": "admin_destructive" | "admin_recovery",
      "ss":   "<security_stamp at issuance>",
      "aid":  "<assertion_id uuid issued by webauthn_service>",
      "jti":  "<random uuid>",
      "iat":  <unix_ts>,
      "exp":  <unix_ts + 300>,
      "factors": null  # admin_destructive
              | {"password": true|false, "second_factor": "totp"|"webauthn"}
                       # admin_recovery (spec/011 FR-011-206)
    }

Security stamp + assertion id keep the token tightly bound to the
ceremony that produced it: rotating ``security_stamp`` (e.g. on password
reset / 2FA reset) immediately invalidates outstanding step-up tokens,
matching the behaviour of session refresh tokens.

spec/011 §FR-011-206 introduces a second scope ``admin_recovery`` that
demands an AND-condition (password re-entry **plus** a fresh 2FA
challenge — TOTP or WebAuthn). The new claim ``factors`` records the
two factors that have completed; ``verify_step_up_token`` enforces the
invariant when callers pass ``expected_scope=SCOPE_ADMIN_RECOVERY``.
The pre-existing ``admin_destructive`` path remains fully
backwards-compatible: ``factors`` is absent (``None``) on those tokens
and the verifier never inspects it for that scope.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
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

#: spec/011 §FR-011-206 — scope used by admin-recovery endpoints
#: (admin password reset, admin self-reset, admin 2FA disable). Tokens
#: minted under this scope MUST also carry a ``factors`` claim
#: representing the AND-condition (password re-entry + a fresh 2FA
#: challenge). The verifier refuses ``admin_recovery`` tokens whose
#: ``factors.password`` is not ``True`` or whose ``factors.second_factor``
#: is not one of ``"totp"`` / ``"webauthn"``.
SCOPE_ADMIN_RECOVERY: Final[str] = "admin_recovery"

#: Allowed values for ``factors.second_factor`` under ``admin_recovery``.
#: Kept in a frozen set so :func:`verify_step_up_token` can refuse
#: anything outside the contract (e.g. ``"sms"``, ``None``, ``""``).
_ADMIN_RECOVERY_SECOND_FACTORS: Final[frozenset[str]] = frozenset(
    {"totp", "webauthn"}
)

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
    """Decoded claims surface for a successfully validated step-up token.

    ``factors`` is ``None`` for the legacy ``admin_destructive`` scope
    (Phase 16 Batch 6g-3 path) and a mapping ``{password, second_factor}``
    for ``admin_recovery`` tokens minted by
    :func:`issue_admin_recovery_step_up_token` (spec/011 §FR-011-206).
    """

    user_id: UUID
    scope: str
    security_stamp: str
    assertion_id: str
    jti: str
    issued_at: datetime
    expires_at: datetime
    factors: dict[str, Any] | None = field(default=None)


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


def issue_admin_recovery_step_up_token(
    *,
    user_id: UUID,
    security_stamp: str,
    assertion_id: str,
    password_verified: bool,
    second_factor: Literal["totp", "webauthn"],
    ttl_seconds: int = STEP_UP_TOKEN_TTL_SECONDS,
) -> tuple[str, datetime]:
    """Mint an ``admin_recovery``-scoped step-up token (spec/011 §FR-011-206).

    Differs from :func:`issue_step_up_token` only in that the payload
    carries a non-``None`` ``factors`` claim representing the
    AND-condition completion (password re-entry + 2FA challenge). The
    scope is hard-coded to :data:`SCOPE_ADMIN_RECOVERY`.

    The caller MUST have just verified the user's current password
    *and* a fresh 2FA challenge (TOTP code or WebAuthn assertion)
    before invoking this helper; the API surface that wraps this
    helper is responsible for that AND-condition gate. The minted
    token's verifier (:func:`verify_step_up_token`) additionally
    refuses tokens whose ``factors.password`` is not literally
    ``True`` or whose ``factors.second_factor`` falls outside
    :data:`_ADMIN_RECOVERY_SECOND_FACTORS`, so a buggy caller cannot
    accidentally mint a token that the gate would accept.

    Args:
        user_id: Authenticated superuser performing the recovery
            action. Becomes the ``sub`` claim.
        security_stamp: Current ``user.security_stamp`` at issuance.
            Rotating this value (e.g. on password reset / 2FA reset)
            immediately invalidates the token.
        assertion_id: WebAuthn-assertion id (or analogous handle from
            the 2FA challenge) used to correlate this token with the
            ceremony that minted it.
        password_verified: ``True`` if the caller re-entered the
            user's current password and the API verified it before
            calling this helper. ``False`` is accepted for issuance
            but the verifier will refuse such a token at gate-time.
            MUST be a strict :class:`bool` — non-bool inputs (e.g.
            ``1``, ``"false"``, ``[1]``) raise :class:`TypeError`
            here so a buggy caller cannot accidentally smuggle a
            truthy non-bool value into ``factors.password`` and
            satisfy the verifier's ``is True`` check by JSON
            serialisation coincidence.
        second_factor: Which 2FA mode just succeeded.
        ttl_seconds: Token lifetime in seconds. Defaults to
            :data:`STEP_UP_TOKEN_TTL_SECONDS` (5 minutes).

    Returns:
        ``(token, expires_at)`` mirroring :func:`issue_step_up_token`.
    """
    settings = get_settings()
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    # Strict type guard — see ``password_verified`` doc above. We
    # deliberately reject ``int`` / ``str`` / ``list`` etc. instead of
    # silently coercing with ``bool(...)``; the verifier's
    # ``factors.password is True`` check is defence-in-depth that we
    # would otherwise defeat by normalising every truthy value into
    # the ``True`` singleton at issuance.
    if not isinstance(password_verified, bool):
        raise TypeError(
            "password_verified must be a strict bool (True or False); "
            f"got {type(password_verified).__name__}"
        )
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=ttl_seconds)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": STEP_UP_TOKEN_TYPE,
        "scope": SCOPE_ADMIN_RECOVERY,
        "ss": security_stamp,
        "aid": assertion_id,
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        # ``factors`` is part of the signed payload so a downstream
        # gate cannot be fooled by replacing the claim post-issuance.
        # ``password`` is stored as-is (no ``bool(...)`` coercion) so
        # the verifier sees the exact value the caller passed.
        "factors": {
            "password": password_verified,
            "second_factor": second_factor,
        },
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

    # spec/011 §FR-011-206 — ``admin_recovery`` scope additionally
    # demands an AND-condition (password re-entry + 2FA challenge).
    # The claim is enforced here so every gate that asks for the new
    # scope inherits the invariant without per-endpoint plumbing. The
    # legacy ``admin_destructive`` path is untouched: ``factors`` is
    # absent (``None``) for those tokens and never inspected.
    factors_raw = payload.get("factors")
    factors: dict[str, Any] | None
    if expected_scope == SCOPE_ADMIN_RECOVERY:
        if not isinstance(factors_raw, dict):
            raise StepUpTokenInvalidError(
                "step_up token factors missing for admin_recovery scope"
            )
        password_factor = factors_raw.get("password")
        if password_factor is not True:
            raise StepUpTokenInvalidError(
                "step_up token factors.password must be True for "
                "admin_recovery scope"
            )
        second_factor = factors_raw.get("second_factor")
        if (
            not isinstance(second_factor, str)
            or second_factor not in _ADMIN_RECOVERY_SECOND_FACTORS
        ):
            raise StepUpTokenInvalidError(
                "step_up token factors.second_factor must be one of "
                f"{sorted(_ADMIN_RECOVERY_SECOND_FACTORS)} for "
                "admin_recovery scope"
            )
        # Surface a sanitised copy so callers never see arbitrary
        # extra keys an attacker might smuggle into the payload.
        factors = {
            "password": True,
            "second_factor": second_factor,
        }
    else:
        # Non-recovery scopes ignore ``factors`` entirely — preserve
        # full backwards compatibility with ``admin_destructive``
        # tokens minted before spec/011.
        factors = None

    return StepUpTokenClaims(
        user_id=user_id,
        scope=scope,
        security_stamp=security_stamp,
        assertion_id=assertion_id,
        jti=jti,
        issued_at=datetime.fromtimestamp(iat_raw, tz=UTC),
        expires_at=datetime.fromtimestamp(exp_raw, tz=UTC),
        factors=factors,
    )


__all__ = [
    "SCOPE_ADMIN_DESTRUCTIVE",
    "SCOPE_ADMIN_RECOVERY",
    "STEP_UP_TOKEN_TTL_SECONDS",
    "STEP_UP_TOKEN_TYPE",
    "StepUpTokenClaims",
    "StepUpTokenError",
    "StepUpTokenExpiredError",
    "StepUpTokenInvalidError",
    "StepUpTokenScopeMismatchError",
    "issue_admin_recovery_step_up_token",
    "issue_step_up_token",
    "verify_step_up_token",
]
