"""FR-077 / FR-081: API key allowed_ip_cidrs enforcement + violation counter.

The ``api_keys.allowed_ip_cidrs`` column stores an optional CIDR allowlist.
When set, requests from IPs outside the allowlist MUST be rejected (403)
and the violation MUST be recorded (audit log entry +
``ip_violation_count`` increment).

Spec references:
- FR-077: ``/api/v1/*`` requires API key; optional ``allowed_ips``.
- FR-081: ``allowed_ips`` violation 3 times → automatic revoke (separate counter).
- Spec line ~898: "allowed_ips 違反別カウンタ" (separate violation counter).

**Implementation status (Phase 17 A-3, T979d follow-up):**

The enforcement helper :mod:`echoroo.middleware.api_key_ip_enforcement`
provides :func:`enforce_api_key_ip`, which:

1. Compares the caller IP against ``api_keys.allowed_ip_cidrs``.
2. On mismatch atomically increments ``ip_violation_count`` (a counter
   independent from ``scope_violation_count_10min``).
3. Auto-revokes the key on the third violation (sets ``revoked_at`` +
   ``revoked_reason='ip_violation_auto_revoke'``).
4. Best-effort writes a ``platform_audit_log`` row describing the event.

The :class:`AuthRouterMiddleware` invokes the helper through the
:class:`IpEnforcer` plug-in **after** :class:`DbApiKeyVerifier` resolves
the row but **before** the principal is attached to ``request.state`` so
a rejected request never reaches the downstream handler.

These tests exercise the helper directly against the test PostgreSQL
instance — the HTTP shell is covered by the auth-router unit tests and
the integration suite under ``tests/contract/``.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_test_user(db_session: Any) -> UUID:
    """Insert a minimal test user row and return its ``id``.

    The ``api_keys.user_id`` foreign-key requires a real ``users`` row;
    we use raw SQL so the test does not need the ORM password hashing
    helpers (the password value here is never verified — it just has to
    satisfy the NOT NULL constraint).
    """
    user_id = uuid4()
    await db_session.execute(
        sa.text(
            "INSERT INTO users "
            "(id, email, password_hash, security_stamp, created_at, updated_at) "
            "VALUES (:id, :email, :pw, :ss, NOW(), NOW())"
        ),
        {
            "id": user_id,
            "email": f"ip-enforce-{user_id}@test.local",
            "pw": "$argon2id$v=19$m=65536,t=3,p=1$" + ("a" * 22) + "$" + ("b" * 43),
            "ss": "ss-" + uuid4().hex,
        },
    )
    await db_session.commit()
    return user_id


async def _create_test_api_key(
    db_session: Any,
    *,
    user_id: UUID,
    allowed_ip_cidrs: list[str] | None,
    granted_permissions: list[str] | None = None,
) -> UUID:
    """Insert a minimal ``api_keys`` row and return its ``id``."""
    key_id = uuid4()
    now = datetime.now(UTC)
    await db_session.execute(
        sa.text(
            "INSERT INTO api_keys "
            "(id, user_id, prefix, hashed_secret, granted_permissions, "
            " allowed_ip_cidrs, expires_at, created_at, updated_at, "
            " scope_violation_count_10min, ip_violation_count) "
            "VALUES (:id, :uid, :prefix, :hash, CAST(:gp AS JSONB), "
            "        :cidrs, :exp, :now, :now, 0, 0)"
        ),
        {
            "id": key_id,
            "uid": user_id,
            "prefix": f"echoroo_{uuid4().hex[:8]}",
            "hash": "f" * 64,
            "gp": '["recordings:read"]'
            if granted_permissions is None
            else __import__("json").dumps(granted_permissions),
            "cidrs": allowed_ip_cidrs,
            "exp": now + timedelta(days=180),
            "now": now,
        },
    )
    await db_session.commit()
    return key_id


# ---------------------------------------------------------------------------
# Model-layer tests (passing)
# ---------------------------------------------------------------------------


def test_api_key_model_has_allowed_ip_cidrs_column() -> None:
    """``ApiKey`` MUST expose the ``allowed_ip_cidrs`` column used for IP enforcement."""
    from echoroo.models.api_key import ApiKey

    mapper = ApiKey.__mapper__
    col_names = {c.key for c in mapper.column_attrs}
    assert "allowed_ip_cidrs" in col_names, (
        "ApiKey.allowed_ip_cidrs column must exist for FR-077 IP enforcement"
    )
    assert "ip_violation_count" in col_names, (
        "ApiKey.ip_violation_count column must exist for FR-081 violation tracking"
    )


def test_new_api_key_allowed_ip_cidrs_defaults_to_none() -> None:
    """A newly constructed ``ApiKey`` without ``allowed_ip_cidrs`` defaults to ``None``.

    ``None`` means "no IP restriction" — all IPs are allowed (FR-077).
    An empty list ``[]`` should also be treated as "no restriction" by the
    enforcement layer (avoids accidentally locking out all traffic).
    """
    from echoroo.models.api_key import ApiKey

    key = ApiKey(
        user_id=uuid4(),
        prefix="echoroo_noipcidr",
        hashed_secret="c" * 64,
        granted_permissions=["recordings:read"],
        expires_at=datetime.now(UTC) + timedelta(days=365),
    )
    # allowed_ip_cidrs not set → None (no restriction)
    assert key.allowed_ip_cidrs is None


def test_api_key_allowed_ip_cidrs_stores_cidr_list() -> None:
    """``ApiKey.allowed_ip_cidrs`` MUST store a list of CIDR strings."""
    from echoroo.models.api_key import ApiKey

    cidrs = ["10.0.0.0/24", "192.168.1.0/28"]
    key = ApiKey(
        user_id=uuid4(),
        prefix="echoroo_withcidrs",
        hashed_secret="d" * 64,
        granted_permissions=["recordings:read"],
        expires_at=datetime.now(UTC) + timedelta(days=365),
        allowed_ip_cidrs=cidrs,
    )
    assert key.allowed_ip_cidrs == cidrs


def test_admin_schema_validates_cidr_strings() -> None:
    """The CIDR validation helper in admin schemas MUST reject malformed CIDRs."""
    from pydantic import ValidationError

    from echoroo.schemas.admin import SuperuserIpAllowlistUpdateRequest

    with pytest.raises(ValidationError):
        SuperuserIpAllowlistUpdateRequest(allowed_ip_cidrs=["not-a-cidr"])


def test_ip_in_cidr_stdlib_logic() -> None:
    """Python stdlib ``ipaddress`` can determine if an IP falls within a CIDR.

    This test documents the pure-Python logic that the enforcement
    middleware uses to compare the caller's IP against
    ``allowed_ip_cidrs``.
    """
    network = ipaddress.ip_network("10.0.0.0/24", strict=False)
    assert ipaddress.ip_address("10.0.0.100") in network
    assert ipaddress.ip_address("10.0.1.1") not in network
    assert ipaddress.ip_address("192.168.1.1") not in network


def test_select_client_ip_ignores_xff_when_no_trusted_proxy_configured() -> None:
    """Phase 17 A-3 Codex Major 1: XFF MUST be ignored when no trusted
    proxy is configured.

    An attacker who can reach the API directly (no reverse proxy in
    front, or a misconfigured proxy that does not strip incoming XFF)
    could otherwise spoof an allowlisted source IP by sending
    ``X-Forwarded-For: 10.0.0.55``. The default-empty
    ``trusted_proxy_cidrs`` list MUST cause the helper to return the
    socket peer regardless of any XFF value.
    """
    from echoroo.middleware.api_key_ip_enforcement import select_client_ip

    # No trusted-proxy config → XFF spoof rejected, peer wins.
    assert (
        select_client_ip(
            forwarded_for="10.0.0.55",
            remote_addr="203.0.113.99",
            trusted_proxy_cidrs=[],
        )
        == "203.0.113.99"
    )
    # ``None`` is the legacy / default; must behave identically.
    assert (
        select_client_ip(
            forwarded_for="10.0.0.55",
            remote_addr="203.0.113.99",
            trusted_proxy_cidrs=None,
        )
        == "203.0.113.99"
    )


def test_select_client_ip_ignores_xff_from_untrusted_peer() -> None:
    """Untrusted socket peers MUST have their XFF ignored even when a
    trusted-proxy list is configured.

    A trusted-proxy CIDR list narrows *who* may speak XFF; a peer
    outside that list is still considered hostile and its XFF header
    is dropped.
    """
    from echoroo.middleware.api_key_ip_enforcement import select_client_ip

    # Trusted proxies live in 10.0.0.0/24, attacker comes from 203.x.
    assert (
        select_client_ip(
            forwarded_for="10.0.0.55",
            remote_addr="203.0.113.99",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "203.0.113.99"
    )


def test_select_client_ip_uses_xff_from_trusted_peer() -> None:
    """A trusted-proxy peer MAY forward the original caller's IP.

    Single-hop case: the proxy at 10.0.0.5 (in the trusted CIDR)
    forwards ``X-Forwarded-For: 198.51.100.7`` and we return the
    forwarded address.
    """
    from echoroo.middleware.api_key_ip_enforcement import select_client_ip

    assert (
        select_client_ip(
            forwarded_for="198.51.100.7",
            remote_addr="10.0.0.5",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "198.51.100.7"
    )


def test_select_client_ip_strips_trusted_chain_right_to_left() -> None:
    """Multi-hop chains MUST strip trusted proxies from the right edge.

    For a chain ``client, edge_proxy, internal_proxy`` the rightmost
    untrusted entry is the original caller. Everything to its right
    is a trusted proxy hop and gets dropped.
    """
    from echoroo.middleware.api_key_ip_enforcement import select_client_ip

    # Two trusted hops on the right; first untrusted from the right is
    # ``198.51.100.7``.
    assert (
        select_client_ip(
            forwarded_for="198.51.100.7, 10.0.0.5, 10.0.0.6",
            remote_addr="10.0.0.6",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "198.51.100.7"
    )


def test_select_client_ip_strips_ipv4_port_from_xff() -> None:
    """Phase 17 Codex Round 2 Minor 1: ``IPv4:port`` XFF hops MUST be normalised.

    Some reverse proxies emit the upstream caller's port alongside the
    address (``198.51.100.7:443``). Without normalisation the bare
    string is fed to the CIDR allowlist check, fails closed, and the
    request is misclassified — a regression rather than a spoof bypass,
    but it produces false 403s under proxies that emit ports.
    """
    from echoroo.middleware.api_key_ip_enforcement import select_client_ip

    # IPv4:port from a trusted proxy peer is normalised to a bare IPv4.
    assert (
        select_client_ip(
            forwarded_for="198.51.100.7:443",
            remote_addr="10.0.0.5",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "198.51.100.7"
    )
    # The peer itself may also arrive with a port suffix (some ASGI
    # bridges expose ``host:port`` from ``request.client.host``).
    assert (
        select_client_ip(
            forwarded_for=None,
            remote_addr="10.0.0.5:51234",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "10.0.0.5"
    )


def test_select_client_ip_strips_bracketed_ipv6_port_from_xff() -> None:
    """Bracketed IPv6 with port (``[2001:db8::1]:443``) MUST be normalised.

    RFC 3986 / 7239 require bracketing IPv6 literals when a port is
    appended; the helper strips both the brackets and the trailing
    ``:port`` so the downstream allowlist sees a canonical IPv6 address.
    """
    from echoroo.middleware.api_key_ip_enforcement import select_client_ip

    # Single trusted IPv6 hop with a port appended.
    assert (
        select_client_ip(
            forwarded_for="[2001:db8::1]:443",
            remote_addr="10.0.0.5",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "2001:db8::1"
    )
    # Bracketed IPv6 with no port also resolves to the bare address.
    assert (
        select_client_ip(
            forwarded_for="[2001:db8::1]",
            remote_addr="10.0.0.5",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "2001:db8::1"
    )


def test_select_client_ip_strips_ports_in_chain() -> None:
    """Mixed chains with port-bearing trusted hops MUST canonicalise correctly.

    ``198.51.100.7, 10.0.0.5:443, 10.0.0.6:443`` from a trusted-proxy
    peer should drop the two trusted hops on the right (after stripping
    their ports) and surface the original public caller.
    """
    from echoroo.middleware.api_key_ip_enforcement import select_client_ip

    assert (
        select_client_ip(
            forwarded_for="198.51.100.7, 10.0.0.5:443, 10.0.0.6:443",
            remote_addr="10.0.0.6:443",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "198.51.100.7"
    )


def test_select_client_ip_rejects_zone_id_ipv6_in_xff() -> None:
    """Phase 17 Codex Round 3: scope-id IPv6 (RFC 6874 ``%scope``) MUST NOT
    be canonicalised. Otherwise the downstream CIDR check could match an
    unintended address (link-local-only addresses with zone identifiers
    must never appear in a routed XFF chain).
    """
    from echoroo.middleware.api_key_ip_enforcement import (
        _normalize_xff_hop,
        select_client_ip,
    )

    # Bare and bracketed scope-id forms are returned verbatim, so the
    # later allowlist match fails closed.
    assert _normalize_xff_hop("fe80::1%eth0") == "fe80::1%eth0"
    assert (
        _normalize_xff_hop("[2001:4860:4860::8888%eth0]:443")
        == "[2001:4860:4860::8888%eth0]:443"
    )

    # End-to-end: a trusted peer presenting a scope-id XFF must not be
    # honoured — the canonicalised value cannot be parsed as a routable IP
    # so select_client_ip falls back to the trusted peer itself.
    assert (
        select_client_ip(
            forwarded_for="fe80::1%eth0",
            remote_addr="10.0.0.5",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "10.0.0.5"
    )


def test_select_client_ip_rejects_ipv4_mapped_ipv6_in_xff() -> None:
    """Phase 17 Codex Round 3: IPv4-mapped IPv6 (``::ffff:a.b.c.d``) MUST
    NOT be canonicalised. An operator who lists v4-mapped form in a CIDR
    cannot use that to backdoor an IPv4 allowlist via the XFF parser.
    """
    from echoroo.middleware.api_key_ip_enforcement import _normalize_xff_hop

    assert _normalize_xff_hop("::ffff:198.51.100.7") == "::ffff:198.51.100.7"
    assert _normalize_xff_hop("[::ffff:198.51.100.7]") == "[::ffff:198.51.100.7]"
    assert (
        _normalize_xff_hop("[::ffff:198.51.100.7]:443")
        == "[::ffff:198.51.100.7]:443"
    )


def test_normalize_xff_hop_rejects_malformed_inputs() -> None:
    """Phase 17 follow-up B: pin the fail-closed behaviour of
    :func:`_normalize_xff_hop` against a wider set of malformed XFF hop
    strings.

    The helper canonicalises only well-formed hops (bare IPv4, bare IPv6,
    bracketed IPv6, optional ``:port``). Any ambiguous or syntactically
    broken input MUST be returned **verbatim** so the downstream
    allowlist comparison fails closed (the verbatim string cannot be
    parsed as an IP and ``is_ip_in_allowlist`` returns ``False``,
    matching the ``_is_bare_ip`` filter inside ``select_client_ip``).

    The cases below extend the Round 3 coverage (scope-id IPv6 +
    IPv4-mapped IPv6) with additional adversarial / proxy-misbehaviour
    shapes that have surfaced in production XFF chains:

    1. trailing junk after the port    (``198.51.100.7:443abc``)
    2. multiple ``%`` zone suffixes    (``fe80::1%eth0%vlan``)
    3. empty bracket forms             (``[]`` / ``[]:443``)
    4. IPv4 with non-digit characters  (``192.168.0.x``)
    5. unclosed bracket                (``[2001:db8::1``)
    6. extra characters after IPv6 port (``[2001:db8::1]:443extra``)
    7. negative port                   (``198.51.100.7:-1``)
    8. whitespace inside an IPv4 hop   (``198. 51.100.7:443``)

    A 9th case pins the *current* behaviour for an out-of-range port
    (``198.51.100.7:99999``): the implementation only checks
    ``str.isdigit()`` and does not range-check ports, so the host is
    extracted. The assertion documents that the host stripping is
    intentional (the port is irrelevant to the allowlist comparison)
    even though the value would not be a valid TCP port. We pin
    rather than fix because tightening the parser to the 0..65535
    range here would require rev-locking the spec; out of scope for
    this follow-up.
    """
    from echoroo.middleware.api_key_ip_enforcement import _normalize_xff_hop

    # 1. trailing junk after the port: "443abc" is not all digits.
    assert _normalize_xff_hop("198.51.100.7:443abc") == "198.51.100.7:443abc"

    # 2. multiple %scope suffixes — any "%" forces fail-closed.
    assert _normalize_xff_hop("fe80::1%eth0%vlan") == "fe80::1%eth0%vlan"

    # 3. empty bracket forms — IPv6Address("") raises, returns verbatim.
    assert _normalize_xff_hop("[]") == "[]"
    assert _normalize_xff_hop("[]:443") == "[]:443"

    # 4. IPv4 with letters — no colon, no bracket → verbatim passthrough.
    #    Falls through to the trailing ``return candidate`` branch,
    #    where the verbatim string is then rejected by ``_is_bare_ip``
    #    in ``select_client_ip`` because ``ip_address("192.168.0.x")``
    #    raises.
    assert _normalize_xff_hop("192.168.0.x") == "192.168.0.x"

    # 5. unclosed bracket — find("]") returns -1 → verbatim.
    assert _normalize_xff_hop("[2001:db8::1") == "[2001:db8::1"

    # 6. extra characters after IPv6 port — port[1:] = "443extra" is not
    #    all digits.
    assert (
        _normalize_xff_hop("[2001:db8::1]:443extra")
        == "[2001:db8::1]:443extra"
    )

    # 7. negative port — "-1" is not isdigit (the leading '-' fails the
    #    digit check), so the value is returned verbatim.
    assert _normalize_xff_hop("198.51.100.7:-1") == "198.51.100.7:-1"

    # 8. whitespace inside an IPv4 host — IPv4Address("198. 51.100.7")
    #    raises, returns verbatim.
    assert _normalize_xff_hop("198. 51.100.7:443") == "198. 51.100.7:443"


def test_normalize_xff_hop_known_behaviour_out_of_range_port() -> None:
    """Known non-rejection seam: port is parsed via ``str.isdigit`` only,
    so out-of-range values (>= 65536) currently STRIP to the host instead
    of failing closed.

    This is **not** a security gap — the port is irrelevant to a CIDR
    allowlist comparison and the host portion still has to parse as a
    valid IPv4 — but it is technically not "fail-closed for malformed
    input" the way the cases in
    :func:`test_normalize_xff_hop_rejects_malformed_inputs` are. The
    test pins the documented behaviour; if a future revision tightens
    the parser to ``0 <= int(port) <= 65535`` (per Codex Round 4
    suggestion), update this assertion to match.
    """
    from echoroo.middleware.api_key_ip_enforcement import _normalize_xff_hop

    # ``99999`` is digit-only → parser strips port → host returned bare.
    assert _normalize_xff_hop("198.51.100.7:99999") == "198.51.100.7"
    # Bracketed IPv6 with a digit-only port also passes the same check.
    assert _normalize_xff_hop("[2001:db8::1]:70000") == "2001:db8::1"


def test_select_client_ip_falls_back_to_peer_when_no_xff() -> None:
    """A trusted peer with no XFF header → use the peer itself."""
    from echoroo.middleware.api_key_ip_enforcement import select_client_ip

    assert (
        select_client_ip(
            forwarded_for=None,
            remote_addr="10.0.0.5",
            trusted_proxy_cidrs=["10.0.0.0/24"],
        )
        == "10.0.0.5"
    )


def test_empty_allowed_ip_cidrs_means_no_restriction() -> None:
    """An empty ``allowed_ip_cidrs`` list MUST be interpreted as 'no restriction'.

    This is the semantic contract: ``None`` and ``[]`` both mean "all IPs
    allowed". The enforcement helper MUST NOT block traffic when
    ``allowed_ip_cidrs`` is empty.
    """
    from echoroo.middleware.api_key_ip_enforcement import is_ip_in_allowlist

    # Both shapes are treated as "allow all".
    assert is_ip_in_allowlist("1.2.3.4", None) is True
    assert is_ip_in_allowlist("1.2.3.4", []) is True
    # A real allowlist that does NOT contain the IP rejects.
    assert is_ip_in_allowlist("1.2.3.4", ["10.0.0.0/24"]) is False
    assert is_ip_in_allowlist("10.0.0.5", ["10.0.0.0/24"]) is True


# ---------------------------------------------------------------------------
# Enforcement helper tests (Phase 17 A-3 — middleware now implemented)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_from_non_allowlisted_ip_returns_403(
    db_session: Any,
) -> None:
    """A request whose source IP is NOT in ``allowed_ip_cidrs`` MUST be rejected.

    Direct unit test of the helper: the auth-router middleware translates
    the boolean outcome into ``HTTP 403 err_ip_not_allowed`` (verified in
    the auth-router unit suite). Here we pin the helper contract: a
    mismatched IP returns ``allowed=False`` AND the row's
    ``ip_violation_count`` is incremented in the same call.
    """
    from echoroo.middleware.api_key_ip_enforcement import enforce_api_key_ip

    user_id = await _create_test_user(db_session)
    api_key_id = await _create_test_api_key(
        db_session, user_id=user_id, allowed_ip_cidrs=["10.0.0.0/24"]
    )

    # Caller IP is OUTSIDE the allowlist.
    result = await enforce_api_key_ip(
        db_session,
        api_key_id=api_key_id,
        user_id=user_id,
        allowed_cidrs=["10.0.0.0/24"],
        client_ip="192.168.1.1",
        request_id="req-test-403",
        user_agent="pytest",
    )

    assert result.allowed is False, (
        "192.168.1.1 should be rejected by allowlist 10.0.0.0/24"
    )
    assert result.violation_count == 1, (
        f"first violation must yield count=1, got {result.violation_count}"
    )

    # Row state matches the result.
    row = (
        await db_session.execute(
            sa.text(
                "SELECT ip_violation_count, revoked_at "
                "FROM api_keys WHERE id = :id"
            ),
            {"id": api_key_id},
        )
    ).first()
    assert row is not None
    assert row[0] == 1
    assert row[1] is None  # not yet revoked at the first violation


@pytest.mark.asyncio
async def test_ip_violation_increments_counter(
    db_session: Any,
) -> None:
    """Each IP-allowlist violation MUST increment ``api_keys.ip_violation_count``.

    Two consecutive violations from the same offending IP must yield
    counts ``1`` then ``2`` — the counter is monotonically increasing
    per violation. Allow-listed calls in between MUST NOT advance the
    counter (separate-counter contract: the IP counter is decoupled
    from the scope counter).
    """
    from echoroo.middleware.api_key_ip_enforcement import enforce_api_key_ip

    user_id = await _create_test_user(db_session)
    api_key_id = await _create_test_api_key(
        db_session, user_id=user_id, allowed_ip_cidrs=["10.0.0.0/24"]
    )

    # First violation.
    r1 = await enforce_api_key_ip(
        db_session,
        api_key_id=api_key_id,
        user_id=user_id,
        allowed_cidrs=["10.0.0.0/24"],
        client_ip="203.0.113.5",
    )
    assert r1.allowed is False
    assert r1.violation_count == 1

    # Allow-listed call between violations: MUST NOT advance the counter.
    r_ok = await enforce_api_key_ip(
        db_session,
        api_key_id=api_key_id,
        user_id=user_id,
        allowed_cidrs=["10.0.0.0/24"],
        client_ip="10.0.0.55",
    )
    assert r_ok.allowed is True
    assert r_ok.violation_count == 0  # untouched

    # Second violation.
    r2 = await enforce_api_key_ip(
        db_session,
        api_key_id=api_key_id,
        user_id=user_id,
        allowed_cidrs=["10.0.0.0/24"],
        client_ip="203.0.113.5",
    )
    assert r2.allowed is False
    assert r2.violation_count == 2, (
        "counter must increment to 2 on the second violation"
    )

    row = (
        await db_session.execute(
            sa.text(
                "SELECT ip_violation_count, revoked_at "
                "FROM api_keys WHERE id = :id"
            ),
            {"id": api_key_id},
        )
    ).first()
    assert row is not None
    assert row[0] == 2
    assert row[1] is None  # still not revoked at 2 violations


@pytest.mark.asyncio
async def test_three_ip_violations_auto_revokes_key(
    db_session: Any,
) -> None:
    """After 3 IP-allowlist violations the API key MUST be auto-revoked (FR-081).

    ``revoked_at`` is set on the third violation, ``revoked_reason`` is
    ``ip_violation_auto_revoke``, and ``ip_violation_count`` is ``3``.
    """
    from echoroo.middleware.api_key_ip_enforcement import (
        REVOKED_REASON_IP_VIOLATION,
        enforce_api_key_ip,
    )

    user_id = await _create_test_user(db_session)
    api_key_id = await _create_test_api_key(
        db_session, user_id=user_id, allowed_ip_cidrs=["10.0.0.0/24"]
    )

    for i in range(1, 4):
        result = await enforce_api_key_ip(
            db_session,
            api_key_id=api_key_id,
            user_id=user_id,
            allowed_cidrs=["10.0.0.0/24"],
            client_ip="198.51.100.7",
            request_id=f"req-{i}",
        )
        assert result.allowed is False
        assert result.violation_count == i
        assert result.revoked is (i >= 3)

    # Final state: revoked_at populated, reason set, count == 3.
    row = (
        await db_session.execute(
            sa.text(
                "SELECT ip_violation_count, revoked_at, revoked_reason "
                "FROM api_keys WHERE id = :id"
            ),
            {"id": api_key_id},
        )
    ).first()
    assert row is not None
    assert row[0] == 3
    assert row[1] is not None, "revoked_at must be set on the 3rd violation"
    assert row[2] == REVOKED_REASON_IP_VIOLATION


@pytest.mark.asyncio
async def test_ip_violation_creates_audit_log_entry(
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An IP-allowlist violation MUST produce a ``platform_audit_log`` entry.

    The audit row carries:
    - ``action = 'api_key.ip_violation'`` (or ``'api_key.auto_revoke_ip_violation'``
      on the revoking call).
    - ``actor_user_id_hash`` derived from the key owner.
    - ``detail`` containing ``api_key_id``, a redacted ``client_ip``, the
      ``allowed_cidrs`` snapshot, the new ``violation_count``, and the
      ``auto_revoked`` flag.

    KMS is stubbed so the test stays hermetic — the chain-hash and PII
    hash become deterministic constants. The test asserts the row exists
    and carries the expected ``action``.
    """
    from echoroo.middleware.api_key_ip_enforcement import (
        AUDIT_ACTION_IP_VIOLATION,
        enforce_api_key_ip,
    )
    from echoroo.services import audit_service

    # Stub KMS — deterministic 64-char hex outputs satisfy the column
    # widths and let the chain insert succeed without a real CMK.
    monkeypatch.setattr(
        audit_service, "compute_pii_hash", lambda _v: "a" * 64, raising=True
    )
    monkeypatch.setattr(
        audit_service,
        "compute_audit_chain_hash",
        lambda _p, _c: "b" * 64,
        raising=True,
    )

    user_id = await _create_test_user(db_session)
    api_key_id = await _create_test_api_key(
        db_session, user_id=user_id, allowed_ip_cidrs=["10.0.0.0/24"]
    )

    # Snapshot the audit table size BEFORE the enforced call so the
    # assertion below targets the row this test inserted, not a residual
    # from a previous test in the same DB.
    before_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM platform_audit_log "
                "WHERE action = :a"
            ),
            {"a": AUDIT_ACTION_IP_VIOLATION},
        )
    ).scalar()

    result = await enforce_api_key_ip(
        db_session,
        api_key_id=api_key_id,
        user_id=user_id,
        allowed_cidrs=["10.0.0.0/24"],
        client_ip="203.0.113.42",
        request_id="req-audit-1",
        user_agent="pytest-audit",
    )
    assert result.allowed is False

    after_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM platform_audit_log "
                "WHERE action = :a"
            ),
            {"a": AUDIT_ACTION_IP_VIOLATION},
        )
    ).scalar()
    assert (after_count or 0) == (before_count or 0) + 1, (
        "exactly one platform_audit_log row should be appended for the "
        f"violation (before={before_count}, after={after_count})"
    )

    # Inspect the most-recent row's detail payload.
    detail_row = (
        await db_session.execute(
            sa.text(
                "SELECT detail FROM platform_audit_log "
                "WHERE action = :a "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"a": AUDIT_ACTION_IP_VIOLATION},
        )
    ).first()
    assert detail_row is not None
    detail = detail_row[0]
    # JSONB → dict via asyncpg
    assert detail.get("api_key_id") == str(api_key_id)
    client_ip_detail = detail.get("client_ip")
    assert isinstance(client_ip_detail, dict)
    assert client_ip_detail.get("redacted") is True
    assert client_ip_detail.get("hash_version") == "v3"
    client_ip_hash = client_ip_detail.get("hash")
    assert isinstance(client_ip_hash, str)
    assert len(client_ip_hash) == 64
    assert all(char in "0123456789abcdef" for char in client_ip_hash)
    assert "203.0.113.42" not in str(detail)
    assert detail.get("violation_count") == 1
    assert detail.get("auto_revoked") is False


# ---------------------------------------------------------------------------
# Allowlisted IP path: verify() should succeed (existing behaviour)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_returns_record_regardless_of_allowed_ip_cidrs() -> None:
    """``DbApiKeyVerifier.verify()`` returns ``ApiKeyRecord`` regardless of
    ``allowed_ip_cidrs`` — IP enforcement is the outer middleware's job.

    This pins the Phase 15 contract: the verifier does NOT perform IP
    checking; it simply threads the CIDR list through the returned
    record so the auth-router's :class:`IpEnforcer` can consume it.
    """
    from echoroo.services.api_key_verification import (
        DbApiKeyVerifier,
        hash_api_key_secret,
    )

    raw_secret = "cidr-test-secret"
    hashed = hash_api_key_secret(raw_secret)
    now = datetime.now(UTC)

    row = MagicMock()
    row.id = uuid4()
    row.user_id = uuid4()
    row.project_id = None
    row.prefix = "echoroo_cidrpref"
    row.hashed_secret = hashed
    row.granted_permissions = ["recordings:read"]
    row.revoked_at = None
    row.last_used_at = None
    row.expires_at = now + timedelta(days=365)
    row.created_at = now - timedelta(days=10)
    # Key has a restrictive CIDR list.
    row.allowed_ip_cidrs = ["10.0.0.0/24"]

    verifier = DbApiKeyVerifier(session_factory=MagicMock())
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    verifier._session_factory = MagicMock(return_value=mock_cm)

    raw_key = f"echoroo_cidrpref_{raw_secret}"
    with patch.object(
        verifier, "_load_by_prefix", new=AsyncMock(return_value=row)
    ), patch.object(verifier, "_maybe_bump_last_used", new=AsyncMock()):
        record = await verifier.verify(raw_key)

    # The verifier returns a record — IP enforcement is the caller's job.
    assert record is not None, (
        "DbApiKeyVerifier.verify() should return ApiKeyRecord regardless of "
        "allowed_ip_cidrs — IP enforcement is the outer middleware's job"
    )
    # Phase 17 A-3: the CIDR list flows through the record so the
    # downstream IpEnforcer does not have to re-load the row.
    assert record.allowed_ip_cidrs == ("10.0.0.0/24",)


__all__ = [
    "test_admin_schema_validates_cidr_strings",
    "test_api_key_allowed_ip_cidrs_stores_cidr_list",
    "test_api_key_model_has_allowed_ip_cidrs_column",
    "test_empty_allowed_ip_cidrs_means_no_restriction",
    "test_ip_in_cidr_stdlib_logic",
    "test_ip_violation_creates_audit_log_entry",
    "test_ip_violation_increments_counter",
    "test_new_api_key_allowed_ip_cidrs_defaults_to_none",
    "test_normalize_xff_hop_known_behaviour_out_of_range_port",
    "test_normalize_xff_hop_rejects_malformed_inputs",
    "test_request_from_non_allowlisted_ip_returns_403",
    "test_select_client_ip_falls_back_to_peer_when_no_xff",
    "test_select_client_ip_ignores_xff_from_untrusted_peer",
    "test_select_client_ip_ignores_xff_when_no_trusted_proxy_configured",
    "test_select_client_ip_rejects_ipv4_mapped_ipv6_in_xff",
    "test_select_client_ip_rejects_zone_id_ipv6_in_xff",
    "test_select_client_ip_strips_bracketed_ipv6_port_from_xff",
    "test_select_client_ip_strips_ipv4_port_from_xff",
    "test_select_client_ip_strips_ports_in_chain",
    "test_select_client_ip_strips_trusted_chain_right_to_left",
    "test_select_client_ip_uses_xff_from_trusted_peer",
    "test_three_ip_violations_auto_revokes_key",
    "test_verifier_returns_record_regardless_of_allowed_ip_cidrs",
]
