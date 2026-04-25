"""First-party authentication router for ``/web-api/v1/auth``."""

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
from sqlalchemy.exc import IntegrityError

from echoroo.core.auth import RefreshTokenRecord, SqlTokenStore, issue_access_token
from echoroo.core.database import AsyncSessionLocal, DbSession
from echoroo.core.security import hash_password
from echoroo.core.settings import get_settings
from echoroo.middleware.csrf import CSRF_HEADER_NAME, issue_csrf_token
from echoroo.models.user import User
from echoroo.repositories.user import UserRepository
from echoroo.schemas.web_v1.auth import (
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
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
from echoroo.services.two_factor_service import TwoFactorService

router = APIRouter(prefix="/auth", tags=["web-auth"])
settings = get_settings()

_login_attempts = InMemoryLoginAttemptRecorder()


class _HttpxHibpChecker:
    async def pwned_count(self, password: str) -> int:
        async with httpx.AsyncClient(timeout=5.0) as client:
            checker = HttpHibpChecker(http_get=client.get)
            return await checker.pwned_count(password)


_hibp_checker: HibpChecker = _HttpxHibpChecker()

_REGISTER_IP_LIMIT = 10
_REGISTER_EMAIL_LIMIT = 5
_REGISTER_WINDOW_SECONDS = 60 * 60
_register_windows: dict[str, list[float]] = {}


@dataclass(frozen=True)
class _RefreshClaims:
    user_id: UUID
    family_id: str
    jti: str
    security_stamp: str
    expires_at: datetime


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


def _issue_interim_token(*, user: User, scope: str) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.web_interim_token_ttl_seconds)
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
    response.set_cookie(
        key=settings.web_refresh_cookie_name,
        value=refresh_token,
        max_age=settings.web_refresh_token_ttl_seconds,
        path="/web-api/v1/auth/refresh",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        key=settings.web_session_cookie_name,
        value=family_id,
        max_age=settings.web_refresh_token_ttl_seconds,
        path="/web-api/v1/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        key=settings.web_csrf_cookie_name,
        value=csrf_token,
        max_age=settings.web_access_token_ttl_seconds,
        path="/web-api/v1/",
        secure=True,
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
            detail={"reason": "backoff"},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Invalid credentials",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except InvalidCredentialsError as exc:
        snapshot = await _login_attempts.recent_failures(
            email=email,
            ip=_client_ip(request),
            window_seconds=900,
            now=datetime.now(UTC),
        )
        if snapshot.failure_count % 5 == 0:
            await _write_platform_audit(
                actor_user_id=None,
                action="auth.login_failed",
                request=request,
                detail={"reason": "invalid_credentials"},
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
