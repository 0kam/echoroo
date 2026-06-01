"""Outbox dispatcher for ``trusted_user.expiry_notification`` (FR-045).

Wiring overview
---------------
:mod:`echoroo.workers.trusted_expiry_notifier` enqueues a row into the
``outbox_events`` table with
``event_type='trusted_user.expiry_notification'`` whenever a Trusted
overlay's ``expires_at`` lands inside the ``[now + 6d, now + 7d]``
window. Without a registered handler the outbox processor's default
handler raises :class:`NotImplementedError` and the row eventually
moves to ``status='dead_letter'`` after MAX_RETRY attempts — i.e. the
FR-045 warning email is never delivered AND the outbox table fills with
dead-letter rows that page the on-call.

This module owns the *processing* side. The handler currently runs as
a logging-only stub: Phase 11+ will swap in a Resend-backed sender
(mirroring :mod:`echoroo.workers.login_notification_dispatcher`) once
the email template is approved. Until then the stub:

1. Sanitises the payload (NFKC normalise + ASCII control char reject)
   so a malformed enqueue cannot poison downstream dispatch.
2. Logs a single line per enqueued event so operators can confirm the
   pipeline is wired end-to-end.
3. Returns cleanly so the outbox processor calls ``mark_done`` and the
   row is consumed (no dead-letter accumulation).

The handler treats every payload field as untrusted. A payload that
fails sanitisation raises :class:`TrustedExpiryPayloadError`; the
outbox processor records the failure and either retries (3 attempts)
or moves the row to ``dead_letter`` (5 attempts) per the standard
retry budget.
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.text import has_control_chars
from echoroo.workers.outbox_processor import register_outbox_handler
from echoroo.workers.trusted_expiry_notifier import OUTBOX_EVENT_TRUSTED_EXPIRY

logger = logging.getLogger(__name__)

#: Hard cap for fields that flow into the (future) email body. Mirrors
#: the cap in :mod:`echoroo.workers.login_notification_dispatcher`.
_MAX_FIELD_LEN: Final[int] = 500


class TrustedExpiryPayloadError(ValueError):
    """Raised when the outbox payload fails sanitisation."""


def _sanitise_field(value: object, *, field_name: str) -> str:
    """NFKC-normalise, reject control chars, and truncate to a hard cap.

    Identical contract to
    :func:`echoroo.workers.login_notification_dispatcher._sanitise_field`
    so future Phase 11 swap to a Resend sender is a drop-in change.
    """
    if value is None:
        return ""
    raw = str(value)
    normalised = unicodedata.normalize("NFKC", raw).strip()
    if has_control_chars(normalised):
        raise TrustedExpiryPayloadError(
            f"trusted_user.expiry_notification payload field {field_name!r} "
            "contains control characters"
        )
    if len(normalised) > _MAX_FIELD_LEN:
        normalised = normalised[:_MAX_FIELD_LEN]
    return normalised


@register_outbox_handler(OUTBOX_EVENT_TRUSTED_EXPIRY)
async def dispatch_trusted_expiry_notification(
    _session: AsyncSession,
    payload: dict[str, Any],
) -> None:
    """Outbox handler for ``event_type='trusted_user.expiry_notification'``.

    Phase 10 lands this as a logging-only stub so the outbox row is
    consumed (``mark_done`` runs in the surrounding transaction) and
    the FR-045 warning pipeline is unblocked. Phase 11+ adds the
    Resend send call and the localised email template.

    Idempotency
    -----------
    The notifier uses an idempotency key of
    ``trusted_expiry:{invitation_id}:{role}:{utc_date}`` so re-running
    the daily beat job collapses on ``ON CONFLICT (idempotency_key) DO
    UPDATE``. The handler itself is a no-op log call, so re-running it
    against the same row is also idempotent (FR-076a).
    """
    role = _sanitise_field(payload.get("role"), field_name="role")
    recipient = _sanitise_field(
        payload.get("recipient_email"), field_name="recipient_email"
    )
    invitation_id = _sanitise_field(
        payload.get("invitation_id"), field_name="invitation_id"
    )
    project_id = _sanitise_field(
        payload.get("project_id"), field_name="project_id"
    )
    expires_at = _sanitise_field(
        payload.get("expires_at"), field_name="expires_at"
    )

    if not recipient:
        # An empty recipient indicates a producer-side bug — the
        # notifier already filters rows whose user/owner email is
        # blank, so this branch should never fire in production. We
        # still raise so the row moves to dead_letter and the on-call
        # gets paged.
        raise TrustedExpiryPayloadError(
            "trusted_user.expiry_notification payload missing recipient email"
        )
    if role not in {"trusted_user", "owner"}:
        raise TrustedExpiryPayloadError(
            f"trusted_user.expiry_notification payload role={role!r} "
            "is not 'trusted_user' or 'owner'"
        )

    # spec/011 T616: the email-send path is permanently gone. The
    # trusted-expiry notice now surfaces purely as the
    # ``project.trusted_user.expiry_notice`` audit row written by
    # :func:`echoroo.workers.trusted_expiry_notifier._record_notice_audit`
    # (which carries ``target_user_id`` so it appears in the trusted
    # user's ``GET /me/activity``). This handler stays a tidy outbox
    # consumer: it validates the payload and returns so ``mark_done``
    # runs in the surrounding transaction and the row does not
    # dead-letter. The recipient address is logged only through the
    # non-PII surrogate hash so we never spill PII into log storage.
    from echoroo.services.email import _safe_recipient_hash  # noqa: PLC0415

    logger.info(
        "trusted_expiry_dispatcher: queued warning notification "
        "role=%s recipient_hash=%s invitation_id=%s project_id=%s "
        "expires_at=%s (spec/011 zero-email stub)",
        role,
        _safe_recipient_hash(recipient),
        invitation_id,
        project_id,
        expires_at,
    )


__all__ = [
    "TrustedExpiryPayloadError",
    "dispatch_trusted_expiry_notification",
]
