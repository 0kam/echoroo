"""Production :class:`ApiKeyVerifier` implementation (Phase 15 T155b).

The verifier resolves a raw Bearer credential against the
``api_keys`` table via the :class:`ApiKey` ORM model lifted in Phase 15
Batch 3.

Wire format
===========
Raw keys follow the layout::

    echoroo_<prefix>_<secret>

* ``prefix`` is an 8-character alphanumeric string stored verbatim in
  the ``api_keys.prefix`` column (with the ``echoroo_`` literal kept as
  part of the stored prefix so the column is self-describing under
  ``\\d`` inspection). Concretely, ``api_keys.prefix`` is up to
  20 characters; we store the literal ``echoroo_<8 chars>`` (16 chars)
  there.
* ``secret`` is a URL-safe random string. Only its SHA-256 hex digest is
  persisted in ``api_keys.hashed_secret``.

The verifier:

1. Splits the raw key into ``prefix`` + ``secret``. Malformed input
   returns ``None`` so the middleware emits a uniform 401 ``auth_invalid``.
2. Looks up the ``api_keys`` row by ``prefix`` (UNIQUE, O(1)).
3. Compares the SHA-256 hash of ``secret`` against ``hashed_secret`` in
   constant time using :func:`hmac.compare_digest`.
4. Validates ``revoked_at IS NULL`` and ``expires_at > now()``.
5. Optionally checks the caller's IP against ``allowed_ip_cidrs``. Per
   the contract of :class:`ApiKeyVerifier`, this verifier returns the
   resolved record without IP enforcement — IP violations are the
   responsibility of an outer middleware that already has the request
   object. The CIDR list is exposed on the returned record for that
   middleware to consume.
6. Updates ``last_used_at`` with a 1-minute debounce so legitimate hot
   loops do not pin the row. The debounce is best-effort; failure to
   write the timestamp never blocks the verification (forensic loss is
   preferable to refusing a valid key).

The implementation is deliberately stateless beyond the session
factory — each call opens a short-lived :class:`AsyncSession`, runs the
lookup + optional debounced UPDATE, and commits. This keeps the
verifier safe to share across requests and avoids long-lived
connections per Phase 15 connection-pool budget.

Scoped record
=============
The :class:`ApiKeyRecord` returned by :meth:`DbApiKeyVerifier.verify`
exposes ``user_id``, ``api_key_id``, ``granted_permissions`` and
``project_id``. Phase 15 R3 NO-GO new-Major fix added ``project_id`` so
the per-key project binding (``api_keys.project_id``) flows through to
:func:`echoroo.core.permissions.gate_action` for the cross-project
mismatch check. ``allowed_ip_cidrs`` remains owned by an outer IP
enforcement middleware that re-loads the row by ``api_key_id`` when
needed.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.middleware.auth_router import ApiKeyRecord, ApiKeyVerifier
from echoroo.models.api_key import ApiKey
from echoroo.services.api_key_lifecycle import effective_permissions_for_age

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wire-format helpers
# ---------------------------------------------------------------------------

#: The literal namespace that prefixes every Echoroo-issued API key.
KEY_NAMESPACE: str = "echoroo_"

#: Length of the random alphanumeric prefix segment.
PREFIX_RANDOM_LEN: int = 8

#: Stored prefix length: ``echoroo_`` (8) + 8 random chars = 16. Fits in the
#: ``api_keys.prefix VARCHAR(20)`` column with a 4-char headroom.
STORED_PREFIX_LEN: int = len(KEY_NAMESPACE) + PREFIX_RANDOM_LEN

#: How long a successful verification may go without bumping
#: ``last_used_at``. Reads inside this window skip the UPDATE entirely.
LAST_USED_DEBOUNCE: timedelta = timedelta(minutes=1)

#: Regex matching the wire-format ``echoroo_<prefix>_<secret>``.
_RAW_KEY_PATTERN: re.Pattern[str] = re.compile(
    rf"^(?P<prefix>{re.escape(KEY_NAMESPACE)}[A-Za-z0-9]{{{PREFIX_RANDOM_LEN}}})_(?P<secret>[A-Za-z0-9_\-]+)$"
)


def parse_api_key(raw_key: str) -> tuple[str, str] | None:
    """Split a raw Bearer key into ``(stored_prefix, secret)``.

    Returns ``None`` when the input does not match the canonical
    ``echoroo_<8 chars>_<secret>`` shape. The caller MUST treat ``None``
    as "credential invalid" — never as "skip this verifier" — to
    maintain the spec's anti-enumeration posture (FR-099).
    """
    if not raw_key:
        return None
    match = _RAW_KEY_PATTERN.fullmatch(raw_key)
    if match is None:
        return None
    return match.group("prefix"), match.group("secret")


def hash_api_key_secret(secret: str) -> str:
    """Return the canonical SHA-256 hex digest of an API-key secret.

    The corresponding column ``api_keys.hashed_secret`` stores 64
    hexadecimal chars. Salting is intentionally omitted: the secret half
    of the key is itself a high-entropy random string, so an unsalted
    SHA-256 is cryptographically sufficient and lets the verifier hash
    once and compare in constant time without a per-row salt fetch.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


class DbApiKeyVerifier(ApiKeyVerifier):
    """Postgres-backed :class:`ApiKeyVerifier` (Phase 15 T155b).

    The constructor accepts an :class:`AsyncSession` factory (typically
    :func:`echoroo.core.database.AsyncSessionLocal`) — each verification
    opens its own short-lived session so the verifier never pins a
    connection between requests.
    """

    def __init__(
        self,
        session_factory: Any,
        *,
        last_used_debounce: timedelta = LAST_USED_DEBOUNCE,
    ) -> None:
        self._session_factory = session_factory
        self._last_used_debounce = last_used_debounce

    async def verify(self, raw_key: str) -> ApiKeyRecord | None:
        """Resolve a raw Bearer credential to an :class:`ApiKeyRecord`.

        Returns ``None`` (i.e. caller emits 401) when:

        * The wire format is malformed.
        * No row matches the supplied ``prefix``.
        * The constant-time hash compare fails.
        * The row is revoked (``revoked_at IS NOT NULL``) or expired
          (``expires_at <= now()``).
        """
        parsed = parse_api_key(raw_key)
        if parsed is None:
            return None
        stored_prefix, raw_secret = parsed

        async with self._session_factory() as session:
            row = await self._load_by_prefix(session, stored_prefix)
            if row is None:
                return None

            now = datetime.now(UTC)

            # Constant-time secret compare. Mismatch is treated identically
            # to an unknown prefix (no telemetry leak).
            expected_hash = hash_api_key_secret(raw_secret)
            if not hmac.compare_digest(
                expected_hash.encode("ascii"),
                (row.hashed_secret or "").encode("ascii"),
            ):
                return None

            # Lifecycle checks.
            if row.revoked_at is not None:
                return None
            if row.expires_at is None:
                # Defensive: column is NOT NULL at the DB layer, but a
                # rogue migration could violate the invariant. Treat
                # missing expiry as invalid rather than infinite.
                return None
            expires_at = (
                row.expires_at
                if row.expires_at.tzinfo is not None
                else row.expires_at.replace(tzinfo=UTC)
            )
            if expires_at <= now:
                return None

            # Phase 17 A-4 — lazy safety net for the age-based scope
            # policy (FR-083). The daily sweep in
            # :mod:`echoroo.workers.api_key_age_check` is the eager
            # path; this re-evaluation guarantees correctness on the
            # very next request even if the beat task lags by a tick.
            #
            # ``effective_permissions_for_age`` returns ``None`` when
            # the key is older than ``API_KEY_REVOKE_DAYS`` (default
            # 270) — the verifier propagates the ``None`` so the
            # middleware emits the same 401 it would for an unknown
            # prefix (no telemetry leak between "revoked" and "expired
            # by age").
            #
            # Round 2 Fix R1-I1: The age-based revoke check MUST run
            # BEFORE ``_maybe_bump_last_used`` so a 270-day-old key is
            # treated as "did not authenticate" — its ``last_used_at``
            # MUST NOT be advanced. Bumping the timestamp for a key the
            # verifier ultimately rejects creates forensic drift with
            # the "270-day keys do not authenticate" model in FR-083.
            granted: list[str] = list(row.granted_permissions or [])
            settings = get_settings()
            effective = effective_permissions_for_age(
                granted=tuple(granted),
                created_at=row.created_at,
                revoked_at=None,  # already short-circuited above
                now=now,
                degrade_days=settings.API_KEY_SCOPE_DEGRADE_DAYS,
                revoke_days=settings.API_KEY_REVOKE_DAYS,
            )
            if effective is None:
                return None
            granted = list(effective)

            # Best-effort debounced last_used_at update. Failure here
            # MUST NOT block the verification — forensic loss of one
            # timestamp is preferable to refusing a valid key.
            try:
                await self._maybe_bump_last_used(session, row, now=now)
                await session.commit()
            except Exception:  # noqa: BLE001 — soft alert
                await session.rollback()
                logger.warning(
                    "DbApiKeyVerifier: failed to bump last_used_at for "
                    "api_key_id=%s (verification still succeeded)",
                    row.id,
                    exc_info=True,
                )
            # Phase 17 A-3: thread ``allowed_ip_cidrs`` through so the
            # outer IP enforcement middleware can compare the caller
            # IP against the persisted CIDR list without re-loading
            # the row. ``None`` is preserved verbatim — the helper
            # treats both ``None`` and ``[]`` as "no restriction".
            raw_cidrs = getattr(row, "allowed_ip_cidrs", None)
            cidrs_tuple: tuple[str, ...] | None = (
                tuple(raw_cidrs) if raw_cidrs is not None else None
            )
            return ApiKeyRecord(
                api_key_id=row.id,
                user_id=row.user_id,
                granted_permissions=tuple(granted),
                # Phase 15 R3 NO-GO new-Major: thread the optional
                # per-key project binding through so the gate can
                # enforce ``api_key_project_scope_mismatch`` on
                # cross-project calls.
                project_id=row.project_id,
                allowed_ip_cidrs=cidrs_tuple,
            )

    # -- internals --------------------------------------------------------

    async def _load_by_prefix(
        self, session: AsyncSession, stored_prefix: str
    ) -> ApiKey | None:
        """SELECT api_keys WHERE prefix = :p — UNIQUE, O(1)."""
        stmt = sa.select(ApiKey).where(ApiKey.prefix == stored_prefix)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _maybe_bump_last_used(
        self,
        session: AsyncSession,
        row: ApiKey,
        *,
        now: datetime,
    ) -> None:
        """1-minute debounced UPDATE on ``last_used_at``."""
        last = row.last_used_at
        if last is not None:
            last_aware = last if last.tzinfo is not None else last.replace(tzinfo=UTC)
            if (now - last_aware) < self._last_used_debounce:
                return
        # Targeted UPDATE so we do not race a concurrent refresh.
        await session.execute(
            sa.update(ApiKey)
            .where(ApiKey.id == row.id)
            .values(last_used_at=now)
        )


__all__ = [
    "DbApiKeyVerifier",
    "KEY_NAMESPACE",
    "LAST_USED_DEBOUNCE",
    "PREFIX_RANDOM_LEN",
    "STORED_PREFIX_LEN",
    "hash_api_key_secret",
    "parse_api_key",
]
