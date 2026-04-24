"""Password authentication service for 006-permissions-redesign.

T061 (Phase 2.5). New file alongside the legacy ``services/auth.py``; the
legacy ``AuthService`` continues to serve Phase 2 routes until Phase 3
rewires authentication. Nothing in this module is wired into FastAPI yet
— the middleware swap-over happens in Phase 2.6 (T070).

Scope (FR-103):

* Password hashing with argon2 (reuses :mod:`echoroo.core.security`).
* NIST SP 800-63B password policy:
    - length ≥ 8
    - no composition rules (no mandatory digit / symbol)
    - reject passwords known to HIBP (pwned count > 0)
* Login attempt tracking with exponential backoff per (email, ip).

Design choices:

* HTTP to HaveIBeenPwned is behind :class:`HibpChecker`, a dependency-
  injectable callable. Tests pass a fake. No outbound I/O happens at
  import time.
* Login attempt persistence goes through an abstract
  :class:`LoginAttemptRecorder` so both the legacy ``login_attempts``
  table and a future per-attempt KV store can be swapped in.
* No FastAPI / HTTPException usage — this layer raises plain
  :class:`AuthenticationError` subclasses; the router translates to
  HTTP codes.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from echoroo.core.security import hash_password, verify_password

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class AuthenticationError(Exception):
    """Base class for all authentication-layer failures."""


class InvalidCredentialsError(AuthenticationError):
    """Email not found or password mismatch."""


class AccountLockedError(AuthenticationError):
    """Too many recent failures — caller should back off."""

    def __init__(self, retry_after_seconds: int):
        super().__init__(f"account locked; retry_after={retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class PasswordPolicyError(AuthenticationError):
    """Candidate password does not meet the NIST policy."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# =============================================================================
# Config
# =============================================================================


@dataclass(frozen=True)
class PasswordPolicy:
    """NIST SP 800-63B password policy parameters.

    ``min_length`` defaults to 8 per NIST SP 800-63B §5.1.1.2. The
    spec does not require composition rules (digit / symbol) and we do
    not add them — NIST advises AGAINST them.
    """

    min_length: int = 8
    max_length: int = 4096  # DoS guard; NIST recommends allowing long passwords
    reject_pwned: bool = True


DEFAULT_PASSWORD_POLICY = PasswordPolicy()


@dataclass(frozen=True)
class RateLimitPolicy:
    """Exponential backoff configuration for login attempts.

    ``window_seconds`` is the sliding window over which we count
    failures. ``base_backoff_seconds`` is the first lock length; each
    subsequent failure doubles up to ``max_backoff_seconds``.
    """

    max_failures_before_backoff: int = 5
    window_seconds: int = 900  # 15 minutes
    base_backoff_seconds: int = 30
    max_backoff_seconds: int = 3600


DEFAULT_RATE_LIMIT_POLICY = RateLimitPolicy()


# =============================================================================
# Dependencies (injectable for tests)
# =============================================================================


class HibpChecker(Protocol):
    """HaveIBeenPwned k-anonymity lookup.

    The production implementation queries
    ``https://api.pwnedpasswords.com/range/{first5}`` and counts
    occurrences. Tests pass a fake that returns deterministic numbers
    based on an in-memory dictionary.
    """

    async def pwned_count(self, password: str) -> int:
        """Return 0 if password is not in HIBP, else occurrence count."""
        ...


class AlwaysFreshHibp:
    """Fallback HIBP checker that always returns 0 (not pwned).

    Used in dev / offline environments where the HIBP check should be
    skipped. NEVER use in production — wire
    :class:`HttpHibpChecker` there.
    """

    async def pwned_count(self, password: str) -> int:  # noqa: ARG002
        return 0


class HttpHibpChecker:
    """Real HIBP k-anonymity client.

    The caller injects an httpx-compatible async client so this class
    can be unit-tested without monkeypatching ``httpx`` at the module
    level.
    """

    def __init__(
        self,
        *,
        http_get: Any,
        base_url: str = "https://api.pwnedpasswords.com/range/",
    ) -> None:
        self._http_get = http_get
        self._base_url = base_url.rstrip("/") + "/"

    @staticmethod
    def _sha1_upper(password: str) -> str:
        return hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # noqa: S324

    async def pwned_count(self, password: str) -> int:
        sha1 = self._sha1_upper(password)
        prefix, suffix = sha1[:5], sha1[5:]
        try:
            response = await self._http_get(self._base_url + prefix)
        except Exception:  # noqa: BLE001 - HIBP outages must not block login
            logger.warning("HIBP lookup failed; failing open", exc_info=True)
            return 0
        text = getattr(response, "text", "") or ""
        for line in text.splitlines():
            parts = line.strip().split(":")
            if len(parts) != 2:
                continue
            candidate, count = parts[0].strip().upper(), parts[1].strip()
            if candidate == suffix:
                try:
                    return max(0, int(count))
                except ValueError:
                    return 0
        return 0


@dataclass(frozen=True)
class LoginAttemptSnapshot:
    """Tuple returned by :class:`LoginAttemptRecorder.recent_failures`.

    Attributes:
        failure_count: Number of failed attempts within the window.
        last_failure_at: Most recent failure timestamp, or None.
    """

    failure_count: int
    last_failure_at: datetime | None


class LoginAttemptRecorder(Protocol):
    """Interface for persisting login attempts + reading recent failures."""

    async def record(
        self,
        *,
        email: str,
        ip: str,
        success: bool,
        now: datetime,
        user_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> None:
        ...

    async def recent_failures(
        self,
        *,
        email: str,
        ip: str,
        window_seconds: int,
        now: datetime,
    ) -> LoginAttemptSnapshot:
        ...


class InMemoryLoginAttemptRecorder:
    """Test double — stores attempts in a list, not thread-safe."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    async def record(
        self,
        *,
        email: str,
        ip: str,
        success: bool,
        now: datetime,
        user_id: UUID | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._rows.append(
            {
                "email": email,
                "ip": ip,
                "success": success,
                "at": now,
                "user_id": user_id,
                "user_agent": user_agent,
            }
        )

    async def recent_failures(
        self,
        *,
        email: str,
        ip: str,
        window_seconds: int,
        now: datetime,
    ) -> LoginAttemptSnapshot:
        cutoff = now - timedelta(seconds=window_seconds)
        failures = [
            r
            for r in self._rows
            if not r["success"]
            and r["at"] >= cutoff
            and (r["email"] == email or r["ip"] == ip)
        ]
        last = max((r["at"] for r in failures), default=None)
        return LoginAttemptSnapshot(failure_count=len(failures), last_failure_at=last)


class UserLookup(Protocol):
    """Minimal interface the service needs for fetching users by email."""

    async def get_by_email(self, email: str) -> Any | None:
        ...


# =============================================================================
# Password policy check
# =============================================================================


async def enforce_password_policy(
    password: str,
    *,
    policy: PasswordPolicy = DEFAULT_PASSWORD_POLICY,
    hibp: HibpChecker | None = None,
) -> None:
    """Validate a candidate password per NIST SP 800-63B.

    Raises :class:`PasswordPolicyError` on the first failing rule.
    """
    if not isinstance(password, str):
        raise PasswordPolicyError("password must be a string")
    if len(password) < policy.min_length:
        raise PasswordPolicyError(
            f"password must be at least {policy.min_length} characters"
        )
    if len(password) > policy.max_length:
        raise PasswordPolicyError(
            f"password must be at most {policy.max_length} characters"
        )

    if policy.reject_pwned and hibp is not None:
        count = await hibp.pwned_count(password)
        if count > 0:
            # NIST SP 800-63B §5.1.1.2 — reject previously-breached passwords.
            raise PasswordPolicyError(
                "password was found in public breach corpora; choose a different one"
            )


def compute_backoff_seconds(
    *,
    failure_count: int,
    policy: RateLimitPolicy = DEFAULT_RATE_LIMIT_POLICY,
) -> int:
    """Return the number of seconds the caller must wait.

    Returns ``0`` when ``failure_count`` is below the threshold.
    Exponential: base × 2^(failures_over_threshold), clamped to
    ``max_backoff_seconds``.
    """
    over = failure_count - policy.max_failures_before_backoff
    if over < 0:
        return 0
    backoff = policy.base_backoff_seconds * (2**over)
    return int(min(backoff, policy.max_backoff_seconds))


# =============================================================================
# Core authenticate entrypoint
# =============================================================================


@dataclass(frozen=True)
class AuthenticateResult:
    """Outcome of a successful ``authenticate`` call."""

    user: Any
    security_stamp: str


async def authenticate(
    *,
    email: str,
    password: str,
    ip: str,
    users: UserLookup,
    attempts: LoginAttemptRecorder,
    now: datetime | None = None,
    policy: RateLimitPolicy = DEFAULT_RATE_LIMIT_POLICY,
    user_agent: str | None = None,
) -> AuthenticateResult:
    """Verify credentials and record the attempt.

    Steps:
      1. Rate-limit check — if the (email, ip) pair has exceeded the
         failure threshold, raise :class:`AccountLockedError` with the
         remaining backoff.
      2. Fetch the user and verify password via argon2.
      3. Record the attempt (success or failure) via ``attempts``.
      4. On success, return the user + their current ``security_stamp``
         so the caller can mint fresh JWTs immediately.

    Failure path uses a constant-time password verify against a dummy
    hash so enumeration of emails is not possible by timing.
    """
    tick = now or datetime.now(UTC)

    # Stage 1: rate limit.
    snapshot = await attempts.recent_failures(
        email=email,
        ip=ip,
        window_seconds=policy.window_seconds,
        now=tick,
    )
    backoff = compute_backoff_seconds(failure_count=snapshot.failure_count, policy=policy)
    if backoff > 0:
        # still-locked window: deny without even trying the password.
        await attempts.record(
            email=email,
            ip=ip,
            success=False,
            now=tick,
            user_agent=user_agent,
        )
        raise AccountLockedError(backoff)

    # Stage 2: look up user + verify password.
    user = await users.get_by_email(email)
    valid = False
    stamp: str | None = None
    if user is not None:
        hashed = getattr(user, "password_hash", None) or getattr(user, "hashed_password", None)
        if isinstance(hashed, str):
            try:
                valid = verify_password(password, hashed)
            except Exception:  # noqa: BLE001 - malformed hash → deny
                valid = False
        stamp = getattr(user, "security_stamp", None)
    else:
        # Constant-time guard: still pay the argon2 cost so an attacker
        # cannot distinguish "unknown email" from "bad password" by
        # timing side channels.
        with contextlib.suppress(Exception):
            verify_password(password, _DUMMY_ARGON2_HASH)

    # Stage 3: record outcome.
    await attempts.record(
        email=email,
        ip=ip,
        success=valid,
        now=tick,
        user_id=getattr(user, "id", None) if valid else None,
        user_agent=user_agent,
    )

    if not valid or user is None or stamp is None:
        raise InvalidCredentialsError("invalid email or password")

    return AuthenticateResult(user=user, security_stamp=stamp)


# A valid argon2 hash of a random password. Used so failed-email
# authentication still runs an argon2 verification for timing parity.
# Generated once at module import; not a secret (never used for real
# auth).
_DUMMY_ARGON2_HASH: str = hash_password("constant-time-dummy-" + "x" * 48)


# =============================================================================
# Registration / password-change helpers
# =============================================================================


async def hash_new_password(
    password: str,
    *,
    policy: PasswordPolicy = DEFAULT_PASSWORD_POLICY,
    hibp: HibpChecker | None = None,
) -> str:
    """Validate the candidate password and return its argon2 hash.

    Used by the registration and password-reset endpoints.
    """
    await enforce_password_policy(password, policy=policy, hibp=hibp)
    return hash_password(password)


# =============================================================================
# Synchronous helpers (non-async entry points)
# =============================================================================


def enforce_password_policy_sync(
    password: str,
    *,
    policy: PasswordPolicy = DEFAULT_PASSWORD_POLICY,
) -> None:
    """Synchronous length-only policy check for callers that cannot await.

    Does NOT run the HIBP check (which is async). Use in non-async
    Pydantic validators where you just need the length floor; the
    router should additionally call :func:`enforce_password_policy`
    before persisting.
    """
    # Delegate to the async function via asyncio.run is inappropriate
    # inside a running loop. We re-implement the sync subset instead.
    if not isinstance(password, str):
        raise PasswordPolicyError("password must be a string")
    if len(password) < policy.min_length:
        raise PasswordPolicyError(
            f"password must be at least {policy.min_length} characters"
        )
    if len(password) > policy.max_length:
        raise PasswordPolicyError(
            f"password must be at most {policy.max_length} characters"
        )


# Silence "imported but unused" on asyncio — the module used to run
# policy checks via asyncio.run; we keep the import for forward compat
# with callers that invoke enforce_password_policy from sync code via
# asyncio.run(enforce_password_policy(...)).
_ = asyncio  # noqa: F841 — intentional


__all__ = [
    "AccountLockedError",
    "AlwaysFreshHibp",
    "AuthenticateResult",
    "AuthenticationError",
    "DEFAULT_PASSWORD_POLICY",
    "DEFAULT_RATE_LIMIT_POLICY",
    "HibpChecker",
    "HttpHibpChecker",
    "InMemoryLoginAttemptRecorder",
    "InvalidCredentialsError",
    "LoginAttemptRecorder",
    "LoginAttemptSnapshot",
    "PasswordPolicy",
    "PasswordPolicyError",
    "RateLimitPolicy",
    "UserLookup",
    "authenticate",
    "compute_backoff_seconds",
    "enforce_password_policy",
    "enforce_password_policy_sync",
    "hash_new_password",
]
