"""First-party authentication router for ``/web-api/v1/auth``."""

# Interim token validation is centralized in `_consume_interim_token_for_user`.
# The helper verifies signature, type/scope, subject, live security stamp,
# deletion state, and one-time JTI consumption before an endpoint proceeds.

from __future__ import annotations

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
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from webauthn.helpers import options_to_json_dict

from echoroo.core.auth import RefreshTokenRecord, SqlTokenStore, issue_access_token
from echoroo.core.database import AsyncSessionLocal, DbSession
from echoroo.core.kms import compute_pii_hash
from echoroo.core.redis import get_redis_connection
from echoroo.core.security import hash_password
from echoroo.core.settings import get_settings
from echoroo.middleware.csrf import CSRF_HEADER_NAME, issue_csrf_token
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
_WEBAUTHN_INTERIM_TTL_SECONDS = 5 * 60
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
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


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
    response.set_cookie(
        key=settings.web_csrf_cookie_name,
        value=csrf_token,
        max_age=settings.web_access_token_ttl_seconds,
        path="/web-api/v1/",
        secure=secure_cookie,
        httponly=False,
        samesite="strict",
    )
    response.headers[CSRF_HEADER_NAME] = csrf_token


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(
        key=settings.web_refresh_cookie_name,
        path="/web-api/v1/auth/refresh",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        key=settings.web_session_cookie_name,
        path="/web-api/v1/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        key=settings.web_csrf_cookie_name,
        path="/web-api/v1/",
        secure=True,
        httponly=False,
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


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: DbSession,
) -> LoginResponse:
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


@router.post("/2fa/setup/totp/confirm", response_model=TotpSetupConfirmResponse)
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
    return TotpSetupConfirmResponse(
        backup_codes=backup_codes,
        access_token=access_token,
        expires_in=settings.web_access_token_ttl_seconds,
    )


@router.post("/2fa/challenge", response_model=TwoFactorChallengeResponse)
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
    return TwoFactorChallengeResponse(
        access_token=access_token,
        expires_in=settings.web_access_token_ttl_seconds,
    )


@router.post(
    "/2fa/webauthn/register",
    response_model=WebAuthnRegisterBeginResponse | WebAuthnRegisterCompleteResponse,
)
async def webauthn_register(
    payload: WebAuthnRegisterRequest,
    request: Request,
    db: DbSession,
) -> WebAuthnRegisterBeginResponse | WebAuthnRegisterCompleteResponse:
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
                ttl_seconds=_WEBAUTHN_INTERIM_TTL_SECONDS,
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
    except (
        WebAuthnChallengeNotFoundError,
        WebAuthnDuplicateCredentialError,
        WebAuthnVerificationError,
    ) as exc:
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
                ttl_seconds=_WEBAUTHN_INTERIM_TTL_SECONDS,
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
    except (
        WebAuthnChallengeNotFoundError,
        WebAuthnReplayDetectedError,
        WebAuthnVerificationError,
    ) as exc:
        raise _webauthn_http_error(exc) from exc

    await _superuser_credential_store.save_credentials(
        user.id,
        _replace_stored_credential(existing, updated),
    )
    access_token = await _issue_real_session(response=response, user=user, db=db)
    await _write_platform_audit(
        actor_user_id=user.id,
        action="auth.webauthn_authentication_succeeded",
        request=request,
        detail={"credential_id": updated["credential_id"]},
    )
    return WebAuthnChallengeCompleteResponse(
        access_token=access_token,
        expires_in=settings.web_access_token_ttl_seconds,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    db: DbSession,
) -> RefreshResponse:
    raw_token = request.cookies.get(settings.web_refresh_cookie_name)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found",
        )

    claims = _decode_web_refresh_token(raw_token)
    store = SqlTokenStore(AsyncSessionLocal)

    if await store.is_family_revoked(claims.family_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user = await UserRepository(db).get_by_id(claims.user_id)
    if user is None:
        await store.revoke_family(claims.family_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    if not secrets.compare_digest(claims.security_stamp, user.security_stamp):
        await store.revoke_family(claims.family_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

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
    family_id = request.cookies.get(settings.web_session_cookie_name)
    if not family_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session not found",
        )

    store = SqlTokenStore(AsyncSessionLocal)
    await store.revoke_family(family_id)
    await _write_platform_audit(
        actor_user_id=None,
        action="auth.logout",
        request=request,
        detail={"family_id": family_id},
    )
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
