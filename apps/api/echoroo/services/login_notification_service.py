"""New-device login notification service (FR-104).

Responsibility
--------------
After every successful sign-in (``/web-api/v1/auth/2fa/challenge`` or
``/web-api/v1/auth/2fa/setup/totp/confirm``), the auth router calls
:meth:`LoginNotificationService.record_and_maybe_notify`. The service:

1. Hashes ``(ip, user_agent)`` via
   :func:`echoroo.core.kms.compute_pii_hash` so the persisted lookup
   keys never carry raw PII (FR-091, FR-091b).

2. Looks up the existing row in
   ``user_login_notifications_seen``. If one exists and was last seen
   less than :data:`LOGIN_NOTIFICATION_SUPPRESS_WINDOW` ago, the
   service refreshes ``last_seen_at`` and returns ``False`` —
   suppressing repeated emails when a user logs in repeatedly from
   the same workstation.

3. Otherwise it ``INSERT ... ON CONFLICT DO UPDATE``s the row,
   enqueues an :class:`OutboxEvent` with
   ``event_type='login_notification'``, and returns ``True``.

The OutboxEvent payload carries the *raw* IP and UA strings so the
dispatcher can render them into a user-facing email — they are
transient (deleted after the dispatcher commits ``status='done'``)
and never cross the security boundary into long-term storage.

Caller contract
---------------
The auth router MUST call this service in a NEW transaction *after*
``_issue_real_session`` has committed. Calling it inside the session-
issuing transaction would pin the OutboxEvent INSERT to that
transaction's success — fine on its own — but the route's audit hook
already runs post-commit, and we want the notification side-effect to
share that ordering so a logged-in user is never missing from the
notification trail.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.kms import compute_pii_hash
from echoroo.models.user import User
from echoroo.services import outbox_service

logger = logging.getLogger(__name__)


#: How long a (user, IP, UA) row stays around as "known". Within this
#: window any login from the same tuple is suppressed (no email);
#: beyond the window the row is considered expired and a fresh login
#: counts as a new device, re-emitting the notification. The Phase-3
#: janitor (TODO) reaps rows older than this so the table does not
#: grow without bound.
LOGIN_RECORD_RETENTION: Final[timedelta] = timedelta(days=30)

#: Alias kept for callers that want a "suppress within X" name. We
#: collapse the two windows into one because the spec intends a
#: simple monotonic contract: known device → silent; new or expired
#: row → email. Keeping both names lets a future caller (e.g. an
#: ops dashboard) distinguish the cases without forcing a refactor
#: when we eventually decouple them.
LOGIN_NOTIFICATION_SUPPRESS_WINDOW: Final[timedelta] = LOGIN_RECORD_RETENTION

#: ``OutboxEvent.event_type`` discriminator consumed by the dispatcher
#: in :mod:`echoroo.workers.login_notification_dispatcher`.
LOGIN_NOTIFICATION_EVENT_TYPE: Final[str] = "login_notification"


class LoginNotificationService:
    """Stateful helper that decides whether to enqueue a login-notification email."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_and_maybe_notify(
        self,
        user: User,
        *,
        ip: str,
        user_agent: str,
    ) -> bool:
        """Record this login and enqueue a notification if it looks "new".

        Args:
            user: The authenticated user. The function only reads
                ``user.id`` / ``user.email``; the row is not modified.
            ip: Caller-resolved IP address (already X-Forwarded-For
                aware via :func:`_client_ip` in the auth router).
            user_agent: Caller-resolved User-Agent header (defaults to
                empty string when missing — both are normalised here).

        Returns:
            ``True`` if a fresh OutboxEvent was enqueued, ``False`` if
            the (IP, UA) tuple was already seen within
            :data:`LOGIN_NOTIFICATION_SUPPRESS_WINDOW`.
        """
        ip_value = (ip or "").strip()
        ua_value = (user_agent or "").strip()
        ip_hash = compute_pii_hash(ip_value)
        ua_hash = compute_pii_hash(ua_value)
        now = datetime.now(UTC)

        existing = await self._fetch_recent_seen(user_id=user.id, ip_hash=ip_hash, ua_hash=ua_hash)
        if existing is not None and (now - existing) <= LOGIN_NOTIFICATION_SUPPRESS_WINDOW:
            # Refresh ``last_seen_at`` so the suppression window slides
            # forward — but DO NOT enqueue a fresh email.
            await self._upsert_seen(
                user_id=user.id,
                ip_hash=ip_hash,
                ua_hash=ua_hash,
                now=now,
            )
            logger.debug(
                "login notification suppressed for user_id=%s (recent seen)",
                user.id,
            )
            return False

        # Either: row missing entirely (genuinely new device) OR
        # row older than the suppression window (treat as new again).
        await self._upsert_seen(
            user_id=user.id,
            ip_hash=ip_hash,
            ua_hash=ua_hash,
            now=now,
        )
        await outbox_service.enqueue(
            self.db,
            event_type=LOGIN_NOTIFICATION_EVENT_TYPE,
            payload={
                "user_id": str(user.id),
                "user_email": user.email,
                "ip": ip_value,
                "user_agent": ua_value,
                "ip_hash": ip_hash,
                "ua_hash": ua_hash,
                "timestamp": now.isoformat(),
            },
            idempotency_key=f"login-notification:{user.id}:{ip_hash}:{ua_hash}:{int(now.timestamp())}",
        )
        return True

    # -- helpers ---------------------------------------------------------

    async def _fetch_recent_seen(
        self,
        *,
        user_id: object,
        ip_hash: str,
        ua_hash: str,
    ) -> datetime | None:
        """Return ``last_seen_at`` for a (user, ip, ua) tuple — or None."""
        result = await self.db.execute(
            sa.text(
                "SELECT last_seen_at FROM user_login_notifications_seen "
                "WHERE user_id = :user_id "
                "  AND ip_hash = :ip_hash "
                "  AND ua_hash = :ua_hash "
                "  AND last_seen_at > :retention_cutoff "
                "LIMIT 1"
            ),
            {
                "user_id": user_id,
                "ip_hash": ip_hash,
                "ua_hash": ua_hash,
                # Anything older than the retention window is treated as
                # absent — we still upsert the row in
                # :meth:`_upsert_seen`, but the caller will count it as
                # a "new" device for notification purposes.
                "retention_cutoff": datetime.now(UTC) - LOGIN_RECORD_RETENTION,
            },
        )
        row = result.first()
        if row is None:
            return None
        last_seen = row[0]
        if last_seen is None:
            return None
        if not isinstance(last_seen, datetime):  # pragma: no cover - DB invariant
            return None
        # asyncpg returns timezone-aware datetimes for TIMESTAMPTZ; guard
        # against naive datetimes in unit-test fakes.
        if last_seen.tzinfo is None:
            return last_seen.replace(tzinfo=UTC)
        return last_seen.astimezone(UTC)

    async def _upsert_seen(
        self,
        *,
        user_id: object,
        ip_hash: str,
        ua_hash: str,
        now: datetime,
    ) -> None:
        """INSERT ... ON CONFLICT (user, ip_hash, ua_hash) DO UPDATE."""
        await self.db.execute(
            sa.text(
                """
                INSERT INTO user_login_notifications_seen
                    (user_id, ip_hash, ua_hash, last_seen_at, created_at)
                VALUES
                    (:user_id, :ip_hash, :ua_hash, :now, :now)
                ON CONFLICT ON CONSTRAINT uq_user_login_notifications_seen_tuple
                DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at
                """
            ),
            {
                "user_id": user_id,
                "ip_hash": ip_hash,
                "ua_hash": ua_hash,
                "now": now,
            },
        )


__all__ = [
    "LOGIN_NOTIFICATION_EVENT_TYPE",
    "LOGIN_NOTIFICATION_SUPPRESS_WINDOW",
    "LOGIN_RECORD_RETENTION",
    "LoginNotificationService",
]
