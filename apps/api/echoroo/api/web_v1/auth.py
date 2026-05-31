"""First-party authentication router for ``/web-api/v1/auth``."""

# Interim token validation is centralized in `_consume_interim_token_for_user`.
# The helper verifies signature, type/scope, subject, live security stamp,
# deletion state, and one-time JTI consumption before an endpoint proceeds.

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, cast
from uuid import UUID

import httpx
import jwt
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import text
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
from echoroo.middleware.auth import CurrentUser, OptionalCurrentUser
from echoroo.middleware.csrf import CSRF_HEADER_NAME, issue_csrf_token
from echoroo.middleware.step_up import STEP_UP_HEADER_NAME
from echoroo.models.user import User
from echoroo.repositories.superuser_credentials import get_default_store
from echoroo.repositories.user import UserRepository
from echoroo.schemas.web_v1.auth import (
    LoginRequest,
    LoginResponse,
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
from echoroo.schemas.web_v1.change_password import (
    ChangePasswordRequest,
    ChangePasswordResponse,
)
from echoroo.schemas.web_v1.step_up import (
    StepUpBeginRequest,
    StepUpBeginResponse,
    StepUpCompleteRequest,
    StepUpCompleteResponse,
)
from echoroo.services import invitation_service, self_password_change
from echoroo.services.audit_service import AuditLogService
from echoroo.services.auth_service import (
    DEFAULT_RATE_LIMIT_POLICY,
    AccountLockedError,
    HibpChecker,
    HttpHibpChecker,
    InMemoryLoginAttemptRecorder,
    InvalidCredentialsError,
    PasswordPolicyError,
    authenticate,
    enforce_password_policy,
)
from echoroo.services.invitation_service import (
    InvitationAlreadyMemberError,
    InvitationConflictError,
    InvitationEmailMismatchError,
    InvitationTokenInvalidError,
    InvitationValidationError,
    accept_invitation_via_public_token,
)
from echoroo.services.login_notification_service import LoginNotificationService
from echoroo.services.step_up_challenge_service import (
    STEP_UP_CHALLENGE_TTL_SECONDS,
    StepUpChallengeMismatchError,
    StepUpChallengeNotFoundError,
)
from echoroo.services.step_up_challenge_service import (
    consume_challenge as consume_step_up_challenge,
)
from echoroo.services.step_up_challenge_service import (
    create_challenge as create_step_up_challenge,
)
from echoroo.services.step_up_token_service import (
    SCOPE_ADMIN_DESTRUCTIVE,
    SCOPE_ADMIN_RECOVERY,
    STEP_UP_TOKEN_TTL_SECONDS,
    issue_admin_recovery_step_up_token,
    issue_step_up_token,
)
from echoroo.services.trusted_device_service import TrustedDeviceService
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
        max_age=settings.web_csrf_ttl_seconds,
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


def _set_trusted_device_cookie(response: Response, *, raw_secret: str) -> None:
    response.set_cookie(
        key=settings.TRUSTED_DEVICE_COOKIE_NAME,
        value=raw_secret,
        max_age=settings.TRUSTED_DEVICE_COOKIE_TTL_SECONDS,
        path="/",
        secure=True,
        httponly=True,
        samesite="Strict",
    )


async def _maybe_issue_trusted_device(
    *,
    payload_trust_device: bool,
    device_label: str | None,
    response: Response,
    request: Request,
    user: User,
    db: DbSession,
) -> bool:
    if not payload_trust_device or not settings.TRUSTED_DEVICE_REGISTRATION_ENABLED:
        return False

    issued = await TrustedDeviceService(db).issue_device(
        user=user,
        label=device_label,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    _set_trusted_device_cookie(response, raw_secret=issued.raw_secret)
    return True


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

    # spec/011 §FR-011-001 / §FR-011-005 — the registration handler no
    # longer issues a verification token. The legacy verification
    # timestamp + required-flag response fields were removed in Step
    # 10 (T126 + T127); the ``ForcedPasswordChangeMiddleware`` and
    # admin-mediated recovery flows replace the pre-spec/011 UX.
    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.user_registered",
        request=request,
        detail={"user_id": str(user.id)},
    )
    return RegisterResponse(
        user_id=user.id,
        email=user.email,
    )


# spec/011 §FR-011-005 — the legacy self-service password-reset
# request / confirm + verify-(token) + resend endpoints were removed
# in Step 10 (T119). Self-service password recovery is replaced by the
# admin-mediated reset flow (``services/admin_password_reset.py`` +
# ``POST /web-api/v1/admin/users/{user_id}/password/reset``); the
# verification flow is removed wholesale because Echoroo no longer
# treats ``users.email`` as anything other than an operator-supplied
# login identifier (see spec.md §Summary + FR-011-002).


@router.post("/login", response_model=LoginResponse, response_model_exclude_none=True)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
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
    trusted_device_reject_reason = "disabled"
    if settings.TRUSTED_DEVICE_BYPASS_ENABLED:
        recent_failures = await _login_attempts.recent_failures(
            email=email,
            ip=_client_ip(request),
            window_seconds=DEFAULT_RATE_LIMIT_POLICY.window_seconds,
            now=datetime.now(UTC),
        )
        evaluation = await TrustedDeviceService(db).evaluate_login_bypass(
            user=user,
            raw_secret=request.cookies.get(settings.TRUSTED_DEVICE_COOKIE_NAME),
            recent_password_failure=recent_failures.failure_count > 0,
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
        if evaluation.accepted:
            await _write_platform_audit(
                actor_user_id=user.id,
                action="auth.trusted_device_bypass_accepted",
                request=request,
                detail={"user_id": str(user.id)},
            )
            access_token = await _issue_real_session(response=response, user=user, db=db)
            await _record_login_notification(user=user, request=request)
            return LoginResponse(
                login_state="complete",
                access_token=access_token,
                expires_in=settings.web_access_token_ttl_seconds,
                trusted_device_used=True,
            )
        trusted_device_reject_reason = evaluation.reject_reason or "unknown"

    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.trusted_device_bypass_rejected",
        request=request,
        detail={
            "user_id": str(user.id),
            "reason": trusted_device_reject_reason,
        },
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
    trusted_device_created = await _maybe_issue_trusted_device(
        payload_trust_device=payload.trust_device,
        device_label=payload.device_label,
        response=response,
        request=request,
        user=user,
        db=db,
    )
    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.two_factor_enrolled_via_login",
        request=request,
        detail={
            "user_id": str(user.id),
            "trusted_device_created": trusted_device_created,
        },
    )
    await _record_login_notification(user=user, request=request)
    return TotpSetupConfirmResponse(
        backup_codes=backup_codes,
        access_token=access_token,
        expires_in=settings.web_access_token_ttl_seconds,
        trusted_device_created=trusted_device_created,
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
    trusted_device_created = await _maybe_issue_trusted_device(
        payload_trust_device=payload.trust_device,
        device_label=payload.device_label,
        response=response,
        request=request,
        user=user,
        db=db,
    )
    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.two_factor_challenge_succeeded",
        request=request,
        detail={
            "method": payload.method,
            "trusted_device_created": trusted_device_created,
        },
    )
    await _record_login_notification(user=user, request=request)
    return TwoFactorChallengeResponse(
        access_token=access_token,
        expires_in=settings.web_access_token_ttl_seconds,
        trusted_device_created=trusted_device_created,
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


# ---------------------------------------------------------------------------
# spec/011 T300 / T301 — admin_recovery step-up begin / complete.
#
# The destructive admin-recovery endpoints
# (``POST /web-api/v1/admin/users/{user_id}/reset-password`` and
# future admin 2FA disable) are gated by
# :func:`echoroo.middleware.step_up.require_step_up_token` configured
# with :data:`SCOPE_ADMIN_RECOVERY`. The verifier demands an
# AND-condition (password re-entry + 2FA challenge) recorded on the
# JWT's ``factors`` claim (FR-011-206).
#
# These two endpoints are the issuance path for that token. They are
# the only authenticated-self route in the auth surface that does NOT
# go through the interim-token ceremony: the caller already holds a
# valid first-party session cookie, and the begin / complete pair only
# re-verifies the password + a fresh 2FA code so the resulting step-up
# token represents a freshly satisfied AND-condition. The session
# cookie alone is intentionally NOT sufficient — a stolen session
# without the user's TOTP secret cannot satisfy ``complete``.
# ---------------------------------------------------------------------------


def _step_up_no_store_headers(response: Response) -> None:
    """Apply contract-mandated response headers to a step-up response.

    Both step-up endpoints carry security-sensitive material in their
    response bodies (a fresh challenge token / a 5-minute privileged
    JWT). The contract YAML mandates
    ``Cache-Control: no-store, no-cache, must-revalidate, private`` and
    a strict ``Referrer-Policy: no-referrer`` so intermediaries and
    proxies cannot retain the payload.
    """
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def _resolve_step_up_factors_required(
    user: User,
) -> list[Literal["password", "totp"]]:
    """Derive ``factors_required`` from the authenticated user's 2FA state.

    spec/011 FR-011-206 demands an AND-condition (password + 2FA). The
    initial release supports the TOTP path only — a user whose only
    second factor is WebAuthn is refused with a 409 by the begin
    handler (a separate follow-up spec covers the WebAuthn-only
    recovery path); the return type therefore narrows to the TOTP
    factor set the contract YAML now exposes.

    Returns:
        ``["password", "totp"]`` when the user has TOTP enrolled.

    Raises:
        HTTPException: 409 when the user has no compatible 2FA enrollment.
    """
    if user.two_factor_enabled and user.two_factor_secret_encrypted is not None:
        return ["password", "totp"]
    # TODO(spec/011 follow-up): once T301 grows a WebAuthn branch, return
    # ["password", "webauthn"] here when the user has registered
    # credentials but no TOTP. Until then, refuse so the frontend can
    # redirect to the WebAuthn-only recovery flow (spec/006 A-11).
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "step_up_2fa_not_enrolled",
            "message": (
                "This release supports TOTP-based step-up only. "
                "WebAuthn step-up is planned for a follow-up release; "
                "if you need admin recovery now please enable TOTP "
                "from security settings."
            ),
        },
    )


@router.post(
    "/step-up/begin",
    response_model=StepUpBeginResponse,
    summary="Begin a step-up authentication challenge (spec/011 T300)",
    responses={
        401: {"description": "Caller is not authenticated"},
        409: {"description": "User has no compatible 2FA enrollment"},
    },
)
async def step_up_begin(
    payload: StepUpBeginRequest,
    request: Request,
    response: Response,
    current_user: OptionalCurrentUser,
) -> StepUpBeginResponse:
    """Issue a step-up challenge_id + factors_required for the session user.

    The challenge state is persisted in Redis under
    ``step_up_challenge:{user_id}:{scope}`` with a 5-minute TTL. A
    fresh ``begin`` call OVERWRITES any previous in-flight challenge
    for the same scope so the caller cannot pin a stale slot.

    Authentication boundary: requires a first-party session cookie
    (resolved via :data:`OptionalCurrentUser`). Anonymous callers
    receive a uniform 401 envelope with ``error_code=auth_required``.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "auth_required",
                "message": "Step-up requires an authenticated session.",
            },
        )

    factors_required = _resolve_step_up_factors_required(current_user)

    redis = await get_redis_connection()
    challenge_id, _issued_at = await create_step_up_challenge(
        redis,
        user_id=current_user.id,
        scope=payload.scope,
        factors_required=factors_required,
        ttl_seconds=STEP_UP_CHALLENGE_TTL_SECONDS,
    )

    await _write_platform_audit(
        actor_user_id=current_user.id,
        action="auth.step_up_challenge_started",
        request=request,
        detail={
            "scope": payload.scope,
            "factors_required": factors_required,
            # ``challenge_id`` is intentionally NOT logged — the field
            # is a short-lived correlator and the audit row's
            # ``actor_user_id`` + ``request_id`` are sufficient for
            # forensics.
        },
    )

    _step_up_no_store_headers(response)
    return StepUpBeginResponse(
        challenge_id=challenge_id,
        factors_required=factors_required,
    )


@router.post(
    "/step-up/complete",
    response_model=StepUpCompleteResponse,
    summary="Complete a step-up challenge and obtain an admin_recovery token (spec/011 T301)",
    responses={
        401: {"description": "Authentication failed (wrong password / TOTP / challenge)"},
        423: {"description": "Account is in forced-change (must_change_password=true)"},
    },
)
async def step_up_complete(
    payload: StepUpCompleteRequest,
    request: Request,
    response: Response,
    db: DbSession,
    current_user: OptionalCurrentUser,
) -> StepUpCompleteResponse:
    """Verify factors and mint an ``admin_recovery``-scoped step-up token.

    Server-side invariants (security review M-1, FR-011-206):

    1. The caller's session is re-validated (``current_user`` not None).
    2. The supplied ``password`` is verified against the user's stored
       hash via :func:`echoroo.core.security.verify_password` BEFORE
       any factor flag is set in the issued JWT.
    3. The supplied ``totp_code`` is verified via
       :meth:`TwoFactorService.verify_totp` — Redis-backed rate
       limiting + lockout already applies.
    4. The matching challenge record (created by ``begin``) is consumed
       atomically: the underlying store uses ``GETDEL`` so a concurrent
       replay of the same ``challenge_id`` sees the record vanish
       between read and verify. Any mismatch in ``challenge_id`` or
       factor set fails closed.

    Only when ALL invariants hold is
    :func:`issue_admin_recovery_step_up_token` invoked with
    ``password_verified=True`` and ``second_factor="totp"``. The
    verifier middleware checks ``factors.password is True`` and
    ``factors.second_factor in {"totp","webauthn"}`` before honouring
    the token at the destructive endpoint.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "auth_required",
                "message": "Step-up requires an authenticated session.",
            },
        )

    # spec/011 FR-011-204: a user inside the forced-change window MUST
    # change their password before issuing any privileged token — the
    # admin-mediated reset endpoint is the upstream of this flow and
    # the step-up token must not extend the user's reach until the
    # forced change clears.
    if getattr(current_user, "must_change_password", False):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "error_code": "must_change_password",
                "message": (
                    "Complete the forced password change before "
                    "requesting a step-up token."
                ),
            },
        )

    # Uniform 401 envelope for every "your supplied step-up factor /
    # challenge is not acceptable" outcome. The internal reason is still
    # recorded on the platform audit trail (for forensics + lockout
    # analytics), but the external response body is intentionally
    # indistinguishable across password mismatch, TOTP mismatch,
    # challenge not found, and challenge id mismatch so the caller
    # cannot derive a side channel (e.g. password-correct + TOTP-wrong
    # vs. password-wrong + TOTP-correct → which credential to retry).
    # Exempt from this unification: anonymous caller (handled above as
    # ``auth_required``), forced-change 423, missing 2FA enrollment 409
    # (a configuration state, not a credential), TOTP lockout 423, rate
    # limit 429 — each carries operator-meaningful semantics callers
    # need to surface.
    _UNIFIED_STEP_UP_401_DETAIL: dict[str, str] = {
        "error_code": "step_up_factor_invalid",
        "message": (
            "Step-up authentication failed. Verify your password and "
            "TOTP code, then restart from begin if the issue persists."
        ),
    }

    redis = await get_redis_connection()
    try:
        factors_required = await consume_step_up_challenge(
            redis,
            user_id=current_user.id,
            scope=SCOPE_ADMIN_RECOVERY,
            # ``payload.challenge_id`` is a ``pydantic.UUID4`` instance —
            # the challenge store keys + compares as ``str`` so we
            # normalise here. ``str(uuid)`` yields the canonical
            # lower-cased dashed form, matching what ``create_challenge``
            # persisted.
            challenge_id=str(payload.challenge_id),
        )
    except StepUpChallengeNotFoundError as exc:
        await _write_platform_audit(
            actor_user_id=current_user.id,
            action="auth.step_up_complete_challenge_not_found",
            request=request,
            detail={
                "scope": SCOPE_ADMIN_RECOVERY,
                "failure_reason": "challenge_not_found",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_UNIFIED_STEP_UP_401_DETAIL,
        ) from exc
    except StepUpChallengeMismatchError as exc:
        await _write_platform_audit(
            actor_user_id=current_user.id,
            action="auth.step_up_complete_challenge_mismatch",
            request=request,
            detail={
                "scope": SCOPE_ADMIN_RECOVERY,
                "failure_reason": "challenge_mismatch",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_UNIFIED_STEP_UP_401_DETAIL,
        ) from exc

    # Defence-in-depth: refuse a completion that tries to satisfy a
    # different factor set than the one negotiated at begin time. This
    # blocks a (currently impossible) future where the client picks the
    # factor shape based on local state and races a 2FA disable on
    # another session. Carries a distinct 409 because the caller cannot
    # repair this with credentials — they must run ``begin`` again.
    expected_factor_set = {"password", "totp"}
    if set(factors_required) != expected_factor_set:
        await _write_platform_audit(
            actor_user_id=current_user.id,
            action="auth.step_up_complete_factor_mismatch",
            request=request,
            detail={"expected": sorted(expected_factor_set), "got": factors_required},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "step_up_factor_set_changed",
                "message": (
                    "Step-up factor set changed between begin and "
                    "complete; restart from begin."
                ),
            },
        )

    # Round 2 blocker C — timing-oracle defence. The previous control
    # flow verified the password first and only ran TOTP verification
    # when the password matched, so a stolen-session attacker could
    # observe a ~argon2-hash-cost timing delta between
    # (password_correct, totp_wrong) and (password_wrong, totp_wrong)
    # and treat that delta as a password oracle. To remove the side
    # channel, BOTH factors are now verified on every call regardless
    # of whether the other factor succeeded; the AND-condition is
    # collapsed at the very end so only a single bit ("any factor
    # failed") leaks via the unified 401 envelope. Side effects
    # specific to TOTP (failure counters, audit, lockout) intentionally
    # still apply uniformly per attempt so the existing lockout
    # threshold is honoured even when the caller never knew a valid
    # password.
    #
    # M-1 invariant unchanged: ``factors.password=True`` is only encoded
    # into the issued JWT when ``password_ok`` AND ``totp_ok`` are both
    # true. The verify_password / verify_totp calls below cannot be
    # short-circuited.

    # Always verify the password. Returns False on mismatch — no
    # exception path, so no early branch is possible.
    password_ok = verify_password(
        payload.factors.password, current_user.password_hash
    )

    # Always verify the TOTP code. Operationally-meaningful exceptions
    # (no-2FA / locked / rate-limited) are still surfaced with their
    # distinct status codes per spec — they are configuration states the
    # caller cannot fix by retrying credentials, and forcing them
    # through the unified 401 envelope would hide the operator-
    # actionable signal. ``TwoFactorInvalidCodeError`` and a plain
    # ``False`` return both collapse into ``totp_ok = False`` so they
    # cannot be distinguished externally from a wrong password.
    two_factor = TwoFactorService(db, await get_redis_connection())
    totp_ok = False
    try:
        totp_ok = await two_factor.verify_totp(
            current_user, payload.factors.totp_code
        )
    except TwoFactorNotEnabledError as exc:
        # Distinct 409: caller had TOTP at begin time but lost it before
        # complete (e.g. concurrent 2FA disable). Surfaced separately so
        # the frontend can route to the re-enrollment flow rather than
        # ask the user to retry credentials they cannot fix. The
        # operator-meaningful semantics dominate the timing-oracle
        # concern here: a stolen-session attacker who reaches this
        # branch has already learned the session user disabled 2FA from
        # the public 2FA-status surface, so the 409 leaks nothing new.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "step_up_2fa_not_enrolled",
                "message": "2FA was disabled mid-flow; restart from begin.",
            },
        ) from exc
    except TwoFactorLockedError as exc:
        # Distinct 423 with Retry-After: lockout is operationally
        # meaningful — caller must wait, not retry credentials.
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "error_code": "two_factor_locked",
                "message": "Too many TOTP failures; try again later.",
            },
            headers={"Retry-After": str(TOTP_LOCK_SECONDS)},
        ) from exc
    except TwoFactorRateLimitedError as exc:
        # Distinct 429: caller needs the Retry-After to back off.
        raise _rate_limit_response(TOTP_FAIL_WINDOW_SECONDS) from exc
    except TwoFactorInvalidCodeError:
        # TOTP mismatch surfaced by the service. Fall through to the
        # unified-401 gate below with ``totp_ok = False`` so it is
        # indistinguishable from a password mismatch externally.
        totp_ok = False

    if not (password_ok and totp_ok):
        # Internal ``failure_reason`` captures BOTH factor outcomes so
        # forensics / lockout analytics retain the full picture. The
        # external response body is the unified envelope only.
        if not password_ok and not totp_ok:
            failure_reason = "both_fail"
        elif not password_ok:
            failure_reason = "password_mismatch"
        else:
            failure_reason = "totp_mismatch"
        await _write_platform_audit(
            actor_user_id=current_user.id,
            action="auth.step_up_complete_factors_failed",
            request=request,
            detail={
                "scope": SCOPE_ADMIN_RECOVERY,
                "failure_reason": failure_reason,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_UNIFIED_STEP_UP_401_DETAIL,
        )

    # All invariants satisfied — mint the token. The ``assertion_id``
    # carried by the WebAuthn path is replaced here by a UUID4 because
    # the TOTP variant has no comparable ceremony id; the security
    # stamp binding still pins the token to the current session.
    step_up_token, step_up_expires_at = issue_admin_recovery_step_up_token(
        user_id=current_user.id,
        security_stamp=current_user.security_stamp,
        assertion_id=str(uuid.uuid4()),
        password_verified=True,
        second_factor="totp",
        ttl_seconds=STEP_UP_TOKEN_TTL_SECONDS,
    )

    await _write_platform_audit(
        actor_user_id=current_user.id,
        action="auth.step_up_challenge_completed",
        request=request,
        detail={
            "scope": SCOPE_ADMIN_RECOVERY,
            "second_factor": "totp",
            # ``step_up_token`` is intentionally NOT logged — it is the
            # credential the response carries.
        },
    )

    _step_up_no_store_headers(response)
    return StepUpCompleteResponse(
        step_up_token=step_up_token,
        expires_at=step_up_expires_at.isoformat(),
        scope_set=[SCOPE_ADMIN_RECOVERY],
    )


async def _handle_change_password(
    *,
    payload: ChangePasswordRequest,
    request: Request,
    db: DbSession,
    current_user: User,
    response: Response | None = None,
    issue_session_cookies: bool = False,
) -> ChangePasswordResponse:
    """Shared self-service change-password handler (spec/011 T320).

    Invoked by BOTH ``POST /web-api/v1/auth/change-password`` and its v1
    mirror ``POST /api/v1/auth/change-password`` so the two surfaces are
    identical by construction. All credential handling is delegated to
    :func:`echoroo.services.self_password_change.change_password`; this
    helper only maps the service's typed exceptions onto the HTTP error
    envelopes documented in the contract YAML.

    Error mapping:
      * wrong current password OR expired temp password → 401
        ``current_password_invalid`` (the two are intentionally
        indistinguishable so the response cannot be used as an oracle).
      * reusing the current password → 400 ``password_reused``.
      * new password fails the shared NIST/HIBP policy → 422
        ``password_policy_violation`` (carries the policy reason).

    Current-session survival (FR-011-205)
    -------------------------------------
    ``self_password_change.change_password`` rotates
    ``users.security_stamp`` to invalidate every OTHER outstanding session
    (refresh tokens, step-up tokens, trusted devices). That rotation also
    invalidates the CALLER's own access token — whose ``ss`` claim now
    mismatches the live stamp — so the very next request would 419
    (``session_revoked``) and soft-lock the user who just changed their
    own password. FR-011-205 requires the current session to be KEPT.

    To satisfy that, on success we mint a FRESH access token carrying the
    rotated stamp and return it in the response body so the caller swaps
    its in-memory / Bearer token seamlessly. For the BFF surface
    (``issue_session_cookies=True``) we ALSO re-issue the session /
    refresh / CSRF cookies via :func:`_set_session_cookies` (new family,
    new stamp) so the cookie surface stays coherent — the prior refresh
    family carried the old stamp and would otherwise be unusable. Net
    effect: the current session continues; all OTHER sessions remain
    invalidated.
    """
    try:
        await self_password_change.change_password(
            db,
            user=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
            hibp=_hibp_checker,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except self_password_change.CurrentPasswordMismatchError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "current_password_invalid",
                "message": (
                    "Current password is incorrect, or the temporary "
                    "password has expired."
                ),
            },
        ) from exc
    except self_password_change.NewPasswordReusedError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "password_reused",
                "message": (
                    "New password must be different from the current "
                    "password."
                ),
            },
        ) from exc
    except PasswordPolicyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "password_policy_violation",
                "message": exc.reason,
            },
        ) from exc

    # The service flushed the User update + trusted-device revocations
    # into the caller's transaction (including the new ``security_stamp``);
    # commit so they are durable. The audit row already committed in its
    # own fresh session inside the service.
    await db.commit()

    # Re-issue the caller's CURRENT session with the rotated stamp
    # (FR-011-205). ``current_user.security_stamp`` now holds the new
    # value (the service mutated the live ORM instance before commit).
    new_access_token = issue_access_token(
        user_id=current_user.id,
        security_stamp=current_user.security_stamp,
        ttl=timedelta(seconds=settings.web_access_token_ttl_seconds),
    )

    if issue_session_cookies and response is not None:
        # BFF cookie surface: start a brand-new refresh family bound to
        # the rotated stamp so the caller's cookies keep authenticating.
        # The OLD refresh family carried the old stamp and is now dead;
        # we intentionally do NOT reuse it (the stamp mismatch would make
        # ``/auth/refresh`` revoke it). Mirrors the login session-issue.
        refresh_token, refresh_record = _issue_web_refresh_token(
            user_id=current_user.id,
            security_stamp=current_user.security_stamp,
        )
        await SqlTokenStore(AsyncSessionLocal).record_issued(refresh_record)
        _set_session_cookies(
            response,
            refresh_token=refresh_token,
            family_id=refresh_record.family_id,
        )

    return ChangePasswordResponse(
        access_token=new_access_token,
        expires_in=settings.web_access_token_ttl_seconds,
    )


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    summary="Change own password and clear the forced-change flag (spec/011 T320)",
    responses={
        400: {"description": "New password is identical to the current password"},
        401: {"description": "Current password / temporary password mismatch"},
        422: {"description": "New password fails the password policy"},
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: DbSession,
    current_user: CurrentUser,
) -> ChangePasswordResponse:
    """Self-service password change (BFF cookie + CSRF surface).

    Reachable while ``must_change_password = true`` because the
    ``(POST, /web-api/v1/auth/change-password)`` tuple is on the
    :data:`echoroo.middleware.forced_password_change.DEFAULT_ALLOWLIST_METHOD_PATHS`
    request-bypass list (T321). It is NOT in
    :data:`echoroo.core.auth_paths.PUBLIC_AUTH_PATHS`, so the
    :class:`echoroo.middleware.csrf.CsrfMiddleware` and the session-cookie
    auth guard both still apply — a live session + CSRF token are
    required (security review M7).

    On success the caller's CURRENT session is RE-ISSUED with the rotated
    security stamp (FR-011-205): the session / refresh / CSRF cookies are
    refreshed (Set-Cookie) and a fresh access token is returned in the
    body so the frontend can swap its in-memory token without a 419.
    """
    return await _handle_change_password(
        payload=payload,
        request=request,
        db=db,
        current_user=current_user,
        response=response,
        issue_session_cookies=True,
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


# ===========================================================================
# spec/011 §FR-011-105..107 — TOKEN_AUTH_ONLY invitation resolver + accept
# ===========================================================================
#
# Phase 7 / US2 / T202 + T203 + T206 + T208. Two endpoints:
#
# * ``GET  /web-api/v1/auth/invitations/{token}``        — resolver
# * ``POST /web-api/v1/auth/invitations/{token}/accept`` — accept
#
# Both are classified ``TOKEN_AUTH_ONLY`` (no ``gate_action``). They are
# registered in the spec/007 public-token allowlist
# (``core/endpoint_allowlist.py``) and pattern-allowlisted in the auth
# router + CSRF middleware (added by the same step). Optional session
# cookie is honoured: when present the resolver exposes
# ``is_logged_in=true`` and ``authenticated_email_matches_bound`` so
# the frontend can route to the existing-user accept branch.
#
# Rate limit (NFR-011-006): per-IP 10/min, global 200/min, sliding
# window. Constant 300ms±50ms response timing pad on every response
# (success + invalid) so timing oracles cannot probe.
# ---------------------------------------------------------------------------


_INVITATION_PUBLIC_WINDOW_SECONDS: Final[int] = 60
_INVITATION_PUBLIC_IP_LIMIT: Final[int] = 10
_INVITATION_PUBLIC_GLOBAL_LIMIT: Final[int] = 200
_INVITATION_PUBLIC_RESPONSE_TARGET_MS: Final[float] = 300.0
"""Constant minimum response time (ms). FR-011-105 / FR-011-107."""


def _invitation_public_client_ip(request: Request) -> str:
    """Resolve the canonical caller IP for the spec/011 public endpoints.

    Reuses :func:`echoroo.middleware.auth_router._resolve_client_ip` (Phase
    17 A-3) so the trusted-proxy logic is identical to the API key IP
    allowlist surface: ``X-Forwarded-For`` is only honoured when the
    socket peer is in ``ECHOROO_TRUSTED_PROXY_CIDRS``; otherwise the peer
    is used directly. This blocks the spoof bypass where an attacker
    reaches the API directly (or via a misconfigured proxy that does not
    strip incoming XFF headers) and submits
    ``X-Forwarded-For: <victim_ip>`` to either consume a victim's
    per-IP rate-limit budget or to evade their own.

    Returns ``"unknown"`` only when neither XFF nor the socket peer
    resolves to a value — the rate-limit key uses the literal string so
    a flood of unknown-source requests still saturates the bucket
    (defence in depth: fail-closed against an empty IP).
    """
    from echoroo.middleware.auth_router import _resolve_client_ip

    cidrs = tuple(settings.TRUSTED_PROXY_CIDRS or ())
    resolved = _resolve_client_ip(request, trusted_proxy_cidrs=cidrs)
    return resolved or "unknown"


async def _invitation_public_rate_limit_check(*, ip: str) -> bool:
    """Return ``True`` when the caller exceeded the spec/011 rate cap.

    NFR-011-006: per-IP fixed-window 10 requests / 60 s and a global
    fixed-window 200 requests / 60 s. Both gates are evaluated and the
    request is rejected when either limit is breached. Implementation
    reuses the Phase 17 A-6 / FR-056 Redis-backed pattern: ``INCR`` +
    ``EXPIRE`` (atomic on first hit) so the counter is shared across
    every worker in the deployment.

    **Fail-closed**: any Redis fault — connection refused, timeout, OOM
    — returns ``True`` (caller treats as rate-limited and surfaces 429).
    Failing open would allow an attacker who can knock Redis offline to
    bypass the cap and run the timing-oracle / brute-force probe the
    rate-limit is meant to deny.

    spec/011 step 7 R1 P0-3: the previous process-local dict counter
    only constrained a single worker; in a multi-worker production
    deployment the effective limit was N × the documented cap. The
    Redis-backed counter restores the documented enforcement.
    """
    keys: tuple[tuple[str, int], ...] = (
        (f"invite_public:ip:{ip}", _INVITATION_PUBLIC_IP_LIMIT),
        ("invite_public:global", _INVITATION_PUBLIC_GLOBAL_LIMIT),
    )
    try:
        redis = await get_redis_connection()
    except Exception:  # noqa: BLE001 — fail-closed on any Redis fault
        logger.warning(
            "spec/011 invitation-public rate limit: Redis unavailable; "
            "failing closed (treating request as rate-limited)",
            exc_info=True,
        )
        return True
    for key, limit in keys:
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, _INVITATION_PUBLIC_WINDOW_SECONDS)
        except Exception:  # noqa: BLE001 — fail-closed on any Redis fault
            logger.warning(
                "spec/011 invitation-public rate limit: Redis incr/expire "
                "failed for key=%s; failing closed",
                key,
                exc_info=True,
            )
            return True
        if count > limit:
            return True
    return False


async def _invitation_public_sleep_for_minimum(started_at: float) -> None:
    """Pad response time to the FR-011-105 / FR-011-107 constant target.

    The constant 300ms target keeps the success / generic-invalid /
    rate-limited surfaces indistinguishable from the network's vantage
    point. Tests can monkey-patch this helper to a no-op when they
    don't care about wallclock latency.
    """
    elapsed_ms = (time.monotonic() - started_at) * 1000.0
    remaining_ms = _INVITATION_PUBLIC_RESPONSE_TARGET_MS - elapsed_ms
    if remaining_ms > 0:
        await asyncio.sleep(remaining_ms / 1000.0)


class _InvitationGenericInvalid(HTTPException):
    """Single shape for every FR-011-107 generic-invalid response.

    The 404 status code, ``ERR_INVITATION_INVALID`` envelope, and the
    body length are all identical regardless of failure cause. The
    response timing is held to the constant target by the caller's
    pad helper. The exception subclass exists so handler-level
    ``raise`` sites read as the spec's "generic invalid" intent
    rather than a bare ``HTTPException(404, ...)``.
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ERR_INVITATION_INVALID",
                "message": "invitation is no longer valid",
            },
        )


# ---------------------------------------------------------------------------
# Pydantic schemas (mirror contracts/invitation-public.yaml)
# ---------------------------------------------------------------------------


class InvitationContextResponse(BaseModel):
    """``GET /auth/invitations/{token}`` 200 body (FR-011-105)."""

    model_config = ConfigDict(extra="forbid")

    project_name: str
    role: str | None = Field(
        default=None,
        description=(
            "Project role (Member-kind) — Viewer / Member / Admin. NULL "
            "for trusted-overlay rows."
        ),
    )
    kind: str = Field(
        ...,
        description="``member`` or ``trusted``.",
    )
    bound_email: str | None = Field(
        default=None,
        description=(
            "Bound recipient email for the signup form prefill. "
            "**spec/011 step 7 R1 P0-4**: surfaced ONLY when the caller "
            "is anonymous (signup branch needs the email for the "
            "read-only form field) OR when the caller is authenticated "
            "AND ``authenticated_email_matches_bound`` is ``true`` "
            "(they already know their own email). When the caller is "
            "authenticated as a DIFFERENT user, this field is "
            "``null`` — never leak the bound recipient identity to a "
            "wrong-account session, which would convert the resolver "
            "into an email-of-invitee oracle for anyone holding a "
            "leaked invitation URL. The hashed counterpart "
            "``bound_email_hash`` is intentionally NOT surfaced by the "
            "public resolver: it lives in the admin listing endpoint "
            "only, where the caller has already passed the "
            "``MANAGE_MEMBERS`` gate."
        ),
    )
    expires_at: datetime
    is_bootstrap: bool = Field(
        default=False,
        description=(
            "True when ``ownership_transfer_on_accept`` is set (SU bootstrap)."
        ),
    )
    is_logged_in: bool
    authenticated_email_matches_bound: bool


class _AcceptTotpEnrollment(BaseModel):
    """Initial TOTP enrollment payload for the signup branch."""

    model_config = ConfigDict(extra="forbid")

    totp_secret_signed: str = Field(
        ...,
        description=(
            "Server-issued TOTP secret returned by the public-signup TOTP "
            "begin step. For spec/011 step 7 this is accepted as the "
            "plain TOTP secret string; a future revision MAY wrap it in "
            "an HMAC envelope without breaking the contract field name."
        ),
    )
    totp_initial_code: str = Field(..., min_length=6, max_length=6)


class _AcceptNewUserPayload(BaseModel):
    """New-user signup branch (FR-011-106 step 1a)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(
        ...,
        description=(
            "MUST canonicalize-equal the bound email. Mismatch → generic "
            "404 (no leak)."
        ),
    )
    password: str = Field(..., min_length=12)
    totp_enrollment: _AcceptTotpEnrollment


class _AcceptExistingUserPayload(BaseModel):
    """Existing-user accept branch (FR-011-106 step 1b)."""

    model_config = ConfigDict(extra="forbid")

    accept: bool = Field(
        ...,
        description=(
            "MUST be ``true``. The single field exists only as a guard so "
            "a misconfigured client cannot send an empty body and trip the "
            "signup branch by accident."
        ),
    )


class InvitationAcceptResponse(BaseModel):
    """``POST /auth/invitations/{token}/accept`` 201 body (FR-011-106)."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    role: str | None = None
    kind: str
    ownership_transferred: bool = False
    membership_created: bool


# ---------------------------------------------------------------------------
# GET /auth/invitations/{token} — resolver
# ---------------------------------------------------------------------------


@router.get(
    "/invitations/{token}",
    response_model=InvitationContextResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve invitation context for the landing page (FR-011-105)",
    description=(
        "TOKEN_AUTH_ONLY public endpoint. Returns the project name, bound "
        "email, role / kind, and ``is_logged_in`` / "
        "``authenticated_email_matches_bound`` flags so the frontend can "
        "route between the signup and existing-user accept branches. "
        "Failure causes (expired, revoked, already-accepted, unknown "
        "token, deleted project) collapse to the same generic 404 with "
        "constant timing (FR-011-107)."
    ),
    responses={
        404: {"description": "Generic invalid (anti-enumeration, constant timing)"},
        429: {"description": "Rate limit exceeded (NFR-011-006)"},
    },
)
async def resolve_invitation(
    token: str,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> InvitationContextResponse:
    """Resolve invitation context for the public landing page (TOKEN_AUTH_ONLY)."""
    started_at = time.monotonic()
    if await _invitation_public_rate_limit_check(
        ip=_invitation_public_client_ip(request),
    ):
        await _invitation_public_sleep_for_minimum(started_at)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="invitation rate limit exceeded",
        )

    authenticated_email = current_user.email if current_user is not None else None
    try:
        outcome = await invitation_service.resolve_invitation_for_public_token(
            db,
            signed_token=token,
            authenticated_email=authenticated_email,
        )
    except InvitationTokenInvalidError:
        await _invitation_public_sleep_for_minimum(started_at)
        raise _InvitationGenericInvalid() from None
    except Exception:
        await _invitation_public_sleep_for_minimum(started_at)
        raise

    invitation = outcome.invitation
    expires_at_aware = invitation.expires_at
    if expires_at_aware.tzinfo is None:  # pragma: no cover — DB guarantees tz-aware
        expires_at_aware = expires_at_aware.replace(tzinfo=UTC)

    role_str = invitation.role.value if invitation.role is not None else None
    matches = outcome.authenticated_email_matches

    # spec/011 step 7 R1 P0-4: branch the ``bound_email`` exposure on the
    # caller's authentication state. The bound recipient identity must
    # NEVER be surfaced to an authenticated session whose own email does
    # NOT match the invitation, or else the resolver becomes an oracle
    # "this invitation belongs to <email>" for any wrong-account caller
    # holding a leaked URL. The contract YAML's
    # ``bound_email: string | null`` shape allows omission.
    #
    # Surface ``bound_email`` when:
    # * caller is anonymous (signup branch needs the value for the
    #   read-only prefill); OR
    # * caller is authenticated AND their email matches (they already
    #   know their own email; the redundant payload simplifies the
    #   frontend's confirm screen).
    #
    # Omit (``None``) when:
    # * caller is authenticated AS A DIFFERENT identity — even one
    #   nibble of bound_email would let them confirm the invitee's
    #   address.
    if outcome.is_logged_in and matches is not True:
        bound_email_safe: str | None = None
    else:
        bound_email_safe = invitation.email or None

    body = InvitationContextResponse(
        project_name=outcome.project_name,
        role=role_str,
        kind=invitation.kind.value,
        bound_email=bound_email_safe,
        expires_at=expires_at_aware,
        is_bootstrap=invitation.ownership_transfer_on_accept,
        is_logged_in=outcome.is_logged_in,
        authenticated_email_matches_bound=bool(matches),
    )

    await _invitation_public_sleep_for_minimum(started_at)
    return body


# ---------------------------------------------------------------------------
# POST /auth/invitations/{token}/accept — accept
# ---------------------------------------------------------------------------


@router.post(
    "/invitations/{token}/accept",
    response_model=InvitationAcceptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Accept an invitation (FR-011-106)",
    description=(
        "TOKEN_AUTH_ONLY public endpoint. Body shape branches on the "
        "caller's auth state: an anonymous caller supplies a "
        "``NewUserPayload`` (email + password + TOTP enrollment); a "
        "logged-in caller supplies an ``ExistingUserPayload`` of "
        "``{accept: true}``. The endpoint atomically flips the "
        "invitation status (FR-011-106 step 2), inserts the membership "
        "row, and emits the appropriate audit action (T208). Email "
        "mismatch / expired / revoked / unknown token / deleted project "
        "all collapse to the same generic 404 with constant timing."
    ),
    responses={
        404: {"description": "Generic invalid (anti-enumeration, constant timing)"},
        409: {"description": "Caller is already a member at same/higher role"},
        429: {"description": "Rate limit exceeded (NFR-011-006)"},
    },
)
async def accept_invitation_public(
    token: str,
    request: Request,
    response: Response,
    current_user: OptionalCurrentUser,
    db: DbSession,
    payload: dict[str, Any],
) -> InvitationAcceptResponse:
    """Accept an invitation via the public-token surface.

    spec/011 step 7 R1 P0-1 + P1-1 atomic-flow contract:

    The new-user signup branch creates a User row, persists a 2FA
    credential, and atomically flips the invitation row to
    ``status='accepted'`` inside a SINGLE database transaction. If any
    of those steps fails — including the atomic UPDATE returning zero
    rows because the invitation drifted to a terminal status between
    the resolver call and the accept call — the WHOLE transaction
    rolls back so no orphan User / 2FA credential is leaked.

    Order of operations:

    1. Validate the request payload against the matching branch shape
       (anonymous → :class:`_AcceptNewUserPayload`; authenticated →
       :class:`_AcceptExistingUserPayload`).
    2. (signup only) Enforce the password policy; reject HIBP-compromised
       passwords with 422 before peeking at the invitation row.
    3. (signup only) Reject if the email is already registered. The 404
       generic-invalid surface keeps the email-existence oracle closed.
    4. (signup only) Create the User row via ``UserRepository.create``
       (flush only — no commit).
    5. (signup only) Confirm TOTP enrollment with ``commit=False`` so
       the 2FA write joins the same transaction as steps 4 and 6.
    6. Run :func:`accept_invitation_via_public_token` which performs
       the atomic ``UPDATE project_invitations SET status='accepted'
       WHERE id=:id AND status='pending' AND expires_at > now()
       RETURNING *``. Zero rows raises
       :class:`InvitationTokenInvalidError`.
    7. Commit the transaction (or rollback on any exception). On a
       successful new-user signup branch, the session-cookie issuance
       in :func:`_issue_real_session` lives AFTER the commit so a
       failed session issue cannot un-persist the membership.
    8. Emit the post-commit audit row in a fresh session.
    """
    started_at = time.monotonic()
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )

    if await _invitation_public_rate_limit_check(
        ip=_invitation_public_client_ip(request),
    ):
        await _invitation_public_sleep_for_minimum(started_at)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="invitation rate limit exceeded",
        )

    # Branch on the caller's auth state. The body shape is union'ed
    # so we validate against the matching branch and reject mismatched
    # shapes uniformly as the generic invalid 404.
    is_logged_in = current_user is not None
    try:
        new_user_payload: _AcceptNewUserPayload | None = None
        existing_user_payload: _AcceptExistingUserPayload | None = None
        if is_logged_in:
            existing_user_payload = _AcceptExistingUserPayload.model_validate(
                payload,
            )
            if not existing_user_payload.accept:
                await _invitation_public_sleep_for_minimum(started_at)
                raise _InvitationGenericInvalid()
        else:
            new_user_payload = _AcceptNewUserPayload.model_validate(payload)
    except ValueError:
        await _invitation_public_sleep_for_minimum(started_at)
        raise _InvitationGenericInvalid() from None

    # ``new_user`` is bound only on the signup branch and is consumed
    # post-commit to issue the BFF session (P1-1).
    new_user: User | None = None

    if is_logged_in:
        accepting_user_id = cast("User", current_user).id
        accepting_user_email = cast("User", current_user).email
        is_new_user_signup = False
    else:
        assert new_user_payload is not None
        # Validate password policy BEFORE peeking at the invitation so a
        # weak password is still rejected with a 422 (consistent with the
        # /register endpoint contract). The generic-invalid 404 surface
        # only applies to invitation-state failures.
        try:
            await enforce_password_policy(
                new_user_payload.password,
                hibp=_hibp_checker,
            )
        except PasswordPolicyError as exc:
            await _invitation_public_sleep_for_minimum(started_at)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.reason,
            ) from exc

        normalized_email = _normalize_email(new_user_payload.email)
        repo = UserRepository(db)
        existing_user = await repo.get_by_email(normalized_email)
        if existing_user is not None:
            # Email already registered → the caller cannot use the
            # signup branch. The frontend should sign them in and retry
            # via the existing-user branch. Collapse to the generic
            # invalid so the email-existence oracle is closed.
            await _invitation_public_sleep_for_minimum(started_at)
            raise _InvitationGenericInvalid()

        now = datetime.now(UTC)
        new_user = User(
            email=normalized_email,
            password_hash=hash_password(new_user_payload.password),
            display_name=normalized_email.split("@", 1)[0],
            security_stamp=secrets.token_urlsafe(48),
            two_factor_enabled=False,
            last_login_at=None,
            last_first_party_activity_at=now,
        )
        try:
            await repo.create(new_user)
        except IntegrityError:
            # The repository's ``flush`` raises on the email-uniqueness
            # collision (race between the ``get_by_email`` check above
            # and the INSERT). Rollback both the new row AND any prior
            # writes that the transaction may have accumulated; surface
            # the generic-invalid so the oracle remains closed.
            await db.rollback()
            await _invitation_public_sleep_for_minimum(started_at)
            raise _InvitationGenericInvalid() from None

        # P0-1: confirm TOTP enrollment WITHOUT committing the
        # transaction. The 2FA credential write joins the same TX as
        # the user INSERT above and the atomic invitation UPDATE below,
        # so a failed-or-missed invitation (e.g. the row was revoked
        # between the resolver call and this accept) rolls back the
        # whole transaction — no orphan account + 2FA row leaks.
        two_factor = TwoFactorService(db)
        try:
            await two_factor.confirm_enrollment(
                new_user,
                new_user_payload.totp_enrollment.totp_secret_signed,
                new_user_payload.totp_enrollment.totp_initial_code,
                commit=False,
            )
        except (
            TwoFactorAlreadyEnabledError,
            TwoFactorInvalidCodeError,
            TwoFactorLockedError,
            TwoFactorRateLimitedError,
        ) as exc:
            await db.rollback()
            await _invitation_public_sleep_for_minimum(started_at)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "ERR_TOTP_ENROLLMENT_INVALID",
                    "message": str(exc),
                },
            ) from exc

        accepting_user_id = new_user.id
        accepting_user_email = normalized_email
        is_new_user_signup = True

    try:
        accept_outcome = await accept_invitation_via_public_token(
            db,
            signed_token=token,
            accepting_user_id=accepting_user_id,
            accepting_user_email=accepting_user_email,
            is_new_user_signup=is_new_user_signup,
            request_id=_request_id(request),
            ip=_invitation_public_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvitationAlreadyMemberError as exc:
        await db.rollback()
        await _invitation_public_sleep_for_minimum(started_at)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_ALREADY_MEMBER",
                "message": str(exc),
            },
        ) from exc
    except (
        InvitationTokenInvalidError,
        InvitationEmailMismatchError,
        InvitationValidationError,
    ):
        # P0-1: any failure of the atomic invitation UPDATE
        # (corrupted envelope, zero-row return, email mismatch,
        # validation drift) rolls back the whole TX — including the
        # User + 2FA writes on the signup branch — so no orphan
        # account leaks to the database.
        await db.rollback()
        await _invitation_public_sleep_for_minimum(started_at)
        raise _InvitationGenericInvalid() from None
    except InvitationConflictError as exc:
        await db.rollback()
        await _invitation_public_sleep_for_minimum(started_at)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_INVITATION_CONFLICT",
                "message": str(exc),
            },
        ) from exc

    await db.commit()
    await invitation_service.emit_public_invitation_accept_audit(accept_outcome)

    # P1-1: establish a session for the new user so they land in the
    # project page already authenticated. The contract YAML's
    # ``201 Created`` response notes "for the new-user branch, a session
    # is established". ``_issue_real_session`` writes ``last_login_at``
    # on the user row + commits, then sets the refresh / session / CSRF
    # cookies. We invoke it AFTER the main commit so that a transient
    # session-issue failure (Redis fault wiping the revoked-user
    # marker, DB hiccup setting last_login_at) cannot un-persist the
    # membership that was just granted.
    if is_new_user_signup and new_user is not None:
        await _issue_real_session(response=response, user=new_user, db=db)

    invitation = accept_outcome.invitation
    role_str = invitation.role.value if invitation.role is not None else None
    body = InvitationAcceptResponse(
        project_id=invitation.project_id,
        role=role_str,
        kind=invitation.kind.value,
        ownership_transferred=accept_outcome.ownership_transferred,
        membership_created=accept_outcome.membership_created,
    )

    await _invitation_public_sleep_for_minimum(started_at)
    return body
