"""2FA enrollment and reset-cooldown enforcement middleware (FR-069, FR-073)."""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from echoroo.core.auth_paths import PUBLIC_AUTH_PATHS
from echoroo.models.user import User

DEFAULT_ALLOWLIST_PATHS: Final[tuple[str, ...]] = ("/health", "/metrics")
TWO_FACTOR_SETUP_PATH: Final[str] = "/web-api/v1/auth/2fa/setup/totp"
PASSWORD_RESET_CONFIRM_PATH: Final[str] = "/web-api/v1/auth/password-reset/confirm"
PASSWORD_RESET_CONFIRM_CACHE_CONTROL: Final[str] = "no-store, max-age=0"


@dataclass(frozen=True)
class CooldownRestrictedPattern:
    """A path regex plus optional HTTP method filter for FR-073 cooldown gates."""

    pattern: re.Pattern[str]
    methods: frozenset[str] | None = None

    def matches(self, *, path: str, method: str) -> bool:
        if self.methods is not None and method.upper() not in self.methods:
            return False
        return self.pattern.match(path) is not None


COOLDOWN_RESTRICTED_PATTERNS: Final[tuple[CooldownRestrictedPattern, ...]] = (
    CooldownRestrictedPattern(
        re.compile(r"^/(api|web-api)/v\d+/projects/?$"),
        frozenset({"POST", "DELETE"}),
    ),
    CooldownRestrictedPattern(
        re.compile(r"^/(api|web-api)/v\d+/projects/[^/]+/?$"),
        frozenset({"DELETE"}),
    ),
    CooldownRestrictedPattern(
        re.compile(r"^/(api|web-api)/v\d+/projects/[^/]+/members(?:/.*)?$"),
        frozenset({"POST", "PUT", "PATCH", "DELETE"}),
    ),
    CooldownRestrictedPattern(
        re.compile(r"^/(api|web-api)/v\d+/projects/[^/]+/transfer-ownership/?$"),
        frozenset({"POST", "PUT", "PATCH"}),
    ),
    CooldownRestrictedPattern(
        re.compile(r"^/(api|web-api)/v\d+/invitations/[^/]+/accept/?$"),
        frozenset({"POST"}),
    ),
    CooldownRestrictedPattern(re.compile(r"^/(api|web-api)/v\d+/api-keys(?:/.*)?$")),
    CooldownRestrictedPattern(re.compile(r"^/(api|web-api)/v\d+/.*download.*$")),
    CooldownRestrictedPattern(re.compile(r"^/(api|web-api)/v\d+/.*export.*$")),
    CooldownRestrictedPattern(
        re.compile(r"^/(api|web-api)/v\d+/projects/[^/]+/join/?$"),
        frozenset({"POST"}),
    ),
)


class TwoFactorEnforcementMiddleware(BaseHTTPMiddleware):
    """Block protected endpoints until first-login 2FA enrollment is complete."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowlist_paths: Sequence[str] = DEFAULT_ALLOWLIST_PATHS,
        cooldown_restricted_patterns: Sequence[CooldownRestrictedPattern] = (
            COOLDOWN_RESTRICTED_PATTERNS
        ),
    ) -> None:
        super().__init__(app)
        self.allowlist_paths = frozenset(allowlist_paths)
        self.cooldown_restricted_patterns = tuple(cooldown_restricted_patterns)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path

        if (
            path in PUBLIC_AUTH_PATHS
            or path == TWO_FACTOR_SETUP_PATH
            or path in self.allowlist_paths
        ):
            return await _call_next_with_response_polish(request, call_next)

        user = getattr(request.state, "user", None)
        if user is None:
            return await _call_next_with_response_polish(request, call_next)

        if _two_factor_enrollment_required(user):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "2FA enrollment required",
                    "next_action": "/2fa/setup/totp",
                },
            )

        cooldown_until = _cooldown_until(user)
        if cooldown_until is None:
            return await _call_next_with_response_polish(request, call_next)

        now = datetime.now(UTC)
        if cooldown_until > now and self._is_cooldown_restricted(request):
            retry_after_seconds = max(1, math.ceil((cooldown_until - now).total_seconds()))
            return JSONResponse(
                status_code=423,
                headers={"Retry-After": str(retry_after_seconds)},
                content={
                    "detail": "2FA reset cooldown active",
                    "retry_after_seconds": retry_after_seconds,
                },
            )

        return await _call_next_with_response_polish(request, call_next)

    def _is_cooldown_restricted(self, request: Request) -> bool:
        path = request.url.path
        method = request.method.upper()
        return any(
            restricted.matches(path=path, method=method)
            for restricted in self.cooldown_restricted_patterns
        )


def _two_factor_enrollment_required(user: User) -> bool:
    return user.two_factor_enabled is False


def _cooldown_until(user: User) -> datetime | None:
    cooldown_until = user.two_factor_reset_cooldown_until
    if cooldown_until is None:
        return None
    if cooldown_until.tzinfo is None:
        return cooldown_until.replace(tzinfo=UTC)
    return cooldown_until.astimezone(UTC)


async def _call_next_with_response_polish(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    if request.url.path == PASSWORD_RESET_CONFIRM_PATH:
        response.headers["Cache-Control"] = PASSWORD_RESET_CONFIRM_CACHE_CONTROL
    return response


__all__ = [
    "COOLDOWN_RESTRICTED_PATTERNS",
    "CooldownRestrictedPattern",
    "DEFAULT_ALLOWLIST_PATHS",
    "PASSWORD_RESET_CONFIRM_CACHE_CONTROL",
    "PASSWORD_RESET_CONFIRM_PATH",
    "TWO_FACTOR_SETUP_PATH",
    "TwoFactorEnforcementMiddleware",
]
