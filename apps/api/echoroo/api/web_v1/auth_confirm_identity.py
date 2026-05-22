"""``/web-api/v1/auth/confirm-identity-for-2fa-reset/*`` endpoints (A-11).

Phase 17 backlog A-11. Two endpoints back the user-facing half of the
admin 2FA reset workflow:

1. ``POST /confirm-identity-for-2fa-reset``
   * Body: ``{"email": "user@example.com"}``.
   * Response: **always 202 Accepted** (enumeration defence — mirrors
     A-6 / password reset). For known accounts we issue a magic-link
     token and dispatch it via Resend.
2. ``POST /confirm-identity-for-2fa-reset/redeem``
   * Body: ``{"magic_token": "..."}``.
   * Response: ``{"confirmation_token": "...", "expires_at": "..."}``.
   * Atomically consumes the magic link and mints a short-lived HMAC
     confirmation token (5 min TTL, one-time-use). The support agent
     then pastes this into the admin reset form.

Rate limiting: per-IP and per-email-hash sliding windows. The audit
chain captures every state transition so a brute-force attempt is
visible in ``platform_audit_log`` even when the response stays 202.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from echoroo.core.database import AsyncSessionLocal, DbSession
from echoroo.core.kms import compute_pii_hash
from echoroo.core.text import has_control_chars
from echoroo.repositories.user import UserRepository
from echoroo.services.audit_service import AuditLogService
from echoroo.services.two_factor_reset_service import (
    AUDIT_ACTION_TOKEN_REDEEMED,
    MagicLinkInvalidError,
    issue_magic_link,
    redeem_magic_link,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Rate limiter — sliding window keyed by IP and email hash. Mirrors the
# A-6 (password reset) helper structure: two scopes, both must be under
# the limit. We deliberately keep it process-local for parity with the
# existing register helper; production tuning lives in research.md.
# ---------------------------------------------------------------------------

_REQUEST_WINDOW_SECONDS: Final[float] = 600.0  # 10 min
_REQUEST_IP_LIMIT: Final[int] = 10
_REQUEST_EMAIL_LIMIT: Final[int] = 3
_request_windows: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:500]


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or ""


def _rate_limit_check(*, ip: str, email_hash: str) -> bool:
    """Return ``True`` when the request should be silently dropped."""
    now = time.monotonic()
    cutoff = now - _REQUEST_WINDOW_SECONDS
    scopes = (
        (f"2fa_reset_request:ip:{ip}", _REQUEST_IP_LIMIT),
        (f"2fa_reset_request:email:{email_hash}", _REQUEST_EMAIL_LIMIT),
    )
    for key, limit in scopes:
        window = [t for t in _request_windows.get(key, []) if t >= cutoff]
        if len(window) >= limit:
            _request_windows[key] = window
            return True
        window.append(now)
        _request_windows[key] = window
    return False


def _normalize_email(raw: str) -> str | None:
    if not isinstance(raw, str):
        return None
    normalized = unicodedata.normalize("NFKC", raw).strip()
    if has_control_chars(normalized):
        return None
    try:
        validated = validate_email(
            normalized,
            allow_smtputf8=True,
            check_deliverability=False,
        )
    except EmailNotValidError:
        return None
    return validated.normalized.lower()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ConfirmIdentityRequest(BaseModel):
    """Body for the magic-link request endpoint."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=320)


class ConfirmIdentityRedeemRequest(BaseModel):
    """Body for the magic-link redeem endpoint."""

    model_config = ConfigDict(extra="forbid")

    magic_token: str = Field(min_length=1, max_length=512)


class ConfirmIdentityRedeemResponse(BaseModel):
    """Response payload for the redeem endpoint."""

    confirmation_token: str
    expires_at: datetime


# ---------------------------------------------------------------------------
# POST /confirm-identity-for-2fa-reset
# ---------------------------------------------------------------------------


@router.post(
    "/confirm-identity-for-2fa-reset",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a 2FA reset magic link (A-11, FR-072)",
    description=(
        "Always returns 202 Accepted to prevent account enumeration. "
        "When the email matches a real account, a short-lived (30 min) "
        "magic link is persisted server-side (spec/011 §FR-011-005 "
        "removed the outbound-email dispatch). The user receives the "
        "link out-of-band, clicks it, the redeem endpoint mints a "
        "confirmation token, and the support agent pastes it into "
        "POST /admin/users/{userId}/reset-2fa."
    ),
)
async def request_confirm_identity(
    payload: ConfirmIdentityRequest,
    request: Request,
    db: DbSession,
) -> Response:
    started_at = time.monotonic()
    normalized = _normalize_email(payload.email)
    email_hash = compute_pii_hash(normalized) if normalized else "<invalid>"

    # Rate-limit drop. We still write a single audit row so brute force
    # is visible in the platform audit log.
    if _rate_limit_check(ip=_client_ip(request), email_hash=email_hash):
        await _write_audit(
            request=request,
            actor_user_id=None,
            action="two_factor_reset.request_rate_limited",
            detail={"email_hash": email_hash},
        )
        await _sleep_for_minimum(started_at)
        return Response(status_code=status.HTTP_202_ACCEPTED)

    if normalized is None:
        await _write_audit(
            request=request,
            actor_user_id=None,
            action="two_factor_reset.request_invalid_email",
            detail={"email_hash": email_hash},
        )
        await _sleep_for_minimum(started_at)
        return Response(status_code=status.HTTP_202_ACCEPTED)

    user = await UserRepository(db).get_by_email(normalized)
    if user is None or user.deleted_at is not None or not user.two_factor_enabled:
        # No-op for unknown / deleted / un-enrolled accounts. We still
        # write the audit row so the dashboard can correlate the
        # outbound 202 with the rejection reason.
        await _write_audit(
            request=request,
            actor_user_id=None,
            action="two_factor_reset.request_unknown_or_ineligible",
            detail={"email_hash": email_hash},
        )
        await _sleep_for_minimum(started_at)
        return Response(status_code=status.HTTP_202_ACCEPTED)

    # Capture identifiers BEFORE any rollback. ``issue_magic_link`` and
    # ``db.commit()`` (or the inner ``except`` branch) may rollback the
    # AsyncSession, which expires every attribute on ``user`` and turns
    # later ``user.id`` reads into MissingGreenlet errors (i.e. the
    # endpoint would 500 instead of writing the failure audit + 202 the
    # enumeration defence requires). Pinning the UUID locally keeps the
    # post-rollback audit + success path safe.
    user_id_for_audit: UUID = user.id

    # Issue + persist the magic link. spec/011 Step 4 (T403) removed
    # the outbound-email branch from ``issue_magic_link``; the
    # remaining exception path here catches DB-level failures during
    # token-hash persistence. The audit action name +
    # ``stage="magic_link_issuance"`` label below are LEGACY from the
    # email era — the entire ``/confirm-identity-for-2fa-reset``
    # surface is removed wholesale in Step 10 (US1) alongside the
    # producer cleanup, at which point both the action constant and
    # the surrounding endpoint disappear. Keeping the labels stable
    # for now avoids a churn-only migration during the incremental
    # refactor.
    try:
        await issue_magic_link(
            db,
            user=user,
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "two_factor_reset magic link issuance failed (email_hash=%s)",
            email_hash,
        )
        # Audit + 202 — the operator will see the failure in the audit
        # log; surfacing it to the caller would defeat enumeration.
        await _write_audit(
            request=request,
            actor_user_id=user_id_for_audit,
            action="two_factor_reset.email_notification_failed",
            detail={"email_hash": email_hash, "stage": "magic_link_issuance"},
        )
        await _sleep_for_minimum(started_at)
        return Response(status_code=status.HTTP_202_ACCEPTED)

    await _write_audit(
        request=request,
        actor_user_id=user_id_for_audit,
        action="two_factor_reset.requested",
        detail={
            "email_hash": email_hash,
            "stage": "magic_link_dispatched",
            "user_id": str(user_id_for_audit),
        },
    )
    await _sleep_for_minimum(started_at)
    return Response(status_code=status.HTTP_202_ACCEPTED)


# ---------------------------------------------------------------------------
# POST /confirm-identity-for-2fa-reset/redeem
# ---------------------------------------------------------------------------


@router.post(
    "/confirm-identity-for-2fa-reset/redeem",
    response_model=ConfirmIdentityRedeemResponse,
    status_code=status.HTTP_200_OK,
    summary="Redeem a 2FA reset magic link (A-11, FR-072)",
    description=(
        "Atomically consumes the magic link and returns a short-lived "
        "(5 min) HMAC confirmation token bound to the user. The token "
        "is one-time-use; the admin reset endpoint will reject any "
        "replay with HTTP 409."
    ),
)
async def redeem_confirm_identity(
    payload: ConfirmIdentityRedeemRequest,
    request: Request,
    db: DbSession,
) -> ConfirmIdentityRedeemResponse:
    try:
        outcome = await redeem_magic_link(db, raw_token=payload.magic_token)
        await db.commit()
    except MagicLinkInvalidError as exc:
        await db.rollback()
        await _write_audit(
            request=request,
            actor_user_id=None,
            action="two_factor_reset.confirmation_token_redeem_failed",
            detail={"error": "invalid_or_expired"},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ERR_INVALID_MAGIC_LINK",
                "message": "Magic link is invalid, expired, or has already been used.",
            },
        ) from exc

    await _write_audit(
        request=request,
        actor_user_id=outcome.user_id,
        action=AUDIT_ACTION_TOKEN_REDEEMED,
        detail={
            "user_id": str(outcome.user_id),
            "expires_at": outcome.expires_at.isoformat(),
        },
    )
    return ConfirmIdentityRedeemResponse(
        confirmation_token=outcome.confirmation_token,
        expires_at=outcome.expires_at,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_MIN_RESPONSE_SECONDS: Final[float] = 0.6


async def _sleep_for_minimum(started_at: float) -> None:
    """Pad the response time so timing-based account probes are blunted."""
    import asyncio

    remaining = _MIN_RESPONSE_SECONDS - (time.monotonic() - started_at)
    if remaining > 0:
        await asyncio.sleep(remaining)


async def _write_audit(
    *,
    request: Request,
    actor_user_id: UUID | None,
    action: str,
    detail: dict[str, Any],
) -> None:
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                await AuditLogService(audit_session).write_platform_event(
                    actor_user_id=actor_user_id,
                    action=action,
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail=detail,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception:  # noqa: BLE001 — soft alert
        logger.warning(
            "two_factor_reset auth audit write failed: action=%s",
            action,
        )


__all__ = ["router"]
