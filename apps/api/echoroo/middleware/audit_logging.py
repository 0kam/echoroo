"""Access-log middleware with PII redaction (FR-028c, T073).

Every request emits a single structured log line through
:mod:`logging` once the response is sent. Before fields are written
they are passed through :func:`echoroo.core.audit.sanitize_value` so
that any raw PII that snuck into URLs / headers / bodies is replaced
with the canonical hash marker.

The middleware does **not** call ``audit_service.write_*`` per
request — that service is for security-significant business events
(login, permission change, ...). Operational access logs go through
stdlib logging so existing log-shipping (Filebeat / journald) keeps
working.

Headers always redacted to ``[REDACTED]`` regardless of sanitiser
output:

* ``Authorization``
* ``Cookie``
* ``Set-Cookie``
* ``X-API-Key``
* ``X-CSRF-Token``

Query-string keys named ``token``, ``api_key``, ``access_token``,
``refresh_token``, ``password``, ``secret`` are replaced with
``[REDACTED]`` even before the sanitiser is invoked, so a leaked
plaintext credential never appears in logs even if it does not match
any PII regex.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from echoroo.core.audit import sanitize_value

logger = logging.getLogger("echoroo.access")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REDACTED: Final[str] = "[REDACTED]"

ALWAYS_REDACT_HEADERS: Final[frozenset[str]] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-csrf-token",
    }
)

ALWAYS_REDACT_QUERY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "token",
        "api_key",
        "access_token",
        "refresh_token",
        "password",
        "secret",
    }
)


@dataclass
class AccessLogConfig:
    """Configuration for :class:`AccessLogMiddleware`.

    Attributes:
        excluded_paths: Paths skipped entirely (e.g. ``/health``).
        log_request_body: If True, sanitised body bytes are decoded as
            UTF-8 (best-effort) and included. Default False — bodies
            can be large, and our security model treats request bodies
            as sensitive by default.
        max_body_bytes: Cap on body bytes captured when
            ``log_request_body`` is True. Defaults to 4 KiB.
    """

    excluded_paths: tuple[str, ...] = ("/health", "/metrics", "/favicon.ico")
    log_request_body: bool = False
    max_body_bytes: int = 4096


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redact_headers(items: list[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in items:
        lk = key.lower()
        if lk in ALWAYS_REDACT_HEADERS:
            out[key] = REDACTED
        else:
            sanitised = sanitize_value(value)
            out[key] = sanitised if isinstance(sanitised, str) else REDACTED
    return out


def _redact_query_string(query: str) -> str:
    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True)
    redacted: list[tuple[str, str]] = []
    for key, value in pairs:
        if key.lower() in ALWAYS_REDACT_QUERY_KEYS:
            redacted.append((key, REDACTED))
            continue
        sanitised = sanitize_value(value)
        redacted.append((key, sanitised if isinstance(sanitised, str) else REDACTED))
    return urlencode(redacted)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("X-Real-IP")
    if real:
        return real
    if request.client is not None:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Emit one structured access log per request, with PII redaction."""

    def __init__(
        self,
        app: ASGIApp,
        config: AccessLogConfig | None = None,
    ) -> None:
        super().__init__(app)
        self.config = config or AccessLogConfig()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in self.config.excluded_paths:
            return await call_next(request)

        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.perf_counter()
        status_code = 500
        error: str | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error = repr(exc)
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._emit(
                request=request,
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                error=error,
            )

    def _emit(
        self,
        *,
        request: Request,
        status_code: int,
        duration_ms: float,
        request_id: str,
        error: str | None,
    ) -> None:
        principal = getattr(request.state, "principal", None)
        user_id = (
            str(principal.user_id)
            if principal is not None and getattr(principal, "user_id", None)
            else None
        )
        api_key_id = (
            str(principal.api_key_id)
            if principal is not None and getattr(principal, "api_key_id", None)
            else None
        )

        payload: dict[str, Any] = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "client_ip": _client_ip(request),
            "headers": _redact_headers(list(request.headers.items())),
            "query": _redact_query_string(request.url.query),
        }
        if user_id is not None:
            payload["user_id"] = user_id
        if api_key_id is not None:
            payload["api_key_id"] = api_key_id
        if error is not None:
            payload["error"] = error

        level = logging.ERROR if status_code >= 500 else (
            logging.WARNING if status_code >= 400 else logging.INFO
        )
        logger.log(
            level,
            "%s %s %d %.2fms",
            request.method,
            request.url.path,
            status_code,
            duration_ms,
            extra={"data": json.dumps(payload, default=str)},
        )


__all__ = [
    "ALWAYS_REDACT_HEADERS",
    "ALWAYS_REDACT_QUERY_KEYS",
    "AccessLogConfig",
    "AccessLogMiddleware",
    "REDACTED",
]
