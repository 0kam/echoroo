"""CMK (customer master key) operational helpers (T977 / Phase 17 A-1).

Wraps boto3 KMS calls with policy enforcement so an operator cannot
accidentally schedule a CMK deletion inside the 30-day cooling
window. AWS allows ``PendingWindowInDays`` as low as 7; the Echoroo
runbook requires at least 30 to give the on-call team a recovery
window for any in-progress data flows that depend on the CMK.

The 30-day minimum is encoded as ``MIN_DELETION_WINDOW_DAYS`` so it
appears in test failure messages and CI grep hooks.

Runbook reference: ``specs/006-permissions-redesign/checklists/security.md``
section "鍵ローテ SLA（Runbook）" — "CMK deletion window 30 日最低".
"""

from __future__ import annotations

import logging
from typing import Any

import boto3

logger = logging.getLogger(__name__)

MIN_DELETION_WINDOW_DAYS = 30
"""Minimum cooling window the runbook accepts. Below this the helper
raises ``CMKDeletionWindowError`` before reaching the AWS API."""


class CMKDeletionWindowError(ValueError):
    """Raised when a CMK deletion request specifies a window below the
    runbook minimum (30 days).

    Inherits from :class:`ValueError` so existing call sites that catch
    ``ValueError`` (or use ``pytest.raises((ValueError, Exception))``)
    still match.
    """


def schedule_cmk_deletion(
    *,
    key_id: str,
    pending_window_in_days: int,
    operator: str | None = None,
    reason: str | None = None,
    kms_client: Any | None = None,
    region_name: str = "us-east-1",
) -> dict[str, Any]:
    """Schedule a CMK for deletion after enforcing the runbook minimum window.

    Args:
        key_id: AWS KMS key ID or alias.
        pending_window_in_days: Cooling window. MUST be ``>= 30`` per
            runbook policy (Echoroo §CMK rotation).
        operator: Human / SSO identity initiating the request, recorded
            in the audit event.
        reason: Free-form justification (ticket / change-request URL),
            recorded in the audit event.
        kms_client: Optional pre-built boto3 KMS client (for tests).
        region_name: AWS region used when ``kms_client`` is not supplied.

    Raises:
        CMKDeletionWindowError: ``pending_window_in_days < 30``. The
            AWS API is NOT called in this case — the request is
            rejected before any state is mutated.

    Returns:
        The AWS ``schedule_key_deletion`` response dict.
    """
    if pending_window_in_days < MIN_DELETION_WINDOW_DAYS:
        # Audit / runbook-level event so the rejected attempt is visible
        # to the security team. Use a structured logger so the standard
        # audit handler picks it up.
        logger.warning(
            "cmk_deletion.rejected",
            extra={
                "key_id": key_id,
                "pending_window_in_days": pending_window_in_days,
                "minimum": MIN_DELETION_WINDOW_DAYS,
                "operator": operator,
                "reason": reason,
            },
        )
        raise CMKDeletionWindowError(
            f"CMK deletion rejected: pending_window_in_days="
            f"{pending_window_in_days} is below the {MIN_DELETION_WINDOW_DAYS}-"
            f"day runbook minimum (Echoroo §CMK rotation policy)."
        )
    if kms_client is None:
        kms_client = boto3.client("kms", region_name=region_name)
    response: dict[str, Any] = kms_client.schedule_key_deletion(
        KeyId=key_id,
        PendingWindowInDays=pending_window_in_days,
    )
    logger.info(
        "cmk_deletion.scheduled",
        extra={
            "key_id": key_id,
            "pending_window_in_days": pending_window_in_days,
            "operator": operator,
            "reason": reason,
        },
    )
    return response


__all__ = [
    "CMKDeletionWindowError",
    "MIN_DELETION_WINDOW_DAYS",
    "schedule_cmk_deletion",
]
