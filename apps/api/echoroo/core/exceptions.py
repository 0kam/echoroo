"""Custom exception classes and error handlers."""

import re
from typing import Any, Final

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppException(Exception):
    """Base exception for application errors."""

    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class NotFoundError(AppException):
    """Resource not found exception."""

    def __init__(self, resource: str, identifier: Any):
        message = f"{resource} with id '{identifier}' not found"
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND)


class AuthenticationError(AppException):
    """Authentication failed exception."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=status.HTTP_401_UNAUTHORIZED)


class AuthorizationError(AppException):
    """Authorization/permission denied exception."""

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, status_code=status.HTTP_403_FORBIDDEN)


class ValidationError(AppException):
    """Business logic validation error."""

    def __init__(self, message: str):
        super().__init__(message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


class ConflictError(AppException):
    """Resource conflict exception (e.g., duplicate email)."""

    def __init__(self, message: str):
        super().__init__(message, status_code=status.HTTP_409_CONFLICT)


class RateLimitError(AppException):
    """Rate limit exceeded exception."""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, status_code=status.HTTP_429_TOO_MANY_REQUESTS)


# Exception handlers


async def app_exception_handler(
    request: Request, exc: AppException  # noqa: ARG001
) -> JSONResponse:
    """Handle custom application exceptions.

    Args:
        request: FastAPI request object (required by FastAPI signature)
        exc: Application exception

    Returns:
        JSON response with error details
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
        },
    )


# Phase 7 polish round 3 (Major 3): the ERR_LICENSE_REQUIRED envelope must
# only fire on the four routes that own the project ``license`` field. A
# path-agnostic detector based purely on ``loc`` would mis-fire on any
# unrelated endpoint that happens to expose a ``license`` field in its
# request body (e.g. a future dataset / model registry endpoint), surfacing
# a confusing FR-085 envelope on a request that has nothing to do with the
# project license contract. The pattern below pins detection to:
#
#   * POST   /api/v1/projects
#   * POST   /web-api/v1/projects
#   * PATCH  /api/v1/projects/{uuid}/license
#   * PATCH  /web-api/v1/projects/{uuid}/license
#
# Trailing slashes are tolerated (FastAPI sometimes redirects, sometimes not,
# depending on how the route was declared). Anything else falls through to
# the generic ``ValidationError`` envelope.
_LICENSE_REQUIRED_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:/api/v1|/web-api/v1)/projects"
    r"(?:/[0-9a-fA-F-]{36}/license)?/?$"
)


def _path_is_license_route(path: str) -> bool:
    """Return ``True`` when ``path`` is one of the license-bearing endpoints."""
    return _LICENSE_REQUIRED_PATH_RE.match(path) is not None


def _is_license_field_error(loc: object) -> bool:
    """Return ``True`` when ``loc`` flags ``license`` as the offending field.

    Phase 7 polish round 2 (致命 2, FR-085): ``POST /projects`` and
    ``PATCH /projects/{id}/license`` surface a missing / invalid
    ``license`` value as ``ERR_LICENSE_REQUIRED`` rather than the generic
    ``ValidationError`` envelope.

    Phase 7 polish round 3 (Major 3): this helper is now combined with a
    path check inside :func:`validation_exception_handler` so the envelope
    only fires on the four owned routes. It is kept as a pure ``loc``
    inspector here so unit tests can exercise the field-detection contract
    in isolation.
    """
    if not isinstance(loc, (list, tuple)):
        return False
    return "license" in loc


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors.

    Phase 7 polish round 2 (致命 2): if any 422 sub-error targets the
    ``license`` body field (``loc`` contains ``"license"``) AND the
    request path is one of the routes that own the project license
    contract, the envelope surfaces ``error = "ERR_LICENSE_REQUIRED"``
    so contract consumers per FR-085 can distinguish a missing license
    from generic validation failures. The full ``details`` list is
    preserved so existing tooling that reads field-level diagnostics
    keeps working.

    Phase 7 polish round 3 (Major 3): the path check guards against
    false positives on unrelated endpoints that happen to carry a
    ``license`` field. Without it, any future schema with a
    ``license``-named attribute would inherit the FR-085 envelope on
    422s that have nothing to do with the project license contract.

    Args:
        request: FastAPI request object — used to scope ERR_LICENSE_REQUIRED
            to the four owned routes (POST/PATCH on ``projects``).
        exc: Request validation error

    Returns:
        JSON response with validation error details
    """
    # Convert errors to JSON-serializable format
    errors = []
    license_field_present = False
    for error in exc.errors():
        loc = error["loc"]
        if _is_license_field_error(loc):
            license_field_present = True
        error_dict = {
            "type": error["type"],
            "loc": loc,
            "msg": error["msg"],
        }
        # Convert ctx values to strings if present
        if "ctx" in error:
            error_dict["ctx"] = {k: str(v) for k, v in error["ctx"].items()}
        errors.append(error_dict)

    # Only emit the FR-085 envelope when BOTH the field is the license
    # AND the request hit one of the four owned routes.
    if license_field_present and _path_is_license_route(request.url.path):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "ERR_LICENSE_REQUIRED",
                "message": "Project license is required (FR-085)",
                "details": errors,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "ValidationError",
            "message": "Request validation failed",
            "details": errors,
        },
    )


async def http_exception_handler(
    request: Request, exc: HTTPException  # noqa: ARG001
) -> JSONResponse:
    """Handle FastAPI HTTP exceptions.

    Phase 8 polish round 2 Major 1 — when a handler raises
    ``HTTPException(detail={"error": "ERR_...", "message": "..."})`` the
    handler passes the dict body through as-is (top-level), so
    contract-coded error envelopes (e.g.
    ``ERR_RESTRICTED_CONFIG_NOT_APPLICABLE``,
    ``ERR_LICENSE_REQUIRED``) reach the client without being wrapped
    inside an extra ``{"detail": {...}}`` layer. Plain string ``detail``
    values keep the legacy ``{"detail": "..."}`` envelope so existing
    consumers are unaffected.

    Args:
        request: FastAPI request object (required by FastAPI signature)
        exc: HTTP exception

    Returns:
        JSON response with error details
    """
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        # Caller supplied a contract envelope explicitly — emit it at the
        # top level so ``body["error"] == "ERR_..."`` is reachable
        # without traversing a nested ``detail`` key.
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content=detail,
        )
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "detail": detail,
        },
    )
