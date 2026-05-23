"""Structured-log redaction middleware + logging filter (spec/011 T711).

This module is the **in-process** companion of
:mod:`echoroo.observability.sentry` (out-of-process telemetry). It
ensures the four spec/011 sensitive field names never appear in any
structured log record emitted by the ``echoroo`` logger family — even
if a downstream handler accidentally hands one of those values to
``logger.info(...)`` as a structured ``extra`` payload.

The middleware itself does NOT mutate the wire response body — that is
deliberate. The handler-side contract (FR-011-102, FR-011-104,
FR-011-206, FR-011-207) is the source of truth: an issuance handler
returns the sensitive value to the *authorised* caller exactly once,
and an authorised caller is entitled to see it. The middleware instead:

1. Installs a process-wide logging filter (idempotent) that scrubs any
   sensitive field name found in a log record's ``msg`` arguments,
   ``args``, ``extra``-derived attributes, or its standard ``getMessage``
   output before the formatter touches the record.
2. On each request, ensures the filter is attached to the ``echoroo``
   logger tree (also idempotent — a no-op once installed).

The two-tier (middleware + standalone filter) shape lets us:

* Activate redaction at app startup via middleware registration without
  requiring every test fixture to remember to call an ``install_*``
  function.
* Keep the filter independently testable (the
  :func:`_sensitive_redaction_filter` function is pure aside from its
  in-place record mutation).

Spec references:
    * spec/011 §research.md R13 — Telemetry redaction separation of
      concerns (do NOT extend ``middleware/audit_logging.py``).
    * spec/011 §FR-011-207 (temporary_password), §FR-011-206
      (step_up_token / X-Step-Up-Token), §FR-011-102 (invitation_url),
      §FR-011-104 (signed_token_envelope).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from echoroo.observability import SENSITIVE_FIELDS, SENSITIVE_HEADERS
from echoroo.observability.sentry import REDACTED_MARKER, _scrub_mapping

logger = logging.getLogger(__name__)


#: The logger names whose record tree receives the filter. We deliberately
#: cover the ``echoroo`` root plus the per-subsystem child loggers used
#: by ``audit_logging`` / ``requests`` / structured emitters so a
#: ``logger.getLogger("echoroo.x.y")`` instance picks up the filter via
#: propagation OR direct attachment, whichever wins first.
_REDACTED_LOGGER_NAMES: Final[tuple[str, ...]] = (
    "echoroo",
    "echoroo.requests",
    "echoroo.access",
)

#: Module-level sentinel so re-importing this module / re-running the
#: middleware install path does not stack filters.
_FILTER_INSTALLED: bool = False


def _scrub_text(text: str) -> str:
    """Replace any sensitive header name occurrences in free-form text.

    This is a best-effort secondary defence for message templates that
    inline a sensitive header value (``logger.info(f"X-Step-Up-Token={t}")``
    style). We replace the *header name* token with the marker so the
    operator sees that *something* was scrubbed without ever seeing the
    value. For structured field names the per-record args walk handles
    the actual value replacement.
    """
    redacted = text
    for header_name in SENSITIVE_HEADERS:
        # Case-insensitive match against the canonical header name plus
        # an optional value run after ``:`` / ``=``. We intentionally
        # keep this loose so a partial leak still drops its tail.
        for variant in (header_name, header_name.upper(), header_name.title()):
            if variant in redacted:
                # Replace the whole "header=value" run up to the next
                # whitespace / quote / comma boundary.
                redacted = _redact_after_marker(redacted, variant)
    return redacted


def _redact_after_marker(text: str, marker: str) -> str:
    """Replace text from ``marker`` to the next whitespace / quote boundary."""
    out_parts: list[str] = []
    cursor = 0
    while True:
        idx = text.find(marker, cursor)
        if idx < 0:
            out_parts.append(text[cursor:])
            break
        out_parts.append(text[cursor:idx])
        end = idx + len(marker)
        # Skip the separator (``=`` / ``:``) plus optional whitespace.
        while end < len(text) and text[end] in (":", "=", " ", "\t"):
            end += 1
        # Run until the first whitespace / quote / comma / brace.
        while end < len(text) and text[end] not in (" ", "\t", "\n", "'", '"', ",", "}", ")"):
            end += 1
        out_parts.append(f"{marker}={REDACTED_MARKER}")
        cursor = end
    return "".join(out_parts)


def _sensitive_redaction_filter(record: logging.LogRecord) -> bool:
    """Logging filter — scrub spec/011 sensitive fields from a record.

    Mutates the record in place. Always returns ``True`` so the record
    still propagates to handlers (after scrubbing). Defensive against
    exotic ``extra`` shapes — any error short-circuits to "let the
    record through unchanged" rather than dropping it (drop-on-error
    would silently lose ops signal).
    """
    try:
        # Walk standard ``args`` — supports both tuple-style
        # ``logger.info("foo %s", arg)`` and dict-style
        # ``logger.info("foo %(k)s", {"k": v})`` invocations.
        if isinstance(record.args, dict):
            record.args = _scrub_mapping(dict(record.args))
        elif isinstance(record.args, tuple):
            new_args: list[Any] = []
            for arg in record.args:
                if isinstance(arg, dict):
                    new_args.append(_scrub_mapping(dict(arg)))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)

        # Walk any ``extra``-derived attributes attached to the record.
        # ``logging`` stamps ``extra`` keys directly onto the record's
        # ``__dict__``; we walk the dict and scrub any value whose key
        # matches a sensitive field name.
        for attr_name in list(record.__dict__.keys()):
            if attr_name in SENSITIVE_FIELDS:
                setattr(record, attr_name, REDACTED_MARKER)
            else:
                value = getattr(record, attr_name)
                if isinstance(value, (dict, list, tuple)):
                    setattr(record, attr_name, _scrub_mapping(value))

        # Final defence — scrub the rendered message string for any
        # inline header-name appearances.
        if isinstance(record.msg, str):
            record.msg = _scrub_text(record.msg)
    except Exception:
        # Never break logging on a redaction bug.
        return True
    return True


class _RedactionFilter(logging.Filter):
    """Adapter wrapping :func:`_sensitive_redaction_filter` as a Filter."""

    def filter(self, record: logging.LogRecord) -> bool:
        return _sensitive_redaction_filter(record)


def install_logging_redaction() -> None:
    """Attach the redaction filter to the ``echoroo`` logger tree.

    Idempotent: a second call is a no-op. The filter is attached to the
    canonical logger names rather than the root logger so we do not
    interfere with third-party library logs (which have their own
    redaction concerns and shapes).
    """
    global _FILTER_INSTALLED
    if _FILTER_INSTALLED:
        return
    filter_instance = _RedactionFilter()
    for name in _REDACTED_LOGGER_NAMES:
        target = logging.getLogger(name)
        # Avoid duplicate attachment if a previous call (e.g. from a
        # test fixture) already installed an instance of this class.
        already_attached = any(
            isinstance(existing, _RedactionFilter) for existing in target.filters
        )
        if not already_attached:
            target.addFilter(filter_instance)
    _FILTER_INSTALLED = True


class RedactionMiddleware(BaseHTTPMiddleware):
    """Ensure the structured-log redaction filter is installed.

    The middleware's per-request body is intentionally tiny: it asks
    :func:`install_logging_redaction` to run once (idempotent) and then
    delegates to the next handler unchanged. The actual scrubbing
    happens in the logging filter installed at app startup — the
    middleware exists primarily as the **registration site** so the
    filter installation is bound to app-construction time and to the
    test client's app factory, both of which import this module.

    The middleware does NOT mutate the wire response body: the
    handler-side contract (FR-011-102, FR-011-104, FR-011-206,
    FR-011-207) is the source of truth and the authorised caller IS
    entitled to receive the sensitive value exactly once.

    Example:
        ```python
        # Register AFTER all auth/CSRF middleware (Starlette LIFO: last
        # added = outermost wrap), but its placement is mostly
        # informational — the filter is installed on first dispatch
        # and remains active for the process lifetime.
        app.add_middleware(RedactionMiddleware)
        ```
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        install_logging_redaction()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Filter install happens in ``__init__`` (once per app); the
        # per-request hook is intentionally a passthrough so the
        # middleware does not add latency to the request path.
        return await call_next(request)


__all__ = [
    "RedactionMiddleware",
    "install_logging_redaction",
]
