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


def _normalize_xff_hop(raw: str) -> str:
    """Strip optional port suffixes from an ``X-Forwarded-For`` hop value.

    Phase 17 Codex Round 2 Minor 1 fix: some reverse proxies emit the
    upstream caller's port alongside the IP (e.g. ``198.51.100.7:443``
    or ``[2001:db8::1]:443``), and the per-hop comparison previously
    handed those raw strings to :func:`is_ip_in_allowlist`, which
    fail-closed against any non-bare IP. That caused legitimate XFF
    chains to be misclassified as "untrusted" — a regression rather than
    a spoof bypass, but it produced false 403s when proxies were
    upgraded to a port-emitting build.

    Accepted shapes (canonicalised to a bare IP literal):

    * ``"198.51.100.7"``       -> ``"198.51.100.7"``
    * ``"198.51.100.7:443"``   -> ``"198.51.100.7"``
    * ``"2001:db8::1"``        -> ``"2001:db8::1"``
    * ``"[2001:db8::1]"``      -> ``"2001:db8::1"``
    * ``"[2001:db8::1]:443"``  -> ``"2001:db8::1"``

    Ambiguous forms are rejected by returning the input unchanged so the
    downstream allowlist check fails closed: a bare ``2001:db8::1:443``
    cannot be unambiguously split into IPv6 host vs. port without
    out-of-band knowledge (the trailing ``:443`` could be a final group
    of an IPv6 address) — RFC 7239 / RFC 3986 require bracketed form for
    IPv6+port for exactly this reason.

    Returns the canonical IP literal on success or the *trimmed* input
    when no port suffix is detected. Empty inputs are returned as-is.
    """
    candidate = raw.strip()
    if not candidate:
        return candidate

    # Reject zone-identifier IPv6 (RFC 6874 ``%scope``) — these are
    # link-local-only, must never appear in a routed XFF chain, and
    # ipaddress.IPv6Address accepts them so a downstream CIDR check
    # could otherwise be tricked into matching unintended addresses.
    if "%" in candidate:
        return candidate

    # Bracketed IPv6: "[addr]" or "[addr]:port".
    if candidate.startswith("["):
        closing = candidate.find("]")
        if closing == -1:
            return candidate
        inner = candidate[1:closing]
        if "%" in inner:
            return candidate
        # Only accept when the host inside the brackets actually parses
        # as an IPv6 literal — otherwise we're looking at a malformed
        # value and should leave it for the fail-closed allowlist check.
        try:
            parsed = ipaddress.IPv6Address(inner)
        except (ValueError, TypeError):
            return candidate
        # IPv4-mapped IPv6 (``::ffff:a.b.c.d``) is rejected so that an
        # operator cannot accidentally bypass an IPv4 allowlist by
        # listing the v4-mapped form in proxy chain headers.
        if parsed.ipv4_mapped is not None:
            return candidate
        suffix = candidate[closing + 1 :]
        if suffix == "" or (suffix.startswith(":") and suffix[1:].isdigit()):
            return inner
        return candidate

    # Bare value: IPv4 (with optional ":port") or unbracketed IPv6.
    if ":" in candidate:
        # IPv6 literals are required by RFC 3986 to be bracketed when a
        # port follows — so a bare value with multiple colons is the
        # unbracketed IPv6 case (no port we can split). Treat it as a
        # raw address and let the IPv6 parser decide.
        if candidate.count(":") > 1:
            try:
                parsed = ipaddress.IPv6Address(candidate)
            except (ValueError, TypeError):
                return candidate
            if parsed.ipv4_mapped is not None:
                return candidate
            return candidate
        # Single colon → IPv4:port shape. Validate the prefix is IPv4.
        host, _, port = candidate.partition(":")
        try:
            ipaddress.IPv4Address(host)
        except (ValueError, TypeError):
            return candidate
        if port.isdigit():
            return host
        return candidate

    return candidate


def _ip_in_any_cidr(ip_str: str, cidrs: list[str]) -> bool:
    """Return ``True`` when ``ip_str`` is contained in at least one CIDR.

    Malformed entries are silently skipped (not fail-open: the caller
    decides what to do when *no* CIDR matches). An empty / unparseable
    ``ip_str`` short-circuits to ``False`` so a missing socket peer is
    never treated as a trusted proxy.
    """
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except (ValueError, TypeError):
        return False
    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except (ValueError, TypeError):
            continue
        if ip in network:
            return True
    return False


def select_client_ip(
    *,
    forwarded_for: str | None,
    remote_addr: str | None,
    trusted_proxy_cidrs: list[str] | None = None,
) -> str:
    """Pick the canonical caller IP from the Starlette request shape.

    Phase 17 A-3 Codex Major 1 fix: ``X-Forwarded-For`` is only honoured
    when the socket peer (``remote_addr``) is itself a trusted reverse
    proxy. Without this guard an attacker reaching the API directly
    (or via a misconfigured proxy that does not strip incoming XFF
    headers) could bypass the per-key ``allowed_ip_cidrs`` allowlist by
    sending ``X-Forwarded-For: 10.0.0.55``.

    Algorithm:

    * If ``trusted_proxy_cidrs`` is empty → XFF is **never** trusted.
      Always return the socket peer (``remote_addr``).
    * If the socket peer is NOT in ``trusted_proxy_cidrs`` → XFF is
      ignored and the peer is returned.
    * If the socket peer IS in ``trusted_proxy_cidrs`` → walk the XFF
      list right-to-left, stripping trailing entries that are themselves
      trusted proxies. The first untrusted entry encountered is the
      original caller. If the entire chain is trusted, the leftmost
      entry is returned (best-effort: a chain composed exclusively of
      proxy hops still surfaces the most-upstream value).

    Returns an empty string when neither XFF nor the socket peer
    resolve to a value — the caller treats that as "unknown" and the
    allowlist check fails closed.
    """
    cidrs = list(trusted_proxy_cidrs or [])
    # Phase 17 Codex Round 2 Minor 1 fix: socket peers from some
    # ASGI/WSGI bridges or reverse proxies arrive carrying a port
    # suffix (``198.51.100.7:443``). Normalise eagerly so the CIDR
    # membership check below sees a bare IP literal.
    peer = _normalize_xff_hop(remote_addr or "")

    # Without a trusted-proxy configuration we MUST ignore XFF entirely.
    if not cidrs:
        return peer

    # Socket peer is not a trusted proxy → ignore any XFF header.
    if not _ip_in_any_cidr(peer, cidrs):
        return peer

    # Peer is trusted. Honour XFF, stripping trusted hops right-to-left.
    if forwarded_for:
        # Phase 17 Codex Round 2 Minor 1: normalise each hop so port-
        # bearing entries (``198.51.100.7:443``, ``[2001:db8::1]:443``)
        # are stripped to a bare IP before the allowlist comparison.
        hops = [
            _normalize_xff_hop(hop)
            for hop in forwarded_for.split(",")
            if hop.strip()
        ]
        # Phase 17 Codex Round 3 Minor: drop entries that did not
        # canonicalise to a bare IP literal — scope-id IPv6, IPv4-mapped
        # IPv6, junk strings — instead of letting them fall through as
        # the chain caller. Combined with ``_normalize_xff_hop`` returning
        # the input verbatim on rejection, this is the fail-closed seam.
        def _is_bare_ip(value: str) -> bool:
            # ``ipaddress.ip_address`` accepts scope-id IPv6 (RFC 6874
            # ``%scope``) — reject those eagerly so a verbatim XFF entry
            # like ``fe80::1%eth0`` cannot resurface as the caller IP.
            if "%" in value:
                return False
            try:
                parsed = ipaddress.ip_address(value)
            except (ValueError, TypeError):
                return False
            # IPv4-mapped IPv6 is also rejected at the chain level so
            # that an attacker cannot launder an IPv4 address past an
            # IPv4-only allowlist by submitting ``::ffff:a.b.c.d``.
            if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
                return False
            return True

        hops = [hop for hop in hops if hop and _is_bare_ip(hop)]
        if hops:
            # Walk from the right end, dropping trusted-proxy hops.
            i = len(hops) - 1
            while i >= 0 and _ip_in_any_cidr(hops[i], cidrs):
                i -= 1
            if i >= 0:
                # First untrusted entry from the right edge.
                return hops[i]
            # Whole chain trusted — fall back to leftmost (closest to
            # original caller per RFC 7239 convention).
            return hops[0]

    # No XFF on a trusted-proxy request → use the peer.
    return peer


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
