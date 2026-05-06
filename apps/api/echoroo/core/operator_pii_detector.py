"""Phase 17 backlog A-13 — PII detector for operator free-form fields.

Operator-supplied ``reason`` / ``support_ticket_id`` strings reach
``platform_audit_log.detail.reason_excerpt`` and (for some endpoints)
business tables (``project_taxon_sensitivity_overrides.rejected_reason``,
``two_factor_reset_requests.reason``, ``superuser_break_glass.reason``,
``superuser_approval_requests.approvals[].reason``) and outbox payloads.

Even though :class:`echoroo.core.audit.AuditLogSanitizer` redacts PII at
audit write time (FR-091a layer b), the **business tables** and
**outbox** rows are NOT routed through that sanitiser — so an email
pasted into ``reason`` would persist in ``project_audit_log.detail`` and
in outbox event payloads in plaintext, breaking the same FR-091a
contract that the audit sanitiser is enforcing on the audit log.

This module rejects PII at the **API boundary** instead, by exposing
reusable Pydantic ``Annotated`` types that validate the operator's
input via ``AfterValidator``. The detector reuses the regex catalogue
from :mod:`echoroo.core.audit` (single source of truth — FR-091a
contract enforced identically everywhere) via the public
:func:`echoroo.core.audit.contains_pii` helper.

Strategy choice (P1 — Pydantic 422 reject)
------------------------------------------
The audit sanitiser remains the runtime safety net for the audit log
itself, but for **operator** input we prefer to reject the request with
HTTP 422 so the operator sees the validation failure immediately and
can rewrite the reason without referencing the data subject by PII.
Reference target users by ``user_id`` or by an external support
ticket reference instead.

Educational, non-detailed error message
---------------------------------------
The error message tells the operator *what kind of input is rejected*
and *what to do instead*, but deliberately does NOT echo back which
specific PII pattern matched (an attacker probing the validator could
otherwise build a regex oracle).
"""

from __future__ import annotations

from typing import Annotated, Final

from pydantic import AfterValidator, Field

# Import the public detection helper rather than the underlying private
# patterns. The audit module retains sole ownership of the regex set so
# audit-time redaction (sanitiser) and API-boundary rejection
# (validator) cannot drift apart.
from echoroo.core.audit import contains_pii

_OPERATOR_PII_ERROR: Final[str] = (
    "Free-form operator field must not contain PII (email addresses, "
    "phone numbers, national identifiers, credit card numbers, API "
    "tokens, etc.). Reference the target user by user_id and use an "
    "external support-ticket reference instead."
)


def reject_if_pii(value: str) -> str:
    """Pydantic ``AfterValidator`` callable.

    Raises ``ValueError`` (Pydantic surfaces this as HTTP 422) if
    ``value`` contains any PII pattern from
    :func:`echoroo.core.audit.contains_pii`. Returns ``value``
    unchanged otherwise — note that we deliberately do NOT mutate or
    redact the input, so audit-log fidelity is preserved when the
    request is accepted.
    """
    if contains_pii(value):
        raise ValueError(_OPERATOR_PII_ERROR)
    return value


# Reusable Annotated string types for operator free-form schema fields.
# Use these in ``schemas/admin.py`` instead of bare ``str`` so the PII
# rejection is applied uniformly at the API boundary.

OperatorReasonText = Annotated[
    str,
    Field(
        min_length=1,
        max_length=2_000,
        description=(
            "Operator-supplied free-form reason. MUST NOT contain PII "
            "(email, phone, national identifier, credit card, API "
            "tokens). Reference target users by user_id and use an "
            "external ticket reference instead. Validated server-side "
            "(Phase 17 A-13) — submitting PII yields HTTP 422."
        ),
    ),
    AfterValidator(reject_if_pii),
]
"""Reusable type for operator ``reason`` fields.

Pairs the standard length limits (1..2000) with the FR-091a PII reject
gate. Callers should NOT add their own length constraints on top — the
``Field(...)`` here is the canonical limit.
"""

OperatorSupportTicketId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        description=(
            "External support ticket reference (e.g. Zendesk id). "
            "Alphanumeric / dashes / underscores typical. MUST NOT "
            "contain PII (email, phone, national identifier). "
            "Validated server-side (Phase 17 A-13) — submitting PII "
            "yields HTTP 422."
        ),
    ),
    AfterValidator(reject_if_pii),
]
"""Reusable type for operator ``support_ticket_id`` fields.

Tighter length limit (200) because external ticket ids are short
identifiers, not free-form prose.
"""


__all__ = [
    "OperatorReasonText",
    "OperatorSupportTicketId",
    "reject_if_pii",
]
