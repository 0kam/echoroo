"""API key age-based lifecycle policy (FR-083, Phase 17 backlog A-4).

Background
----------
FR-083 mandates a "推奨 rotation 90 日、UI warning バナー、上限 2 年" policy
for programmatic API keys. The 2-year hard expiry is enforced by the DB
``ck_api_keys_expires_at_window`` CHECK constraint, but the soft middle
of the rotation curve — ``180 day scope degrade`` and ``270 day grace
revoke`` — has historically lived only in the spec.

Phase 17 A-4 wires the policy into two coordinated paths:

1. **Eager beat task** (``echoroo.workers.api_key_age_check``) runs daily
   at 01:15 UTC. It:
   * Strips write scopes from rows with ``created_at <= now - 180d`` and
     a non-empty write subset of ``granted_permissions``.
   * Marks rows with ``created_at <= now - 270d`` as revoked with
     ``revoked_at = NOW()`` + ``revoked_reason`` + ``granted_permissions
     = []`` (Codex-recommended audit-friendly representation).

2. **Lazy verifier safety net** (``DbApiKeyVerifier.verify``) re-applies
   :func:`effective_permissions_for_age` on every request so a 180-day
   key cannot mutate even if the beat task lags behind by a tick.

Truth model
-----------
The DB row is the canonical state. The verifier-side safety net only
**narrows** the granted set — it never expands it. A row that the beat
task has already revoked stays revoked even if a clock skew temporarily
makes ``effective_permissions_for_age`` return a non-empty tuple.

Write-scope catalogue
---------------------
:data:`API_KEY_WRITE_PERMISSIONS` is a deliberately explicit allowlist
of every scope string that mutates state. Two families coexist in the
codebase today:

* The ``Permission`` enum in :mod:`echoroo.core.permissions` (canonical,
  snake_case identifiers like ``upload`` or ``manage_dataset``).
* Legacy fixture / contract test strings shaped ``<resource>:<verb>``
  (``recordings:write``, ``detections:write``).

Both are listed verbatim so the policy works in production *and* in the
xfail tests inherited from the Phase 15 TDD-red drop.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Final

from echoroo.core.permissions import Permission

#: spec/011 §NFR-011-005 / T020 — canonical platform-scope audit-action
#: strings for the two API-key lifecycle events. ``scope_degrade`` is
#: emitted when a key crosses the 180-day mark and its write scopes are
#: stripped; ``revoke`` is emitted when a key crosses the 270-day mark
#: (or is revoked out-of-band). Declaring the constants here (the
#: service that owns the age-curve policy) is the foundational T020
#: step; the email->audit emit that consumes them (replacing the legacy
#: ``send_api_key_scope_degrade_email`` / ``send_api_key_revoke_email``)
#: lands with the US7 ``services/email.py`` rewrite (T613 / T614). The
#: detail carries the opaque ``api_key`` id only — no secret material
#: (NFR-011-005 / A-13). ``platform.api_key.revoke`` is banner-eligible
#: (see :data:`echoroo.services.user_banner.BANNER_ELIGIBLE_ACTIONS`).
AUDIT_ACTION_PLATFORM_API_KEY_SCOPE_DEGRADE: Final[str] = (
    "platform.api_key.scope_degrade"
)
AUDIT_ACTION_PLATFORM_API_KEY_REVOKE: Final[str] = "platform.api_key.revoke"

#: Canonical write-scope catalogue. Membership in this set means the
#: caller can mutate state — beat / verifier filter these strings out
#: once a key crosses the 180-day mark.
#:
#: NOTE: keep this set conservative. Adding a new scope here causes the
#: verifier to silently drop it from 180-day-old keys; that is the
#: correct behaviour for genuinely write-shaped scopes but would be a
#: regression for read scopes that merely happen to share a substring.
API_KEY_WRITE_PERMISSIONS: Final[frozenset[str]] = frozenset(
    {
        # -- Canonical Permission enum (snake_case, FR-009) --
        Permission.VOTE.value,
        Permission.COMMENT.value,
        Permission.CREATE_TAG.value,
        Permission.ANNOTATE.value,
        Permission.UPLOAD.value,
        Permission.MANAGE_SITE.value,
        Permission.MANAGE_DATASET.value,
        Permission.MANAGE_DATASET_ADMIN.value,
        Permission.RUN_INFERENCE.value,
        Permission.TRAIN_MODEL.value,
        Permission.MANAGE_MEMBERS.value,
        Permission.MANAGE_TRUSTED.value,
        Permission.EDIT_PROJECT.value,
        Permission.MANAGE_LICENSE.value,
        Permission.DELETE_PROJECT.value,
        Permission.TRANSFER_OWNERSHIP.value,
        Permission.OVERRIDE_TAXON_SENSITIVITY.value,
        Permission.MANAGE_API_KEY.value,
        Permission.MANAGE_2FA.value,
        # -- Legacy ``<resource>:<verb>`` fixture strings --
        # The Phase 15 xfail tests and a handful of older contract
        # fixtures still use this shape. Listing them explicitly avoids
        # a brittle ``endswith(":write")`` heuristic that could catch
        # genuine read scopes named like ``audit:writeable_filter``.
        "recordings:write",
        "detections:write",
        "datasets:write",
        "projects:write",
        "models:write",
        "tags:write",
        "votes:write",
        "annotations:write",
        "uploads:write",
    }
)


def is_write_scope(permission: str) -> bool:
    """Return ``True`` when ``permission`` grants mutate access.

    The check is membership-based against
    :data:`API_KEY_WRITE_PERMISSIONS`. Unknown / future scope strings
    default to read-only (``False``) — the safer side of the cliff for
    a degrade-only policy that only ever *removes* permissions.
    """
    return permission in API_KEY_WRITE_PERMISSIONS


def filter_to_read_only(permissions: Iterable[str]) -> tuple[str, ...]:
    """Return ``permissions`` with every write-scope entry stripped.

    The output preserves input order (callers occasionally rely on the
    leading entry being the most-used scope for UI presentation) and
    deduplicates only via set-membership in :func:`is_write_scope`.
    """
    return tuple(p for p in permissions if not is_write_scope(p))


def effective_permissions_for_age(
    *,
    granted: tuple[str, ...],
    created_at: datetime,
    revoked_at: datetime | None,
    now: datetime | None = None,
    degrade_days: int = 180,
    revoke_days: int = 270,
) -> tuple[str, ...] | None:
    """Compute the runtime-effective permission set for an API key.

    Args:
        granted: The persisted ``api_keys.granted_permissions`` tuple.
        created_at: ``api_keys.created_at`` (UTC-aware preferred).
        revoked_at: ``api_keys.revoked_at`` — non-NULL means the row is
            already revoked and the verifier MUST emit ``None``.
        now: Override for the current time. Defaults to
            :func:`datetime.now(UTC)`. Tests pin this to make the age
            arithmetic deterministic.
        degrade_days: Threshold (default 180) past which write scopes
            are stripped.
        revoke_days: Threshold (default 270) past which the key is
            treated as revoked regardless of the persisted
            ``revoked_at`` column.

    Returns:
        * ``None`` when the row is revoked OR older than
          ``revoke_days``.
        * The read-only filtered tuple when the row is in the
          ``degrade_days <= age < revoke_days`` window.
        * The ``granted`` tuple verbatim for fresh keys.

    The function is deliberately pure / side-effect free so the verifier
    safety net and the beat sweep share one source of truth for the
    policy curve.
    """
    current = now if now is not None else datetime.now(UTC)
    if revoked_at is not None:
        return None
    # Defensive: tolerate naive ``created_at`` even though the DB column
    # is TIMESTAMPTZ. SQLAlchemy occasionally hands back naive values
    # from raw ``text()`` ``RETURNING`` rows on some PG / driver combos.
    created_aware = (
        created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    )
    age = current - created_aware
    if age >= timedelta(days=revoke_days):
        return None
    if age >= timedelta(days=degrade_days):
        return filter_to_read_only(granted)
    return granted


__all__ = [
    "API_KEY_WRITE_PERMISSIONS",
    "AUDIT_ACTION_PLATFORM_API_KEY_REVOKE",
    "AUDIT_ACTION_PLATFORM_API_KEY_SCOPE_DEGRADE",
    "effective_permissions_for_age",
    "filter_to_read_only",
    "is_write_scope",
]
