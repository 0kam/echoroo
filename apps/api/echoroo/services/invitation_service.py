"""Project invitation service (Phase 10 / T502, FR-047 / FR-048 / FR-051..056).

This module owns issuance and consumption of :class:`ProjectInvitation`
rows for both ``kind='member'`` and ``kind='trusted'`` invitations. Audit
side-effects are deliberately deferred to **after** the main transaction
commits (mirrors :mod:`echoroo.services.license_service` and
:mod:`echoroo.services.restricted_config_service`):

1. ``await create_invitation(...)`` / ``accept_invitation(...)`` /
   ``decline_invitation_by_recipient(...)`` flushes the row mutation and
   returns an outcome dataclass.
2. The endpoint commits its main transaction.
3. The endpoint calls ``trigger_post_commit_side_effects(outcome)`` which
   writes the audit row in a fresh session (FR-093 SERIALIZABLE contract).
   Failures here are WARNING-logged only — the persisted invitation row is
   the security-critical bit; observability is secondary.

Token shape (FR-052, spec/011 NFR-011-010):

* The raw 256-bit token is generated with :func:`secrets.token_bytes`,
  base64url-encoded for the URL.
* The DB row stores the **SHA-256 hex digest** in ``token_hash`` so an
  attacker who reads the table cannot forge a redeem URL.
* The URL token is an HMAC-SHA-256 envelope (spec/011 step 6 widened it
  from 3-part to 4-part to carry a ``kid``)::

      {raw_token_b64u}.{expires_at_unix}.{kid}.{mac_b64u}

  MAC = ``HMAC-SHA-256(secret_for(kid), raw || "." || expires || "." || kid)``.
  Verification is constant-time (:func:`hmac.compare_digest`).
* During the rotation grace window verifiers also accept (a) 4-part
  envelopes whose ``kid`` matches ``INVITATION_TOKEN_KID_OLD`` and (b)
  3-part legacy envelopes signed under the legacy ``HMAC_KEY_OLD`` key
  while ``now < created_at + 7d + GRACE_HOURS``.

Plain-text token confidentiality (FR-011-102..104):

* The signed envelope is carried on :class:`InvitationCreateOutcome` as
  ``signed_token_envelope`` and surfaced to the issuing admin as the
  ``invitation_url`` body field on the issue endpoint (formal supersede
  of spec/006 FR-051 by spec/011 FR-011-103). The token never persists
  past that single HTTP turn and is never logged.

Email matching (FR-054):

* The receiver's email is matched against the invitation's stored
  ``email_hash`` using NFKC + casefold on both sides. Mismatch → 403.
* The check applies to both ``current_user.email`` (primary) and any
  authenticated secondary email present on the principal (a future
  feature; today only the primary is consulted).

Rate limiting (FR-056) is implemented in :func:`check_rate_limits` —
50 issues / hour / actor and 200 issues / hour / project. Implementation
uses Redis ``INCR`` + ``EXPIRE`` so concurrent issues from a single
actor cannot race past the window. **Fail-closed**: if Redis is
unreachable :func:`create_invitation` raises so callers cannot bypass
the cap. Production wiring always injects a live client.

Idempotency (FR-053):

* :func:`accept_invitation` requires a live Redis client (non-Optional)
  and accepts an optional ``idempotency_key``. The resulting outcome is
  pinned to the key in Redis (24 h TTL). A retry with the same key
  returns the cached outcome marker (``is_replay=True``); a retry with
  a *different* token under the same key raises
  :class:`InvitationConflictError` (HTTP 409). Read / write faults
  surface as :class:`InvitationInfraUnavailableError` (HTTP 503,
  fail-closed) so a partial Redis outage cannot bypass the dedupe
  guarantee.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.permissions import (
    TRUSTED_ALLOWED_PERMISSIONS,
    Permission,
)
from echoroo.core.settings import get_settings
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
    ProjectTrustedStatus,
)
from echoroo.models.project import ProjectInvitation, ProjectMember
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.services.audit_service import AuditLogService

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Raw token length in bytes (256 bits, FR-051).
TOKEN_BYTES: int = 32

#: Default token TTL (FR-052: 7 days). The function signature exposes this
#: as the *only* knob a caller can use; values exceeding the cap raise
#: :class:`InvitationValidationError` (FR-052 hard cap).
INVITATION_TTL_SECONDS: int = 7 * 24 * 3600

#: FR-052 hard cap: the issued token MUST NOT live past 7 days.
INVITATION_MAX_TTL_SECONDS: int = INVITATION_TTL_SECONDS

#: Default Trusted overlay duration (FR-043: 90 days).
TRUSTED_DEFAULT_DURATION_SECONDS: int = 90 * 24 * 3600

#: Hard cap on Trusted overlay duration (FR-043: 1 year).
TRUSTED_MAX_DURATION_SECONDS: int = 365 * 24 * 3600

#: FR-056: invitation rate limits.
RATE_LIMIT_ACTOR_PER_HOUR: int = 50
RATE_LIMIT_PROJECT_PER_HOUR: int = 200
_RATE_LIMIT_WINDOW_SECONDS: int = 3600

#: FR-053 idempotency: cached accept outcomes live for 24 h. Same key,
#: same token -> 200 dedupe; same key, different token -> 409 conflict.
_IDEMPOTENCY_TTL_SECONDS: int = 24 * 3600
_IDEMPOTENCY_KEY_PREFIX: str = "idem:invite:accept:"

# spec/011 FR-011-106 / T208 — audit-action constants for the three accept
# branches. The constants are deliberately service-private (per HANDOFF
# line 79) so renames stay local to this module; the verb.noun.verb
# 3-segment pattern matches the rest of the existing audit catalogue.
AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP: Final[str] = (
    "project.member.invite_accepted_signup"
)
AUDIT_ACTION_MEMBER_INVITE_ACCEPTED: Final[str] = (
    "project.member.invite_accepted"
)
AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED: Final[str] = (
    "project.trusted_user.invite_accepted"
)


# ---------------------------------------------------------------------------
# Public errors (engine-level; the endpoint maps to HTTP)
# ---------------------------------------------------------------------------


class InvitationError(Exception):
    """Base class for invitation-service domain errors."""


class InvitationValidationError(InvitationError):
    """Pre-DB validation failure (HTTP 422)."""


class InvitationRateLimitError(InvitationError):
    """FR-056: Owner/Admin or project hit the issue rate cap (HTTP 429)."""


class InvitationConflictError(InvitationError):
    """An equivalent pending invitation already exists (HTTP 409)."""


class InvitationTokenInvalidError(InvitationError):
    """FR-052: HMAC signature missing/expired/tampered (HTTP 410)."""


class InvitationStateError(InvitationError):
    """FR-053: invitation already accepted/declined/revoked/expired (HTTP 410)."""


class InvitationEmailMismatchError(InvitationError):
    """FR-054: invitation email != caller email (HTTP 403, public-shape 404).

    The endpoint MAY render this as 404 to honour FR-055 enumeration
    guarantees; the service raises a distinct class so the audit log can
    record the real reason.
    """


class InvitationInfraUnavailableError(InvitationError):
    """FR-056: the rate-limiter (Redis) is unreachable.

    Mapped to HTTP 503 by the endpoint. We deliberately fail **closed**:
    accepting issuance under a partial Redis outage would let an attacker
    spray invitations past the documented rate cap.
    """


class InvitationAlreadyMemberError(InvitationError):
    """spec/011 FR-011-106 step 3 — caller is already a member of the project.

    Raised by the existing-user accept branch when the authenticated caller
    already holds an active membership row on the target project at the
    same OR higher role than the invitation grants. The endpoint maps this
    to HTTP 409 with a generic ``already a member`` body. The bound-email
    check has already succeeded by the time this error fires, so the
    response intentionally reveals that the caller IS the right recipient —
    it just has nothing new to grant.
    """


# ---------------------------------------------------------------------------
# Outcomes (the values endpoints need for post-commit side effects)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvitationCreateOutcome:
    """Snapshot returned by :func:`create_invitation`.

    Plain-text token surface (spec/011 FR-011-102..104):

    * ``signed_token_envelope`` is the 4-part HMAC envelope returned to
      the issuing admin once on the HTTP response (the ``invitation_url``
      body field). It MUST NOT be logged, telemetered, or persisted past
      that single HTTP turn — the formal supersede of spec/006 FR-051 by
      FR-011-103 makes the issuing admin's response the only exfil path
      for the plain-text token.
    * The endpoint surfaces ``signed_token_envelope`` directly into the
      ``invitation_url`` body field; ``invitation`` carries the safe
      subset of row metadata (id, expires_at, status). The two surfaces
      are kept apart so a refactor cannot accidentally serialise the
      envelope into the row-shaped JSON.

    Other fields:
        invitation: The freshly-flushed (not committed) invitation row.
        actor_user_id: User who issued the invitation (audit plumbing).
        request_id / ip / user_agent: Audit-row plumbing.
        is_new: ``False`` when the row was a duplicate idempotent return.
            Currently always ``True``; reserved for future deduplication
            of duplicate retries.
    """

    invitation: ProjectInvitation
    actor_user_id: UUID
    signed_token_envelope: str
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""
    is_new: bool = True


@dataclass(frozen=True)
class InvitationAcceptOutcome:
    """Snapshot returned by :func:`accept_invitation`.

    The invitation row, the resulting ProjectMember (Member kind) or
    ProjectTrustedUser (Trusted kind), and audit/email plumbing.
    """

    invitation: ProjectInvitation
    member: ProjectMember | None
    trusted_user: ProjectTrustedUser | None
    actor_user_id: UUID
    is_replay: bool = False
    """``True`` when the same Idempotency-Key resolved a previously-accepted
    row — the endpoint should return 200 with the same payload (FR-053)."""

    request_id: str = ""
    ip: str = ""
    user_agent: str = ""


@dataclass(frozen=True)
class InvitationDeclineOutcome:
    """Snapshot returned by :func:`decline_invitation_by_recipient` (T512).

    ``is_replay`` is True for the second-and-onward decline of the same
    pending invitation — the endpoint returns 204 idempotently in either
    case (FR-107).
    """

    invitation: ProjectInvitation
    actor_user_id: UUID
    is_replay: bool = False
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""


@dataclass(frozen=True)
class _IdempotencyRecord:
    """Internal cache shape for FR-053 idempotency-key storage."""

    invitation_id: str
    token_hash: str
    is_replay: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


# ---------------------------------------------------------------------------
# Hashing / token helpers (FR-051, FR-052, FR-055)
# ---------------------------------------------------------------------------


def _b64u_encode(data: bytes) -> str:
    """URL-safe base64 with no padding (RFC 4648 §5)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(value: str) -> bytes:
    """Tolerant URL-safe base64 decoder (re-pads to multiple of 4)."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_token(raw_token_b64u: str) -> str:
    """Return the SHA-256 hex digest of the raw token (DB ``token_hash``)."""
    return hashlib.sha256(raw_token_b64u.encode("ascii")).hexdigest()


def canonicalize_email(email: str) -> str:
    """Return the FR-054 / FR-055 canonical form of ``email``.

    Centralised so the legacy Python-HMAC path
    (:func:`hash_email`) and the KMS-backed path
    (:func:`hash_email_dual`) can never disagree on canonicalisation.

    spec/011 NFR-011-003 / FR-011-106 — the public name was added in
    Step 7 (US2 existing-user accept branch) so the auth resolver and
    the accept handlers can compare the authenticated caller's email
    against the invitation's bound email using exactly the same byte
    sequence that the HMAC / KMS pipelines see. The private alias
    ``_canonical_email`` is retained for backward compatibility with
    historical callers (workers, tests).
    """
    return unicodedata.normalize("NFKC", email).strip().casefold()


# Backwards-compatible private alias preserved for historical callers
# (``workers/pii_hash_backfill.py``, security tests). New code MUST use
# :func:`canonicalize_email`.
_canonical_email = canonicalize_email


def hash_email(email: str, *, hmac_secret: str) -> str:
    """Return the canonical ``email_hash`` value.

    The hash is keyed (HMAC-SHA-256) so an attacker who dumps the table
    cannot derive emails by precomputing rainbow tables. The ``email``
    is NFKC + casefolded first so two visually-identical addresses
    collide (FR-054 / FR-055).

    Legacy path (Phase 17 backlog A-2): this helper computes the
    historical ``web_session_secret`` Python-HMAC value persisted in
    the ``email_hash`` column. New rows ALSO populate
    ``email_hash_v2`` via :func:`hash_email_dual`; lookups try the
    KMS-backed v2/v1 path first and fall back to this helper for
    pre-A-2 rows. The signature is intentionally preserved so older
    tests that pass ``hmac_secret=...`` keep working.
    """
    canonical = _canonical_email(email).encode("utf-8")
    return hmac.new(hmac_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _email_matches_invitation(
    current_user_email: str,
    invitation: ProjectInvitation,
    *,
    hmac_secret: str,
) -> bool:
    """Email match against an invitation row (FR-054).

    Phase 17 backlog A-2 (FR-091b): rows created after migration 0016
    carry a KMS-keyed ``email_hash_v2`` alongside the legacy
    ``email_hash``. We evaluate BOTH paths unconditionally and OR the
    results so the function's runtime profile does not leak which
    branch produced the match (Round 2 R1-I3).

      * KMS path — :func:`echoroo.core.kms.verify_pii_hash` (which
        itself tries v2 then v1 of the rotated CMK). Skipped only
        when ``email_hash_v2`` is NULL (pre-A-2 row); KMS errors are
        swallowed to keep availability over a marginal observability
        win, and the warning log there records the unavailability.
      * Legacy path — Python HMAC against ``email_hash``. Always
        evaluated so the wallclock cost is independent of whether
        the v2 sibling exists.

    Both per-path comparisons use :func:`hmac.compare_digest`. The
    OR-combine is a plain Python ``or`` — given that both operands
    have already been computed, the short-circuit only saves an
    integer test, not a KMS round-trip, so the timing channel here
    is bounded by the small constant-time compare itself.
    """
    # Local import to avoid a heavy KMS module load at service import.
    from echoroo.core.kms import verify_pii_hash

    canonical = _canonical_email(current_user_email)

    matched_kms = False
    if invitation.email_hash_v2:
        try:
            matched_kms = verify_pii_hash(canonical, invitation.email_hash_v2)
        except Exception:  # noqa: BLE001 — KMS unavailable → legacy fallback
            logger.warning(
                "verify_pii_hash failed; relying on legacy hash compare",
                exc_info=True,
            )
            matched_kms = False

    expected_legacy = hash_email(current_user_email, hmac_secret=hmac_secret)
    matched_legacy = hmac.compare_digest(expected_legacy, invitation.email_hash)

    return matched_kms or matched_legacy


def hash_email_dual(email: str) -> dict[str, str]:
    """Return KMS-backed dual-write hashes for ``email`` (FR-091b).

    Single-key mode → ``{"v1": <hex>}``. Rotation in progress →
    ``{"v1": <hex>, "v2": <hex>}``. The canonicalisation matches
    :func:`hash_email` byte-for-byte so the two paths are
    interchangeable for the purposes of the FR-054 email-match
    check (modulo the underlying key, of course).

    The KMS round-trip happens here rather than at column-fill time
    so the writer in :func:`create_invitation` can emit a single
    paired set of inserts.
    """
    # Local import — avoids a circular import at module load time
    # (``echoroo.core.kms`` is otherwise import-light).
    from echoroo.core.kms import compute_pii_hash_dual

    return compute_pii_hash_dual(_canonical_email(email))


def _ensure_utc(value: datetime) -> datetime:
    """Return ``value`` converted to UTC.

    Naive datetimes are interpreted as UTC (defence in depth — every
    persisted ``expires_at`` is ``timestamptz`` so this branch should
    never fire in production). Aware datetimes are normalised via
    :meth:`datetime.astimezone`, which preserves the absolute instant
    (the prior implementation used ``replace(tzinfo=UTC)`` which would
    silently shift a non-UTC value by its offset).
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _mac_invitation_token_legacy(
    *,
    raw_token_b64u: str,
    expires_at_unix: int,
    hmac_secret: str,
) -> str:
    """Return the legacy 3-part HMAC over ``{raw}.{exp}``.

    Used during the spec/011 grace window to verify 3-part envelopes
    issued before the kid extension landed (NFR-011-010 path (b)).
    """
    payload = f"{raw_token_b64u}.{expires_at_unix}".encode("ascii")
    mac = hmac.new(hmac_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _b64u_encode(mac)


def _mac_invitation_token_v2(
    *,
    raw_token_b64u: str,
    expires_at_unix: int,
    kid: str,
    hmac_secret: str,
) -> str:
    """Return the 4-part HMAC over ``{raw}.{exp}.{kid}`` (spec/011 step 6).

    The MAC inputs cover the kid so an attacker cannot swap a 4-part
    envelope's ``kid`` slot to point at a more-permissive key without
    invalidating the signature.
    """
    payload = f"{raw_token_b64u}.{expires_at_unix}.{kid}".encode("ascii")
    mac = hmac.new(hmac_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _b64u_encode(mac)


def sign_invitation_token(
    *,
    raw_token_b64u: str,
    expires_at: datetime,
    hmac_secret: str | None = None,
) -> str:
    """Produce the 4-part ``{token}.{exp}.{kid}.{mac}`` envelope.

    The envelope is signed under the NEW kid declared in
    ``settings.INVITATION_TOKEN_KID_NEW`` with the matching HMAC key
    ``INVITATION_TOKEN_HMAC_KEY`` (spec/011 NFR-011-010). The
    ``hmac_secret`` keyword is preserved for backward compatibility with
    historical callers (it is now ignored — Step 6 routes the signing
    secret exclusively through the env-driven kid pair so a rotation
    only needs env var changes, never source bumps).
    """
    settings = get_settings()
    kid = settings.invitation_token_kid_new
    key = settings.invitation_token_hmac_key
    # ``hmac_secret`` is intentionally accepted but ignored — kept on the
    # signature so legacy unit tests that pre-date the env-driven
    # rotation keep parsing without a flag day.
    del hmac_secret
    expires_at_unix = int(_ensure_utc(expires_at).timestamp())
    mac = _mac_invitation_token_v2(
        raw_token_b64u=raw_token_b64u,
        expires_at_unix=expires_at_unix,
        kid=kid,
        hmac_secret=key,
    )
    return f"{raw_token_b64u}.{expires_at_unix}.{kid}.{mac}"


def verify_invitation_token(
    signed_token: str,
    *,
    hmac_secret: str | None = None,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Decode and verify a signed invitation token (spec/011 NFR-011-010).

    Accepts either:

    * A 4-part envelope ``{raw}.{exp}.{kid}.{mac}`` whose ``kid`` matches
      ``INVITATION_TOKEN_KID_NEW`` (preferred) or ``INVITATION_TOKEN_KID_OLD``
      (during the rotation grace window). The HMAC key is routed by the
      kid so a stolen OLD-kid envelope cannot upgrade itself to NEW.
    * A 3-part legacy envelope ``{raw}.{exp}.{mac}`` whose MAC verifies
      under ``INVITATION_TOKEN_HMAC_KEY_OLD`` IFF
      ``now < expires_at + INVITATION_TOKEN_KID_GRACE_HOURS``. Legacy
      acceptance requires the ``_OLD`` slot to be configured — refusal
      to start is enforced by ``Settings._validate_production_secrets``.

    Returns ``(raw_token_b64u, expires_at)`` on success.

    Raises :class:`InvitationTokenInvalidError` on any failure (missing
    parts, unknown kid, MAC mismatch, expiry past, legacy envelope
    outside grace). The error class is deliberately narrow so the
    endpoint can map every signal to the same generic-invalid HTTP
    response (FR-055 / FR-011-107 enumeration mitigation). All MAC
    comparisons go through :func:`hmac.compare_digest` (NFR-011-003).
    """
    del hmac_secret  # legacy keyword preserved for compatibility (ignored)
    settings = get_settings()
    now_eff = now or datetime.now(UTC)

    parts = signed_token.split(".")
    if len(parts) == 4:
        raw_token_b64u, expires_at_str, kid, mac_b64u = parts
        try:
            expires_at_unix = int(expires_at_str)
        except ValueError as exc:
            raise InvitationTokenInvalidError(
                "invalid expiry component",
            ) from exc

        # Route by kid. We compute the candidate MAC ONLY for the
        # matching kid so a stolen OLD-kid envelope cannot probe the NEW
        # key (defence in depth — the MAC inputs already cover the kid,
        # so a swap would not verify, but routing keeps the timing
        # signature uniform).
        if kid == settings.invitation_token_kid_new:
            expected_key = settings.invitation_token_hmac_key
        elif (
            settings.invitation_token_kid_old is not None
            and kid == settings.invitation_token_kid_old
        ):
            old_key = settings.invitation_token_hmac_key_old
            if old_key is None:  # pragma: no cover — co-presence guard
                raise InvitationTokenInvalidError(
                    "invitation token signed under retired kid",
                )
            expected_key = old_key
        else:
            raise InvitationTokenInvalidError(
                "invitation token signed under unknown kid",
            )

        expected_mac = _mac_invitation_token_v2(
            raw_token_b64u=raw_token_b64u,
            expires_at_unix=expires_at_unix,
            kid=kid,
            hmac_secret=expected_key,
        )
        if not hmac.compare_digest(expected_mac, mac_b64u):
            raise InvitationTokenInvalidError(
                "invitation token signature mismatch",
            )

        expires_at = datetime.fromtimestamp(expires_at_unix, tz=UTC)
        if now_eff >= expires_at:
            raise InvitationTokenInvalidError("invitation token has expired")
        return raw_token_b64u, expires_at

    if len(parts) == 3:
        # Legacy 3-part envelope (spec/011 NFR-011-010 (b)): verify under
        # the OLD key during the grace window. ``KID_OLD`` MUST be set
        # for this path — the settings co-presence guard ensures it.
        old_key = settings.invitation_token_hmac_key_old
        if old_key is None:
            raise InvitationTokenInvalidError(
                "legacy invitation token rejected: rotation OLD key unset",
            )
        raw_token_b64u, expires_at_str, mac_b64u = parts
        try:
            expires_at_unix = int(expires_at_str)
        except ValueError as exc:
            raise InvitationTokenInvalidError(
                "invalid expiry component",
            ) from exc
        expected_mac = _mac_invitation_token_legacy(
            raw_token_b64u=raw_token_b64u,
            expires_at_unix=expires_at_unix,
            hmac_secret=old_key,
        )
        if not hmac.compare_digest(expected_mac, mac_b64u):
            raise InvitationTokenInvalidError(
                "invitation token signature mismatch",
            )
        expires_at = datetime.fromtimestamp(expires_at_unix, tz=UTC)
        # Reject past TTL + grace window. The grace window extends past
        # the envelope's ``expires_at`` so a 3-part token that was 1
        # minute from natural expiry at deploy time remains verifiable
        # until ``expires_at + GRACE_HOURS``.
        #
        # Equivalence with NFR-011-010(b)'s wording ("now < created_at +
        # 7d + GRACE_HOURS"): for any legitimately-issued legacy token
        # the envelope's ``expires_at`` equals ``created_at + 7d`` (the
        # canonical invitation TTL set at issuance), so the two
        # formulas yield the same admit/reject boundary. They diverge
        # only if an attacker controls the OLD HMAC key and re-signs an
        # envelope with a forged ``expires_at``; in that scenario the
        # system is already fully compromised (any unexpired raw token
        # plus the key lets the attacker accept) and the DB-row-time
        # formula buys no additional defence. We keep the envelope
        # formula because (a) the DB row is not yet fetched at this
        # validation layer (token-hash lookup happens in
        # ``redeem_invitation_token``) and (b) every existing caller
        # expects ``expires_at``-based behaviour.
        grace = timedelta(hours=settings.invitation_token_kid_grace_hours)
        if now_eff >= expires_at + grace:
            raise InvitationTokenInvalidError(
                "legacy invitation token outside grace window",
            )
        return raw_token_b64u, expires_at

    raise InvitationTokenInvalidError("malformed invitation token")


# ---------------------------------------------------------------------------
# Permission allowlist filter (FR-012, FR-014, FR-042)
# ---------------------------------------------------------------------------


def coerce_granted_permissions(
    raw: Iterable[str | Permission],
) -> frozenset[Permission]:
    """Validate + intersect ``granted_permissions`` against the Trusted allowlist.

    Raises :class:`InvitationValidationError` when any entry is not a known
    Permission name OR is outside ``TRUSTED_ALLOWED_PERMISSIONS``. We **do
    not** silently filter at issue-time — the operator must learn that a
    requested capability is unsupported (FR-012 expectation: the UI / API
    surface only Trusted-eligible rows). The runtime safety net in
    :mod:`echoroo.core.permissions` filters anyway, but the error here
    keeps the row aligned with the UI contract.
    """
    out: set[Permission] = set()
    for entry in raw:
        if isinstance(entry, Permission):
            perm = entry
        else:
            try:
                perm = Permission(entry)
            except ValueError as exc:
                raise InvitationValidationError(
                    f"unknown permission name: {entry!r}"
                ) from exc
        if perm not in TRUSTED_ALLOWED_PERMISSIONS:
            raise InvitationValidationError(
                f"permission {perm.value!r} is not in TRUSTED_ALLOWED_PERMISSIONS",
            )
        out.add(perm)
    if not out:
        raise InvitationValidationError("granted_permissions must be non-empty")
    return frozenset(out)


# ---------------------------------------------------------------------------
# Rate-limit helpers (FR-056)
# ---------------------------------------------------------------------------


async def check_rate_limits(
    redis: Redis,
    *,
    actor_user_id: UUID,
    project_id: UUID,
) -> None:
    """Increment + verify the per-actor and per-project rate counters.

    FR-056: Owner/Admin 50/h, project 200/h. Both keys live in Redis with
    a fixed-window TTL; the increment-then-compare pattern ensures the
    counter survives the request even if the caller subsequently aborts
    (worst case: a few "consumed" counts that did not result in a row,
    which is acceptable — over-counting tightens the limit, never loosens).

    **Fail-closed**: callers MUST pass a live :class:`Redis`. A missing or
    unreachable Redis surfaces as :class:`InvitationInfraUnavailableError`
    so the issuer cannot bypass the cap by waiting out an outage.
    """
    actor_key = f"invitation_rate:actor:{actor_user_id}"
    project_key = f"invitation_rate:project:{project_id}"

    try:
        actor_count = await redis.incr(actor_key)
        if actor_count == 1:
            await redis.expire(actor_key, _RATE_LIMIT_WINDOW_SECONDS)
    except Exception as exc:  # noqa: BLE001 — fail-closed for any redis fault
        raise InvitationInfraUnavailableError(
            "invitation rate limiter (Redis) is unavailable"
        ) from exc
    if actor_count > RATE_LIMIT_ACTOR_PER_HOUR:
        raise InvitationRateLimitError(
            f"actor {actor_user_id} exceeded invitation rate limit "
            f"({RATE_LIMIT_ACTOR_PER_HOUR}/h)"
        )

    try:
        project_count = await redis.incr(project_key)
        if project_count == 1:
            await redis.expire(project_key, _RATE_LIMIT_WINDOW_SECONDS)
    except Exception as exc:  # noqa: BLE001 — fail-closed for any redis fault
        raise InvitationInfraUnavailableError(
            "invitation rate limiter (Redis) is unavailable"
        ) from exc
    if project_count > RATE_LIMIT_PROJECT_PER_HOUR:
        raise InvitationRateLimitError(
            f"project {project_id} exceeded invitation rate limit "
            f"({RATE_LIMIT_PROJECT_PER_HOUR}/h)"
        )


# ---------------------------------------------------------------------------
# Public API: create_invitation
# ---------------------------------------------------------------------------


async def create_invitation(
    session: AsyncSession,
    *,
    project_id: UUID,
    kind: ProjectInvitationKind,
    email: str,
    invited_by_id: UUID,
    hmac_secret: str,
    redis: Redis,
    role: ProjectMemberRole | None = None,
    granted_permissions: Sequence[str | Permission] | None = None,
    trusted_duration_seconds: int | None = None,
    invitation_ttl_seconds: int | None = None,
    ownership_transfer_on_accept: bool = False,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
    now: datetime | None = None,
) -> InvitationCreateOutcome:
    """Issue a Member or Trusted invitation, returning a signed URL token.

    Steps:

    1. Validate the kind × payload combination (FR-048 mirrored at the
       application layer so we can raise structured errors before the DB
       check kicks in). spec/011 R5 — reject
       ``ownership_transfer_on_accept=True`` when ``kind != MEMBER``.
    2. ``check_rate_limits`` — FR-056 (fail-closed; Redis required).
    3. Generate the 256-bit raw token, compute ``token_hash`` and
       the 4-part HMAC-signed envelope (FR-052 / NFR-011-010).
    4. Insert the row inside the caller's transaction. Caller commits.
       The signed envelope is attached to the outcome as
       ``signed_token_envelope`` for the handler to surface as
       ``invitation_url`` (FR-011-102..104).

    Args:
        session: Caller-owned async session. Caller commits.
        project_id: Target project.
        kind: Invitation kind discriminator.
        email: Plain-text recipient email; ``email_hash`` is computed here.
        invited_by_id: Owner / Admin issuing the invitation.
        hmac_secret: HMAC key for the ``email_hash`` column. Pass
            ``settings.web_session_secret`` from the endpoint. The
            invitation envelope itself is signed under the env-driven
            ``INVITATION_TOKEN_KID_NEW`` / ``HMAC_KEY`` pair
            (spec/011 NFR-011-010) — independent of this argument.
        redis: Async Redis client used by the FR-056 rate limiter (and the
            FR-053 idempotency cache on accept). Required — fail-closed.
        role: Required when ``kind=='member'``.
        granted_permissions: Required when ``kind=='trusted'``.
        trusted_duration_seconds: Required when ``kind=='trusted'``;
            defaults handled by the endpoint per spec.
        invitation_ttl_seconds: Optional override of the FR-052 default
            (7 days). Hard-capped at :data:`INVITATION_MAX_TTL_SECONDS`;
            anything larger raises :class:`InvitationValidationError` so
            an operator cannot extend the URL window beyond spec.
        ownership_transfer_on_accept: spec/011 FR-011-121..125 flag. When
            ``True`` MUST be paired with ``kind=ProjectInvitationKind.MEMBER``
            (R5); other kinds raise :class:`InvitationStateError`.
        request_id / ip / user_agent: Audit plumbing (passed through to
            the outcome dataclass; the writer hashes them later).
        now: Override for ``datetime.now(UTC)`` — testing only.

    Returns:
        :class:`InvitationCreateOutcome` carrying the row and the
        ``signed_token_envelope`` (FR-011-102..104). The handler surfaces
        the envelope as the ``invitation_url`` body field; it MUST NOT
        appear in logs, telemetry, or any persisted column past this
        single HTTP turn.

    Raises:
        InvitationValidationError: Bad payload combination or TTL > 7 d.
        InvitationStateError: R5 — ``ownership_transfer_on_accept`` set
            on a non-MEMBER kind (defence in depth above the DB CHECK
            added by migration 0021).
        InvitationRateLimitError: Rate limit exceeded.
        InvitationInfraUnavailableError: Redis is unreachable.
        InvitationConflictError: A pending invitation already exists for
            ``(project_id, email_hash)``.
    """
    now_eff = now or datetime.now(UTC)

    # 0. TTL guard (FR-052 hard cap = 7 days).
    if invitation_ttl_seconds is None:
        ttl_seconds = INVITATION_TTL_SECONDS
    else:
        ttl_seconds = invitation_ttl_seconds
    if not 1 <= ttl_seconds <= INVITATION_MAX_TTL_SECONDS:
        raise InvitationValidationError(
            "invitation_ttl_seconds must be in "
            f"[1, {INVITATION_MAX_TTL_SECONDS}] (FR-052 hard cap = 7 days)"
        )

    # 0.5. spec/011 R5 (FR-011-122..125) — ``ownership_transfer_on_accept``
    # is only valid for Member-kind invitations. The DB
    # ``ck_project_invitations_ownership_transfer_kind_member`` CHECK
    # constraint (migration 0021) is the source of truth; this
    # application-level guard surfaces a typed error BEFORE the INSERT
    # so callers get a structured error class instead of a bare
    # IntegrityError. Order matters: we evaluate the cheap kind check
    # before any DB round-trip and before rate-limit consumption.
    if ownership_transfer_on_accept and kind is not ProjectInvitationKind.MEMBER:
        raise InvitationStateError(
            "ownership_transfer_on_accept_invalid_for_kind",
        )

    # 1. kind × payload validation (FR-048)
    if kind is ProjectInvitationKind.MEMBER:
        if role is None:
            raise InvitationValidationError(
                "role is required when kind='member'"
            )
        if granted_permissions is not None or trusted_duration_seconds is not None:
            raise InvitationValidationError(
                "granted_permissions / trusted_duration_seconds must be NULL "
                "when kind='member'"
            )
        granted_perms_db: list[str] | None = None
        duration_db: int | None = None
    elif kind is ProjectInvitationKind.TRUSTED:
        if role is not None:
            raise InvitationValidationError(
                "role must be NULL when kind='trusted'"
            )
        if granted_permissions is None:
            raise InvitationValidationError(
                "granted_permissions is required when kind='trusted'"
            )
        if trusted_duration_seconds is None:
            trusted_duration_seconds = TRUSTED_DEFAULT_DURATION_SECONDS
        if not 1 <= trusted_duration_seconds <= TRUSTED_MAX_DURATION_SECONDS:
            raise InvitationValidationError(
                f"trusted_duration_seconds must be in [1, {TRUSTED_MAX_DURATION_SECONDS}]"
            )
        valid_perms = coerce_granted_permissions(granted_permissions)
        granted_perms_db = sorted(p.value for p in valid_perms)
        duration_db = trusted_duration_seconds
    else:  # pragma: no cover - StrEnum exhaustive
        raise InvitationValidationError(f"unknown invitation kind: {kind!r}")

    # 2. rate limit (FR-056) — fail-closed
    await check_rate_limits(
        redis, actor_user_id=invited_by_id, project_id=project_id,
    )

    # 3. token + hash (FR-051 / FR-052 / FR-055)
    raw_token_b64u = _b64u_encode(secrets.token_bytes(TOKEN_BYTES))
    token_hash = hash_token(raw_token_b64u)
    expires_at = now_eff + timedelta(seconds=ttl_seconds)
    signed_token = sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=expires_at,
        hmac_secret=hmac_secret,
    )
    email_hash_value = hash_email(email, hmac_secret=hmac_secret)
    # Phase 17 backlog A-2 (FR-091b): emit the KMS dual-write hash
    # into the ``email_hash_v2`` sibling so future lookups can match
    # under v1 OR v2 of the rotated PII CMK without needing the
    # legacy ``web_session_secret`` to remain stable.
    #
    # Round 2 R1-C1: ``email_hash_v2`` is a TRUE v2 column. We only
    # populate it when the dual-write helper actually produced a v2
    # component (i.e. rotation has started and ``get_pii_hash_version``
    # → 2). In single-key mode we leave it NULL so the daily
    # backfill worker (``pii_hash_backfill.py``) — which selects on
    # ``email_hash_v2 IS NULL`` — can pick the row up the moment an
    # operator flips the v2 alias on. Writing the v1 value here would
    # otherwise hide single-key-period invitations from the backfill
    # forever.
    email_hash_kms = hash_email_dual(email)
    if "v2" in email_hash_kms:
        email_hash_v2_value: str | None = email_hash_kms["v2"]
        pii_hash_version_value: int | None = 2
    else:
        email_hash_v2_value = None
        pii_hash_version_value = None

    # 4. Insert (caller-owned TX). The (project_id, email_hash) WHERE
    # status='pending' partial unique index is the FR-049 guard; collisions
    # surface as IntegrityError, which we map to InvitationConflictError.
    #
    # Round trip note: the ``granted_permissions`` column is JSONB; passing
    # Python ``None`` to a JSONB attribute would otherwise serialise as the
    # JSON literal ``null`` (not SQL NULL), which trips
    # ``ck_project_invitations_kind_fields`` because the CHECK uses
    # ``IS NULL``. We therefore omit the column from the constructor when
    # the value is None — SQLAlchemy honours the column's
    # ``nullable=True`` default and INSERTs SQL NULL.
    invitation_kwargs: dict[str, Any] = {
        "project_id": project_id,
        "kind": kind,
        "email": email,
        "email_hash": email_hash_value,
        "email_hash_v2": email_hash_v2_value,
        "pii_hash_version": pii_hash_version_value,
        "role": role if kind is ProjectInvitationKind.MEMBER else None,
        "trusted_duration_seconds": duration_db,
        "token_hash": token_hash,
        "invited_by_id": invited_by_id,
        "expires_at": expires_at,
        "status": ProjectInvitationStatus.PENDING,
        "ownership_transfer_on_accept": ownership_transfer_on_accept,
    }
    if granted_perms_db is not None:
        invitation_kwargs["granted_permissions"] = granted_perms_db
    invitation = ProjectInvitation(**invitation_kwargs)
    session.add(invitation)
    try:
        await session.flush()
    except IntegrityError as exc:
        # The endpoint will rollback; surface a typed error so the audit
        # log records the reason without leaking stack traces.
        raise InvitationConflictError(
            "an equivalent pending invitation already exists",
        ) from exc

    return InvitationCreateOutcome(
        invitation=invitation,
        actor_user_id=invited_by_id,
        signed_token_envelope=signed_token,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Idempotency helpers (FR-053)
# ---------------------------------------------------------------------------


def _idempotency_redis_key(idempotency_key: str) -> str:
    return f"{_IDEMPOTENCY_KEY_PREFIX}{idempotency_key}"


async def _get_idempotent_outcome(
    redis: Redis,
    idempotency_key: str,
) -> _IdempotencyRecord | None:
    """Return the cached :class:`_IdempotencyRecord` for ``idempotency_key``.

    Returns ``None`` when no record exists. **Fail-closed**: any Redis
    transport / runtime fault is converted to
    :class:`InvitationInfraUnavailableError` (HTTP 503) so the caller
    cannot bypass the FR-053 idempotency guard during a partial outage.
    A silent ``None`` would let an attacker reuse the same key with a
    different token and get a fresh accept; mapping the fault to 503
    forces the client to retry against a healthy primary instead.
    """
    try:
        raw = await redis.get(_idempotency_redis_key(idempotency_key))
    except Exception as exc:  # noqa: BLE001 — fail-closed for any redis fault
        raise InvitationInfraUnavailableError(
            "invitation idempotency cache (Redis) is unavailable"
        ) from exc
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return _IdempotencyRecord(
        invitation_id=str(data.get("invitation_id", "")),
        token_hash=str(data.get("token_hash", "")),
        is_replay=True,
        created_at=str(data.get("created_at", "")),
    )


async def _set_idempotent_outcome(
    redis: Redis,
    idempotency_key: str,
    record: _IdempotencyRecord,
) -> None:
    """Pin ``record`` to ``idempotency_key`` (24 h TTL).

    We use ``SET ... NX`` so we never overwrite a pre-existing record
    (the conflict path in :func:`accept_invitation` relies on the cached
    row remaining stable for the lifetime of the key).

    **Fail-closed**: any Redis transport / runtime fault surfaces as
    :class:`InvitationInfraUnavailableError`. Without the cached pin the
    24 h dedupe contract for FR-053 cannot be guaranteed (a subsequent
    retry would hit a cold cache and we would have no way to detect a
    different-token replay). A failed ``SET NX`` against an existing key
    is **not** a fault — it means a concurrent accept already pinned the
    same key, which is the expected idempotent path; we treat that as
    success.
    """
    payload = json.dumps(
        {
            "invitation_id": record.invitation_id,
            "token_hash": record.token_hash,
            "created_at": record.created_at,
        },
        sort_keys=True,
    )
    try:
        await redis.set(
            _idempotency_redis_key(idempotency_key),
            payload,
            ex=_IDEMPOTENCY_TTL_SECONDS,
            nx=True,
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed for any redis fault
        raise InvitationInfraUnavailableError(
            "invitation idempotency cache (Redis) is unavailable"
        ) from exc


# ---------------------------------------------------------------------------
# Public API: accept_invitation
# ---------------------------------------------------------------------------


async def accept_invitation(
    session: AsyncSession,
    *,
    signed_token: str,
    current_user_id: UUID,
    current_user_email: str,
    hmac_secret: str,
    redis: Redis,
    idempotency_key: str | None = None,
    project_id_scope: UUID | None = None,
    now: datetime | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> InvitationAcceptOutcome:
    """Consume an invitation atomically (FR-053 / FR-054).

    Implementation contract (strict order — see security review):

    1. **HMAC verify** the signed token; reject expired / tampered tokens
       with :class:`InvitationTokenInvalidError`.
    2. **(Optional) idempotency-key short-circuit**: if ``idempotency_key``
       is supplied and Redis already has a record bound to a *different*
       token, raise :class:`InvitationConflictError` (HTTP 409). If the
       record matches the current token, return a replay outcome.
    3. **Row lookup** by ``token_hash`` with ``SELECT ... FOR UPDATE`` so
       two parallel accepts serialise on the same row.
    4. **Email match check** (NFKC + casefold; FR-054). Performed *before*
       the status check so a user holding a token issued for someone else
       always gets 403 — they never learn whether the invitation has
       already been consumed (FR-055 enumeration mitigation, prevents
       cross-account accepted-token replay).
    5. **Status check**: ``pending`` is the only acceptable state. An
       ``accepted`` state plus a *matching* idempotency-key resolves to
       a replay; otherwise the function raises
       :class:`InvitationStateError` (HTTP 410).
    6. **Apply the grant** (Member → ProjectMember, Trusted →
       ProjectTrustedUser) and flip ``status`` to ``accepted`` in the
       same transaction. When an active membership row already exists
       for the same (project_id, user_id), we REUSE it only if the
       cached idempotency record under the supplied key has a matching
       ``token_hash``; otherwise we raise 409 to prevent unrelated
       memberships from silently flipping a pending invitation to
       ``accepted``. Caller commits.

    Args:
        redis: Live Redis client. **Required** (non-Optional). Used for
            the FR-053 idempotency cache. Read / write faults raise
            :class:`InvitationInfraUnavailableError` (HTTP 503) —
            fail-closed so a partial Redis outage cannot bypass the
            FR-053 dedupe guarantee.

    Raises:
        InvitationTokenInvalidError: bad / expired signature, missing row.
        InvitationEmailMismatchError: caller email != invitation email.
        InvitationStateError: invitation already terminal (no replay key).
        InvitationConflictError: idempotency-key reused with different
            token, OR existing active membership without matching
            idempotency record.
        InvitationInfraUnavailableError: Redis is unreachable.
    """
    now_eff = now or datetime.now(UTC)

    # 1. HMAC verify (FR-052)
    raw_token_b64u, signed_expires_at = verify_invitation_token(
        signed_token, hmac_secret=hmac_secret, now=now_eff,
    )
    token_hash = hash_token(raw_token_b64u)

    # 2. Idempotency-key short-circuit (FR-053)
    #
    # ``redis`` is required (non-Optional). When the caller supplies an
    # ``idempotency_key`` we fetch the cached record fail-closed: a
    # transient Redis fault raises :class:`InvitationInfraUnavailableError`
    # so the caller cannot bypass FR-053 by waiting out an outage.
    if idempotency_key is not None:
        cached = await _get_idempotent_outcome(redis, idempotency_key)
        if cached is not None and cached.token_hash and cached.token_hash != token_hash:
            raise InvitationConflictError(
                "Idempotency-Key reused with a different invitation token",
            )

    # 3. Row lookup with FOR UPDATE (FR-053)
    result = await session.execute(
        select(ProjectInvitation)
        .where(ProjectInvitation.token_hash == token_hash)
        .with_for_update(),
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise InvitationTokenInvalidError("invitation not found")

    # Phase 10 Batch 2 Round 2 fix (致命 3): the URL path's ``project_id``
    # MUST match the row's ``project_id``. Without this guard a caller
    # could POST a valid token under a *different* project's URL and
    # accept the invite, which would let an attacker exercise the FR-055
    # enumeration mitigation in reverse — reading the success response
    # would confirm the token's true project. We collapse the mismatch
    # into the same "invitation not found" branch the handler already
    # maps to 404 so the response shape stays uniform.
    if project_id_scope is not None and invitation.project_id != project_id_scope:
        raise InvitationTokenInvalidError("invitation not found")

    # spec/011 R5 (FR-011-122..125) — defence in depth above the DB CHECK:
    # if a row somehow exists with ``ownership_transfer_on_accept=True``
    # but ``kind != member`` (e.g. data corruption, manual SQL backdoor),
    # refuse to accept. The DB CHECK
    # ``ck_project_invitations_ownership_transfer_kind_member`` already
    # prevents the row from being INSERTed in the first place, but a
    # data-corruption scenario or a CHECK-bypassing migration shim
    # would otherwise allow a non-member transfer-on-accept path. The
    # service-layer guard surfaces a typed error class so the handler
    # never silently transfers ownership through a misclassified row.
    if (
        invitation.ownership_transfer_on_accept
        and invitation.kind is not ProjectInvitationKind.MEMBER
    ):
        raise InvitationStateError(
            "ownership_transfer_on_accept_invalid_for_kind",
        )

    # The signed expiry is the source of truth for the URL; the row's
    # expires_at is an additional guard. Reject if either failed.
    invitation_expires_at = _ensure_utc(invitation.expires_at)
    if invitation_expires_at <= now_eff:
        raise InvitationTokenInvalidError("invitation has expired")

    # 4. Email match (FR-054). The signed token already authenticates the
    # *URL*; this step authenticates the *recipient* against the URL.
    # Performed before the status check so an attacker holding a stolen
    # accepted-token never learns the invitation status.
    if not _email_matches_invitation(
        current_user_email,
        invitation,
        hmac_secret=hmac_secret,
    ):
        raise InvitationEmailMismatchError(
            "current user's email does not match the invitation",
        )

    # 5. Status checks (FR-053)
    if invitation.status != ProjectInvitationStatus.PENDING:
        # Idempotent replay path — only allowed when:
        #   (a) the row is in ACCEPTED state, AND
        #   (b) the caller supplied a matching idempotency-key.
        # Without the key we cannot prove the caller is the original
        # accepter, so the safe default is HTTP 410.
        if (
            invitation.status == ProjectInvitationStatus.ACCEPTED
            and idempotency_key is not None
        ):
            cached = await _get_idempotent_outcome(redis, idempotency_key)
            if cached is not None and cached.token_hash == token_hash:
                replay_member, replay_trusted_user = await _load_existing_grant(
                    session, invitation, current_user_id,
                )
                return InvitationAcceptOutcome(
                    invitation=invitation,
                    member=replay_member,
                    trusted_user=replay_trusted_user,
                    actor_user_id=current_user_id,
                    is_replay=True,
                    request_id=request_id,
                    ip=ip,
                    user_agent=user_agent,
                )
        raise InvitationStateError(
            f"invitation is in terminal state: {invitation.status.value}"
        )

    # Sanity: the signed token's expiry should never run past the row's
    # expiry. If it does, the row was tampered with — fall through as
    # token-invalid for FR-055 enumeration uniformity.
    if signed_expires_at < invitation_expires_at - timedelta(seconds=1):
        # Allow a small clock skew margin (1 s) but reject anything larger.
        raise InvitationTokenInvalidError("invitation token expiry mismatch")

    # 6. Apply the grant in the same TX.
    member: ProjectMember | None = None
    trusted_user: ProjectTrustedUser | None = None

    if invitation.kind is ProjectInvitationKind.MEMBER:
        if invitation.role is None:  # pragma: no cover - DB CHECK guards this
            raise InvitationValidationError(
                "Member invitation has NULL role (data corruption)"
            )
        # Pre-flight: re-use the existing active membership row when one
        # already exists for the same (project_id, user_id) so the
        # ``ux_project_members_active`` partial unique does not surface
        # as IntegrityError. REUSE is only honoured when:
        #
        #   (a) the caller supplied an idempotency-key, AND
        #   (b) Redis has a cached record under that key whose
        #       ``token_hash`` matches the *current* invitation's token.
        #
        # Without (b) we cannot prove the existing membership row was
        # created by *this* invitation — it might be an unrelated row
        # (e.g. the user was added by another Owner via a different
        # invitation, or via the legacy direct-add path). Re-using such
        # a row would silently flip an unrelated invitation to
        # ``accepted`` status, which would let an attacker use a stolen
        # idempotency-key to mark arbitrary pending invitations as
        # consumed. Instead we raise 409 conflict so the caller is
        # forced to revoke / re-issue.
        existing_member_result = await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == invitation.project_id,
                ProjectMember.user_id == current_user_id,
                ProjectMember.removed_at.is_(None),
            ),
        )
        existing_member = existing_member_result.scalar_one_or_none()
        if existing_member is not None:
            if idempotency_key is None:
                raise InvitationConflictError(
                    "user already has an active membership in this project",
                )
            cached_for_reuse = await _get_idempotent_outcome(
                redis, idempotency_key,
            )
            if (
                cached_for_reuse is None
                or cached_for_reuse.token_hash != token_hash
            ):
                raise InvitationConflictError(
                    "user already has an active membership in this project",
                )
            member = existing_member
        else:
            member = ProjectMember(
                project_id=invitation.project_id,
                user_id=current_user_id,
                role=invitation.role,
                joined_at=now_eff,
                invited_by_id=invitation.invited_by_id,
            )
            session.add(member)
    else:  # ProjectInvitationKind.TRUSTED
        if (
            invitation.granted_permissions is None
            or invitation.trusted_duration_seconds is None
        ):  # pragma: no cover - DB CHECK guards this
            raise InvitationValidationError(
                "Trusted invitation has NULL granted_permissions/duration "
                "(data corruption)"
            )
        # Re-validate the persisted permission set against the runtime
        # allowlist so a future allowlist tightening immediately blocks
        # accept (FR-014). The set is also re-sorted for determinism.
        valid_perms = coerce_granted_permissions(invitation.granted_permissions)
        expires_at = now_eff + timedelta(seconds=invitation.trusted_duration_seconds)
        # Cap at granted_at + 1 year for defence in depth (DB CHECK does
        # the same, but raising at the application layer gives the
        # endpoint a structured error).
        if expires_at - now_eff > timedelta(seconds=TRUSTED_MAX_DURATION_SECONDS):
            raise InvitationValidationError(
                "trusted_duration_seconds resolves past the FR-043 cap"
            )
        trusted_user = ProjectTrustedUser(
            project_id=invitation.project_id,
            user_id=current_user_id,
            invitation_id=invitation.id,
            granted_by_id=invitation.invited_by_id,
            granted_at=now_eff,
            expires_at=expires_at,
            status=ProjectTrustedStatus.ACTIVE,
            granted_permissions=sorted(p.value for p in valid_perms),
            email_at_invitation=invitation.email,
            email_at_invitation_hash=invitation.email_hash,
        )
        session.add(trusted_user)

    invitation.status = ProjectInvitationStatus.ACCEPTED
    invitation.accepted_at = now_eff

    try:
        await session.flush()
    except IntegrityError as exc:
        # E.g. ux_project_trusted_users_active partial unique violation when
        # the same user already has an active overlay — surface as state
        # error so the endpoint maps to 409.
        raise InvitationConflictError(
            "concurrent grant already exists for this user/project",
        ) from exc

    # Pin the idempotency record so a retry returns the same outcome.
    if idempotency_key is not None:
        await _set_idempotent_outcome(
            redis,
            idempotency_key,
            _IdempotencyRecord(
                invitation_id=str(invitation.id),
                token_hash=token_hash,
                is_replay=True,
            ),
        )

    return InvitationAcceptOutcome(
        invitation=invitation,
        member=member,
        trusted_user=trusted_user,
        actor_user_id=current_user_id,
        is_replay=False,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# spec/011 FR-011-105 / FR-011-106 — Public-token resolver + accept
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvitationResolveOutcome:
    """Snapshot returned by :func:`resolve_invitation_for_public_token`.

    Carries the safe subset of invitation metadata the public landing page
    needs to render its signup / accept form. ``authenticated_email_matches``
    is ``None`` when no session cookie was supplied (the resolver still
    succeeds — the frontend renders the signup branch).
    """

    invitation: ProjectInvitation
    project_name: str
    is_logged_in: bool
    authenticated_email_matches: bool | None


@dataclass(frozen=True)
class InvitationPublicAcceptOutcome:
    """Snapshot returned by :func:`accept_invitation_via_public_token`.

    The accepting user (newly created or pre-existing), the resulting
    membership / trusted-overlay row, the invitation row, and the branch
    discriminator used by the audit emitter. ``audit_action`` is one of
    :data:`AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP`,
    :data:`AUDIT_ACTION_MEMBER_INVITE_ACCEPTED`, or
    :data:`AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED` (T208).
    """

    invitation: ProjectInvitation
    accepting_user_id: UUID
    member: ProjectMember | None
    trusted_user: ProjectTrustedUser | None
    audit_action: str
    membership_created: bool
    ownership_transferred: bool = False
    request_id: str = ""
    ip: str = ""
    user_agent: str = ""


async def resolve_invitation_for_public_token(
    session: AsyncSession,
    *,
    signed_token: str,
    authenticated_email: str | None,
    now: datetime | None = None,
) -> InvitationResolveOutcome:
    """Resolve invitation context for the public landing page (FR-011-105).

    The resolver authenticates by the signed token alone (TOKEN_AUTH_ONLY).
    When the caller also presents a valid session cookie the handler passes
    the authenticated user's email so the resolver can report whether the
    bound email matches; the frontend uses the flag to gate the existing-
    user accept branch vs. force a sign-out for a mismatched session.

    Raises :class:`InvitationTokenInvalidError` for any failure cause
    (bad signature, expired envelope, unknown token, terminal-status row,
    deleted project). The handler maps every cause to the same generic
    response with constant timing (FR-011-107). Project visibility /
    role-validity guards on the row mirror the live application gate so
    a stale invitation whose target role no longer matches the project's
    visibility is rejected uniformly.
    """
    now_eff = now or datetime.now(UTC)

    raw_token_b64u, _ = verify_invitation_token(
        signed_token, now=now_eff,
    )
    token_hash = hash_token(raw_token_b64u)

    result = await session.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.token_hash == token_hash,
        ),
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise InvitationTokenInvalidError("invitation not found")

    if invitation.status != ProjectInvitationStatus.PENDING:
        # Any terminal status — accepted / declined / revoked / expired —
        # collapses to the same generic-invalid surface (FR-011-107).
        raise InvitationTokenInvalidError("invitation not pending")

    invitation_expires_at = _ensure_utc(invitation.expires_at)
    if invitation_expires_at <= now_eff:
        raise InvitationTokenInvalidError("invitation has expired")

    # Local import — avoid a heavy ``Project`` model load at module import.
    from echoroo.models.project import Project

    project_row = (
        await session.execute(
            select(Project.name).where(Project.id == invitation.project_id),
        )
    ).first()
    if project_row is None:
        raise InvitationTokenInvalidError("invitation target project missing")
    project_name = str(project_row[0])

    is_logged_in = authenticated_email is not None
    authenticated_email_matches: bool | None
    if authenticated_email is None or invitation.email is None:
        authenticated_email_matches = None if not is_logged_in else False
    else:
        authenticated_email_matches = canonicalize_email(
            authenticated_email
        ) == canonicalize_email(invitation.email)

    return InvitationResolveOutcome(
        invitation=invitation,
        project_name=project_name,
        is_logged_in=is_logged_in,
        authenticated_email_matches=authenticated_email_matches,
    )


async def accept_invitation_via_public_token(
    session: AsyncSession,
    *,
    signed_token: str,
    accepting_user_id: UUID,
    accepting_user_email: str,
    project_id_scope: UUID | None = None,
    is_new_user_signup: bool = False,
    now: datetime | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> InvitationPublicAcceptOutcome:
    """Accept an invitation under the spec/011 public-token surface.

    Implements FR-011-106 in a single transaction:

    1. HMAC-verify the signed envelope (constant-time MAC compare via
       :func:`verify_invitation_token`).
    2. Look up the row by ``token_hash``; mismatch / missing →
       :class:`InvitationTokenInvalidError`.
    3. Compare ``canonicalize_email(accepting_user_email)`` with the bound
       email (NFKC + casefold). Mismatch →
       :class:`InvitationEmailMismatchError` (handler maps to generic 404).
    4. Atomic state flip via parameterised SQL (FR-011-106 step 2). Zero
       rows returned → :class:`InvitationTokenInvalidError`.
    5. Insert the grant row (ProjectMember / ProjectTrustedUser). When the
       caller already holds an active membership at the same OR higher
       role, raise :class:`InvitationAlreadyMemberError` (handler →
       409). Otherwise insert and audit-emit per branch.

    The caller's authentication state is signalled via
    ``is_new_user_signup``: ``True`` selects
    :data:`AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP`,
    ``False`` selects :data:`AUDIT_ACTION_MEMBER_INVITE_ACCEPTED` (or
    :data:`AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED` for trusted-overlay
    rows). The caller is responsible for having created the user row
    BEFORE invoking this function on the signup branch — the service
    layer never receives the cleartext password.

    Caller commits the transaction. Audit side effects fire post-commit
    via :func:`trigger_post_commit_side_effects`.
    """
    now_eff = now or datetime.now(UTC)

    # Step 1 — HMAC verify (NFR-011-003 constant-time compare).
    raw_token_b64u, _ = verify_invitation_token(signed_token, now=now_eff)
    token_hash = hash_token(raw_token_b64u)

    # Step 2 — Row lookup (read-only). The conditional UPDATE in step 4
    # is the concurrency gate; the SELECT serves only to surface the
    # invitation context (project_id, kind, role, bound email, ownership-
    # transfer flag) and to raise the spec/011 generic-invalid surface
    # for terminal-status / expired / missing rows BEFORE the atomic
    # UPDATE runs. The earlier ``SELECT ... FOR UPDATE`` was redundant
    # (and surplus-locking): per FR-011-106 step 2 the
    # ``UPDATE ... WHERE status='pending' AND expires_at > now()
    # RETURNING *`` itself is the single-statement compare-and-swap. A
    # parallel accept that loses the race finds zero rows returned from
    # the UPDATE and surfaces the generic-invalid path (Codex R1 P0-2).
    result = await session.execute(
        select(ProjectInvitation).where(
            ProjectInvitation.token_hash == token_hash,
        ),
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise InvitationTokenInvalidError("invitation not found")

    if project_id_scope is not None and invitation.project_id != project_id_scope:
        raise InvitationTokenInvalidError("invitation not found")

    if invitation.status != ProjectInvitationStatus.PENDING:
        raise InvitationTokenInvalidError("invitation not pending")

    invitation_expires_at = _ensure_utc(invitation.expires_at)
    if invitation_expires_at <= now_eff:
        raise InvitationTokenInvalidError("invitation has expired")

    # spec/011 R5 — defence in depth above the DB CHECK.
    if (
        invitation.ownership_transfer_on_accept
        and invitation.kind is not ProjectInvitationKind.MEMBER
    ):
        raise InvitationStateError(
            "ownership_transfer_on_accept_invalid_for_kind",
        )

    # Step 3 — bound-email match (FR-011-106 step 1 substep). The check
    # uses :func:`canonicalize_email` on both sides so a fullwidth or
    # combining-mark variant cannot bypass via Unicode normalisation
    # tricks. Mismatch is :class:`InvitationEmailMismatchError`; the
    # handler maps to the generic 404.
    if invitation.email is None:
        raise InvitationEmailMismatchError(
            "invitation row missing bound email",
        )
    if canonicalize_email(accepting_user_email) != canonicalize_email(
        invitation.email,
    ):
        raise InvitationEmailMismatchError(
            "current user's email does not match the invitation",
        )

    # Step 4 — atomic state flip (FR-011-106 step 2). Named placeholders
    # only; no string concatenation. The WHERE clause re-checks the
    # status + expiry so this single statement is the compare-and-swap
    # gate: any concurrent accept that wins the race leaves the row in
    # ``status='accepted'`` and our UPDATE matches zero rows. Likewise
    # an admin revoke landing between the SELECT above and this UPDATE
    # flips the row to ``revoked`` and we surface the generic-invalid
    # response. The lock duration is intentionally the UPDATE itself
    # (Postgres row-level write lock) — no separate ``SELECT FOR UPDATE``
    # is needed.
    update_stmt = text(
        """
        UPDATE project_invitations
           SET status = 'accepted',
               accepted_at = now(),
               updated_at = now()
         WHERE id = :invitation_id
           AND status = 'pending'
           AND expires_at > now()
        RETURNING id
        """
    )
    update_result = await session.execute(
        update_stmt,
        {"invitation_id": invitation.id},
    )
    if update_result.fetchone() is None:
        # Lost the atomicity race OR the row drifted to a terminal state
        # (e.g. an admin revoke landed concurrently). Generic-invalid per
        # FR-011-106. spec/011 step 7 R1 P0-1: callers performing user
        # creation + 2FA enrollment in the same TX MUST rollback the
        # whole transaction when this raises so no orphan account leaks.
        raise InvitationTokenInvalidError("invitation not found")

    # Re-attach the freshly-flipped row to the ORM identity map so
    # downstream consumers (audit emitter, response shaping) see the
    # accepted status without an additional SELECT.
    invitation.status = ProjectInvitationStatus.ACCEPTED
    invitation.accepted_at = now_eff

    # Step 5 — apply the grant.
    member: ProjectMember | None = None
    trusted_user: ProjectTrustedUser | None = None
    membership_created = False
    audit_action: str

    if invitation.kind is ProjectInvitationKind.MEMBER:
        if invitation.role is None:  # pragma: no cover — DB CHECK guards this
            raise InvitationValidationError(
                "Member invitation has NULL role (data corruption)",
            )
        # FR-011-106 step 3: existing-user branch — refuse if caller is
        # already a member at the same OR higher role. The role ordering
        # is VIEWER < MEMBER < ADMIN; ``_role_rank`` encapsulates the
        # comparison so the enum stays the single source of truth.
        existing = (
            await session.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == invitation.project_id,
                    ProjectMember.user_id == accepting_user_id,
                    ProjectMember.removed_at.is_(None),
                ),
            )
        ).scalar_one_or_none()
        if existing is not None:
            if _role_rank(existing.role) >= _role_rank(invitation.role):
                raise InvitationAlreadyMemberError(
                    "user already has an active membership at "
                    "the same or higher role",
                )
            # Lower-rank existing membership → upgrade in place. The
            # ``ux_project_members_active`` partial unique would
            # otherwise reject the INSERT below.
            existing.role = invitation.role
            existing.invited_by_id = invitation.invited_by_id
            member = existing
            membership_created = False
        else:
            member = ProjectMember(
                project_id=invitation.project_id,
                user_id=accepting_user_id,
                role=invitation.role,
                joined_at=now_eff,
                invited_by_id=invitation.invited_by_id,
            )
            session.add(member)
            membership_created = True
        audit_action = (
            AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP
            if is_new_user_signup
            else AUDIT_ACTION_MEMBER_INVITE_ACCEPTED
        )
    else:  # ProjectInvitationKind.TRUSTED
        if (
            invitation.granted_permissions is None
            or invitation.trusted_duration_seconds is None
        ):  # pragma: no cover — DB CHECK guards this
            raise InvitationValidationError(
                "Trusted invitation has NULL granted_permissions/duration "
                "(data corruption)",
            )
        valid_perms = coerce_granted_permissions(invitation.granted_permissions)
        trusted_expires_at = now_eff + timedelta(
            seconds=invitation.trusted_duration_seconds,
        )
        if trusted_expires_at - now_eff > timedelta(
            seconds=TRUSTED_MAX_DURATION_SECONDS,
        ):
            raise InvitationValidationError(
                "trusted_duration_seconds resolves past the FR-043 cap"
            )
        trusted_user = ProjectTrustedUser(
            project_id=invitation.project_id,
            user_id=accepting_user_id,
            invitation_id=invitation.id,
            granted_by_id=invitation.invited_by_id,
            granted_at=now_eff,
            expires_at=trusted_expires_at,
            status=ProjectTrustedStatus.ACTIVE,
            granted_permissions=sorted(p.value for p in valid_perms),
            email_at_invitation=invitation.email,
            email_at_invitation_hash=invitation.email_hash,
        )
        session.add(trusted_user)
        membership_created = True
        audit_action = AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED

    try:
        await session.flush()
    except IntegrityError as exc:
        # ``ux_project_trusted_users_active`` partial unique violation or
        # similar concurrent insert → surface as 409 conflict.
        raise InvitationConflictError(
            "concurrent grant already exists for this user/project",
        ) from exc

    return InvitationPublicAcceptOutcome(
        invitation=invitation,
        accepting_user_id=accepting_user_id,
        member=member,
        trusted_user=trusted_user,
        audit_action=audit_action,
        membership_created=membership_created,
        ownership_transferred=False,  # FR-011-123 SAVEPOINT lands in Phase 9
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )


# spec/011 FR-011-106 step 3 — role-rank helper. ProjectMemberRole is a
# StrEnum so direct enum comparison is unstable; the explicit table
# below documents the ordering once.
_ROLE_RANK: Final[dict[ProjectMemberRole, int]] = {
    ProjectMemberRole.VIEWER: 1,
    ProjectMemberRole.MEMBER: 2,
    ProjectMemberRole.ADMIN: 3,
}


def _role_rank(role: ProjectMemberRole) -> int:
    """Return the comparable integer rank for ``role`` (FR-011-106 step 3)."""
    return _ROLE_RANK.get(role, 0)


async def emit_public_invitation_accept_audit(
    outcome: InvitationPublicAcceptOutcome,
) -> None:
    """Write the spec/011 T208 audit row in a fresh session.

    Mirrors :func:`_write_invitation_audit` for the new public-token
    accept path. The emitter is a best-effort post-commit hook —
    failures are WARNING-logged so observability never undoes the
    persisted membership / overlay row (FR-088 soft-alert pattern).
    """
    invitation = outcome.invitation
    detail: dict[str, Any] = {
        "invitation_id": str(invitation.id),
        "kind": invitation.kind.value,
        "membership_created": outcome.membership_created,
        "ownership_transferred": outcome.ownership_transferred,
    }
    if outcome.member is not None:
        detail["member_id"] = str(outcome.member.id)
    if outcome.trusted_user is not None:
        detail["trusted_user_id"] = str(outcome.trusted_user.id)
    await _write_invitation_audit(
        action=outcome.audit_action,
        actor_user_id=outcome.accepting_user_id,
        project_id=invitation.project_id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail=detail,
        before={"status": ProjectInvitationStatus.PENDING.value},
        after={"status": invitation.status.value},
    )


# ---------------------------------------------------------------------------
# Public API: decline_invitation_by_recipient (T512 skeleton)
# ---------------------------------------------------------------------------


async def decline_invitation_by_recipient(
    session: AsyncSession,
    *,
    signed_token: str,
    current_user_id: UUID,
    current_user_email: str,
    hmac_secret: str,
    project_id_scope: UUID | None = None,
    now: datetime | None = None,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
) -> InvitationDeclineOutcome:
    """Recipient-driven self-decline (T512 skeleton).

    Mirrors :func:`accept_invitation` for HMAC verification + email match
    but transitions ``status`` to ``DECLINED`` instead. Idempotent: a
    second decline of the same row returns ``is_replay=True`` so the
    endpoint can return 204 either way.

    The full handler-side enumeration mapping (404 on email mismatch /
    token unknown / others' token, 410 on terminal states, 204 on pending
    + replay) lives in T512's endpoint layer; this service surfaces the
    distinct error classes so the handler can perform the mapping.
    """
    now_eff = now or datetime.now(UTC)

    raw_token_b64u, _ = verify_invitation_token(
        signed_token, hmac_secret=hmac_secret, now=now_eff,
    )
    token_hash = hash_token(raw_token_b64u)

    result = await session.execute(
        select(ProjectInvitation)
        .where(ProjectInvitation.token_hash == token_hash)
        .with_for_update(),
    )
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise InvitationTokenInvalidError("invitation not found")

    # Phase 10 Batch 2 Round 2 fix (致命 3): URL path ``project_id`` must
    # match the row. See :func:`accept_invitation` for the rationale.
    if project_id_scope is not None and invitation.project_id != project_id_scope:
        raise InvitationTokenInvalidError("invitation not found")

    if not _email_matches_invitation(
        current_user_email,
        invitation,
        hmac_secret=hmac_secret,
    ):
        raise InvitationEmailMismatchError(
            "current user's email does not match the invitation",
        )

    if invitation.status == ProjectInvitationStatus.DECLINED:
        # Idempotent replay path (FR-107).
        return InvitationDeclineOutcome(
            invitation=invitation,
            actor_user_id=current_user_id,
            is_replay=True,
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
        )
    if invitation.status != ProjectInvitationStatus.PENDING:
        raise InvitationStateError(
            f"invitation is in terminal state: {invitation.status.value}"
        )

    invitation.status = ProjectInvitationStatus.DECLINED
    invitation.declined_at = now_eff
    await session.flush()

    return InvitationDeclineOutcome(
        invitation=invitation,
        actor_user_id=current_user_id,
        is_replay=False,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Post-commit side effects (audit only — outbox-email enqueue removed in
# spec/011 step 6 / T054; FR-011-103 makes the issuing admin's HTTP
# response the sole exfil path for the plain-text invitation token)
# ---------------------------------------------------------------------------


async def trigger_post_commit_side_effects(
    outcome: InvitationCreateOutcome
    | InvitationAcceptOutcome
    | InvitationDeclineOutcome,
) -> None:
    """Fire audit side effects after the main TX commits.

    All side-effects are best-effort. Failures are WARNING-logged so
    observability does not undo the persisted invitation row.
    Three audit actions are emitted depending on the outcome type:

    * :class:`InvitationCreateOutcome` → ``project.invitation.create``
      (spec/011 step 6 / T054: the outbox-email enqueue is REMOVED — the
      plain-text envelope ``signed_token_envelope`` is surfaced to the
      issuing admin as the HTTP response's ``invitation_url`` field;
      it MUST NOT be persisted or telemetered past that single turn).
    * :class:`InvitationAcceptOutcome` → ``project.invitation.accept``.
    * :class:`InvitationDeclineOutcome` → ``project.invitation.decline``.
    """
    if isinstance(outcome, InvitationCreateOutcome):
        await _post_commit_create(outcome)
    elif isinstance(outcome, InvitationAcceptOutcome):
        await _post_commit_accept(outcome)
    elif isinstance(outcome, InvitationDeclineOutcome):
        await _post_commit_decline(outcome)
    else:  # pragma: no cover — exhaustive
        logger.warning(
            "trigger_post_commit_side_effects: unknown outcome type %r",
            type(outcome).__name__,
        )


async def _post_commit_create(outcome: InvitationCreateOutcome) -> None:
    # spec/011 Step 6 (T054): outbound-email enqueue removed. The audit
    # emit remains so existing observability tooling keeps surfacing the
    # invitation issuance event; the plain-text envelope is intentionally
    # NOT included in the audit detail (FR-011-102: token confidentiality).
    invitation = outcome.invitation
    detail: dict[str, Any] = {
        "invitation_id": str(invitation.id),
        "kind": invitation.kind.value,
        "expires_at": _ensure_utc(invitation.expires_at).isoformat(),
        "is_new": outcome.is_new,
    }
    await _write_invitation_audit(
        action="project.invitation.create",
        actor_user_id=outcome.actor_user_id,
        project_id=invitation.project_id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail=detail,
        before=None,
        after={"status": invitation.status.value},
    )


async def _post_commit_accept(outcome: InvitationAcceptOutcome) -> None:
    invitation = outcome.invitation
    detail: dict[str, Any] = {
        "invitation_id": str(invitation.id),
        "kind": invitation.kind.value,
        "is_replay": outcome.is_replay,
    }
    if outcome.member is not None:
        detail["member_id"] = str(outcome.member.id)
    if outcome.trusted_user is not None:
        detail["trusted_user_id"] = str(outcome.trusted_user.id)
    await _write_invitation_audit(
        action="project.invitation.accept",
        actor_user_id=outcome.actor_user_id,
        project_id=invitation.project_id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail=detail,
        before={"status": ProjectInvitationStatus.PENDING.value},
        after={"status": invitation.status.value},
    )


async def _post_commit_decline(outcome: InvitationDeclineOutcome) -> None:
    invitation = outcome.invitation
    detail: dict[str, Any] = {
        "invitation_id": str(invitation.id),
        "kind": invitation.kind.value,
        "is_replay": outcome.is_replay,
    }
    await _write_invitation_audit(
        action="project.invitation.decline",
        actor_user_id=outcome.actor_user_id,
        project_id=invitation.project_id,
        request_id=outcome.request_id,
        ip=outcome.ip,
        user_agent=outcome.user_agent,
        detail=detail,
        before={"status": ProjectInvitationStatus.PENDING.value},
        after={"status": invitation.status.value},
    )


async def _write_invitation_audit(
    *,
    action: str,
    actor_user_id: UUID,
    project_id: UUID,
    request_id: str,
    ip: str,
    user_agent: str,
    detail: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """Append a project_audit_log row in a *fresh* session.

    A fresh session is required because the audit writer issues
    ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` (FR-093), which
    PostgreSQL rejects on a session that has already issued statements.
    """
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                service = AuditLogService(audit_session)
                await service.write_project_event(
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                    action=action,
                    request_id=request_id,
                    ip=ip,
                    user_agent=user_agent,
                    detail=detail,
                    before=before,
                    after=after,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert
        logger.warning(
            "%s audit write failed (FR-088 soft alert): "
            "actor=%s project=%s detail=%r error=%r",
            action,
            actor_user_id,
            project_id,
            detail,
            exc,
        )


# spec/011 Step 6 (T054): ``_enqueue_invitation_email`` removed. The
# Resend / SMTP outbox path is gone; FR-011-103 makes the issuing admin's
# HTTP response the sole exfil channel for the plain-text invitation
# token. Future maintainers: do NOT re-introduce an outbox-enqueue path
# here — every helper in ``services/email.py`` is a no-op stub as of
# Step 2 and the destructive migration ``0022`` removes the supporting
# tables entirely.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_existing_grant(
    session: AsyncSession,
    invitation: ProjectInvitation,
    current_user_id: UUID,
) -> tuple[ProjectMember | None, ProjectTrustedUser | None]:
    """Fetch the downstream grant row created by a prior accept."""
    member: ProjectMember | None = None
    trusted_user: ProjectTrustedUser | None = None
    if invitation.kind is ProjectInvitationKind.MEMBER:
        member_result = await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == invitation.project_id,
                ProjectMember.user_id == current_user_id,
                ProjectMember.removed_at.is_(None),
            ),
        )
        member = member_result.scalar_one_or_none()
    else:
        trusted_result = await session.execute(
            select(ProjectTrustedUser).where(
                ProjectTrustedUser.invitation_id == invitation.id,
                ProjectTrustedUser.user_id == current_user_id,
            ),
        )
        trusted_user = trusted_result.scalar_one_or_none()
    return member, trusted_user


__all__ = [
    "AUDIT_ACTION_MEMBER_INVITE_ACCEPTED",
    "AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP",
    "AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED",
    "INVITATION_MAX_TTL_SECONDS",
    "INVITATION_TTL_SECONDS",
    "InvitationAcceptOutcome",
    "InvitationAlreadyMemberError",
    "InvitationConflictError",
    "InvitationCreateOutcome",
    "InvitationDeclineOutcome",
    "InvitationEmailMismatchError",
    "InvitationError",
    "InvitationInfraUnavailableError",
    "InvitationPublicAcceptOutcome",
    "InvitationRateLimitError",
    "InvitationResolveOutcome",
    "InvitationStateError",
    "InvitationTokenInvalidError",
    "InvitationValidationError",
    "RATE_LIMIT_ACTOR_PER_HOUR",
    "RATE_LIMIT_PROJECT_PER_HOUR",
    "TOKEN_BYTES",
    "TRUSTED_DEFAULT_DURATION_SECONDS",
    "TRUSTED_MAX_DURATION_SECONDS",
    "accept_invitation",
    "accept_invitation_via_public_token",
    "canonicalize_email",
    "check_rate_limits",
    "coerce_granted_permissions",
    "create_invitation",
    "decline_invitation_by_recipient",
    "emit_public_invitation_accept_audit",
    "hash_email",
    "hash_email_dual",
    "hash_token",
    "resolve_invitation_for_public_token",
    "sign_invitation_token",
    "trigger_post_commit_side_effects",
    "verify_invitation_token",
]
