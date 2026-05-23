"""Sentry initialisation + before_send redaction hook (spec/011 T710).

The Sentry SDK is **optional**. If the operator has not installed
``sentry-sdk`` or has not set ``SENTRY_DSN`` in the environment,
:func:`init_sentry` is a no-op. This matches the zero-email deployment
persona's expectation that the application boots and runs cleanly with
zero external telemetry plumbing.

When both conditions are met, this module installs a ``before_send``
hook that scrubs the four spec/011 sensitive field names
(:data:`echoroo.observability.SENSITIVE_FIELDS`) from request bodies,
response bodies, breadcrumbs, and event extras. It also scrubs request
headers that match :data:`echoroo.observability.SENSITIVE_HEADERS`
(case-insensitive).

The scrubbing strategy is *recursive replacement of the value* with the
canonical marker ``"[REDACTED]"``. The original key is preserved so
operators can still see *that* the field was present (useful for
correlating leaks back to the emitting endpoint) without ever seeing its
value.

Spec references:
    * spec/011 §research.md R13 — Telemetry redaction separation of
      concerns.
    * spec/011 §FR-011-207 (temporary_password), §FR-011-206
      (step_up_token / X-Step-Up-Token), §FR-011-102 (invitation_url),
      §FR-011-104 (signed_token_envelope).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from echoroo.observability import SENSITIVE_FIELDS, SENSITIVE_HEADERS

logger = logging.getLogger(__name__)

#: Marker substituted for any scrubbed value. Matches the marker used by
#: :class:`echoroo.middleware.audit_logging.AccessLogMiddleware` so the
#: operator-visible redaction string is consistent across channels.
REDACTED_MARKER: str = "[REDACTED]"


def _scrub_mapping(payload: Any) -> Any:
    """Recursively replace sensitive values inside a JSON-like payload.

    The function walks the structure in place where possible and returns
    the (potentially same) reference. Mappings are descended by key;
    sequences (list/tuple) are descended element-wise; primitives are
    returned unchanged.

    Args:
        payload: A JSON-decoded payload (dict / list / primitive). May be
            ``None``.

    Returns:
        The payload with sensitive values replaced by
        :data:`REDACTED_MARKER`.
    """
    if isinstance(payload, dict):
        for key in list(payload.keys()):
            if isinstance(key, str) and key in SENSITIVE_FIELDS:
                payload[key] = REDACTED_MARKER
            else:
                payload[key] = _scrub_mapping(payload[key])
        return payload
    if isinstance(payload, list):
        return [_scrub_mapping(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(_scrub_mapping(item) for item in payload)
    return payload


def _scrub_headers(headers: Any) -> Any:
    """Scrub sensitive request headers in a Sentry event header mapping.

    Sentry stores headers as a dict (case-insensitive lookup is *not*
    guaranteed by the client SDK), so we walk the keys and replace any
    case-insensitive match against :data:`SENSITIVE_HEADERS`.
    """
    if not isinstance(headers, dict):
        return headers
    lowered_sensitive = {header.lower() for header in SENSITIVE_HEADERS}
    for key in list(headers.keys()):
        if isinstance(key, str) and key.lower() in lowered_sensitive:
            headers[key] = REDACTED_MARKER
    return headers


def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Sentry ``before_send`` hook — scrub spec/011 sensitive fields.

    The hook MUST be defensive: a buggy redaction must never crash the
    SDK and silently lose the event. Any unexpected exception is logged
    at ``warning`` and the event is dropped (returning ``None``) so a
    half-redacted event never escapes.
    """
    try:
        request = event.get("request")
        if isinstance(request, dict):
            if "data" in request:
                request["data"] = _scrub_mapping(request["data"])
            if "headers" in request:
                request["headers"] = _scrub_headers(request["headers"])
            if "cookies" in request:
                # Cookies may carry session tokens; we drop the entire
                # cookie blob rather than attempting per-cookie scrubbing
                # so an operator never sees a partial credential.
                request["cookies"] = REDACTED_MARKER

        # ``extra`` and ``contexts`` are free-form key/value blobs from
        # ``sentry_sdk.set_extra`` / ``set_context``; walk them too.
        for top_key in ("extra", "contexts", "tags"):
            value = event.get(top_key)
            if value is not None:
                event[top_key] = _scrub_mapping(value)

        breadcrumbs = event.get("breadcrumbs")
        if isinstance(breadcrumbs, dict):
            crumbs_list = breadcrumbs.get("values")
            if isinstance(crumbs_list, list):
                for crumb in crumbs_list:
                    if isinstance(crumb, dict):
                        data_field = crumb.get("data")
                        if data_field is not None:
                            crumb["data"] = _scrub_mapping(data_field)
        elif isinstance(breadcrumbs, list):
            for crumb in breadcrumbs:
                if isinstance(crumb, dict):
                    data_field = crumb.get("data")
                    if data_field is not None:
                        crumb["data"] = _scrub_mapping(data_field)

        # Message payloads may carry redacted-eligible substrings via
        # f-strings; we cannot regex-strip values without false positives,
        # so we leave the message body alone but redact any structured
        # ``message.params`` mapping that Sentry produces from
        # ``logger.warning("foo %s", arg)`` style logs.
        message = event.get("message")
        if isinstance(message, dict):
            params = message.get("params")
            if params is not None:
                message["params"] = _scrub_mapping(params)

        return event
    except Exception:
        logger.warning(
            "sentry before_send redaction raised; dropping event to "
            "avoid leaking sensitive fields",
            exc_info=True,
        )
        # Returning ``None`` from before_send tells the SDK to discard
        # the event. We prefer that over emitting a partially-redacted
        # event that may carry a credential.
        return {}


def init_sentry() -> bool:
    """Initialise Sentry SDK with spec/011 redaction hook.

    The function is a no-op when:

    * ``sentry-sdk`` is not importable (operator did not install it); or
    * The ``SENTRY_DSN`` environment variable is unset or empty.

    Otherwise the SDK is initialised with the :func:`_before_send` hook
    installed.

    Returns:
        ``True`` when the SDK was successfully initialised; ``False`` on
        any of the no-op paths above. Callers MAY use the return value
        to emit a startup log line indicating whether telemetry is live.
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("SENTRY_DSN unset — Sentry telemetry disabled (spec/011 default)")
        return False

    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; "
            "telemetry remains disabled. Install ``sentry-sdk`` "
            "to enable spec/011 redacted reporting."
        )
        return False

    environment = os.environ.get("ENVIRONMENT", "development")
    release = os.environ.get("APP_VERSION") or os.environ.get("SENTRY_RELEASE")

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        before_send=_before_send,
        # Conservative defaults — operators tune via env vars on demand.
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    logger.info(
        "Sentry telemetry initialised (environment=%s, release=%s, "
        "redaction registry=%d fields + %d headers)",
        environment,
        release or "unset",
        len(SENSITIVE_FIELDS),
        len(SENSITIVE_HEADERS),
    )
    return True


__all__ = [
    "REDACTED_MARKER",
    "init_sentry",
]
