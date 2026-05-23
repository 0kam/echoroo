"""Observability primitives for spec/011 zero-email deployment.

This package owns out-of-process telemetry wiring (currently Sentry, with
optional OTEL hooks expected in a follow-up). The principal invariant is
that **no plaintext credential, invitation URL, step-up token, or
temporary password ever leaves the process through a telemetry channel**.

The four sensitive field names registered for redaction are:

* ``temporary_password`` (admin password reset, FR-011-207)
* ``step_up_token`` (admin recovery step-up, FR-011-206)
* ``invitation_url`` (project invitation issuance, FR-011-102)
* ``signed_token_envelope`` (invitation envelope, FR-011-104)

…plus the request header ``X-Step-Up-Token`` (the wire counterpart of
``step_up_token``, also FR-011-206).

The registry is intentionally duplicated between
:mod:`echoroo.observability.sentry` (out-of-process egress) and
:mod:`echoroo.middleware.redaction` (in-process structured-log envelope)
with a shared module-level tuple
(:data:`SENSITIVE_FIELDS`) so both consumers fail the same way on
extension drift.

Spec references:
    * spec/011-zero-email-deployment §research.md R13 (telemetry redaction).
    * spec/011-zero-email-deployment §FR-011-207, §FR-011-206, §FR-011-102,
      §FR-011-104.
"""

from __future__ import annotations

from typing import Final

#: Canonical list of sensitive field names that MUST be scrubbed from any
#: telemetry channel (Sentry breadcrumbs / request bodies / response
#: bodies, structured-log envelopes, future OTEL spans). Shared by
#: :mod:`echoroo.observability.sentry` and
#: :mod:`echoroo.middleware.redaction`; updating this tuple updates both
#: code paths in lock-step.
SENSITIVE_FIELDS: Final[tuple[str, ...]] = (
    "temporary_password",
    "step_up_token",
    "invitation_url",
    "signed_token_envelope",
)

#: Canonical list of sensitive request / response headers that MUST be
#: scrubbed.
#:
#: * ``x-step-up-token`` — wire counterpart of the ``step_up_token``
#:   response/body field (FR-011-206).
#: * ``authorization`` — bearer tokens / session JWTs presented by API
#:   key holders. Step 12 R1 P0-2: the spec/011 cutover removed the
#:   email subsystem but did NOT narrow the set of credential-bearing
#:   headers; ``Authorization`` was always in scope but the original
#:   T710 hook only enumerated ``x-step-up-token``. Adding it here
#:   ensures both request- and response-side scrubbing branches walk
#:   it case-insensitively.
#: * ``cookie`` / ``set-cookie`` — session cookies + their refresh
#:   counterparts on response. Sentry stores ``request.cookies``
#:   separately (handled by a blanket replace inside
#:   :func:`echoroo.observability.sentry._before_send`); listing the
#:   header form here covers the path where a client / proxy serialises
#:   cookies into the ``Cookie`` *header* rather than the dedicated
#:   cookies blob, AND the response-side ``Set-Cookie`` payload.
#: * ``x-csrf-token`` — paired with the session cookie. Stripped on
#:   both request and response so an event that carries the header on
#:   either edge never lands in telemetry.
SENSITIVE_HEADERS: Final[tuple[str, ...]] = (
    "x-step-up-token",
    "authorization",
    "cookie",
    "set-cookie",
    "x-csrf-token",
)

__all__ = [
    "SENSITIVE_FIELDS",
    "SENSITIVE_HEADERS",
]
