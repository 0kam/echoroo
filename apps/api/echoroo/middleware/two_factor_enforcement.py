"""2FA enrollment and reset-cooldown enforcement middleware (FR-069, FR-073).

T155 polish wiring (this revision)
----------------------------------
The middleware reads ``request.state.principal`` (a :class:`Principal`
populated by :class:`AuthRouterMiddleware`) instead of the never-set
``request.state.user`` attribute the original draft inspected. When a
principal is present we open a fresh :class:`AsyncSessionLocal` and
fetch the corresponding ``User`` row by ``principal.user_id`` so the
existing ``two_factor_enabled`` / ``two_factor_reset_cooldown_until``
checks have real data to evaluate (Option A in the T155 polish brief —
chosen over a translator middleware to keep DB work in one place).

Enforcement scope (T155 polish round 2 — IMPORTANT)
---------------------------------------------------
This middleware enforces 2FA on the **first-party session surface**
(``/web-api/v1/*``) ONLY. The ``/api/v1/*`` programmatic surface is
deliberately left out of enforcement until **Phase 15 task T155b**
wires the real :class:`ApiKeyVerifier` into
:class:`AuthRouterMiddleware`. Rationale:

* :class:`AuthRouterMiddleware` is currently configured with a
  sentinel ``programmatic_prefix`` so ``/api/v1/*`` falls through to
  the legacy :mod:`echoroo.middleware.auth` ``Depends``-based stack
  (which never populates ``request.state.principal``).
* If we left enforcement scope open across both prefixes, every
  authenticated ``/api/v1/*`` request would surface as
  ``principal is None`` and silently bypass FR-069 / FR-073 — a real
  production gap, not a benign edge case.
* Narrowing to ``/web-api/v1/*`` makes the deferral explicit: until
  T155b lands, ``/api/v1/*`` 2FA enforcement is a documented
  follow-up rather than a silent loophole. The session UI surface
  (which is the *only* surface end-users currently hit) is fully
  covered.

Fail-closed posture
~~~~~~~~~~~~~~~~~~~
If the ``users`` row is missing or carries ``deleted_at IS NOT NULL``
we treat the request as if 2FA enrollment is required. The principal
came from the auth router which already validated the session cookie,
so a missing ORM row is a corruption / race condition we fail closed
on rather than silently grant. Returning 403 ``2FA enrollment required``
keeps the user experience consistent and gives the security audit a
single, distinct telemetry signal to track.

Forensic audit
~~~~~~~~~~~~~~
Every block (403 enrollment + 423 cooldown) emits a structured WARNING
log line with ``user_id``, ``path``, ``method``, ``reason`` and writes
an ``auth.two_factor_enforcement_blocked`` platform-audit event so
operators can detect attempted evasion patterns even when other audit
hooks remain silent.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from echoroo.core.auth_paths import PUBLIC_AUTH_PATHS
from echoroo.core.database import AsyncSessionLocal
from echoroo.models.user import User
from echoroo.services.audit_service import AuditLogService

logger = logging.getLogger(__name__)


DEFAULT_ALLOWLIST_PATHS: Final[tuple[str, ...]] = ("/health", "/metrics")
DEFAULT_ENFORCEMENT_PREFIX: Final[str] = "/web-api/v1/"
"""Default path prefix the middleware applies to when no override is given.

Kept as a single string for backwards compatibility with callers that
construct the middleware via ``enforcement_prefix=``. Phase 15 T155b
introduces :data:`DEFAULT_ENFORCEMENT_PREFIXES` (plural) to cover both
the session and programmatic surfaces; new callers should prefer the
plural variant.
"""

DEFAULT_ENFORCEMENT_PREFIXES: Final[tuple[str, ...]] = (
    "/web-api/v1/",
    "/api/v1/",
)
"""Phase 15 T155b: dual-prefix enforcement.

Once :class:`DbApiKeyVerifier` populates ``request.state.principal`` for
``/api/v1/*`` Bearer callers, the same enrollment / cooldown gates that
guard ``/web-api/v1/*`` SHOULD also guard the programmatic surface so a
2FA-disabled user cannot escape the spec by switching to API-key auth.

Anonymous / cookie-only ``/api/v1/*`` callers (see
``AuthRouterConfig.allow_legacy_session_fallback``) carry
``principal is None`` and short-circuit out of enforcement at the
``principal is None or principal.user_id is None`` guard inside
:meth:`TwoFactorEnforcementMiddleware.dispatch`.
"""

TWO_FACTOR_SETUP_PATH: Final[str] = "/web-api/v1/auth/2fa/setup/totp"
"""Module-public alias kept for callers that already imported it.

The constant is a member of :data:`PUBLIC_AUTH_PATHS` and is therefore
already covered by the public-allowlist short-circuit. The middleware
no longer references it directly because doing so would be dead code.
"""

PASSWORD_RESET_CONFIRM_PATH: Final[str] = "/web-api/v1/auth/password-reset/confirm"
PASSWORD_RESET_CONFIRM_CACHE_CONTROL: Final[str] = "no-store, max-age=0"

ENFORCEMENT_AUDIT_ACTION: Final[str] = "auth.two_factor_enforcement_blocked"


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
        enforcement_prefix: str | None = None,
        enforcement_prefixes: Sequence[str] | None = None,
        user_resolver: Callable[[UUID], Awaitable[User | None]] | None = None,
        audit_writer: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(app)
        self.allowlist_paths = frozenset(allowlist_paths)
        self.cooldown_restricted_patterns = tuple(cooldown_restricted_patterns)
        # Phase 15 T155b: support BOTH the legacy single-prefix kwarg
        # (``enforcement_prefix``) and the dual-prefix variant
        # (``enforcement_prefixes``) so existing tests pinning the
        # ``/web-api/v1/`` scope keep working without modification while
        # production swaps in the broader prefix set.
        if enforcement_prefixes is not None and enforcement_prefix is not None:
            raise ValueError(
                "pass either enforcement_prefix or enforcement_prefixes, not both"
            )
        if enforcement_prefixes is not None:
            prefixes = tuple(enforcement_prefixes)
        elif enforcement_prefix is not None:
            prefixes = (enforcement_prefix,)
        else:
            prefixes = (DEFAULT_ENFORCEMENT_PREFIX,)
        if not prefixes:
            raise ValueError("enforcement_prefixes must not be empty")
        self.enforcement_prefixes: tuple[str, ...] = prefixes
        # Backward-compatibility alias — some callers (and the
        # ``__all__`` export list) still inspect ``enforcement_prefix``.
        # We expose the FIRST configured prefix on that attribute.
        self.enforcement_prefix: str = prefixes[0]
        # ``user_resolver`` and ``audit_writer`` are pluggable so the
        # existing fast unit tests can avoid spinning up Postgres while
        # the production wiring goes through ``AsyncSessionLocal``.
        self._user_resolver = user_resolver or _default_user_resolver
        self._audit_writer = audit_writer or _default_audit_writer

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path

        # Scope short-circuit. Phase 15 T155b: enforcement now covers
        # the configured prefix tuple (``/web-api/v1/*`` plus
        # ``/api/v1/*`` in production). Paths outside every configured
        # prefix bypass the middleware entirely.
        if not any(path.startswith(p) for p in self.enforcement_prefixes):
            return await _call_next_with_response_polish(request, call_next)

        # Public allowlist short-circuit. ``TWO_FACTOR_SETUP_PATH`` is a
        # member of ``PUBLIC_AUTH_PATHS`` so we no longer need a
        # standalone branch for it (T155 polish — dead-branch removal).
        if path in PUBLIC_AUTH_PATHS or path in self.allowlist_paths:
            return await _call_next_with_response_polish(request, call_next)

        principal = getattr(request.state, "principal", None)
        if principal is None or principal.user_id is None:
            # No authenticated principal — auth router already passed
            # the request through, so there is no enforcement context.
            return await _call_next_with_response_polish(request, call_next)

        user = await self._user_resolver(principal.user_id)
        if user is None or user.deleted_at is not None:
            # Fail-closed: see module docstring. The principal is
            # internally consistent (signature + security_stamp ok) but
            # the ORM row is missing or soft-deleted — surface the same
            # 403 the enrollment-required path uses so a consistent
            # signal reaches both clients and the audit chain.
            return await self._block_enrollment(
                request=request,
                user_id=principal.user_id,
                reason="user_missing_or_deleted",
            )

        if _two_factor_enrollment_required(user):
            return await self._block_enrollment(
                request=request,
                user_id=user.id,
                reason="two_factor_enrollment_required",
            )

        if _trusted_device_session_used(request) and self._is_cooldown_restricted(request):
            return await self._block_recent_step_up_required(
                request=request,
                user_id=user.id,
            )

        cooldown_until = _cooldown_until(user)
        if cooldown_until is None:
            return await _call_next_with_response_polish(request, call_next)

        now = datetime.now(UTC)
        if cooldown_until > now and self._is_cooldown_restricted(request):
            retry_after_seconds = max(1, math.ceil((cooldown_until - now).total_seconds()))
            return await self._block_cooldown(
                request=request,
                user_id=user.id,
                retry_after_seconds=retry_after_seconds,
            )

        return await _call_next_with_response_polish(request, call_next)

    def _is_cooldown_restricted(self, request: Request) -> bool:
        path = request.url.path
        method = request.method.upper()
        return any(
            restricted.matches(path=path, method=method)
            for restricted in self.cooldown_restricted_patterns
        )

    # -- block helpers ----------------------------------------------------

    async def _block_enrollment(
        self,
        *,
        request: Request,
        user_id: UUID,
        reason: str,
    ) -> JSONResponse:
        logger.warning(
            "2FA enforcement blocked request",
            extra={
                "user_id": str(user_id),
                "path": request.url.path,
                "method": request.method.upper(),
                "reason": reason,
            },
        )
        await self._safe_audit(
            request=request,
            user_id=user_id,
            detail={
                "reason": reason,
                "status_code": 403,
                "path": request.url.path,
                "method": request.method.upper(),
            },
        )
        return JSONResponse(
            status_code=403,
            content={
                "detail": "2FA enrollment required",
                "next_action": "/web-api/v1/auth/2fa/setup/totp",
            },
        )

    async def _block_cooldown(
        self,
        *,
        request: Request,
        user_id: UUID,
        retry_after_seconds: int,
    ) -> JSONResponse:
        logger.warning(
            "2FA enforcement blocked request",
            extra={
                "user_id": str(user_id),
                "path": request.url.path,
                "method": request.method.upper(),
                "reason": "two_factor_reset_cooldown_active",
            },
        )
        await self._safe_audit(
            request=request,
            user_id=user_id,
            detail={
                "reason": "two_factor_reset_cooldown_active",
                "status_code": 423,
                "path": request.url.path,
                "method": request.method.upper(),
                "retry_after_seconds": retry_after_seconds,
            },
        )
        return JSONResponse(
            status_code=423,
            headers={"Retry-After": str(retry_after_seconds)},
            content={
                "detail": "2FA reset cooldown active",
                "retry_after_seconds": retry_after_seconds,
            },
        )

    async def _block_recent_step_up_required(
        self,
        *,
        request: Request,
        user_id: UUID,
    ) -> JSONResponse:
        logger.warning(
            "2FA enforcement blocked request",
            extra={
                "user_id": str(user_id),
                "path": request.url.path,
                "method": request.method.upper(),
                "reason": "trusted_device_recent_step_up_required",
            },
        )
        await self._safe_audit(
            request=request,
            user_id=user_id,
            detail={
                "reason": "trusted_device_recent_step_up_required",
                "status_code": 403,
                "path": request.url.path,
                "method": request.method.upper(),
                "trusted_device_used": True,
            },
        )
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Recent step-up required",
                "error_code": "recent_step_up_required",
            },
        )

    async def _safe_audit(
        self,
        *,
        request: Request,
        user_id: UUID,
        detail: dict[str, Any],
    ) -> None:
        """Best-effort audit write — never raise out of the middleware."""
        try:
            await self._audit_writer(
                request=request,
                actor_user_id=user_id,
                action=ENFORCEMENT_AUDIT_ACTION,
                detail=detail,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "audit write failed for 2FA enforcement block",
                extra={"user_id": str(user_id), "path": request.url.path},
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


def _trusted_device_session_used(request: Request) -> bool:
    return bool(getattr(request.state, "trusted_device_used", False))


async def _call_next_with_response_polish(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    if request.url.path == PASSWORD_RESET_CONFIRM_PATH:
        response.headers["Cache-Control"] = PASSWORD_RESET_CONFIRM_CACHE_CONTROL
    return response


async def _default_user_resolver(user_id: UUID) -> User | None:
    """Open a fresh session and load the ``User`` row by id."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(sa.select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


async def _default_audit_writer(
    *,
    request: Request,
    actor_user_id: UUID,
    action: str,
    detail: dict[str, Any],
) -> None:
    """Open a fresh session and append a platform-audit row.

    Mirrors the pattern in :func:`echoroo.api.web_v1.auth._write_platform_audit`.
    Failures are swallowed by the caller (``_safe_audit``) — the audit
    write is forensic, never a hard dependency of the enforcement
    response itself.
    """
    request_id = (
        request.headers.get("x-request-id")
        or getattr(request.state, "request_id", None)
        or "internal"
    )
    ip = (request.client.host or "0.0.0.0") if request.client is not None else "0.0.0.0"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",", 1)[0].strip() or ip
    user_agent = request.headers.get("user-agent") or ""
    async with AsyncSessionLocal() as session:
        try:
            audit = AuditLogService(session)
            await audit.write_platform_event(
                actor_user_id=actor_user_id,
                action=action,
                request_id=str(request_id),
                ip=ip,
                user_agent=user_agent,
                detail=detail,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


__all__ = [
    "COOLDOWN_RESTRICTED_PATTERNS",
    "CooldownRestrictedPattern",
    "DEFAULT_ALLOWLIST_PATHS",
    "DEFAULT_ENFORCEMENT_PREFIX",
    "DEFAULT_ENFORCEMENT_PREFIXES",
    "ENFORCEMENT_AUDIT_ACTION",
    "PASSWORD_RESET_CONFIRM_CACHE_CONTROL",
    "PASSWORD_RESET_CONFIRM_PATH",
    "TWO_FACTOR_SETUP_PATH",
    "TwoFactorEnforcementMiddleware",
]
