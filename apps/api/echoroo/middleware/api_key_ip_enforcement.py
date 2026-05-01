"""API-key allowed-IP enforcement helpers (FR-077, FR-081, Phase 17 A-3).

Each ``api_keys`` row may carry an optional CIDR allowlist
(``allowed_ip_cidrs``). When the column is non-NULL and non-empty, every
API-key authenticated request MUST come from a source IP that falls
within at least one of the listed CIDRs. Violations:

1. Reject the request with HTTP 403 ``err_ip_not_allowed``.
2. Atomically increment ``api_keys.ip_violation_count`` (a counter
   independent from ``scope_violation_count_10min`` per FR-077: ``allowed_ips
   違反別カウンタ``).
3. After the third violation auto-revoke the key (FR-081) by setting
   ``revoked_at = now()`` and ``revoked_reason = 'ip_violation_auto_revoke'``.
4. Append a ``platform_audit_log`` row describing the violation
   (best-effort: a KMS / DB outage MUST NOT mask the 403 itself).

The helper is intentionally split out of :class:`AuthRouterMiddleware`
so that:

* The middleware can call ``enforce_api_key_ip()`` after the API-key
  verifier resolves the row, with the caller-IP / CIDRs in hand.
* Unit tests can drive the same helper against a real ``AsyncSession``
  without spinning up an HTTP stack.

The audit write is tolerant of KMS unavailability: if the keyed PII
hashing call fails (e.g. moto KMS not provisioned in a unit test) the
helper logs a warning and proceeds — the *enforcement* outcome (403 +
counter + revoke) is the security-critical contract; audit completeness
is monitored separately.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


#: Threshold at which an API key is auto-revoked after repeated IP
#: violations (FR-081 ``allowed_ips 違反別カウンタ`` 3 strikes).
IP_VIOLATION_AUTO_REVOKE_THRESHOLD: Final[int] = 3

#: Audit ``action`` value for IP allowlist violations. Mirrors the
#: ``api_key.*`` family used by the rest of the API key audit surface.
AUDIT_ACTION_IP_VIOLATION: Final[str] = "api_key.ip_violation"

#: Audit ``action`` value emitted alongside the third (revoking)
#: violation so the audit reader can surface the lifecycle event.
AUDIT_ACTION_AUTO_REVOKE: Final[str] = "api_key.auto_revoke_ip_violation"

#: Reason string persisted on ``api_keys.revoked_reason`` when the
#: enforcement helper auto-revokes the key. Free-form ASCII < 100 chars
#: per the column constraint.
REVOKED_REASON_IP_VIOLATION: Final[str] = "ip_violation_auto_revoke"


@dataclass(frozen=True)
class IpEnforcementResult:
    """Outcome of an :func:`enforce_api_key_ip` call.

    Attributes:
        allowed: ``True`` when the source IP matched the allowlist (or
            no allowlist was configured) — the caller MUST continue with
            the request. ``False`` means the request MUST be rejected
            with 403 ``err_ip_not_allowed``.
        violation_count: New value of ``api_keys.ip_violation_count``
            *after* the increment. ``0`` for an allowed request.
        revoked: ``True`` when this call tripped the auto-revoke
            threshold (FR-081). The row's ``revoked_at`` is set; any
            future :meth:`DbApiKeyVerifier.verify` call returns ``None``.
    """

    allowed: bool
    violation_count: int = 0
    revoked: bool = False


def is_ip_in_allowlist(client_ip: str, allowed_cidrs: list[str] | None) -> bool:
    """Return ``True`` when ``client_ip`` matches at least one CIDR.

    Semantics (FR-077, spec §"allowed_ips 違反別カウンタ"):

    * ``allowed_cidrs is None`` — no restriction configured → ``True``.
    * ``allowed_cidrs == []``   — explicit empty list, treated identically
      to ``None`` (no restriction) so that a half-configured row never
      locks out all traffic.
    * Any malformed CIDR / IP string → ``False`` (fail-closed). The
      schema-level :class:`SuperuserIpAllowlistUpdateRequest` already
      validates CIDR shape on write; reaching the fail-closed branch in
      production indicates DB corruption and a 403 is the correct
      response.
    """
    if not allowed_cidrs:
        return True
    try:
        ip = ipaddress.ip_address(client_ip)
    except (ValueError, TypeError):
        return False
    for cidr in allowed_cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except (ValueError, TypeError):
            # Skip malformed entries — do NOT silently allow.
            continue
        if ip in network:
            return True
    return False


def select_client_ip(
    *,
    forwarded_for: str | None,
    remote_addr: str | None,
) -> str:
    """Pick the canonical caller IP from the Starlette request shape.

    Reverse-proxy header ``X-Forwarded-For`` wins when present (the first
    comma-separated entry is the original caller per RFC 7239 / common
    practice); otherwise we fall back to the direct socket address.
    Returns an empty string when neither source resolves — the caller
    should treat that as "unknown" and proceed with the allowlist check
    in fail-closed mode (the empty IP never matches a CIDR).
    """
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0].strip()
        if first:
            return first
    if remote_addr:
        return remote_addr.strip()
    return ""


async def enforce_api_key_ip(
    session: AsyncSession,
    *,
    api_key_id: UUID,
    user_id: UUID,
    allowed_cidrs: list[str] | None,
    client_ip: str,
    request_id: str = "",
    user_agent: str = "",
) -> IpEnforcementResult:
    """Enforce ``allowed_ip_cidrs`` for a single API-key request.

    Always commits the increment (and optional revoke) on violation so
    the counter is durable even when a downstream handler short-circuits
    the response. The audit write is best-effort.

    The call MUST run on a fresh ``AsyncSession`` (one that has not
    issued any other SQL on the connection) when audit writes are
    enabled because :class:`AuditLogService` requires SERIALIZABLE
    isolation. The middleware satisfies this by opening a dedicated
    session for enforcement.
    """
    if is_ip_in_allowlist(client_ip, allowed_cidrs):
        return IpEnforcementResult(allowed=True)

    # Atomic increment under a row lock. ``RETURNING`` gives us the new
    # counter value without a follow-up SELECT.
    update_stmt = (
        sa.text(
            "UPDATE api_keys "
            "SET ip_violation_count = ip_violation_count + 1, "
            "    updated_at = :now "
            "WHERE id = :id "
            "RETURNING ip_violation_count"
        )
        .bindparams(now=datetime.now(UTC), id=api_key_id)
    )
    result = await session.execute(update_stmt)
    row = result.first()
    new_count = int(row[0]) if row is not None else 0

    revoked = False
    if new_count >= IP_VIOLATION_AUTO_REVOKE_THRESHOLD:
        # FR-081: auto-revoke the key. Only set ``revoked_at`` when it
        # is still NULL — re-revoking a previously revoked key would
        # silently overwrite the original timestamp / reason.
        revoke_stmt = (
            sa.text(
                "UPDATE api_keys "
                "SET revoked_at = :now, revoked_reason = :reason, "
                "    updated_at = :now "
                "WHERE id = :id AND revoked_at IS NULL"
            )
            .bindparams(
                now=datetime.now(UTC),
                reason=REVOKED_REASON_IP_VIOLATION,
                id=api_key_id,
            )
        )
        revoke_result = await session.execute(revoke_stmt)
        # ``CursorResult.rowcount`` is the post-UPDATE count (>0 when the
        # ``revoked_at IS NULL`` predicate matched). Using ``getattr`` keeps
        # mypy happy against the generic ``Result[Any]`` return type while
        # preserving runtime behaviour against asyncpg's CursorResult.
        revoked = bool(getattr(revoke_result, "rowcount", 0) or 0)

    await session.commit()

    # Best-effort audit write. A failure here MUST NOT mask the 403 we
    # are about to return — log + swallow.
    try:
        await _write_ip_violation_audit(
            session,
            api_key_id=api_key_id,
            user_id=user_id,
            client_ip=client_ip,
            allowed_cidrs=allowed_cidrs,
            new_count=new_count,
            revoked=revoked,
            request_id=request_id,
            user_agent=user_agent,
        )
    except Exception:  # noqa: BLE001 — soft alert
        logger.warning(
            "enforce_api_key_ip: audit write failed for api_key_id=%s "
            "(enforcement still applied)",
            api_key_id,
            exc_info=True,
        )

    return IpEnforcementResult(
        allowed=False,
        violation_count=new_count,
        revoked=revoked,
    )


async def _write_ip_violation_audit(
    session: AsyncSession,
    *,
    api_key_id: UUID,
    user_id: UUID,
    client_ip: str,
    allowed_cidrs: list[str] | None,
    new_count: int,
    revoked: bool,
    request_id: str,
    user_agent: str,
) -> None:
    """Append the ``api_key.ip_violation`` row to ``platform_audit_log``.

    Imports :class:`AuditLogService` lazily to avoid pulling in the
    KMS-backed dependency tree on every middleware import (and to
    keep the helper testable in environments where moto KMS is not
    provisioned — the caller catches any raise from this function).
    """
    from echoroo.services.audit_service import AuditLogService

    service = AuditLogService(session)
    detail: dict[str, object] = {
        "api_key_id": str(api_key_id),
        "client_ip": client_ip or "",
        "allowed_cidrs": list(allowed_cidrs or []),
        "violation_count": new_count,
        "auto_revoked": revoked,
    }
    action = AUDIT_ACTION_AUTO_REVOKE if revoked else AUDIT_ACTION_IP_VIOLATION
    await service.write_platform_event(
        actor_user_id=user_id,
        action=action,
        request_id=request_id or "",
        ip=client_ip or "",
        user_agent=user_agent or "",
        detail=detail,
    )


class DbIpEnforcer:
    """Production :class:`IpEnforcer` backed by an ``AsyncSession`` factory.

    Each ``enforce()`` call opens a fresh short-lived session — the
    audit write requires a SERIALIZABLE upgrade that PostgreSQL only
    accepts on a connection that has not yet executed any other SQL.
    Sharing the verifier's session would either bypass audit or break
    isolation; opening a dedicated session is the documented contract
    (``AuditLogService._write`` docstring).
    """

    def __init__(self, session_factory: object) -> None:
        self._session_factory = session_factory

    async def enforce(
        self,
        *,
        api_key_id: UUID,
        user_id: UUID,
        allowed_cidrs: tuple[str, ...] | None,
        client_ip: str,
        request_id: str,
        user_agent: str,
    ) -> bool:
        # Cheap fast-path: no allowlist configured → no DB hit at all.
        if not allowed_cidrs:
            return True

        # Slow path needs a session for the increment + audit.
        cidrs_list = list(allowed_cidrs)
        async with self._session_factory() as session:  # type: ignore[operator]
            result = await enforce_api_key_ip(
                session,
                api_key_id=api_key_id,
                user_id=user_id,
                allowed_cidrs=cidrs_list,
                client_ip=client_ip,
                request_id=request_id,
                user_agent=user_agent,
            )
        return result.allowed


__all__ = [
    "AUDIT_ACTION_AUTO_REVOKE",
    "AUDIT_ACTION_IP_VIOLATION",
    "DbIpEnforcer",
    "IP_VIOLATION_AUTO_REVOKE_THRESHOLD",
    "IpEnforcementResult",
    "REVOKED_REASON_IP_VIOLATION",
    "enforce_api_key_ip",
    "is_ip_in_allowlist",
    "select_client_ip",
]
