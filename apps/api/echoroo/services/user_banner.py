"""User banner + activity service — spec/011 zero-email deployment (T060).

This service implements the read side of the in-app banner subsystem
introduced by spec/011 (FR-011-301..310). Banner content is sourced
from the existing audit tables (``project_audit_log`` and
``platform_audit_log``); the table ``user_banner_dismissals`` records
per-user dismissals so a banner stops surfacing once the user has
acknowledged it (FR-011-302).

Three read paths plus a write path:

* :func:`list_banners` — undismissed audit rows targeting the user,
  age-capped at 30 days (FR-011-302).
* :func:`list_activity` — full reverse-chronological audit history
  targeting the user; dismissal does NOT filter this list and the
  30-day age cap does NOT apply (FR-011-307).
* :func:`dismiss` — record a dismissal. MUST validate at write time
  that the targeted audit row's ``actor_user_id_hash`` matches the
  authenticated user's hashed id OR the row's ``detail.target_user_id``
  matches the authenticated user's id (FR-011-302 / data-model.md M-2
  anti-impersonation invariant). Mismatch returns the same 404 shape
  as "row not found" for anti-enumeration parity.
* :func:`enqueue_event` — no-op shim retained so callers can make the
  banner surface explicit. The audit row itself is what surfaces; this
  helper exists purely as a hook so the Phase 9 US7 rewrite (when the
  email helpers in ``services/email.py`` become true banner
  enqueuers) has a single entry point to plug into.

No HTTP endpoint is exposed by this PR — endpoints land in Phase 9
US7 (``tasks.md`` T600-T602). This module is the **service-level
contract** the endpoints will build on.

Targeting model
---------------

A user "targets" an audit row when either:

1. The user authored the action — ``actor_user_id_hash`` (or the
   rotation sibling ``actor_user_id_hash_v2``) equals ``HMAC(user.id)``.
2. The audit row's ``detail.target_user_id`` (raw UUID JSON string)
   equals ``user.id``. This is the path used by superuser-initiated
   actions (admin password reset, admin 2FA disable, etc.) where the
   actor is the superuser but the audience for the banner is the
   targeted user (FR-011-303..306, FR-011-401..402).

The audit tables only persist the HASHED actor id (``actor_user_id_hash``
column — see ``alembic/versions/0001_baseline_permissions_redesign.py``
line 1152), so the actor-match path computes ``compute_pii_hash(user.id)``
at query time and matches against the v1 column ``OR`` the v2 column
(mirrors ``api/web_v1/audit.py`` line 208 ``actor_user_id_hash = :h OR
actor_user_id_hash_v2 = :h``). The target-match path matches against
``detail->>'target_user_id'`` because the raw UUID is the conventional
sanitised-payload representation in the existing audit detail JSONB
(see ``core/audit.py`` AuditLogSanitizer documentation).
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.kms import compute_pii_hash

logger = logging.getLogger(__name__)

# Allowlist of audit table names that may appear in
# ``user_banner_dismissals.audit_table``. Mirrors the SQL
# ``CHECK`` constraint declared by migration ``0021`` and the
# ``BannerItem.audit_table`` enum in
# ``contracts/me-banners-activity.yaml``. Centralised here so callers
# (and ``dismiss``) can reject unknown values with a single source of
# truth before issuing SQL.
ALLOWED_AUDIT_TABLES: Final[frozenset[str]] = frozenset(
    {"project_audit_log", "platform_audit_log"}
)

# Default age cap for the banner-list response (FR-011-302). Rows
# older than this fall out of the banner stack; they remain reachable
# via the activity view (FR-011-307).
DEFAULT_BANNER_MAX_AGE_DAYS: Final[int] = 30

# Default page size for the activity view (matches the OpenAPI default
# in ``contracts/me-banners-activity.yaml`` query parameter ``limit``).
DEFAULT_ACTIVITY_LIMIT: Final[int] = 50

# Hard upper bound for the activity view page size (defends against
# pathological clients asking for million-row pages). Matches the
# ``maximum`` in the contract YAML.
MAX_ACTIVITY_LIMIT: Final[int] = 100

# Soft upper bound for the banner list. The contract is silent on a
# page size for ``/me/banners`` because banners are expected to be a
# small set (single-digit typical); the cap is defence-in-depth.
MAX_BANNER_LIMIT: Final[int] = 200

# Audit-action allowlist for the banner surface (FR-011-008,
# FR-011-302). Without this filter every audit row targeting the
# user surfaces as a banner — including high-volume project
# bookkeeping actions like ``project.create`` that the spec
# deliberately keeps out of the in-app banner stack (they remain
# visible through ``list_activity`` per FR-011-307).
#
# The set mirrors the 11 audit actions ``spec/011`` calls out as
# in-app banner targets. They will be declared as service-private
# string constants by tasks ``T020`` (e.g.
# ``services/two_factor_reset_service.AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER``)
# in later steps; until those land we keep a single module-local
# frozenset so this filter is the one source of truth at Step 2.
# Once the constants land, swap each literal for the imported name
# (same string value — the equality check is by value, not by
# identity, so cutover is a mechanical rename).
BANNER_ELIGIBLE_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "auth.login.new_device",                              # FR-011-008 login notification
        "platform.user.email_changed",                        # FR-011-008 email change
        "platform.user.two_factor_reset_by_superuser",        # FR-011-008 admin 2FA reset
        "platform.api_key.revoke",                            # FR-011-008 api key revoke
        "platform.user.password_reset_by_superuser",          # FR-011-008 admin-reset
        "platform.user.password_reset_self",                  # FR-011-008 self-reset
        "project.member.invite_accepted_signup",              # FR-011-008 invitation accept (signup)
        "project.member.invite_accepted",                     # FR-011-008 invitation accept (existing)
        "project.trusted_user.invite_accepted",               # FR-011-008 trusted-user accept
        "project.ownership.bootstrap_transfer",               # FR-011-008 ownership transfer
        "auth.trusted_device.revoke_all",                     # FR-011-008 trusted-device revoke-all
    }
)


class BannerNotFoundError(Exception):
    """Raised by :func:`dismiss` when the target audit row is not
    visible to the authenticated user.

    "Not visible" collapses three real conditions (FR-011-302):

    * The row does not exist (random / brute-forced UUID).
    * The row exists but neither actor-match nor target-match holds
      for this user.
    * The ``audit_table`` value is outside the allowlist.

    The endpoint layer (Phase 9 US7) translates this exception into a
    404 response with constant timing so the three conditions are
    externally indistinguishable (anti-enumeration).
    """


@dataclass(frozen=True)
class BannerItem:
    """A single undismissed banner targeting the authenticated user.

    Shape mirrors the OpenAPI ``BannerItem`` schema in
    ``contracts/me-banners-activity.yaml``. The endpoint layer (Phase
    9 US7) is responsible for redacting / formatting ``detail`` into
    the contract ``summary`` field before serialisation.
    """

    audit_table: str
    audit_log_id: UUID
    action: str
    actor_user_id_hash: str
    occurred_at: datetime
    detail: dict[str, Any]
    project_id: UUID | None = None


@dataclass(frozen=True)
class ActivityItem:
    """A single audit-history row visible to the authenticated user.

    Activity is a strict superset of banner-eligible rows (the OpenAPI
    contract is explicit about this), so the activity endpoint
    surfaces every row a banner query would, plus rows that fall
    outside the banner-eligible action set or beyond the 30-day cap.
    """

    audit_table: str
    audit_log_id: UUID
    action: str
    actor_user_id_hash: str
    occurred_at: datetime
    detail: dict[str, Any]
    project_id: UUID | None = None


@dataclass(frozen=True)
class ActivityPage:
    """A single page of :class:`ActivityItem` rows plus an opaque cursor."""

    items: list[ActivityItem]
    next_cursor: str | None


# ---------------------------------------------------------------------------
# Cursor opaque encoding (activity pagination)
# ---------------------------------------------------------------------------
#
# The activity view uses keyset pagination over the natural row
# ordering ``(occurred_at DESC, audit_table, audit_log_id)``. The
# opaque cursor encodes the last row of the previous page so the next
# query can resume strictly after it. Encoding is base64-of-JSON for
# (a) URL-safety and (b) trivial human debuggability in dev. The
# format is deliberately not signed — a malformed cursor degrades to
# "start from the top" rather than crashing, which is the right
# behaviour for an opaque pagination token.


def _encode_cursor(*, occurred_at: datetime, audit_table: str, audit_log_id: UUID) -> str:
    """Encode a position into an opaque URL-safe cursor string."""
    payload = {
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "audit_table": audit_table,
        "audit_log_id": str(audit_log_id),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: str) -> dict[str, Any] | None:
    """Decode an opaque cursor; return ``None`` on any failure.

    A malformed cursor is treated as absent (start from the top)
    rather than an error because the cursor is opaque from the
    caller's perspective and any drift in encoding shouldn't surface
    as a 4xx.
    """
    try:
        padding = b"=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + padding)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        required = {"occurred_at", "audit_table", "audit_log_id"}
        if not required.issubset(payload.keys()):
            return None
        # Validate types eagerly so the SQL bind step does not raise.
        datetime.fromisoformat(str(payload["occurred_at"]))
        UUID(str(payload["audit_log_id"]))
        if payload["audit_table"] not in ALLOWED_AUDIT_TABLES:
            return None
        return payload
    except Exception:  # pragma: no cover — defensive
        return None


# ---------------------------------------------------------------------------
# Targeting predicate (SQL fragment shared by read + dismiss paths)
# ---------------------------------------------------------------------------
#
# The targeting predicate is shared verbatim across the three query
# paths so the actor-match-OR-target-match invariant cannot drift
# between read and write. The fragment binds two parameters:
#
# * ``:actor_hash`` — ``compute_pii_hash(str(user_id))`` for the
#   authenticated user (matches both the v1 and v2 columns to honour
#   the rotation pattern established by Phase 17 A-2 — see
#   ``api/web_v1/audit.py`` line 208).
# * ``:target_user_id`` — ``str(user_id)`` matched against the JSONB
#   path ``detail->>'target_user_id'``.

def _targeting_predicate(alias: str) -> str:
    """Build the actor-OR-target match SQL predicate for table ``alias``.

    The fragment is consumed verbatim by the three query paths so the
    invariant cannot drift between read and write. It binds two
    parameters (``:actor_hash`` and ``:target_user_id``) — see
    :func:`_targeting_bind_params`.
    """
    return (
        f"({alias}.actor_user_id_hash = :actor_hash "
        f"OR {alias}.actor_user_id_hash_v2 = :actor_hash "
        f"OR {alias}.detail->>'target_user_id' = :target_user_id)"
    )


def _targeting_bind_params(user_id: UUID) -> dict[str, str]:
    """Compute the bind params used by the targeting predicate.

    The hash is computed once per call rather than once per row;
    ``compute_pii_hash`` is a KMS-backed HMAC and we never want to
    call it inside a SQL loop.
    """
    user_id_str = str(user_id)
    return {
        "actor_hash": compute_pii_hash(user_id_str),
        "target_user_id": user_id_str,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def list_banners(
    session: AsyncSession,
    *,
    user_id: UUID,
    max_age_days: int = DEFAULT_BANNER_MAX_AGE_DAYS,
    limit: int = MAX_BANNER_LIMIT,
) -> list[BannerItem]:
    """Return undismissed audit rows targeting ``user_id`` within the age cap.

    Args:
        session: Active AsyncSession bound to the request transaction.
        user_id: Authenticated user identifier.
        max_age_days: Maximum row age in days (FR-011-302 caps at 30).
        limit: Defence-in-depth cap on returned row count.

    Returns:
        Reverse-chronological list of :class:`BannerItem` whose
        ``action`` is in :data:`BANNER_ELIGIBLE_ACTIONS`. Non-eligible
        rows (e.g. ``project.create``) remain reachable via
        :func:`list_activity` (FR-011-307) but never surface as a
        banner. The eligibility filter is applied inside both arms of
        the UNION so the planner can use the existing
        ``(created_at, action)`` indices on the audit tables.
    """
    if max_age_days <= 0:
        return []
    if limit <= 0:
        return []
    effective_limit = min(limit, MAX_BANNER_LIMIT)
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    bind = _targeting_bind_params(user_id)

    # UNION ALL across both audit tables, LEFT JOIN against
    # user_banner_dismissals, keep only NULL-matched dismissal rows.
    # The PK on user_banner_dismissals serves the (user_id,
    # audit_table, audit_log_id) lookup directly so the LEFT JOIN is
    # an index-only scan.
    #
    # ``action = ANY(:banner_actions)`` (rather than ``IN (...)``) is
    # the parameterised form psycopg / asyncpg accept for a frozenset
    # bind — it avoids in-clause string interpolation and keeps the
    # eligibility list a single bind variable for query-plan caching.
    sql = sa.text(
        f"""
        SELECT combined.audit_table AS audit_table,
               combined.audit_log_id AS audit_log_id,
               combined.action AS action,
               combined.actor_user_id_hash AS actor_user_id_hash,
               combined.occurred_at AS occurred_at,
               combined.detail AS detail,
               combined.project_id AS project_id
        FROM (
            SELECT 'project_audit_log' AS audit_table,
                   p.id AS audit_log_id,
                   p.action AS action,
                   p.actor_user_id_hash AS actor_user_id_hash,
                   p.created_at AS occurred_at,
                   p.detail AS detail,
                   p.project_id AS project_id
            FROM project_audit_log p
            WHERE p.created_at >= :cutoff
              AND p.action = ANY(:banner_actions)
              AND {_targeting_predicate('p')}
            UNION ALL
            SELECT 'platform_audit_log' AS audit_table,
                   pl.id AS audit_log_id,
                   pl.action AS action,
                   pl.actor_user_id_hash AS actor_user_id_hash,
                   pl.created_at AS occurred_at,
                   pl.detail AS detail,
                   NULL::uuid AS project_id
            FROM platform_audit_log pl
            WHERE pl.created_at >= :cutoff
              AND pl.action = ANY(:banner_actions)
              AND {_targeting_predicate('pl')}
        ) AS combined
        LEFT JOIN user_banner_dismissals d
          ON d.user_id = :user_id
         AND d.audit_table = combined.audit_table
         AND d.audit_log_id = combined.audit_log_id
        WHERE d.user_id IS NULL
        ORDER BY combined.occurred_at DESC,
                 combined.audit_table ASC,
                 combined.audit_log_id ASC
        LIMIT :limit
        """
    )
    params: dict[str, Any] = {
        "cutoff": cutoff,
        "user_id": str(user_id),
        "limit": effective_limit,
        # ``= ANY(array)`` accepts a Python list as the bind; cast the
        # frozenset to a sorted list so the SQL plan cache key is
        # deterministic across calls.
        "banner_actions": sorted(BANNER_ELIGIBLE_ACTIONS),
        **bind,
    }
    result = await session.execute(sql, params)
    rows = result.mappings().all()
    return [
        BannerItem(
            audit_table=str(row["audit_table"]),
            audit_log_id=UUID(str(row["audit_log_id"])),
            action=str(row["action"]),
            actor_user_id_hash=str(row["actor_user_id_hash"]),
            occurred_at=row["occurred_at"],
            detail=dict(row["detail"]) if row["detail"] is not None else {},
            project_id=UUID(str(row["project_id"])) if row["project_id"] is not None else None,
        )
        for row in rows
    ]


async def list_activity(
    session: AsyncSession,
    *,
    user_id: UUID,
    cursor: str | None = None,
    limit: int = DEFAULT_ACTIVITY_LIMIT,
) -> ActivityPage:
    """Return the user's full audit history (reverse chronological).

    No dismissal filter is applied — dismissal only suppresses banner
    surface, not the permanent record (FR-011-307). No 30-day age cap
    is applied either.

    Args:
        session: Active AsyncSession.
        user_id: Authenticated user identifier.
        cursor: Opaque cursor from a previous page's ``next_cursor``;
            ``None`` returns the first page. Malformed cursors are
            treated as ``None``.
        limit: Page size; clamped to ``MAX_ACTIVITY_LIMIT``.

    Returns:
        ActivityPage with ``items`` and an opaque ``next_cursor`` (or
        ``None`` when no more pages remain).
    """
    if limit <= 0:
        return ActivityPage(items=[], next_cursor=None)
    effective_limit = min(limit, MAX_ACTIVITY_LIMIT)
    bind = _targeting_bind_params(user_id)

    decoded = _decode_cursor(cursor) if cursor else None
    cursor_clause = ""
    if decoded is not None:
        # Keyset pagination over the mixed-direction ordering
        # ``(occurred_at DESC, audit_table ASC, audit_log_id ASC)``.
        # A tuple ``<`` comparison assumes **all** columns share the
        # same direction; here they do not, so rows that share
        # ``occurred_at`` with the cursor row land on the wrong side
        # of the boundary and a page leak / duplicate emerges. The
        # cursor row is the **tail** of the previous page, so a row
        # comes "after" the cursor when (per ORDER BY direction
        # column-by-column):
        #
        #   * strictly **older** time (occurred_at DESC, so "after"
        #     means strictly less), OR
        #   * same time and lexicographically **greater**
        #     audit_table (audit_table ASC, so "after" means
        #     strictly greater), OR
        #   * same time, same table, and **greater** audit_log_id
        #     (audit_log_id ASC, so "after" means strictly greater).
        cursor_clause = (
            "AND ("
            "combined.occurred_at < :cur_occurred_at "
            "OR (combined.occurred_at = :cur_occurred_at "
            "    AND combined.audit_table > :cur_audit_table) "
            "OR (combined.occurred_at = :cur_occurred_at "
            "    AND combined.audit_table = :cur_audit_table "
            "    AND combined.audit_log_id > :cur_audit_log_id)"
            ")"
        )

    sql = sa.text(
        f"""
        SELECT combined.audit_table AS audit_table,
               combined.audit_log_id AS audit_log_id,
               combined.action AS action,
               combined.actor_user_id_hash AS actor_user_id_hash,
               combined.occurred_at AS occurred_at,
               combined.detail AS detail,
               combined.project_id AS project_id
        FROM (
            SELECT 'project_audit_log' AS audit_table,
                   p.id AS audit_log_id,
                   p.action AS action,
                   p.actor_user_id_hash AS actor_user_id_hash,
                   p.created_at AS occurred_at,
                   p.detail AS detail,
                   p.project_id AS project_id
            FROM project_audit_log p
            WHERE {_targeting_predicate('p')}
            UNION ALL
            SELECT 'platform_audit_log' AS audit_table,
                   pl.id AS audit_log_id,
                   pl.action AS action,
                   pl.actor_user_id_hash AS actor_user_id_hash,
                   pl.created_at AS occurred_at,
                   pl.detail AS detail,
                   NULL::uuid AS project_id
            FROM platform_audit_log pl
            WHERE {_targeting_predicate('pl')}
        ) AS combined
        WHERE 1=1
          {cursor_clause}
        ORDER BY combined.occurred_at DESC,
                 combined.audit_table ASC,
                 combined.audit_log_id ASC
        LIMIT :limit
        """
    )
    params: dict[str, Any] = {
        "limit": effective_limit + 1,  # +1 to detect "more pages exist"
        **bind,
    }
    if decoded is not None:
        params["cur_occurred_at"] = datetime.fromisoformat(str(decoded["occurred_at"]))
        params["cur_audit_table"] = str(decoded["audit_table"])
        params["cur_audit_log_id"] = str(decoded["audit_log_id"])

    result = await session.execute(sql, params)
    rows = result.mappings().all()

    items = [
        ActivityItem(
            audit_table=str(row["audit_table"]),
            audit_log_id=UUID(str(row["audit_log_id"])),
            action=str(row["action"]),
            actor_user_id_hash=str(row["actor_user_id_hash"]),
            occurred_at=row["occurred_at"],
            detail=dict(row["detail"]) if row["detail"] is not None else {},
            project_id=UUID(str(row["project_id"])) if row["project_id"] is not None else None,
        )
        for row in rows[:effective_limit]
    ]
    next_cursor: str | None = None
    if len(rows) > effective_limit and items:
        tail = items[-1]
        next_cursor = _encode_cursor(
            occurred_at=tail.occurred_at,
            audit_table=tail.audit_table,
            audit_log_id=tail.audit_log_id,
        )
    return ActivityPage(items=items, next_cursor=next_cursor)


async def dismiss(
    session: AsyncSession,
    *,
    user_id: UUID,
    audit_table: str,
    audit_log_id: UUID,
) -> None:
    """Record a dismissal for ``(audit_table, audit_log_id)``.

    Validates at write time (data-model.md M-2 invariant):

    1. ``audit_table`` is in :data:`ALLOWED_AUDIT_TABLES`.
    2. A row with id ``audit_log_id`` exists in that table.
    3. The row's ``actor_user_id_hash`` (or v2 sibling) matches
       ``HMAC(user_id)`` OR the row's ``detail->>'target_user_id'``
       equals ``str(user_id)``.

    On any of (1)/(2)/(3) failing, raises :class:`BannerNotFoundError`
    — the endpoint layer collapses all three into a 404 (FR-011-302
    anti-enumeration). The 404 path is constant-timing relative to
    the success path because we always issue the same one SELECT
    regardless of which failure mode we hit (the SELECT returns no
    rows for any of the three mismatches).

    On success, performs ``INSERT ... ON CONFLICT DO NOTHING`` so
    repeated calls are idempotent (FR-011-302 ``Repeated dismiss ...
    returns 204 each time``). The caller (the endpoint handler) is
    responsible for committing the surrounding transaction.

    Args:
        session: Active AsyncSession bound to the request transaction.
        user_id: Authenticated user identifier.
        audit_table: ``'project_audit_log'`` or ``'platform_audit_log'``.
        audit_log_id: UUID of the audit row to dismiss.

    Raises:
        BannerNotFoundError: Row not found, not targeting this user, or
            ``audit_table`` not allowlisted.
    """
    if audit_table not in ALLOWED_AUDIT_TABLES:
        # Treat allowlist mismatch the same as "row not found" — the
        # endpoint layer collapses to 404 either way and the constant
        # timing target is preserved by short-circuiting before any
        # SQL round-trip (the alternative — issuing a guaranteed-empty
        # SELECT — would only hide the divergence, not eliminate it).
        raise BannerNotFoundError(
            f"audit_table {audit_table!r} not in allowlist"
        )

    # Single targeted SELECT — checks existence AND the actor/target
    # match in one round-trip. Constant SQL shape across both tables
    # because we interpolate the table name (it's in the allowlist so
    # no injection risk).
    bind = _targeting_bind_params(user_id)
    select_sql = sa.text(
        f"""
        SELECT 1
        FROM {audit_table}
        WHERE id = :audit_log_id
          AND (actor_user_id_hash = :actor_hash
               OR actor_user_id_hash_v2 = :actor_hash
               OR detail->>'target_user_id' = :target_user_id)
        LIMIT 1
        """
    )
    select_params: dict[str, Any] = {
        "audit_log_id": str(audit_log_id),
        **bind,
    }
    result = await session.execute(select_sql, select_params)
    if result.first() is None:
        raise BannerNotFoundError(
            f"audit row {audit_log_id} not found in {audit_table} or not "
            "targeting authenticated user"
        )

    # Idempotent insert. The composite PK ensures the second-and-later
    # dismissal of the same (user, audit_table, audit_log_id) is a
    # no-op rather than an integrity error.
    insert_sql = sa.text(
        """
        INSERT INTO user_banner_dismissals (user_id, audit_table, audit_log_id)
        VALUES (:user_id, :audit_table, :audit_log_id)
        ON CONFLICT (user_id, audit_table, audit_log_id) DO NOTHING
        """
    )
    await session.execute(
        insert_sql,
        {
            "user_id": str(user_id),
            "audit_table": audit_table,
            "audit_log_id": str(audit_log_id),
        },
    )


async def enqueue_event(
    session: AsyncSession,  # noqa: ARG001 — preserved for Phase 9 US7 signature parity
    *,
    user_id: UUID,
    audit_table: str,
    audit_log_id: UUID,
) -> None:
    """Marker shim for callers that want to make banner surface explicit.

    The audit row written by :class:`AuditLogService` is what actually
    surfaces in :func:`list_banners`; no additional state needs to be
    persisted for the banner to appear. This helper exists so a Phase
    9 US7 rewrite of the (currently stubbed) email helpers in
    :mod:`echoroo.services.email` has a single call to plug into,
    rather than having to thread audit-row metadata back to its
    enqueue site.

    Today this is a structured-log emission only. The signature
    accepts the same ``(session, user_id, audit_table, audit_log_id)``
    tuple the dismiss path uses so a future change that needs to
    persist additional banner metadata (e.g. a denormalised "seen"
    table for read-receipts) can be added here without churning every
    caller.
    """
    if audit_table not in ALLOWED_AUDIT_TABLES:
        # Don't raise — this helper is fire-and-forget and a wrong
        # audit_table is a programmer bug, not a security event.
        # Logging the mismatch is enough to flag it during the Phase 9
        # US7 rewrite.
        logger.warning(
            "user_banner.enqueue_event: unknown audit_table=%r for "
            "user_id=%s audit_log_id=%s",
            audit_table,
            user_id,
            audit_log_id,
        )
        return
    logger.debug(
        "user_banner.enqueue_event: banner surface marker user_id=%s "
        "audit_table=%s audit_log_id=%s",
        user_id,
        audit_table,
        audit_log_id,
    )


__all__ = [
    "ALLOWED_AUDIT_TABLES",
    "BANNER_ELIGIBLE_ACTIONS",
    "DEFAULT_ACTIVITY_LIMIT",
    "DEFAULT_BANNER_MAX_AGE_DAYS",
    "MAX_ACTIVITY_LIMIT",
    "MAX_BANNER_LIMIT",
    "ActivityItem",
    "ActivityPage",
    "BannerItem",
    "BannerNotFoundError",
    "dismiss",
    "enqueue_event",
    "list_activity",
    "list_banners",
]
