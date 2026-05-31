"""Self-service change-password request / response schemas (spec/011 T320).

Models for ``POST /web-api/v1/auth/change-password`` and its v1 mirror
``POST /api/v1/auth/change-password``. Both endpoints share these
schemas so the two surfaces stay byte-identical at the contract level
(``specs/011-zero-email-deployment/contracts/admin-password-reset.yaml``).

The endpoint lets a user (including one inside the
``ForcedPasswordChangeMiddleware`` 423 gate) supply their current
password — or the most-recent admin-issued temporary password while it
is still inside its 24h TTL — together with a new password, clearing the
forced-change flag on success (FR-011-204).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChangePasswordRequest(BaseModel):
    """Request body for the self-service change-password endpoints."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description=(
            "The active password OR the most-recent admin-issued "
            "temporary password (accepted only while the 24h "
            "temp-password TTL has not elapsed)."
        ),
    )
    new_password: str = Field(
        ...,
        # DoS guard ONLY (kept at 1). The effective server floor is 8
        # characters (``DEFAULT_PASSWORD_POLICY``, NIST SP 800-63B), but we
        # deliberately do NOT raise this Pydantic bound to 8: a sub-8
        # password must reach ``enforce_password_policy`` so it surfaces the
        # friendly 422 ``{error_code: password_policy_violation, message}``
        # envelope the frontend + tests depend on. Raising ``min_length``
        # here would instead produce FastAPI's generic list-shaped 422
        # ``detail`` and break that envelope (verified — a sub-8 value would
        # otherwise lose the ``error_code`` key). The contract YAML advertises
        # ``minLength: 8`` (the real policy floor) for documentation parity.
        min_length=1,
        max_length=4096,
        description=(
            "Candidate replacement password. Validated server-side "
            "against the shared NIST SP 800-63B policy (+ HIBP); the "
            "request-schema bound is only a DoS guard. The effective "
            "minimum length is 8 (enforced by the policy validator, which "
            "returns the friendly password_policy_violation 422)."
        ),
    )


class ChangePasswordResponse(BaseModel):
    """Response body returned on a successful password change.

    The optional ``access_token`` / ``expires_in`` fields carry a FRESH
    access token minted for the caller after the security-stamp rotation
    (spec/011 FR-011-205). Because change-password rotates
    ``users.security_stamp`` to invalidate every OTHER session, the
    caller's *existing* access token (carrying the old stamp) would 419
    on its next request. Returning a new stamp-matching token here lets
    the caller's CURRENT session continue seamlessly:

      * BFF (``/web-api/v1``): the handler ALSO re-issues the session /
        refresh / CSRF cookies (Set-Cookie) so the cookie surface stays
        coherent; the frontend swaps its in-memory access token with the
        value returned here.
      * v1 Bearer (``/api/v1``): the Bearer client reads ``access_token``
        and replaces its stored token, mirroring the v1 login token body.

    ``message`` is always present so existing clients / tests that only
    look at the confirmation string keep working.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        default="Password changed successfully.",
        description=(
            "Human-readable confirmation. The ``must_change_password`` "
            "flag is now cleared; all other sessions were invalidated "
            "and trusted-device records revoked."
        ),
    )
    access_token: str | None = Field(
        default=None,
        description=(
            "Fresh access token (carrying the rotated security stamp) for "
            "the caller's CURRENT session. ``None`` is never returned on "
            "the success path — present so the response model documents "
            "the re-issue contract."
        ),
    )
    expires_in: int | None = Field(
        default=None,
        description="Lifetime of ``access_token`` in seconds.",
    )


__all__ = [
    "ChangePasswordRequest",
    "ChangePasswordResponse",
]
