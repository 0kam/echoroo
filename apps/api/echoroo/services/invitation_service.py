"""Project invitation service (Phase 10 / T502, FR-047 / FR-048 / FR-051..056).

This module owns issuance and consumption of :class:`ProjectInvitation`
rows for both ``kind='member'`` and ``kind='trusted'`` invitations. Audit
+ email side-effects are deliberately deferred to **after** the main
transaction commits (mirrors :mod:`echoroo.services.license_service` and
:mod:`echoroo.services.restricted_config_service`):

1. ``await create_invitation(...)`` / ``accept_invitation(...)`` /
   ``decline_invitation_by_recipient(...)`` flushes the row mutation and
   returns an outcome dataclass.
2. The endpoint commits its main transaction.
3. The endpoint calls ``trigger_post_commit_side_effects(outcome)`` which
   writes the audit row in a fresh session (FR-093 SERIALIZABLE contract)
   and enqueues the email notification through the outbox. Failures here
   are WARNING-logged only — the persisted invitation row is the
   security-critical bit; observability is secondary.

Token shape (FR-051 / FR-052):

* The raw 256-bit token is generated with :func:`secrets.token_bytes`,
  base64url-encoded for the URL.
* The DB row stores the **SHA-256 hex digest** in ``token_hash`` so an
  attacker who reads the table cannot forge a redeem URL.
* The URL token sent in email is an HMAC-SHA-256 envelope::

      {raw_token_b64u}.{expires_at_unix}.{mac_b64u}

  MAC = ``HMAC-SHA-256(web_session_secret, raw_token_b64u || "." || expires)``.
  Verification is constant-time (:func:`hmac.compare_digest`).

Plain-text token confidentiality (FR-051):

* The raw / signed token is **only** carried inside the internal
  :class:`InvitationMailPayload` attached to :class:`InvitationCreateOutcome`
  and is consumed solely by :func:`trigger_post_commit_side_effects` when
  enqueuing the outbound email. The handler / API response layer must
  surface the **safe subset** (``invitation_id``, ``email``, ``expires_at``,
  ``status``) — never the plain token.

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
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.permissions import (
    TRUSTED_ALLOWED_PERMISSIONS,
    Permission,
)
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
    ProjectTrustedStatus,
)
from echoroo.models.project import ProjectInvitation, ProjectMember
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.services import outbox_service
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

#: Outbox event-type discriminator for invitation emails.
_OUTBOX_EVENT_INVITATION_EMAIL: str = "project.invitation.email"


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


# ---------------------------------------------------------------------------
# Outcomes (the values endpoints need for post-commit side effects)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvitationMailPayload:
    """Internal-only carrier for the plain-text invitation token (FR-051).

    Constructed by :func:`create_invitation` and consumed exclusively by
    :func:`trigger_post_commit_side_effects` when enqueuing the email.
    The handler / API response MUST NOT surface these fields.
    """

    raw_token_b64u: str
    signed_token: str
    recipient_email: str
    invitation_id: UUID
    project_id: UUID
    kind: ProjectInvitationKind
    expires_at: datetime


@dataclass(frozen=True)
class InvitationCreateOutcome:
    """Snapshot returned by :func:`create_invitation`.

    Plain-text token confidentiality (FR-051):

    * ``mail_payload`` carries the raw / signed token but is **internal
      only** — :func:`trigger_post_commit_side_effects` consumes it for
      the email outbox enqueue and the field is never serialised back to
      the API caller.
    * The endpoint surfaces the safe subset (``invitation``,
      ``actor_user_id``) into a Pydantic response that excludes the token
      entirely.

    Other fields:
        invitation: The freshly-flushed (not committed) invitation row.
        actor_user_id: User who issued the invitation (audit + email).
        request_id / ip / user_agent: Audit-row plumbing.
        is_new: ``False`` when the row was a duplicate idempotent return
            (no email should be sent). Currently always ``True``; reserved
            for future deduplication of duplicate retries.
    """

    invitation: ProjectInvitation
    actor_user_id: UUID
    mail_payload: InvitationMailPayload
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


def hash_email(email: str, *, hmac_secret: str) -> str:
    """Return the canonical ``email_hash`` value.

    The hash is keyed (HMAC-SHA-256) so an attacker who dumps the table
    cannot derive emails by precomputing rainbow tables. The ``email``
    is NFKC + casefolded first so two visually-identical addresses
    collide (FR-054 / FR-055).
    """
    canonical = unicodedata.normalize("NFKC", email).strip().casefold().encode("utf-8")
    return hmac.new(hmac_secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


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


def _mac_invitation_token(
    *,
    raw_token_b64u: str,
    expires_at_unix: int,
    hmac_secret: str,
) -> str:
    payload = f"{raw_token_b64u}.{expires_at_unix}".encode("ascii")
    mac = hmac.new(hmac_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _b64u_encode(mac)


def sign_invitation_token(
    *,
    raw_token_b64u: str,
    expires_at: datetime,
    hmac_secret: str,
) -> str:
    """Produce the URL-safe ``{token}.{exp}.{mac}`` envelope (FR-052)."""
    expires_at_unix = int(_ensure_utc(expires_at).timestamp())
    mac = _mac_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at_unix=expires_at_unix,
        hmac_secret=hmac_secret,
    )
    return f"{raw_token_b64u}.{expires_at_unix}.{mac}"


def verify_invitation_token(
    signed_token: str,
    *,
    hmac_secret: str,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Decode and verify a signed invitation token.

    Returns ``(raw_token_b64u, expires_at)`` on success.
    Raises :class:`InvitationTokenInvalidError` on any failure (missing
    parts, malformed mac, mac mismatch, expiry past). The error class is
    deliberately narrow so the endpoint can map every signal to the same
    HTTP 410 response (FR-055 enumeration mitigation).
    """
    parts = signed_token.split(".")
    if len(parts) != 3:
        raise InvitationTokenInvalidError("malformed invitation token")
    raw_token_b64u, expires_at_str, mac_b64u = parts

    try:
        expires_at_unix = int(expires_at_str)
    except ValueError as exc:
        raise InvitationTokenInvalidError("invalid expiry component") from exc

    expected_mac = _mac_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at_unix=expires_at_unix,
        hmac_secret=hmac_secret,
    )
    if not hmac.compare_digest(expected_mac, mac_b64u):
        raise InvitationTokenInvalidError("invitation token signature mismatch")

    expires_at = datetime.fromtimestamp(expires_at_unix, tz=UTC)
    if (now or datetime.now(UTC)) >= expires_at:
        raise InvitationTokenInvalidError("invitation token has expired")

    return raw_token_b64u, expires_at


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
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
    now: datetime | None = None,
) -> InvitationCreateOutcome:
    """Issue a Member or Trusted invitation, returning a signed URL token.

    Steps:

    1. Validate the kind × payload combination (FR-048 mirrored at the
       application layer so we can raise structured errors before the DB
       check kicks in).
    2. ``check_rate_limits`` — FR-056 (fail-closed; Redis required).
    3. Generate the 256-bit raw token, compute ``token_hash`` (FR-051) and
       the HMAC-signed URL token (FR-052). The plain-text envelope is
       attached to :class:`InvitationMailPayload` and is **never** placed
       on the response-bound part of the outcome.
    4. Insert the row inside the caller's transaction. Caller commits.
       Post-commit, the handler calls
       :func:`trigger_post_commit_side_effects` which consumes the
       mail payload to enqueue the outbound email.

    Args:
        session: Caller-owned async session. Caller commits.
        project_id: Target project.
        kind: Invitation kind discriminator.
        email: Plain-text recipient email; ``email_hash`` is computed here.
        invited_by_id: Owner / Admin issuing the invitation.
        hmac_secret: HMAC key for token signature + email hash. Pass
            ``settings.web_session_secret`` from the endpoint.
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
        request_id / ip / user_agent: Audit plumbing (passed through to
            the outcome dataclass; the writer hashes them later).
        now: Override for ``datetime.now(UTC)`` — testing only.

    Returns:
        :class:`InvitationCreateOutcome` carrying the row + the
        internal-only :class:`InvitationMailPayload`. The handler MUST
        return only the safe subset to the API caller.

    Raises:
        InvitationValidationError: Bad payload combination or TTL > 7 d.
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

    # 4. Insert (caller-owned TX). The (project_id, email_hash) WHERE
    # status='pending' partial unique index is the FR-049 guard; collisions
    # surface as IntegrityError, which we map to InvitationConflictError.
    invitation = ProjectInvitation(
        project_id=project_id,
        kind=kind,
        email=email,
        email_hash=email_hash_value,
        role=role if kind is ProjectInvitationKind.MEMBER else None,
        granted_permissions=granted_perms_db,
        trusted_duration_seconds=duration_db,
        token_hash=token_hash,
        invited_by_id=invited_by_id,
        expires_at=expires_at,
        status=ProjectInvitationStatus.PENDING,
    )
    session.add(invitation)
    try:
        await session.flush()
    except IntegrityError as exc:
        # The endpoint will rollback; surface a typed error so the audit
        # log records the reason without leaking stack traces.
        raise InvitationConflictError(
            "an equivalent pending invitation already exists",
        ) from exc

    mail_payload = InvitationMailPayload(
        raw_token_b64u=raw_token_b64u,
        signed_token=signed_token,
        recipient_email=email,
        invitation_id=invitation.id,
        project_id=project_id,
        kind=kind,
        expires_at=expires_at,
    )

    return InvitationCreateOutcome(
        invitation=invitation,
        actor_user_id=invited_by_id,
        mail_payload=mail_payload,
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

    # The signed expiry is the source of truth for the URL; the row's
    # expires_at is an additional guard. Reject if either failed.
    invitation_expires_at = _ensure_utc(invitation.expires_at)
    if invitation_expires_at <= now_eff:
        raise InvitationTokenInvalidError("invitation has expired")

    # 4. Email match (FR-054). The signed token already authenticates the
    # *URL*; this step authenticates the *recipient* against the URL.
    # Performed before the status check so an attacker holding a stolen
    # accepted-token never learns the invitation status.
    expected_hash = hash_email(current_user_email, hmac_secret=hmac_secret)
    if not hmac.compare_digest(expected_hash, invitation.email_hash):
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
# Public API: decline_invitation_by_recipient (T512 skeleton)
# ---------------------------------------------------------------------------


async def decline_invitation_by_recipient(
    session: AsyncSession,
    *,
    signed_token: str,
    current_user_id: UUID,
    current_user_email: str,
    hmac_secret: str,
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

    expected_hash = hash_email(current_user_email, hmac_secret=hmac_secret)
    if not hmac.compare_digest(expected_hash, invitation.email_hash):
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
# Post-commit side effects (audit + email outbox)
# ---------------------------------------------------------------------------


async def trigger_post_commit_side_effects(
    outcome: InvitationCreateOutcome
    | InvitationAcceptOutcome
    | InvitationDeclineOutcome,
) -> None:
    """Fire audit + email-outbox side effects after the main TX commits.

    All side-effects are best-effort. Failures are WARNING-logged so
    observability does not undo the persisted invitation row.
    Two distinct audit actions are emitted depending on the outcome
    type:

    * :class:`InvitationCreateOutcome` → ``project.invitation.create``
      and an ``project.invitation.email`` outbox row carrying the
      *internal-only* :class:`InvitationMailPayload` (FR-051: plain-text
      token leaves the API process **only** through this enqueue path).
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
    if outcome.is_new:
        await _enqueue_invitation_email(outcome)


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


async def _enqueue_invitation_email(outcome: InvitationCreateOutcome) -> None:
    """Enqueue the outbound invitation email through the outbox table.

    The outbox row carries the internal :class:`InvitationMailPayload`;
    the worker that materialises the email body (T514 follow-up) is the
    *only* code-path that touches the plain-text token after this point.
    Failures here are WARNING-logged — the invitation row is already
    committed and the operator can re-issue if the email never arrives.
    """
    payload = outcome.mail_payload
    body: dict[str, Any] = {
        "invitation_id": str(payload.invitation_id),
        "project_id": str(payload.project_id),
        "kind": payload.kind.value,
        "recipient_email": payload.recipient_email,
        "expires_at": _ensure_utc(payload.expires_at).isoformat(),
        "raw_token_b64u": payload.raw_token_b64u,
        "signed_token": payload.signed_token,
    }
    idempotency_key = f"invitation_email:{payload.invitation_id}"
    try:
        async with AsyncSessionLocal() as outbox_session:
            try:
                await outbox_service.enqueue(
                    outbox_session,
                    event_type=_OUTBOX_EVENT_INVITATION_EMAIL,
                    payload=body,
                    idempotency_key=idempotency_key,
                )
                await outbox_session.commit()
            except Exception:
                await outbox_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert
        logger.warning(
            "invitation email enqueue failed (FR-088 soft alert): "
            "invitation_id=%s error=%r",
            payload.invitation_id,
            exc,
        )


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
    "INVITATION_MAX_TTL_SECONDS",
    "INVITATION_TTL_SECONDS",
    "InvitationAcceptOutcome",
    "InvitationConflictError",
    "InvitationCreateOutcome",
    "InvitationDeclineOutcome",
    "InvitationEmailMismatchError",
    "InvitationError",
    "InvitationInfraUnavailableError",
    "InvitationMailPayload",
    "InvitationRateLimitError",
    "InvitationStateError",
    "InvitationTokenInvalidError",
    "InvitationValidationError",
    "RATE_LIMIT_ACTOR_PER_HOUR",
    "RATE_LIMIT_PROJECT_PER_HOUR",
    "TOKEN_BYTES",
    "TRUSTED_DEFAULT_DURATION_SECONDS",
    "TRUSTED_MAX_DURATION_SECONDS",
    "accept_invitation",
    "check_rate_limits",
    "coerce_granted_permissions",
    "create_invitation",
    "decline_invitation_by_recipient",
    "hash_email",
    "hash_token",
    "sign_invitation_token",
    "trigger_post_commit_side_effects",
    "verify_invitation_token",
]
