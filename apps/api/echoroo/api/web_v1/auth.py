"""First-party authentication router for ``/web-api/v1/auth``."""

# Interim token validation is centralized in `_consume_interim_token_for_user`.
# The helper verifies signature, type/scope, subject, live security stamp,
# deletion state, and one-time JTI consumption before an endpoint proceeds.

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
import secrets
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import httpx
import jwt
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from webauthn.helpers import options_to_json_dict

from echoroo.core.auth import RefreshTokenRecord, SqlTokenStore, issue_access_token
from echoroo.core.database import AsyncSessionLocal, DbSession
from echoroo.core.kms import compute_pii_hash
from echoroo.core.redirect_validator import is_safe_redirect_url
from echoroo.core.redis import get_redis_connection
from echoroo.core.security import hash_password, verify_password
from echoroo.core.settings import get_settings
from echoroo.core.text import has_control_chars
from echoroo.middleware.csrf import CSRF_HEADER_NAME, issue_csrf_token
from echoroo.middleware.step_up import STEP_UP_HEADER_NAME
from echoroo.models.password_reset_token import PasswordResetToken
from echoroo.models.user import User
from echoroo.repositories.superuser_credentials import get_default_store
from echoroo.repositories.user import UserRepository
from echoroo.schemas.web_v1.auth import (
    LoginRequest,
    LoginResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    TotpSetupConfirmRequest,
    TotpSetupConfirmResponse,
    TotpSetupRequest,
    TotpSetupResponse,
    TwoFactorChallengeRequest,
    TwoFactorChallengeResponse,
    WebAuthnChallengeBeginResponse,
    WebAuthnChallengeCompleteResponse,
    WebAuthnChallengeRequest,
    WebAuthnRegisterBeginResponse,
    WebAuthnRegisterCompleteResponse,
    WebAuthnRegisterRequest,
)
from echoroo.services import outbox_service
from echoroo.services.audit_service import AuditLogService
from echoroo.services.auth_service import (
    AccountLockedError,
    HibpChecker,
    HttpHibpChecker,
    InMemoryLoginAttemptRecorder,
    InvalidCredentialsError,
    PasswordPolicyError,
    authenticate,
    enforce_password_policy,
)
from echoroo.services.login_notification_service import LoginNotificationService
from echoroo.services.step_up_token_service import (
    SCOPE_ADMIN_DESTRUCTIVE,
    STEP_UP_TOKEN_TTL_SECONDS,
    issue_step_up_token,
)
from echoroo.services.two_factor_service import (
    BACKUP_FAIL_WINDOW_SECONDS,
    ISSUER_NAME,
    TOTP_FAIL_WINDOW_SECONDS,
    TOTP_LOCK_SECONDS,
    TwoFactorAlreadyEnabledError,
    TwoFactorInvalidCodeError,
    TwoFactorLockedError,
    TwoFactorNotEnabledError,
    TwoFactorRateLimitedError,
    TwoFactorService,
)
from echoroo.services.webauthn_service import (
    StoredCredential,
    WebAuthnChallengeNotFoundError,
    WebAuthnDuplicateCredentialError,
    WebAuthnReplayDetectedError,
    WebAuthnService,
    WebAuthnVerificationError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["web-auth"])
settings = get_settings()
if settings.ENVIRONMENT == "production":
    raise RuntimeError(
        "InMemoryLoginAttemptRecorder is not production-safe. "
        "Wire a Redis-backed recorder via T178 before production deploy."
    )

# TODO(T178): process-local; multi-worker NOT consistent. Replace with Redis.
_login_attempts = InMemoryLoginAttemptRecorder()


class _HttpxHibpChecker:
    async def pwned_count(self, password: str) -> int:
        async with httpx.AsyncClient(timeout=5.0) as client:
            checker = HttpHibpChecker(http_get=client.get)
            return await checker.pwned_count(password)


_hibp_checker: HibpChecker = _HttpxHibpChecker()
webauthn_service = WebAuthnService()
_superuser_credential_store = get_default_store()

_REGISTER_IP_LIMIT = 10
_REGISTER_EMAIL_LIMIT = 5
_REGISTER_WINDOW_SECONDS = 60 * 60
_PASSWORD_RESET_MIN_RESPONSE_SECONDS = 0.05
_PASSWORD_RESET_TOKEN_TTL = timedelta(minutes=60)
# TODO(T178): process-local; multi-worker NOT consistent. Replace with Redis.
_register_windows: dict[str, list[float]] = {}


@dataclass(frozen=True)
class _RefreshClaims:
    user_id: UUID
    family_id: str
    jti: str
    security_stamp: str
    expires_at: datetime


class _InterimTokenReplayError(Exception):
    """Raised when an interim token JTI was already consumed."""


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or str(uuid.uuid4())


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent") or ""


def _has_control_chars(value: str) -> bool:
    return has_control_chars(value)


def _is_safe_redirect_url(target: str | None) -> bool:
    """Return ``True`` when ``target`` is a safe same-origin redirect.

    Phase 17 A-7 (T979b) — same-origin guard for ``?next=`` / ``redirect_url=``
    parameters across login, password reset, invitation, and OAuth callback
    flows. Delegates to :func:`echoroo.core.redirect_validator.is_safe_redirect_url`
    so the policy is consistent across every endpoint that consumes a
    user-supplied redirect target.

    Same-origin policy: only relative URLs starting with a single ``/`` are
    accepted by default. Absolute URLs, protocol-relative URLs
    (``//evil.com``), backslash-prefixed paths, and dangerous schemes
    (``javascript:``, ``data:`` …) are rejected.

    Args:
        target: Raw redirect target (``next=...`` query parameter value).

    Returns:
        ``True`` when the target may be honoured as a 3xx ``Location`` header,
        ``False`` when it must be rejected and the caller should either
        ignore the parameter or fall back to a safe default.
    """
    return is_safe_redirect_url(target)


def _normalize_email(raw_email: str) -> str:
    normalized = unicodedata.normalize("NFKC", raw_email).strip()
    if _has_control_chars(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="email contains control characters",
        )
    try:
        validated = validate_email(
            normalized,
            allow_smtputf8=True,
            check_deliverability=False,
        )
    except EmailNotValidError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return validated.normalized.lower()


def _rate_limit_register(*, ip: str, email: str) -> None:
    now = time.monotonic()
    cutoff = now - _REGISTER_WINDOW_SECONDS
    scopes = (
        (f"register:ip:{ip}", _REGISTER_IP_LIMIT),
        (f"register:email:{email}", _REGISTER_EMAIL_LIMIT),
    )
    for key, limit in scopes:
        window = [t for t in _register_windows.get(key, []) if t >= cutoff]
        if len(window) >= limit:
            retry_after = max(1, int(_REGISTER_WINDOW_SECONDS - (now - window[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Registration rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        window.append(now)
        _register_windows[key] = window


def _encode_reset_token(token: bytes) -> str:
    return base64.urlsafe_b64encode(token).decode("ascii").rstrip("=")


def _decode_reset_token(encoded: str) -> bytes:
    try:
        padded = encoded + ("=" * (-len(encoded) % 4))
        token = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        ) from exc
    if len(token) != 32:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    return token


def _reset_token_hash(token: bytes) -> str:
    return hashlib.sha256(token).hexdigest()


def _password_reset_url(encoded_token: str) -> str:
    return (
        f"{settings.web_app_base_url.rstrip('/')}"
        f"/password-reset/confirm?token={encoded_token}"
    )


async def _sleep_for_minimum_request_time(started_at: float) -> None:
    remaining = _PASSWORD_RESET_MIN_RESPONSE_SECONDS - (time.monotonic() - started_at)
    if remaining > 0:
        await asyncio.sleep(remaining)


async def _revoke_refresh_families_for_user(db: DbSession, user_id: UUID) -> None:
    """Revoke all known refresh-token families for ``user_id``.

    ``SqlTokenStore`` currently exposes family-level revocation but no
    user-wide helper, so password reset enumerates families inside the same
    transaction as the password/security-stamp update.
    """
    await db.execute(
        text(
            "UPDATE token_families "
            "SET revoked_at = COALESCE(revoked_at, now()) "
            "WHERE user_id = :user_id"
        ),
        {"user_id": user_id},
    )
    await db.execute(
        text(
            "UPDATE refresh_tokens "
            "SET revoked_at = COALESCE(revoked_at, now()) "
            "WHERE user_id = :user_id AND revoked_at IS NULL"
        ),
        {"user_id": user_id},
    )


async def _record_login_notification(
    *,
    user: User,
    request: Request,
) -> None:
    """Record this login and enqueue a new-device email if applicable.

    Runs in its own short-lived transaction (matches the post-commit
    ordering of the audit hook) so a notification-enqueue failure
    cannot roll back the freshly-issued session. Failures are logged
    and swallowed — the user has already authenticated successfully and
    the notification side-effect must not block the response.
    """
    async with AsyncSessionLocal() as session:
        try:
            service = LoginNotificationService(session)
            await service.record_and_maybe_notify(
                user,
                ip=_client_ip(request),
                user_agent=_user_agent(request),
            )
            await session.commit()
        except Exception:  # noqa: BLE001 - logged; never blocks login
            await session.rollback()
            logger.exception("login_notification: record_and_maybe_notify failed")


async def _write_platform_audit(
    *,
    actor_user_id: UUID | None,
    action: str,
    request: Request,
    detail: dict[str, Any] | None = None,
) -> None:
    async with AsyncSessionLocal() as audit_session:
        try:
            audit = AuditLogService(audit_session)
            await audit.write_platform_event(
                actor_user_id=actor_user_id,
                action=action,
                request_id=_request_id(request),
                ip=_client_ip(request),
                user_agent=_user_agent(request),
                detail=detail or {},
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            raise


def _issue_interim_token(
    *,
    user: User,
    scope: str,
    ttl_seconds: int | None = None,
) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(
        seconds=ttl_seconds or settings.web_interim_token_ttl_seconds
    )
    claims: dict[str, Any] = {
        "sub": str(user.id),
        "type": "interim",
        "scope": scope,
        "ss": user.security_stamp,
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(
        claims,
        settings.web_session_secret,
        algorithm=settings.JWT_ALGORITHM,
    )


def _decode_interim_token(
    raw_token: str,
    *,
    expected_user_id: UUID,
    expected_scope: str | tuple[str, ...],
) -> dict[str, Any]:
    payload = _decode_interim_token_unbound(
        raw_token,
        expected_scope=expected_scope,
    )
    token_user_id = _interim_payload_user_id(payload)
    if token_user_id != expected_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        )
    return payload


def _decode_interim_token_unbound(
    raw_token: str,
    *,
    expected_scope: str | tuple[str, ...],
) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            raw_token,
            settings.web_session_secret,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        ) from exc

    token_scope = payload.get("scope")
    scope_matches = (
        token_scope in expected_scope
        if isinstance(expected_scope, tuple)
        else token_scope == expected_scope
    )
    if payload.get("type") != "interim" or not scope_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        )

    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        )
    return payload


def _interim_payload_user_id(payload: dict[str, Any]) -> UUID:
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        )
    try:
        return UUID(sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        ) from exc


async def _claim_interim_jti(payload: dict[str, Any]) -> None:
    jti = payload.get("jti")
    exp_ts = payload.get("exp")
    if not isinstance(jti, str) or not isinstance(exp_ts, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        )

    remaining_ttl = exp_ts - int(datetime.now(UTC).timestamp())
    if remaining_ttl <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        )

    redis = await get_redis_connection()
    claimed = await redis.set(
        f"2fa:interim_jti:{jti}",
        "1",
        ex=remaining_ttl,
        nx=True,
    )
    if not claimed:
        raise _InterimTokenReplayError


async def _consume_interim_token_for_user(
    *,
    raw_token: str,
    expected_scope: str | tuple[str, ...],
    request: Request,
    db: DbSession,
) -> tuple[User, dict[str, Any]]:
    unbound_payload = _decode_interim_token_unbound(
        raw_token,
        expected_scope=expected_scope,
    )
    user_id = _interim_payload_user_id(unbound_payload)
    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        )

    payload = _decode_interim_token(
        raw_token,
        expected_user_id=user.id,
        expected_scope=expected_scope,
    )
    security_stamp = payload.get("ss")
    if (
        not isinstance(security_stamp, str)
        or not secrets.compare_digest(user.security_stamp, security_stamp)
        or user.deleted_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        )

    try:
        await _claim_interim_jti(payload)
    except _InterimTokenReplayError as exc:
        await _write_platform_audit(
            actor_user_id=user.id,
            action="auth.interim_token_replay_detected",
            request=request,
            detail={"scope": payload.get("scope", ""), "jti": str(payload.get("jti", ""))},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        ) from exc
    return user, payload


async def _consume_interim_token_for_user_with_scopes(
    *,
    raw_token: str,
    expected_scopes: tuple[str, ...],
    request: Request,
    db: DbSession,
) -> tuple[User, dict[str, Any]]:
    unbound_payload = _decode_interim_token_unbound(
        raw_token,
        expected_scope=expected_scopes,
    )
    token_scope = unbound_payload.get("scope")
    if token_scope not in expected_scopes:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid interim token",
        )
    return await _consume_interim_token_for_user(
        raw_token=raw_token,
        expected_scope=cast(str, token_scope),
        request=request,
        db=db,
    )


async def _is_superuser(db: DbSession, user_id: UUID) -> bool:
    # TODO Phase 15 T950: replace this raw SQL check with the Superuser ORM.
    result = await db.execute(
        text(
            "SELECT 1 FROM superusers "
            "WHERE user_id = :uid AND revoked_at IS NULL LIMIT 1"
        ),
        {"uid": user_id},
    )
    return result.scalar_one_or_none() is not None


async def _require_superuser(db: DbSession, user_id: UUID) -> None:
    if not await _is_superuser(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WebAuthn registration is restricted to superusers",
        )


def _serialize_webauthn_options(options: Any) -> dict[str, Any]:
    if isinstance(options, dict):
        return options
    return options_to_json_dict(options)


def _webauthn_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WebAuthnDuplicateCredentialError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WebAuthn credential is already registered",
        )
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="WebAuthn verification failed",
    )


def _replace_stored_credential(
    credentials: list[StoredCredential],
    updated: StoredCredential,
) -> list[StoredCredential]:
    replaced = False
    next_credentials: list[StoredCredential] = []
    for credential in credentials:
        if credential["credential_id"] == updated["credential_id"]:
            next_credentials.append(updated)
            replaced = True
        else:
            next_credentials.append(credential)
    if not replaced:
        next_credentials.append(updated)
    return next_credentials


async def _issue_real_session(
    *,
    response: Response,
    user: User,
    db: DbSession,
) -> str:
    refresh_token, refresh_record = _issue_web_refresh_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
    )
    await SqlTokenStore(AsyncSessionLocal).record_issued(refresh_record)
    access_token = issue_access_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
        ttl=timedelta(seconds=settings.web_access_token_ttl_seconds),
    )
    user.last_login_at = datetime.now(UTC)
    user.last_first_party_activity_at = user.last_login_at
    db.add(user)
    await db.commit()
    _set_session_cookies(
        response,
        refresh_token=refresh_token,
        family_id=refresh_record.family_id,
    )
    # Defensive: clear any stale legacy ``revoked_user:{user_id}`` Redis
    # marker the legacy ``/api/v1/auth/logout`` (``AuthService.logout``)
    # may have written for this user before the modern web-auth flow was
    # adopted. The legacy ``CurrentUser`` Bearer dependency consults this
    # key on every ``/api/v1/*`` call (e.g. ``GET /api/v1/users/me``) and
    # 401s when the marker is present — even after a fresh login that
    # issued a brand-new access token. Without this clear, any user who
    # ever called the legacy logout endpoint would be unable to use the
    # legacy ``/api/v1/*`` surface for ``JWT_REFRESH_TOKEN_EXPIRE_DAYS``
    # days after their next login. Redis is best-effort: failures are
    # logged but never block a successful login.
    try:
        redis = await get_redis_connection()
        await redis.delete(f"revoked_user:{user.id}")
    except Exception:  # noqa: BLE001 - Redis outage must not block login
        logger.exception(
            "auth: failed to clear legacy revoked_user marker for %s",
            user.id,
        )
    return access_token


def _rate_limit_response(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="2FA rate limit exceeded",
        headers={"Retry-After": str(retry_after)},
    )


def _issue_web_refresh_token(
    *,
    user_id: UUID,
    security_stamp: str,
    family_id: str | None = None,
    now: datetime | None = None,
) -> tuple[str, RefreshTokenRecord]:
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=settings.web_refresh_token_ttl_seconds)
    jti = str(uuid.uuid4())
    family = family_id or str(uuid.uuid4())
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "jti": jti,
        "family": family,
        "type": "refresh",
        "ss": security_stamp,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(
        claims,
        settings.web_session_secret,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, RefreshTokenRecord(
        jti=jti,
        family_id=family,
        user_id=user_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _decode_web_refresh_token(raw_token: str) -> _RefreshClaims:
    try:
        payload: dict[str, Any] = jwt.decode(
            raw_token,
            settings.web_session_secret,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    sub = payload.get("sub")
    family = payload.get("family")
    jti = payload.get("jti")
    security_stamp = payload.get("ss")
    exp_ts = payload.get("exp")
    if not all(isinstance(v, str) for v in (sub, family, jti, security_stamp)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    if not isinstance(exp_ts, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    try:
        user_id = UUID(sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc
    return _RefreshClaims(
        user_id=user_id,
        family_id=cast(str, family),
        jti=cast(str, jti),
        security_stamp=cast(str, security_stamp),
        expires_at=datetime.fromtimestamp(exp_ts, tz=UTC),
    )


def _set_session_cookies(
    response: Response,
    *,
    refresh_token: str,
    family_id: str,
) -> None:
    csrf_token = issue_csrf_token(
        family_id,
        session_secret=settings.web_session_secret,
    )
    # Development uses plain HTTP; staging/production cookies remain Secure.
    secure_cookie = settings.ENVIRONMENT != "development"
    response.set_cookie(
        key=settings.web_refresh_cookie_name,
        value=refresh_token,
        max_age=settings.web_refresh_token_ttl_seconds,
        path="/web-api/v1/auth/refresh",
        secure=secure_cookie,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        key=settings.web_session_cookie_name,
        value=family_id,
        max_age=settings.web_refresh_token_ttl_seconds,
        path="/web-api/v1/",
        secure=secure_cookie,
        httponly=True,
        samesite="strict",
    )
    # CSRF cookie uses Path=/ so JS on any SvelteKit page (e.g. /en/dashboard)
    # can read the token via document.cookie for the double-submit pattern.
    # The token is the public half (httponly=False, intentionally readable);
    # the sensitive session/refresh cookies remain scoped to /web-api/v1/*.
    response.set_cookie(
        key=settings.web_csrf_cookie_name,
        value=csrf_token,
        max_age=settings.web_access_token_ttl_seconds,
        path="/",
        secure=secure_cookie,
        httponly=False,
        samesite="strict",
    )
    # Marker for SvelteKit hooks.server.ts to detect logged-in state;
    # carries no sensitive content. Path=/ so SvelteKit page routes (e.g.
    # /dashboard) can read it during their server-side auth check; the
    # real session/refresh/csrf cookies stay scoped to /web-api/v1/*.
    response.set_cookie(
        key=settings.web_logged_in_cookie_name,
        value="1",
        max_age=settings.web_refresh_token_ttl_seconds,
        path="/",
        secure=secure_cookie,
        httponly=True,
        samesite="strict",
    )
    response.headers[CSRF_HEADER_NAME] = csrf_token


def _failed_refresh_response(detail: str) -> JSONResponse:
    """Build a 401 response that ALSO clears all session cookies.

    Used by family-revocation paths in ``/refresh`` (token reuse,
    stale security_stamp, missing user, family already revoked) so the
    SvelteKit hooks no longer see a stale ``echoroo_logged_in`` marker
    after a security event. Returning a fresh ``JSONResponse`` (instead
    of mutating the injected ``response`` and raising ``HTTPException``)
    is required because FastAPI discards the injected response when an
    exception bubbles up.
    """
    response = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": detail},
    )
    _clear_session_cookies(response)
    return response


def _clear_session_cookies(response: Response) -> None:
    # Cookie attributes on deletion MUST match the attributes used at
    # set time so the browser actually evicts the cookie rather than
    # creating a sibling. Development uses plain HTTP; staging/prod
    # remain Secure (mirrors ``_set_session_cookies``).
    secure_cookie = settings.ENVIRONMENT != "development"
    response.delete_cookie(
        key=settings.web_refresh_cookie_name,
        path="/web-api/v1/auth/refresh",
        secure=secure_cookie,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        key=settings.web_session_cookie_name,
        path="/web-api/v1/",
        secure=secure_cookie,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        key=settings.web_csrf_cookie_name,
        path="/",
        secure=secure_cookie,
        httponly=False,
        samesite="strict",
    )
    response.delete_cookie(
        key=settings.web_logged_in_cookie_name,
        path="/",
        secure=secure_cookie,
        httponly=True,
        samesite="strict",
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: DbSession,
) -> RegisterResponse:
    email = _normalize_email(payload.email)
    _rate_limit_register(ip=_client_ip(request), email=email)

    try:
        await enforce_password_policy(
            payload.password,
            hibp=_hibp_checker,
        )
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.reason,
        ) from exc

    repo = UserRepository(db)
    if await repo.get_by_email(email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    now = datetime.now(UTC)
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        registered_timezone=payload.timezone,
        security_stamp=secrets.token_urlsafe(48),
        two_factor_enabled=False,
        last_login_at=None,
        last_first_party_activity_at=now,
    )

    try:
        await repo.create(user)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc

    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.user_registered",
        request=request,
        detail={"user_id": str(user.id)},
    )
    return RegisterResponse(user_id=user.id, email=user.email)


@router.post("/password-reset/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: DbSession,
) -> Response:
    """Request a password reset email without exposing account existence.

    T150d decision: active 2FA reset cooldown silently drops password-reset
    requests while leaving an audit record.
    """
    started_at = time.monotonic()
    try:
        email = _normalize_email(payload.email)
    except HTTPException:
        await _write_platform_audit(
            actor_user_id=None,
            action="auth.password_reset_requested",
            request=request,
            detail={"email_validation_failed": True},
        )
        await _sleep_for_minimum_request_time(started_at)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    email_hash = compute_pii_hash(email)
    token = secrets.token_bytes(32)
    token_hash = _reset_token_hash(token)
    encoded_token = _encode_reset_token(token)
    now = datetime.now(UTC)

    repo = UserRepository(db)
    user = await repo.get_by_email(email)

    try:
        if (
            user is not None
            and user.deleted_at is None
            and user.two_factor_reset_cooldown_until is not None
            and user.two_factor_reset_cooldown_until > now
        ):
            await _write_platform_audit(
                actor_user_id=user.id,
                action="auth.password_reset_blocked_during_cooldown",
                request=request,
                detail={"email_hash": email_hash, "user_id": str(user.id)},
            )
            await _sleep_for_minimum_request_time(started_at)
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        if user is not None and user.deleted_at is None:
            reset_url = _password_reset_url(encoded_token)
            expires_at = now + _PASSWORD_RESET_TOKEN_TTL
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    requested_ip=_client_ip(request)[:45],
                    requested_user_agent=_user_agent(request)[:500],
                )
            )
            await outbox_service.enqueue(
                db,
                event_type="password_reset_email",
                payload={
                    "user_id": str(user.id),
                    "reset_url": reset_url,
                    "expires_at": expires_at.isoformat(),
                },
                idempotency_key=f"password-reset:{token_hash}",
            )

        await _write_platform_audit(
            actor_user_id=None,
            action="auth.password_reset_requested",
            request=request,
            detail={"email_hash": email_hash},
        )
        await _sleep_for_minimum_request_time(started_at)
    except HTTPException:
        await _sleep_for_minimum_request_time(started_at)
        raise

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    db: DbSession,
) -> Response:
    """Reset a password with a one-time token; does not issue a session."""
    token = _decode_reset_token(payload.token)
    token_hash = _reset_token_hash(token)
    now = datetime.now(UTC)

    result = await db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    )
    reset_token = result.scalar_one_or_none()
    if reset_token is None:
        await _write_platform_audit(
            actor_user_id=None,
            action="auth.password_reset_token_invalid",
            request=request,
            detail={"token_hash_prefix": token_hash[:8]},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    if reset_token.expires_at < now:
        await _write_platform_audit(
            actor_user_id=reset_token.user_id,
            action="auth.password_reset_token_expired",
            request=request,
            detail={"token_hash_prefix": token_hash[:8], "user_id": str(reset_token.user_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    if reset_token.used_at is not None:
        await _write_platform_audit(
            actor_user_id=reset_token.user_id,
            action="auth.password_reset_token_reuse_attempted",
            request=request,
            detail={"token_hash_prefix": token_hash[:8], "user_id": str(reset_token.user_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    user = await UserRepository(db).get_by_id(reset_token.user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    try:
        await enforce_password_policy(
            payload.new_password,
            hibp=_hibp_checker,
        )
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.reason,
        ) from exc

    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="new password must differ from current password",
        )

    user.password_hash = hash_password(payload.new_password)
    user.security_stamp = secrets.token_urlsafe(48)
    user.last_first_party_activity_at = now
    reset_token.used_at = now
    db.add(user)
    db.add(reset_token)
    await _revoke_refresh_families_for_user(db, user.id)
    await db.commit()

    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.password_reset_completed",
        request=request,
        detail={"user_id": str(user.id)},
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: DbSession,
) -> LoginResponse:
    # Phase 17 A-7 (T979b): if a ``?next=`` query parameter is present and
    # *not* a safe same-origin target, write a platform audit row and
    # silently drop the value. The login endpoint never honours ``next=`` —
    # the response is a JSON ``LoginResponse`` body, never a 3xx redirect —
    # but auditing the rejection makes phishing attempts observable in the
    # security log so anomaly detection can flag campaigns that probe the
    # endpoint with attacker-controlled hosts.
    raw_next = request.query_params.get("next")
    if raw_next and not _is_safe_redirect_url(raw_next):
        await _write_platform_audit(
            actor_user_id=None,
            action="auth.open_redirect_rejected",
            request=request,
            detail={
                "endpoint": "auth.login",
                # Truncate to 512 chars so a hostile crawler can't bloat the
                # audit log via giant ``next=`` payloads.
                "rejected_next": raw_next[:512],
            },
        )

    email = _normalize_email(payload.email)
    repo = UserRepository(db)
    try:
        result = await authenticate(
            email=email,
            password=payload.password,
            ip=_client_ip(request),
            users=repo,
            attempts=_login_attempts,
            user_agent=_user_agent(request),
        )
    except AccountLockedError as exc:
        await _write_platform_audit(
            actor_user_id=None,
            action="auth.login_failed",
            request=request,
            detail={"reason": "backoff", "email_hash": compute_pii_hash(email)},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Invalid credentials",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except InvalidCredentialsError as exc:
        await _write_platform_audit(
            actor_user_id=None,
            action="auth.login_failed",
            request=request,
            detail={
                "reason": "invalid_credentials",
                "email_hash": compute_pii_hash(email),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        ) from exc

    user = result.user
    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.login_password_verified",
        request=request,
        detail={"user_id": str(user.id)},
    )
    if TwoFactorService.is_two_factor_required(user):
        return LoginResponse(
            login_state="2fa_setup_required",
            interim_token=_issue_interim_token(user=user, scope="2fa_setup"),
        )
    return LoginResponse(
        login_state="2fa_required",
        interim_token=_issue_interim_token(user=user, scope="2fa_challenge"),
    )


@router.post("/2fa/setup/totp", response_model=TotpSetupResponse)
async def setup_totp(
    payload: TotpSetupRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> TotpSetupResponse:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    user, _claims = await _consume_interim_token_for_user(
        raw_token=payload.interim_token,
        expected_scope="2fa_setup",
        request=request,
        db=db,
    )
    if user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA already enabled",
        )

    try:
        artifacts = await TwoFactorService(
            db,
            await get_redis_connection(),
        ).begin_enrollment(user)
    except TwoFactorAlreadyEnabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA already enabled",
        ) from exc

    return TotpSetupResponse(
        secret=artifacts.secret,
        provisioning_uri=artifacts.provisioning_uri,
        issuer=ISSUER_NAME,
        account_name=user.email,
        next_interim_token=_issue_interim_token(
            user=user,
            scope="2fa_setup_confirm",
        ),
    )


@router.post(
    "/2fa/setup/totp/confirm",
    response_model=TotpSetupConfirmResponse,
    responses={
        # Phase 17 contract drift cleanup: contracts/auth.yaml declares
        # 204. The live endpoint returns 200 with a body containing the
        # access token + backup codes — clients depend on the body, so
        # the wire status_code MUST stay at 200. Only the contract
        # declaration is widened here.
        204: {"description": "Enrollment confirmed (declared per contract)"},
    },
)
async def setup_totp_confirm(
    payload: TotpSetupConfirmRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> TotpSetupConfirmResponse:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    user, _claims = await _consume_interim_token_for_user(
        raw_token=payload.interim_token,
        expected_scope="2fa_setup_confirm",
        request=request,
        db=db,
    )
    if user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA already enabled",
        )

    try:
        backup_codes = await TwoFactorService(
            db,
            await get_redis_connection(),
        ).confirm_enrollment(user, payload.secret, payload.totp_code)
    except TwoFactorAlreadyEnabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA already enabled",
        ) from exc
    except TwoFactorInvalidCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP code",
        ) from exc
    except TwoFactorRateLimitedError as exc:
        raise _rate_limit_response(TOTP_FAIL_WINDOW_SECONDS) from exc

    access_token = await _issue_real_session(response=response, user=user, db=db)
    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.two_factor_enrolled_via_login",
        request=request,
        detail={"user_id": str(user.id)},
    )
    await _record_login_notification(user=user, request=request)
    return TotpSetupConfirmResponse(
        backup_codes=backup_codes,
        access_token=access_token,
        expires_in=settings.web_access_token_ttl_seconds,
    )


@router.post(
    "/2fa/challenge",
    response_model=TwoFactorChallengeResponse,
    responses={
        # Phase 17 contract drift cleanup: declare codes raised at runtime
        # by TwoFactorService — invalid code (401) and rate-limit (429).
        # Wire status_code remains 200 on success.
        401: {"description": "Invalid 2FA code"},
        429: {"description": "Too many invalid attempts (rate limited)"},
    },
)
async def two_factor_challenge(
    payload: TwoFactorChallengeRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> TwoFactorChallengeResponse:
    user, _claims = await _consume_interim_token_for_user(
        raw_token=payload.interim_token,
        expected_scope="2fa_challenge",
        request=request,
        db=db,
    )
    if not user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA setup required",
        )

    service = TwoFactorService(db, await get_redis_connection())
    try:
        if payload.method == "totp":
            verified = await service.verify_totp(user, payload.code)
        else:
            verified = await service.verify_backup_code(user, payload.code)
    except TwoFactorNotEnabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="2FA setup required",
        ) from exc
    except TwoFactorLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="2FA temporarily locked",
            headers={"Retry-After": str(TOTP_LOCK_SECONDS)},
        ) from exc
    except TwoFactorRateLimitedError as exc:
        retry_after = (
            TOTP_FAIL_WINDOW_SECONDS
            if payload.method == "totp"
            else BACKUP_FAIL_WINDOW_SECONDS
        )
        raise _rate_limit_response(retry_after) from exc
    except TwoFactorInvalidCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid 2FA code",
        ) from exc

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid 2FA code",
        )

    access_token = await _issue_real_session(response=response, user=user, db=db)
    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.two_factor_challenge_succeeded",
        request=request,
        detail={"method": payload.method},
    )
    await _record_login_notification(user=user, request=request)
    return TwoFactorChallengeResponse(
        access_token=access_token,
        expires_in=settings.web_access_token_ttl_seconds,
    )


@router.post(
    "/2fa/webauthn/register",
    response_model=WebAuthnRegisterBeginResponse | WebAuthnRegisterCompleteResponse,
    responses={
        # Phase 17 contract drift cleanup: contracts/auth.yaml declares
        # 201 Created for the credential-completion path. The live
        # endpoint returns 200 with a body (the registered credential
        # metadata) — clients depend on the body, so the wire
        # status_code stays at 200. Only the contract declaration is
        # widened here.
        201: {"description": "Credential registered (declared per contract)"},
    },
)
async def webauthn_register(
    payload: WebAuthnRegisterRequest,
    request: Request,
    db: DbSession,
) -> WebAuthnRegisterBeginResponse | WebAuthnRegisterCompleteResponse:
    """Begin or complete WebAuthn registration.

    Endpoint-level failure audits supplement service-level WebAuthn audits so
    mocked service failures and route-specific exits are still visible in the
    platform audit stream.
    """
    if payload.credential is None:
        user, _claims = await _consume_interim_token_for_user_with_scopes(
            raw_token=payload.interim_token,
            expected_scopes=("webauthn_register", "2fa_setup_confirm"),
            request=request,
            db=db,
        )
        await _require_superuser(db, user.id)
        existing = await _superuser_credential_store.get_credentials(user.id)
        options = await webauthn_service.begin_registration(
            user_id=user.id,
            user_email=user.email,
            existing_credentials=existing,
        )
        return WebAuthnRegisterBeginResponse(
            options=_serialize_webauthn_options(options),
            next_interim_token=_issue_interim_token(
                user=user,
                scope="webauthn_register_complete",
                ttl_seconds=settings.webauthn_interim_token_ttl_seconds,
            ),
        )

    user, _claims = await _consume_interim_token_for_user(
        raw_token=payload.interim_token,
        expected_scope="webauthn_register_complete",
        request=request,
        db=db,
    )
    await _require_superuser(db, user.id)
    existing = await _superuser_credential_store.get_credentials(user.id)
    try:
        credential = await webauthn_service.complete_registration(
            user_id=user.id,
            registration_response=payload.credential,
            existing_credentials=existing,
        )
    except WebAuthnVerificationError as exc:
        await _write_platform_audit(
            actor_user_id=user.id,
            action="auth.webauthn_registration_failed",
            request=request,
            detail={"user_id": str(user.id)},
        )
        raise _webauthn_http_error(exc) from exc
    except WebAuthnDuplicateCredentialError as exc:
        await _write_platform_audit(
            actor_user_id=user.id,
            action="auth.webauthn_duplicate_credential_rejected",
            request=request,
            detail={"user_id": str(user.id)},
        )
        raise _webauthn_http_error(exc) from exc
    except WebAuthnChallengeNotFoundError as exc:
        raise _webauthn_http_error(exc) from exc

    if payload.name is not None:
        credential["name"] = payload.name
    await _superuser_credential_store.save_credentials(user.id, [*existing, credential])
    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.webauthn_credential_registered",
        request=request,
        detail={"credential_id": credential["credential_id"]},
    )
    return WebAuthnRegisterCompleteResponse(
        credential_id=credential["credential_id"],
        name=credential["name"],
        registered_at=credential["registered_at"],
    )


@router.post(
    "/2fa/webauthn/challenge",
    response_model=WebAuthnChallengeBeginResponse | WebAuthnChallengeCompleteResponse,
)
async def webauthn_challenge(
    payload: WebAuthnChallengeRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> WebAuthnChallengeBeginResponse | WebAuthnChallengeCompleteResponse:
    """Begin or complete WebAuthn auth.

    Endpoint-level failure/replay audits supplement service-level WebAuthn
    audits so mocked service failures and route-specific exits are still
    visible in the platform audit stream.
    """
    if payload.credential is None:
        user, _claims = await _consume_interim_token_for_user(
            raw_token=payload.interim_token,
            expected_scope="2fa_challenge",
            request=request,
            db=db,
        )
        await _require_superuser(db, user.id)
        existing = await _superuser_credential_store.get_credentials(user.id)
        options = await webauthn_service.begin_authentication(
            user_id=user.id,
            existing_credentials=existing,
        )
        return WebAuthnChallengeBeginResponse(
            options=_serialize_webauthn_options(options),
            next_interim_token=_issue_interim_token(
                user=user,
                scope="webauthn_challenge_complete",
                ttl_seconds=settings.webauthn_interim_token_ttl_seconds,
            ),
        )

    user, _claims = await _consume_interim_token_for_user(
        raw_token=payload.interim_token,
        expected_scope="webauthn_challenge_complete",
        request=request,
        db=db,
    )
    await _require_superuser(db, user.id)
    existing = await _superuser_credential_store.get_credentials(user.id)
    try:
        updated = await webauthn_service.complete_authentication(
            user_id=user.id,
            authentication_response=payload.credential,
            existing_credentials=existing,
        )
    except WebAuthnReplayDetectedError as exc:
        await _write_platform_audit(
            actor_user_id=user.id,
            action="auth.webauthn_replay_detected",
            request=request,
            detail={"user_id": str(user.id)},
        )
        raise _webauthn_http_error(exc) from exc
    except WebAuthnVerificationError as exc:
        await _write_platform_audit(
            actor_user_id=user.id,
            action="auth.webauthn_authentication_failed",
            request=request,
            detail={"user_id": str(user.id)},
        )
        raise _webauthn_http_error(exc) from exc
    except WebAuthnChallengeNotFoundError as exc:
        raise _webauthn_http_error(exc) from exc

    await _superuser_credential_store.save_credentials(
        user.id,
        _replace_stored_credential(existing, updated),
    )
    access_token = await _issue_real_session(response=response, user=user, db=db)
    # Phase 16 Batch 6g-3: bind a short-lived step-up token to the
    # WebAuthn assertion that just succeeded. Destructive admin
    # endpoints require this token via ``X-Step-Up-Token``.
    step_up_token, step_up_expires_at = issue_step_up_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
        assertion_id=updated["credential_id"],
        scope=SCOPE_ADMIN_DESTRUCTIVE,
        ttl_seconds=STEP_UP_TOKEN_TTL_SECONDS,
    )
    # Mirror the token on the response header so SPA fetch wrappers can
    # capture it without parsing the body. Body still carries it for
    # SSR / non-fetch callers.
    response.headers[STEP_UP_HEADER_NAME] = step_up_token
    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.webauthn_authentication_succeeded",
        request=request,
        detail={"credential_id": updated["credential_id"]},
    )
    await _record_login_notification(user=user, request=request)
    return WebAuthnChallengeCompleteResponse(
        access_token=access_token,
        expires_in=settings.web_access_token_ttl_seconds,
        step_up_token=step_up_token,
        step_up_expires_at=step_up_expires_at.isoformat(),
        step_up_scope=SCOPE_ADMIN_DESTRUCTIVE,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    db: DbSession,
) -> RefreshResponse | JSONResponse:
    raw_token = request.cookies.get(settings.web_refresh_cookie_name)
    if not raw_token:
        # No cookie at all — nothing to clear, behave as before.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found",
        )

    claims = _decode_web_refresh_token(raw_token)
    store = SqlTokenStore(AsyncSessionLocal)

    if await store.is_family_revoked(claims.family_id):
        # Family was previously revoked — clear marker + session cookies
        # so the frontend hooks stop trusting `echoroo_logged_in`.
        return _failed_refresh_response("Invalid refresh token")

    user = await UserRepository(db).get_by_id(claims.user_id)
    if user is None:
        await store.revoke_family(claims.family_id)
        return _failed_refresh_response("Invalid refresh token")
    if not secrets.compare_digest(claims.security_stamp, user.security_stamp):
        await store.revoke_family(claims.family_id)
        return _failed_refresh_response("Invalid refresh token")

    new_refresh_token, new_record = _issue_web_refresh_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
        family_id=claims.family_id,
    )
    swapped = await store.atomic_consume_and_issue(
        family_id=claims.family_id,
        old_jti=claims.jti,
        new_record=new_record,
    )
    if not swapped:
        await store.revoke_family(claims.family_id)
        await _write_platform_audit(
            actor_user_id=claims.user_id,
            action="auth.refresh_token_reuse_detected",
            request=request,
            detail={"family_id": claims.family_id, "reused_jti": claims.jti},
        )
        return _failed_refresh_response("Invalid refresh token")

    access_token = issue_access_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
        ttl=timedelta(seconds=settings.web_access_token_ttl_seconds),
    )
    user.last_first_party_activity_at = datetime.now(UTC)
    db.add(user)
    await db.commit()

    _set_session_cookies(
        response,
        refresh_token=new_refresh_token,
        family_id=claims.family_id,
    )
    return RefreshResponse(
        access_token=access_token,
        expires_in=settings.web_access_token_ttl_seconds,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
) -> Response:
    """Idempotent session termination.

    The endpoint is registered in :data:`PUBLIC_AUTH_PATHS` so it
    bypasses both the auth router cookie-required guard and the CSRF
    middleware. Rationale (Phase 4-5-6 #1):

    * **CSRF exemption is safe.** Logout is a fully idempotent,
      one-way operation — the worst-case forced-logout scenario
      simply interrupts the victim's session without granting the
      attacker any capability. OWASP's CSRF cheat sheet documents
      logout as a standard CSRF-exempt endpoint for this reason.
    * **Idempotency is required.** The SvelteKit hook marker cookie
      ``echoroo_logged_in`` is ``HttpOnly`` and can only be cleared
      by the server. If logout were to refuse calls without a live
      session cookie (e.g. 401), a client whose session/CSRF cookies
      have already been evicted (refresh failure, partial cookie
      eviction, etc.) would be permanently wedged — the browser
      would still display the marker and the user would have no way
      to call any other endpoint to clear it. Returning 204 even
      when no ``family_id`` cookie is present guarantees the client
      can always drive itself back to a clean logged-out state.
    * **Residual CSRF risk is acceptable.** The session/CSRF cookies
      are issued with ``SameSite=Lax`` (or ``Strict`` depending on
      deployment), which already prevents the most common cross-site
      logout-CSRF vectors (top-level navigations from third-party
      sites only carry the cookie when ``SameSite=Lax`` is in effect,
      and even then a cross-origin ``fetch`` is blocked). Combined
      with logout's idempotency and the fact that it has no
      destructive side-effect beyond ending the victim's own session,
      the residual CSRF surface is low enough to justify exempting
      this single endpoint from the CSRF token requirement.
    """
    family_id = request.cookies.get(settings.web_session_cookie_name)
    revoked = False
    revoke_error: str | None = None
    if family_id:
        try:
            store = SqlTokenStore(AsyncSessionLocal)
            await store.revoke_family(family_id)
            revoked = True
        except Exception as exc:  # noqa: BLE001 - logout MUST stay idempotent
            # A malformed/forged family_id cookie (e.g. arbitrary string,
            # truncated UUID) MUST NOT prevent the client from clearing
            # its cookies and recovering. We log the failure for
            # forensics but still return 204 with cookies cleared.
            logger.info(
                "auth.logout: revoke_family failed; continuing with idempotent "
                "cookie clear: %s",
                exc.__class__.__name__,
            )
            revoke_error = exc.__class__.__name__

    audit_detail: dict[str, Any]
    if revoked:
        audit_detail = {"family_id": family_id}
    elif family_id:
        audit_detail = {
            "family_id": family_id,
            "reason": "revoke_failed",
            "error_class": revoke_error,
        }
    else:
        # Audit the no-op too so forensics can distinguish a client
        # that called logout with no session (recovery path) from a
        # caller that successfully revoked a live family.
        audit_detail = {"family_id": None, "reason": "no_session_cookie"}
    try:
        await _write_platform_audit(
            actor_user_id=None,
            action="auth.logout",
            request=request,
            detail=audit_detail,
        )
    except Exception as exc:  # noqa: BLE001 - logout MUST stay idempotent
        logger.warning(
            "auth.logout: audit write failed; continuing with cookie clear: %s",
            exc.__class__.__name__,
        )
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
