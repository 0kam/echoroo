"""Protected-action email verification enforcement middleware."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from echoroo.core.auth_paths import PUBLIC_AUTH_PATHS
from echoroo.core.database import AsyncSessionLocal
from echoroo.core.settings import get_settings
from echoroo.models.user import User

ERROR_CODE_EMAIL_VERIFICATION_REQUIRED: Final[str] = "ERR_EMAIL_VERIFICATION_REQUIRED"
DEFAULT_ALLOWLIST_PATHS: Final[tuple[str, ...]] = ("/health", "/metrics")
DEFAULT_ENFORCEMENT_PREFIXES: Final[tuple[str, ...]] = (
    "/web-api/v1/",
    "/api/v1/",
)

_PUBLIC_API_AUTH_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/refresh",
        "/api/v1/auth/password-reset/request",
        "/api/v1/auth/password-reset/confirm",
        "/api/v1/auth/verify-email",
    }
)
_PROJECT_READ_RE = re.compile(
    r"^/(?:web-api|api)/v1/projects/?(?:[^/]+/?(?:recordings/?)?)?$"
)


class EmailVerificationEnforcementMiddleware(BaseHTTPMiddleware):
    """Block authenticated protected actions until the caller verifies email."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        session_factory: Any | None = None,
        allowlist_paths: Sequence[str] = DEFAULT_ALLOWLIST_PATHS,
        enforcement_prefixes: Sequence[str] = DEFAULT_ENFORCEMENT_PREFIXES,
    ) -> None:
        super().__init__(app)
        if not enforcement_prefixes:
            raise ValueError("enforcement_prefixes must not be empty")
        self.session_factory = session_factory or AsyncSessionLocal
        self.allowlist_paths = frozenset(allowlist_paths)
        self.enforcement_prefixes = tuple(enforcement_prefixes)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if not settings.EMAIL_VERIFICATION_ENFORCEMENT_ENABLED:
            return await call_next(request)

        path = request.url.path
        if not any(path.startswith(prefix) for prefix in self.enforcement_prefixes):
            return await call_next(request)

        if self._is_public_request(request):
            return await call_next(request)

        principal = getattr(request.state, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if user_id is None:
            return await call_next(request)

        user = await self._load_user(user_id)
        if user is None or user.deleted_at is not None or user.email_verified_at is None:
            return _email_verification_required_response()

        return await call_next(request)

    def _is_public_request(self, request: Request) -> bool:
        path = request.url.path
        method = request.method.upper()
        if path in self.allowlist_paths:
            return True
        if path in PUBLIC_AUTH_PATHS or path in _PUBLIC_API_AUTH_PATHS:
            return True
        return method == "GET" and _PROJECT_READ_RE.fullmatch(path) is not None

    async def _load_user(self, user_id: UUID) -> User | None:
        async with self.session_factory() as session:
            result = await session.execute(sa.select(User).where(User.id == user_id))
            return result.scalar_one_or_none()


def _email_verification_required_response() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "code": ERROR_CODE_EMAIL_VERIFICATION_REQUIRED,
            "detail": "Email verification required",
        },
    )


__all__ = [
    "DEFAULT_ALLOWLIST_PATHS",
    "DEFAULT_ENFORCEMENT_PREFIXES",
    "ERROR_CODE_EMAIL_VERIFICATION_REQUIRED",
    "EmailVerificationEnforcementMiddleware",
]
