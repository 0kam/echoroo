"""Authentication token primitives for 006-permissions-redesign.

This module is the single source of truth for JWT access / refresh token
issuance and verification, and for the ``security_stamp``-based session
revocation mechanism described in data-model §3.1 and plan.md §Auth.

Scope (Phase 2.5, T060a-T060c):

* ``issue_access_token`` / ``verify_access_token``
    JWT access tokens, 15-minute lifetime (FR-055). Claims include the
    user's current ``security_stamp`` so that bumping the stamp
    immediately invalidates every previously-issued access token without
    any server-side bookkeeping.

* ``issue_refresh_token`` / ``rotate_refresh_token``
    Refresh tokens are one-time-use. Every rotation preserves the token
    ``family`` id so that if the SAME jti is ever presented twice, the
    entire family is revoked (FR-055 / FR-071 replay detection).

* ``revoke_family`` / ``invalidate_stamp``
    Helpers the surrounding services (auth_service, password reset,
    logout, superuser revoke) call to kill sessions wholesale.

Design choices:

* No database access from this module — callers hold the
  ``AsyncSession`` and a :class:`TokenStore` implementation, and we call
  thin, typed methods on those. The middleware in Phase 2.6 wires these
  against real Redis + Postgres. Tests use the in-memory store below.
* JWT signing uses HS256 with ``settings.JWT_SECRET_KEY``. Moving to
  KMS-signed JWTs is out of scope — the data-model does not require it,
  and HS256 with a rotated secret is adequate for first-party sessions.
* ``security_stamp`` is intentionally carried in every access token so
  verification can reject stale tokens without a DB round-trip (the
  middleware compares the claim to a cached-per-user current stamp).
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast
from uuid import UUID

import jwt

from echoroo.core.settings import get_settings

settings = get_settings()


# =============================================================================
# Constants
# =============================================================================

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"
MEDIA_TOKEN_TYPE = "media"
MEDIA_TOKEN_TYP = "echoroo.media"

MediaTokenScope = Literal["audio", "playback", "spectrogram", "download"]
MEDIA_TOKEN_SCOPES: frozenset[str] = frozenset(
    {"audio", "playback", "spectrogram", "download"}
)

MediaResourceType = Literal["recording", "clip", "search_session"]
"""The kind of resource a media token is bound to.

W2-4 generalises the scoped media token so it can address a whole recording,
a single clip within a recording, or a persisted reference-audio source of a
search session. The ``search_session`` variant streams one entry of the
session's ``reference_audio_keys`` list, addressed by ``source_index``.
"""
MEDIA_RESOURCE_TYPES: frozenset[str] = frozenset(
    {"recording", "clip", "search_session"}
)

DEFAULT_ACCESS_TTL = timedelta(minutes=15)
"""FR-055: access tokens are short-lived (15 minutes)."""

DEFAULT_MEDIA_TTL = DEFAULT_ACCESS_TTL
"""Scoped media URL tokens match access-token TTL while limiting path scope."""


# =============================================================================
# Data containers
# =============================================================================


@dataclass(frozen=True)
class AccessTokenClaims:
    """Decoded access-token claims, returned by ``verify_access_token``.

    Attributes:
        user_id: Subject user id (``sub`` claim, parsed to UUID).
        security_stamp: The user's ``security_stamp`` as it was at
            issuance. Callers MUST compare against the current DB value
            to detect session revocation.
        jti: Unique token id.
        expires_at: Expiration timestamp as tz-aware UTC datetime.
    """

    user_id: UUID
    security_stamp: str
    jti: str
    expires_at: datetime


@dataclass(frozen=True)
class RefreshTokenClaims:
    """Decoded refresh-token claims, produced internally by rotate."""

    user_id: UUID
    family_id: str
    jti: str
    expires_at: datetime


@dataclass(frozen=True)
class MediaTokenClaims:
    """Decoded scoped media-token claims.

    ``resource_type`` + ``resource_id`` identify the addressed media resource
    (a recording, a clip within one, or a search session). ``project_id``
    still scopes the token to a single project so a token can never leak
    across project boundaries. ``parent_id`` binds a clip token to its parent
    recording so the token cannot be replayed under a different recording path
    segment. ``source_index`` binds a ``search_session`` token to one entry of
    the session's ``reference_audio_keys`` list so it cannot be replayed for a
    different source index.
    """

    user_id: UUID
    security_stamp: str
    project_id: UUID
    resource_type: MediaResourceType
    resource_id: UUID
    scope: MediaTokenScope
    jti: str
    expires_at: datetime
    parent_id: UUID | None = None
    source_index: int | None = None


@dataclass(frozen=True)
class RefreshTokenRecord:
    """Server-side bookkeeping shape for a newly-issued refresh token.

    The caller (auth_service) persists this into whatever
    :class:`TokenStore` implementation is wired for the current runtime
    environment. The record is deliberately minimal — no PII — so the
    persistence tier can be any KV or DB.
    """

    jti: str
    family_id: str
    user_id: UUID
    issued_at: datetime
    expires_at: datetime


# =============================================================================
# Exceptions
# =============================================================================


class AuthTokenError(Exception):
    """Base class for all token verification failures."""


class InvalidTokenError(AuthTokenError):
    """Token signature / structure is invalid or expired."""


class StaleTokenError(AuthTokenError):
    """Token was once valid but its security_stamp is no longer current."""


class ReusedTokenError(AuthTokenError):
    """Refresh token was already consumed — replay attack suspected."""


class RevokedFamilyError(AuthTokenError):
    """Entire refresh-token family has been revoked."""


# =============================================================================
# TokenStore protocol
# =============================================================================


class TokenStore(Protocol):
    """Persistence interface for refresh-token rotation state.

    The production implementation (Phase 2.6) will be backed by Redis.
    Tests use :class:`InMemoryTokenStore` below.

    Every method is async so that the Redis-backed implementation can
    issue non-blocking I/O without forcing the in-memory test double to
    care.
    """

    async def get_family_state(self, family_id: str) -> dict[str, Any] | None:
        """Return persisted state for a token family, or ``None``.

        The state dict must at minimum contain ``revoked`` (bool) and
        ``consumed_jtis`` (iterable of str).
        """
        ...

    async def record_issued(self, record: RefreshTokenRecord) -> None:
        """Persist metadata for a newly-issued refresh token."""
        ...

    async def mark_consumed(self, family_id: str, jti: str) -> None:
        """Mark ``jti`` as consumed within ``family_id``.

        Idempotent. Later calls to ``is_consumed`` return True.
        """
        ...

    async def is_consumed(self, family_id: str, jti: str) -> bool:
        """Return True if ``jti`` was previously marked consumed."""
        ...

    async def revoke_family(self, family_id: str) -> None:
        """Mark an entire family as revoked."""
        ...

    async def is_family_revoked(self, family_id: str) -> bool:
        """Return True if ``family_id`` is revoked."""
        ...

    async def atomic_consume_and_issue(
        self, *, family_id: str, old_jti: str, new_record: RefreshTokenRecord
    ) -> bool:
        """Atomically: check old jti is unconsumed, mark it, persist new record.

        Returns ``True`` if the swap committed (the caller may safely
        return the ``new_record``'s minted token to the client). Returns
        ``False`` if ``old_jti`` was already consumed — concurrent
        rotation lost the race; the caller MUST treat this as reuse and
        revoke the family.

        Implementations MUST execute the consumption + issue in a single
        critical section (lock, transaction, or ``UPDATE ... WHERE
        consumed_at IS NULL RETURNING id``) so that two concurrent
        callers cannot both observe ``is_consumed == False`` and both
        proceed to issue successor tokens.
        """
        ...


class InMemoryTokenStore:
    """Reference TokenStore implementation for tests and dev.

    Not thread-safe (callers are expected to use it inside a single
    pytest-asyncio event loop). Production code MUST use the Redis-backed
    implementation wired in Phase 2.6.
    """

    def __init__(self) -> None:
        self._families: dict[str, dict[str, Any]] = {}
        # Single asyncio.Lock guards the whole store so that the
        # atomic_consume_and_issue critical section is serialised across
        # concurrent coroutines on the same loop. The chosen granularity
        # (process-wide rather than per-family) is acceptable for tests
        # and dev — production uses Redis with per-family locking.
        self._lock = asyncio.Lock()

    def _ensure(self, family_id: str) -> dict[str, Any]:
        state = self._families.get(family_id)
        if state is None:
            state = {"revoked": False, "consumed_jtis": set(), "records": []}
            self._families[family_id] = state
        return state

    async def get_family_state(self, family_id: str) -> dict[str, Any] | None:
        state = self._families.get(family_id)
        if state is None:
            return None
        # Return a stable copy snapshot to protect internal state from callers.
        return {
            "revoked": bool(state["revoked"]),
            "consumed_jtis": set(state["consumed_jtis"]),
        }

    async def record_issued(self, record: RefreshTokenRecord) -> None:
        state = self._ensure(record.family_id)
        state["records"].append(record)

    async def mark_consumed(self, family_id: str, jti: str) -> None:
        state = self._ensure(family_id)
        state["consumed_jtis"].add(jti)

    async def is_consumed(self, family_id: str, jti: str) -> bool:
        state = self._families.get(family_id)
        if state is None:
            return False
        return jti in state["consumed_jtis"]

    async def revoke_family(self, family_id: str) -> None:
        state = self._ensure(family_id)
        state["revoked"] = True

    async def is_family_revoked(self, family_id: str) -> bool:
        state = self._families.get(family_id)
        if state is None:
            return False
        return bool(state["revoked"])

    async def atomic_consume_and_issue(
        self, *, family_id: str, old_jti: str, new_record: RefreshTokenRecord
    ) -> bool:
        """Single-lock implementation of the atomic swap.

        Holds :attr:`_lock` for the duration of the check + mutation so
        two concurrent rotation calls on the same store cannot both pass
        the "is consumed?" check.
        """
        async with self._lock:
            state = self._ensure(family_id)
            if old_jti in state["consumed_jtis"]:
                return False
            state["consumed_jtis"].add(old_jti)
            state["records"].append(new_record)
            return True


class SqlTokenStore:
    """SQL-backed :class:`TokenStore` (Phase 2.11 P0-d).

    Backed by the ``refresh_tokens`` and ``token_families`` tables that
    migration ``0002_refresh_token_storage`` creates. The atomic
    primitive uses PostgreSQL's row-level lock via
    ``UPDATE refresh_tokens SET consumed_at = NOW() WHERE jti = :old
    AND consumed_at IS NULL RETURNING jti``: only one concurrent caller
    can flip ``consumed_at`` from NULL to a non-NULL value, so two
    simultaneous rotations cannot both observe the row as
    "unconsumed". The losing caller treats the empty RETURNING as a
    reuse signal and revokes the family.

    Phase 3 owns the FastAPI / Celery wiring that calls this class —
    we deliberately do NOT touch ``main.py`` here.

    Args:
        session_factory: A zero-arg callable returning an
            :class:`sqlalchemy.ext.asyncio.AsyncSession` instance.
            Typically passed as ``echoroo.core.database.AsyncSessionLocal``.
            Each method opens its own short-lived session so the store
            does not pin a connection between calls.
    """

    def __init__(self, session_factory: Any) -> None:
        # Type: ``Callable[[], AsyncSession]``. Kept as ``Any`` to avoid
        # forcing a SQLAlchemy import on modules that just want the type.
        self._session_factory = session_factory

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _to_uuid(value: str) -> UUID:
        """Coerce string family_id / jti to UUID for asyncpg binding."""
        if isinstance(value, UUID):
            return value
        return UUID(value)

    # -- TokenStore protocol ---------------------------------------------

    async def get_family_state(self, family_id: str) -> dict[str, Any] | None:
        """Return ``{"revoked", "consumed_jtis"}`` for the family, or None."""
        # Local import to keep module-level import surface minimal — only
        # SqlTokenStore consumers need SQLAlchemy.
        from sqlalchemy import text

        family_uuid = self._to_uuid(family_id)
        async with self._session_factory() as session:
            family_row = await session.execute(
                text(
                    "SELECT family_id, revoked_at FROM token_families "
                    "WHERE family_id = :family_id"
                ),
                {"family_id": family_uuid},
            )
            family = family_row.mappings().first()
            if family is None:
                return None
            consumed_rows = await session.execute(
                text(
                    "SELECT jti FROM refresh_tokens "
                    "WHERE family_id = :family_id AND consumed_at IS NOT NULL"
                ),
                {"family_id": family_uuid},
            )
            consumed = {str(r["jti"]) for r in consumed_rows.mappings().all()}
            return {
                "revoked": family["revoked_at"] is not None,
                "consumed_jtis": consumed,
            }

    async def record_issued(self, record: RefreshTokenRecord) -> None:
        """INSERT ``record`` into ``refresh_tokens`` (creates the family if absent).

        Used on initial login (no prior token) — every rotation goes
        through :meth:`atomic_consume_and_issue` instead so the new
        record + the swap commit together.
        """
        from sqlalchemy import text

        family_uuid = self._to_uuid(record.family_id)
        jti_uuid = self._to_uuid(record.jti)
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO token_families (family_id, user_id, created_at) "
                    "VALUES (:family_id, :user_id, :created_at) "
                    "ON CONFLICT (family_id) DO NOTHING"
                ),
                {
                    "family_id": family_uuid,
                    "user_id": record.user_id,
                    "created_at": record.issued_at,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO refresh_tokens "
                    "(jti, user_id, family_id, issued_at, expires_at) "
                    "VALUES (:jti, :user_id, :family_id, :issued_at, :expires_at)"
                ),
                {
                    "jti": jti_uuid,
                    "user_id": record.user_id,
                    "family_id": family_uuid,
                    "issued_at": record.issued_at,
                    "expires_at": record.expires_at,
                },
            )

    async def mark_consumed(self, family_id: str, jti: str) -> None:
        """Flip ``consumed_at`` for one token (idempotent).

        :meth:`atomic_consume_and_issue` is the preferred path — this
        method exists for completeness and for tools that need to
        invalidate a single token without rotating to a successor.
        """
        from sqlalchemy import text

        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE refresh_tokens SET consumed_at = COALESCE(consumed_at, now()) "
                    "WHERE jti = :jti AND family_id = :family_id"
                ),
                {
                    "jti": self._to_uuid(jti),
                    "family_id": self._to_uuid(family_id),
                },
            )

    async def is_consumed(self, family_id: str, jti: str) -> bool:
        """SELECT ``consumed_at IS NOT NULL`` for a single (family, jti)."""
        from sqlalchemy import text

        async with self._session_factory() as session:
            row = await session.execute(
                text(
                    "SELECT consumed_at FROM refresh_tokens "
                    "WHERE jti = :jti AND family_id = :family_id"
                ),
                {
                    "jti": self._to_uuid(jti),
                    "family_id": self._to_uuid(family_id),
                },
            )
            first = row.mappings().first()
            if first is None:
                return False
            return first["consumed_at"] is not None

    async def revoke_family(self, family_id: str) -> None:
        """Set ``revoked_at`` on every member of the family (idempotent)."""
        from sqlalchemy import text

        family_uuid = self._to_uuid(family_id)
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE token_families "
                    "SET revoked_at = COALESCE(revoked_at, now()) "
                    "WHERE family_id = :family_id"
                ),
                {"family_id": family_uuid},
            )
            await session.execute(
                text(
                    "UPDATE refresh_tokens "
                    "SET revoked_at = COALESCE(revoked_at, now()) "
                    "WHERE family_id = :family_id AND revoked_at IS NULL"
                ),
                {"family_id": family_uuid},
            )

    async def is_family_revoked(self, family_id: str) -> bool:
        """SELECT ``revoked_at IS NOT NULL`` on the family row."""
        from sqlalchemy import text

        async with self._session_factory() as session:
            row = await session.execute(
                text(
                    "SELECT revoked_at FROM token_families "
                    "WHERE family_id = :family_id"
                ),
                {"family_id": self._to_uuid(family_id)},
            )
            first = row.mappings().first()
            if first is None:
                # No row = treat as not revoked. The caller has to
                # mint the family on first use via record_issued /
                # atomic_consume_and_issue.
                return False
            return first["revoked_at"] is not None

    async def atomic_consume_and_issue(
        self, *, family_id: str, old_jti: str, new_record: RefreshTokenRecord
    ) -> bool:
        """Atomic rotate: consume ``old_jti``, INSERT ``new_record``, commit.

        SQL semantics (PostgreSQL):

            UPDATE refresh_tokens
               SET consumed_at = now()
             WHERE jti = :old_jti
               AND family_id = :family_id
               AND consumed_at IS NULL
            RETURNING jti;

        Only one concurrent caller can flip ``consumed_at`` from NULL
        to a value because PostgreSQL takes a row-level lock during
        the UPDATE. The losing caller's RETURNING is empty -> we
        treat that as reuse and return ``False`` (the caller must
        revoke the family).

        On success we INSERT the new record in the SAME transaction so
        the visible state always advances "old consumed + new issued"
        atomically.
        """
        from sqlalchemy import text

        family_uuid = self._to_uuid(family_id)
        old_jti_uuid = self._to_uuid(old_jti)
        new_jti_uuid = self._to_uuid(new_record.jti)

        async with self._session_factory() as session, session.begin():
            # Step 1: atomic compare-and-swap on consumed_at.
            consume_result = await session.execute(
                text(
                    "UPDATE refresh_tokens "
                    "SET consumed_at = now() "
                    "WHERE jti = :old_jti "
                    "  AND family_id = :family_id "
                    "  AND consumed_at IS NULL "
                    "RETURNING jti"
                ),
                {"old_jti": old_jti_uuid, "family_id": family_uuid},
            )
            consumed_jti = consume_result.scalar()
            if consumed_jti is None:
                # Lost the race — either the row never existed, the
                # token was already consumed, or the family is gone.
                # Returning False signals "treat as reuse" to the
                # rotation flow.
                return False

            # Step 2: INSERT the successor in the same TX. The (family_id,
            # jti) UNIQUE index guards against duplicate inserts under
            # bizarre clock-skew scenarios.
            await session.execute(
                text(
                    "INSERT INTO refresh_tokens "
                    "(jti, user_id, family_id, issued_at, expires_at) "
                    "VALUES (:jti, :user_id, :family_id, :issued_at, :expires_at)"
                ),
                {
                    "jti": new_jti_uuid,
                    "user_id": new_record.user_id,
                    "family_id": family_uuid,
                    "issued_at": new_record.issued_at,
                    "expires_at": new_record.expires_at,
                },
            )
            return True


# =============================================================================
# Security stamp helpers
# =============================================================================


def new_security_stamp() -> str:
    """Generate a fresh 64-character hex security stamp.

    Matches data-model §3.1: ``secrets.token_hex(32)`` produces 64
    lowercase hex characters which fits the ``users.security_stamp``
    VARCHAR(64) column exactly.
    """
    return secrets.token_hex(32)


async def invalidate_stamp(
    *,
    user: Any,
    session: Any,
    audit: Any | None = None,
    request_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Rotate the user's ``security_stamp`` and persist it.

    Works with either a legacy ``User`` ORM instance (with
    ``security_stamp`` attribute) or a Pydantic-shaped stand-in used in
    tests. ``audit`` is optional — when provided we emit a
    ``auth.security_stamp_rotated`` platform audit row.

    Returns the new stamp value so callers can use it for a freshly
    re-issued access token in the same request.
    """
    new_stamp = new_security_stamp()
    user.security_stamp = new_stamp  # noqa: B010 - generic principal shape

    # If we were given a real session, it's the caller's responsibility
    # to commit. We just stage the change.
    if session is not None and hasattr(session, "add"):
        with contextlib.suppress(Exception):  # pragma: no cover - defensive
            session.add(user)

    if audit is not None:
        # Platform-scope event — auth / session-layer change.
        await audit.write_platform_event(
            actor_user_id=getattr(user, "id", None),
            action="auth.security_stamp_rotated",
            request_id=request_id or "internal",
            ip=ip or "0.0.0.0",
            user_agent=user_agent or "",
            detail={"reason": "invalidate_stamp"},
        )

    return new_stamp


# =============================================================================
# T060b: access token
# =============================================================================


def issue_access_token(
    *,
    user_id: UUID,
    security_stamp: str,
    ttl: timedelta = DEFAULT_ACCESS_TTL,
    now: datetime | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Sign a short-lived access JWT.

    Args:
        user_id: Subject user id. Embedded as ``sub``.
        security_stamp: The user's current stamp, copied into the
            ``ss`` claim. Verification later compares this to the live
            DB value so stamp rotation cleanly revokes outstanding
            tokens (FR-055, FR-071).
        ttl: Lifetime. Defaults to 15 minutes (FR-055).
        now: Override "current time" for tests. Production callers pass
            ``None`` and we use :func:`datetime.now(UTC)`.
        extra_claims: Optional additional claims (e.g. ``is_superuser``).
            Do NOT use to carry authorization decisions — those are
            re-evaluated per request in the permission engine.
    """
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + ttl
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "ss": security_stamp,
        "jti": str(uuid.uuid4()),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if extra_claims:
        # Reserved claim names win — callers cannot clobber sub/ss/jti/type/exp.
        reserved = {"sub", "ss", "jti", "type", "iat", "exp"}
        for k, v in extra_claims.items():
            if k in reserved:
                continue
            claims[k] = v

    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_access_token(
    token: str,
    *,
    current_security_stamp: str | None = None,
) -> AccessTokenClaims:
    """Verify an access token's signature, type, and freshness.

    Args:
        token: Encoded JWT string.
        current_security_stamp: The user's live stamp, as read from DB
            (or a per-request cache). If provided and does not match the
            token's ``ss`` claim, :class:`StaleTokenError` is raised.
            Pass ``None`` to skip the stamp check — typically only the
            token-refresh endpoint does this.

    Returns:
        :class:`AccessTokenClaims` for downstream use.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("access token invalid") from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError("token is not an access token")

    sub = payload.get("sub")
    ss = payload.get("ss")
    jti = payload.get("jti")
    exp_ts = payload.get("exp")
    if not isinstance(sub, str) or not isinstance(ss, str) or not isinstance(jti, str):
        raise InvalidTokenError("access token missing required claims")
    if not isinstance(exp_ts, int):
        raise InvalidTokenError("access token missing exp")

    try:
        user_id = UUID(sub)
    except (TypeError, ValueError) as exc:
        raise InvalidTokenError("access token sub is not a UUID") from exc

    if current_security_stamp is not None and not secrets.compare_digest(
        ss, current_security_stamp
    ):
        raise StaleTokenError("security_stamp has been rotated")

    return AccessTokenClaims(
        user_id=user_id,
        security_stamp=ss,
        jti=jti,
        expires_at=datetime.fromtimestamp(exp_ts, tz=UTC),
    )


# =============================================================================
# Scoped media token
# =============================================================================


def issue_media_token(
    *,
    user_id: UUID,
    security_stamp: str,
    project_id: UUID,
    resource_type: MediaResourceType,
    resource_id: UUID,
    scope: MediaTokenScope,
    parent_id: UUID | None = None,
    source_index: int | None = None,
    ttl: timedelta = DEFAULT_MEDIA_TTL,
    now: datetime | None = None,
) -> str:
    """Sign a short-lived JWT scoped to one media resource.

    ``resource_type`` selects between a whole recording (``"recording"``), a
    single clip (``"clip"``), and a search session's reference audio
    (``"search_session"``); ``resource_id`` is the recording id, clip id, or
    session id accordingly. The compact ``rtype`` claim carries the resource
    type; the resource id continues to live under the ``recording_id`` claim
    key so the on-wire shape stays stable for the common recording case. Clip
    tokens MUST bind their parent recording via ``parent_id`` so the token
    cannot be replayed under another recording's path. ``search_session``
    tokens MUST bind their ``source_index`` (carried under the ``src_idx``
    claim) so the token cannot be replayed for a different reference-audio
    source.
    """
    if scope not in MEDIA_TOKEN_SCOPES:
        raise ValueError("invalid media token scope")
    if resource_type not in MEDIA_RESOURCE_TYPES:
        raise ValueError("invalid media token resource type")
    if (resource_type == "clip") != (parent_id is not None):
        raise ValueError("parent_id is required for clip tokens and forbidden otherwise")
    if (resource_type == "search_session") != (source_index is not None):
        raise ValueError(
            "source_index is required for search_session tokens and forbidden otherwise"
        )

    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + ttl
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "ss": security_stamp,
        "project_id": str(project_id),
        "rtype": resource_type,
        "recording_id": str(resource_id),
        "scope": scope,
        **({"parent_id": str(parent_id)} if parent_id is not None else {}),
        **({"src_idx": source_index} if source_index is not None else {}),
        "jti": str(uuid.uuid4()),
        "type": MEDIA_TOKEN_TYPE,
        "typ": MEDIA_TOKEN_TYP,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_media_token(
    token: str,
    *,
    current_security_stamp: str,
    project_id: UUID,
    resource_type: MediaResourceType,
    resource_id: UUID,
    scope: MediaTokenScope,
    parent_id: UUID | None = None,
    source_index: int | None = None,
) -> MediaTokenClaims:
    """Verify a scoped media token against the requested resource and scope.

    ``parent_id`` is the parent recording id from the request path for clip
    resources; the token's ``parent_id`` claim must match it exactly (and must
    be absent for non-clip resources). ``source_index`` is the reference-audio
    index from the request path for ``search_session`` resources; the token's
    ``src_idx`` claim must match it exactly (and must be absent for other
    resources).
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("media token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("media token invalid") from exc

    if payload.get("type") != MEDIA_TOKEN_TYPE or payload.get("typ") != MEDIA_TOKEN_TYP:
        raise InvalidTokenError("token is not a media token")

    sub = payload.get("sub")
    ss = payload.get("ss")
    token_project_id = payload.get("project_id")
    token_resource_type = payload.get("rtype")
    token_resource_id = payload.get("recording_id")
    token_parent_id = payload.get("parent_id")
    token_source_index = payload.get("src_idx")
    token_scope = payload.get("scope")
    jti = payload.get("jti")
    exp_ts = payload.get("exp")
    if (
        not isinstance(sub, str)
        or not isinstance(ss, str)
        or not isinstance(token_project_id, str)
        or not isinstance(token_resource_type, str)
        or not isinstance(token_resource_id, str)
        or not isinstance(token_scope, str)
        or not isinstance(jti, str)
    ):
        raise InvalidTokenError("media token missing required claims")
    if not isinstance(exp_ts, int):
        raise InvalidTokenError("media token missing exp")
    if token_scope not in MEDIA_TOKEN_SCOPES:
        raise InvalidTokenError("media token scope invalid")
    if token_scope != scope:
        raise InvalidTokenError("media token scope mismatch")
    if token_resource_type not in MEDIA_RESOURCE_TYPES:
        raise InvalidTokenError("media token resource type invalid")
    if token_resource_type != resource_type:
        raise InvalidTokenError("media token resource type mismatch")

    try:
        user_id = UUID(sub)
        claim_project_id = UUID(token_project_id)
        claim_resource_id = UUID(token_resource_id)
        claim_parent_id = UUID(token_parent_id) if token_parent_id is not None else None
    except (TypeError, ValueError) as exc:
        raise InvalidTokenError("media token UUID claim invalid") from exc

    if claim_project_id != project_id or claim_resource_id != resource_id:
        raise InvalidTokenError("media token path mismatch")
    if claim_parent_id != parent_id:
        raise InvalidTokenError("media token parent mismatch")

    # The ``src_idx`` claim must be an int when present (a bool is not a valid
    # source index — ``isinstance(True, int)`` is True, so reject bools too).
    if token_source_index is not None and (
        isinstance(token_source_index, bool)
        or not isinstance(token_source_index, int)
    ):
        raise InvalidTokenError("media token source index invalid")
    if token_source_index != source_index:
        raise InvalidTokenError("media token source index mismatch")

    if not secrets.compare_digest(ss, current_security_stamp):
        raise StaleTokenError("security_stamp has been rotated")

    return MediaTokenClaims(
        user_id=user_id,
        security_stamp=ss,
        project_id=claim_project_id,
        resource_type=cast(MediaResourceType, token_resource_type),
        resource_id=claim_resource_id,
        scope=cast(MediaTokenScope, token_scope),
        jti=jti,
        expires_at=datetime.fromtimestamp(exp_ts, tz=UTC),
        parent_id=claim_parent_id,
        source_index=token_source_index,
    )


# =============================================================================
# T060c: refresh token rotation
# =============================================================================


def issue_refresh_token(
    *,
    user_id: UUID,
    family_id: str | None = None,
    ttl_days: int | None = None,
    now: datetime | None = None,
) -> tuple[str, RefreshTokenRecord]:
    """Mint a new refresh token.

    Callers use this in two scenarios:

    * Login / 2FA completion — no ``family_id`` given, a new family is
      created.
    * Rotation inside :func:`rotate_refresh_token` — the previous
      token's family id is passed in so the replay-detection chain
      stays together.

    Returns:
        ``(encoded_token, bookkeeping_record)``. The caller persists
        ``record`` via :class:`TokenStore` in the same transaction as
        any user-visible side effect.
    """
    issued_at = now or datetime.now(UTC)
    ttl = timedelta(days=ttl_days or settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    expires_at = issued_at + ttl
    jti = str(uuid.uuid4())
    family = family_id or str(uuid.uuid4())

    claims: dict[str, Any] = {
        "sub": str(user_id),
        "jti": jti,
        "family": family,
        "type": REFRESH_TOKEN_TYPE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(
        claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    record = RefreshTokenRecord(
        jti=jti,
        family_id=family,
        user_id=user_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return token, record


def _decode_refresh(token: str) -> RefreshTokenClaims:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("refresh token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("refresh token invalid") from exc

    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise InvalidTokenError("token is not a refresh token")

    sub = payload.get("sub")
    jti = payload.get("jti")
    family = payload.get("family")
    exp_ts = payload.get("exp")
    if (
        not isinstance(sub, str)
        or not isinstance(jti, str)
        or not isinstance(family, str)
        or not isinstance(exp_ts, int)
    ):
        raise InvalidTokenError("refresh token missing required claims")

    try:
        user_id = UUID(sub)
    except (TypeError, ValueError) as exc:
        raise InvalidTokenError("refresh token sub is not a UUID") from exc

    return RefreshTokenClaims(
        user_id=user_id,
        family_id=family,
        jti=jti,
        expires_at=datetime.fromtimestamp(exp_ts, tz=UTC),
    )


async def rotate_refresh_token(
    raw_token: str,
    *,
    store: TokenStore,
    now: datetime | None = None,
    audit: Any | None = None,
    request_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, RefreshTokenRecord]:
    """Consume a refresh token and mint its successor.

    Semantics (FR-055, research §auth):

    1. Decode the presented token. Reject on signature / structure /
       expiry issues.
    2. Reject if the token's family is already revoked.
    3. If the token's ``jti`` was already consumed → REUSE DETECTED.
       Revoke the entire family and raise :class:`ReusedTokenError`.
    4. Mark the jti consumed, mint a new token preserving ``family``,
       record it via the store, return ``(new_raw_token, record)``.

    The function is async because every :class:`TokenStore` call is.

    Args:
        raw_token: Encoded refresh JWT to rotate.
        store: :class:`TokenStore` backing replay / family state.
        now: Override clock for tests.
        audit: Optional :class:`AuditLogService`-shaped object; when
            set, family revocation on replay emits
            ``auth.refresh_reuse_detected``.
        request_id / ip / user_agent: Forwarded to the audit writer so
            the row has a populated request context.

    Raises:
        InvalidTokenError: Structural / cryptographic failure.
        RevokedFamilyError: Family was already blown up.
        ReusedTokenError: jti was previously consumed — attack signal.
    """
    claims = _decode_refresh(raw_token)

    if await store.is_family_revoked(claims.family_id):
        raise RevokedFamilyError("refresh token family already revoked")

    # Mint the candidate successor BEFORE attempting the atomic swap so
    # the swap itself is the single critical section. If the swap fails
    # (concurrent rotation already consumed ``claims.jti``) we discard
    # the candidate and treat the call as a reuse attempt.
    new_token, record = issue_refresh_token(
        user_id=claims.user_id,
        family_id=claims.family_id,
        now=now,
    )

    swapped = await store.atomic_consume_and_issue(
        family_id=claims.family_id,
        old_jti=claims.jti,
        new_record=record,
    )

    if not swapped:
        # Atomic check + mark + issue lost the race → ``claims.jti`` was
        # already consumed by a concurrent rotation (or by an attacker
        # replaying an old token). Either way, revoke the family.
        await store.revoke_family(claims.family_id)
        if audit is not None:
            await audit.write_platform_event(
                actor_user_id=claims.user_id,
                action="auth.refresh_reuse_detected",
                request_id=request_id or "internal",
                ip=ip or "0.0.0.0",
                user_agent=user_agent or "",
                detail={
                    "family_id": claims.family_id,
                    "reused_jti": claims.jti,
                },
            )
        raise ReusedTokenError("refresh token reuse detected; family revoked")

    return new_token, record


async def revoke_family(
    family_id: str,
    *,
    store: TokenStore,
    audit: Any | None = None,
    actor_user_id: UUID | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Revoke a refresh-token family (e.g. user clicks Log Out on all devices).

    Idempotent: calling twice is a no-op on the second call.
    """
    await store.revoke_family(family_id)
    if audit is not None:
        await audit.write_platform_event(
            actor_user_id=actor_user_id,
            action="auth.refresh_family_revoked",
            request_id=request_id or "internal",
            ip=ip or "0.0.0.0",
            user_agent=user_agent or "",
            detail={
                "family_id": family_id,
                "reason": reason or "manual",
            },
        )


__all__ = [
    "ACCESS_TOKEN_TYPE",
    "AccessTokenClaims",
    "AuthTokenError",
    "DEFAULT_ACCESS_TTL",
    "DEFAULT_MEDIA_TTL",
    "InMemoryTokenStore",
    "InvalidTokenError",
    "MEDIA_RESOURCE_TYPES",
    "MEDIA_TOKEN_SCOPES",
    "MEDIA_TOKEN_TYPE",
    "MEDIA_TOKEN_TYP",
    "MediaResourceType",
    "MediaTokenClaims",
    "MediaTokenScope",
    "REFRESH_TOKEN_TYPE",
    "RefreshTokenClaims",
    "RefreshTokenRecord",
    "RevokedFamilyError",
    "ReusedTokenError",
    "SqlTokenStore",
    "StaleTokenError",
    "TokenStore",
    "invalidate_stamp",
    "issue_access_token",
    "issue_media_token",
    "issue_refresh_token",
    "new_security_stamp",
    "revoke_family",
    "rotate_refresh_token",
    "verify_access_token",
    "verify_media_token",
]
