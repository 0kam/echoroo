"""Step-up token FastAPI dependency for destructive admin endpoints.

Phase 16 Batch 6g-3: every destructive superuser admin endpoint
(``add`` / ``revoke`` / ``approve`` / ``reject`` / ``break-glass enter``
/ ``ip-allowlist update``) must be gated by a fresh WebAuthn
assertion.  After the WebAuthn ceremony succeeds the API issues a
short-lived step-up token (see
:mod:`echoroo.services.step_up_token_service`); the destructive
endpoint expects it on the ``X-Step-Up-Token`` request header.

This module provides :func:`require_step_up_token` — a FastAPI
``Depends`` factory.  It returns the validated
:class:`echoroo.services.step_up_token_service.StepUpTokenClaims` so
audit handlers can record the assertion id alongside the action.

Phase 16 Batch 6h-0 (Codex Major): the dependency additionally binds
the decoded ``sub`` (user_id) and ``ss`` (security_stamp) claims to the
*current authenticated session*. A token minted for user A cannot be
replayed against user B's session, and rotating ``security_stamp`` (e.g.
on logout / password change / 2FA reset) immediately invalidates every
outstanding step-up token for that user. Without this binding the JWT
signature alone is sufficient to authorise the destructive action,
which would re-open the very attacker path Batch 6g-3 closed.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Final

from fastapi import Depends, HTTPException, Request, status

from echoroo.middleware.auth import get_current_user_optional
from echoroo.models.user import User
from echoroo.services.step_up_token_service import (
    SCOPE_ADMIN_DESTRUCTIVE,
    StepUpTokenClaims,
    StepUpTokenExpiredError,
    StepUpTokenInvalidError,
    StepUpTokenScopeMismatchError,
    verify_step_up_token,
)

#: Header carrying the step-up JWT.  Mirrors how ``X-CSRF-Token`` is
#: positioned alongside the session cookie.
STEP_UP_HEADER_NAME: Final[str] = "X-Step-Up-Token"


def _missing_token_response() -> HTTPException:
    """401 envelope returned when the header is absent."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error_code": "step_up_token_required",
            "message": (
                "Step-up token is required for destructive admin actions. "
                "Complete the WebAuthn ceremony to obtain one."
            ),
        },
    )


def _expired_token_response() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error_code": "step_up_token_expired",
            "message": (
                "Step-up token has expired. Re-run the WebAuthn ceremony "
                "and retry."
            ),
        },
    )


def _invalid_token_response(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error_code": "step_up_token_invalid",
            "message": message or "Step-up token is invalid.",
        },
    )


def _scope_mismatch_response(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "step_up_token_scope_mismatch",
            "message": (
                message
                or "Step-up token scope does not match the destructive action."
            ),
        },
    )


def _user_mismatch_response() -> HTTPException:
    """401 envelope when the token's ``sub`` differs from the session user.

    A step-up token is bound to the WebAuthn ceremony of a single user;
    presenting it under a different session is treated as a replay
    attempt and refused without distinguishing whether the foreign
    session is authenticated or anonymous (see Phase 16 Batch 6h-0).
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error_code": "step_up_token_user_mismatch",
            "message": (
                "Step-up token does not belong to the current session. "
                "Re-run the WebAuthn ceremony as the correct user."
            ),
        },
    )


def _security_stamp_rotated_response() -> HTTPException:
    """401 envelope when the user's ``security_stamp`` rotated post-issuance."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error_code": "step_up_token_security_stamp_rotated",
            "message": (
                "Step-up token has been invalidated by a session refresh "
                "(logout / password change / 2FA reset). Re-run the "
                "WebAuthn ceremony to obtain a fresh token."
            ),
        },
    )


def require_step_up_token(
    scope: str = SCOPE_ADMIN_DESTRUCTIVE,
) -> Callable[..., Coroutine[Any, Any, StepUpTokenClaims]]:
    """Build a ``Depends`` callable that asserts a valid step-up header.

    The returned dependency now also binds the token to the current
    authenticated session: the JWT's ``sub`` claim must match the
    session user's ``id`` and the ``ss`` claim must match
    ``user.security_stamp`` at request time.  Without this binding a
    token minted for user A could be replayed by an attacker holding a
    session for user B, and a rotated security stamp (logout / password
    change / 2FA reset) would not invalidate outstanding tokens — both
    of which would re-open the path Batch 6g-3 closed (Phase 16 6h-0).

    Args:
        scope: The expected ``scope`` claim. Defaults to
            ``SCOPE_ADMIN_DESTRUCTIVE`` which is the only scope wired
            in Phase 16 Batch 6g-3.

    Returns:
        An async FastAPI dependency callable. The callable raises
        :class:`HTTPException` on any failure, otherwise returns the
        decoded :class:`StepUpTokenClaims` instance.

    Example::

        @router.post(
            "/superusers",
            dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_DESTRUCTIVE))],
        )
        async def add_superuser(...): ...
    """

    async def _dependency(
        request: Request,
        current_user: Annotated[User | None, Depends(get_current_user_optional)],
    ) -> StepUpTokenClaims:
        raw = request.headers.get(STEP_UP_HEADER_NAME)
        if raw is None or raw.strip() == "":
            raise _missing_token_response()
        try:
            claims = verify_step_up_token(raw, expected_scope=scope)
        except StepUpTokenExpiredError as exc:
            raise _expired_token_response() from exc
        except StepUpTokenScopeMismatchError as exc:
            raise _scope_mismatch_response(str(exc)) from exc
        except StepUpTokenInvalidError as exc:
            raise _invalid_token_response(str(exc)) from exc

        # Phase 16 Batch 6h-0 (Codex Major): bind to the current session.
        # The endpoint body still owns the superuser-status enforcement
        # via ``_require_authenticated_superuser`` — this gate only
        # asserts that the WebAuthn ceremony embedded in the token
        # matches the *caller* of the destructive action.
        if current_user is None:
            # No backing session at all — refuse uniformly as user
            # mismatch rather than 401 generic, so the auditing /
            # alerting pipeline can distinguish step-up replay attempts
            # from "forgot to log in".
            raise _user_mismatch_response()
        if claims.user_id != current_user.id:
            raise _user_mismatch_response()
        if claims.security_stamp != current_user.security_stamp:
            raise _security_stamp_rotated_response()
        return claims

    return _dependency


__all__ = [
    "STEP_UP_HEADER_NAME",
    "require_step_up_token",
]
