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
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from fastapi import HTTPException, Request, status

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


def require_step_up_token(
    scope: str = SCOPE_ADMIN_DESTRUCTIVE,
) -> Callable[[Request], StepUpTokenClaims]:
    """Build a ``Depends`` callable that asserts a valid step-up header.

    Args:
        scope: The expected ``scope`` claim. Defaults to
            ``SCOPE_ADMIN_DESTRUCTIVE`` which is the only scope wired
            in Phase 16 Batch 6g-3.

    Returns:
        A FastAPI dependency callable. The callable raises
        :class:`HTTPException` on any failure, otherwise returns the
        decoded :class:`StepUpTokenClaims` instance.

    Example::

        @router.post(
            "/superusers",
            dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_DESTRUCTIVE))],
        )
        async def add_superuser(...): ...
    """

    def _dependency(request: Request) -> StepUpTokenClaims:
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
        return claims

    return _dependency


__all__ = [
    "STEP_UP_HEADER_NAME",
    "require_step_up_token",
]
