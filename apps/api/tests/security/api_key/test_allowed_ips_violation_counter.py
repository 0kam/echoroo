"""FR-077 / FR-081: API key allowed_ip_cidrs enforcement + violation counter (T979d).

The ``api_keys.allowed_ip_cidrs`` column stores an optional CIDR allowlist.
When set, requests from IPs outside the allowlist MUST be rejected (403) and
the violation MUST be recorded (audit log entry + ``ip_violation_count``
increment).

Spec references:
- FR-077: ``/api/v1/*`` requires API key; optional ``allowed_ips``.
- FR-081: ``allowed_ips`` violation 3 times → automatic revoke (separate counter).
- Spec line ~898: "allowed_ips 違反別カウンタ" (separate violation counter).

**Current implementation status:**
The ``DbApiKeyVerifier.verify()`` (Phase 15 T155b) resolves the API key and
returns an ``ApiKeyRecord`` carrying ``allowed_ip_cidrs`` on the ORM row — but
the actual IP-vs-CIDR comparison and counter increment are documented as the
responsibility of an "outer IP enforcement middleware" (see the module docstring
of ``api_key_verification.py`` line 30). That outer middleware is **NOT
implemented** in the current phase.

Consequently:
- Tests that verify the *model* layer (column existence, default value, CIDR
  schema validation) run as normal passing tests.
- Tests that require the outer middleware to enforce the CIDR restriction
  (reject 403, increment counter, auto-revoke at 3 violations) are marked
  ``xfail(strict=True)`` to document the TDD-red state.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: F401
from uuid import uuid4

import pytest

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

    This test documents the pure-Python logic that an enforcement middleware
    MUST use to compare the caller's IP against ``allowed_ip_cidrs``.
    """
    network = ipaddress.ip_network("10.0.0.0/24", strict=False)
    assert ipaddress.ip_address("10.0.0.100") in network
    assert ipaddress.ip_address("10.0.1.1") not in network
    assert ipaddress.ip_address("192.168.1.1") not in network


def test_empty_allowed_ip_cidrs_means_no_restriction() -> None:
    """An empty ``allowed_ip_cidrs`` list MUST be interpreted as 'no restriction'.

    This is the semantic contract: ``None`` and ``[]`` both mean "all IPs
    allowed". An enforcement middleware MUST NOT block traffic when
    ``allowed_ip_cidrs`` is empty.
    """
    # Document the expected semantics: both None and [] → allow-all.
    for cidrs in [None, []]:
        if cidrs is None:
            restricted = False
        else:
            # Empty list → no CIDR to check → allow-all.
            restricted = any(
                ipaddress.ip_address("1.2.3.4") in ipaddress.ip_network(c, strict=False)
                for c in cidrs
            )
        assert not restricted, (
            f"allowed_ip_cidrs={cidrs!r} should mean no restriction"
        )


# ---------------------------------------------------------------------------
# Enforcement middleware tests (xfail — middleware not yet implemented)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The outer IP-enforcement middleware that inspects "
        "ApiKey.allowed_ip_cidrs and rejects requests from non-allowlisted "
        "IPs with HTTP 403 is NOT implemented in the current phase. "
        "DbApiKeyVerifier.verify() returns the ApiKeyRecord with the CIDR "
        "list but does not perform IP comparison itself (see module docstring "
        "of api_key_verification.py). Implement the middleware in a future task."
    ),
)
@pytest.mark.asyncio
async def test_request_from_non_allowlisted_ip_returns_403(
    db_session: Any,
) -> None:
    """A request whose source IP is NOT in ``allowed_ip_cidrs`` MUST be rejected
    with HTTP 403.

    The enforcement middleware should:
    1. Resolve the API key via ``DbApiKeyVerifier.verify()``.
    2. Load the ``allowed_ip_cidrs`` from the row.
    3. Compare the client IP against each CIDR.
    4. If no CIDR matches → HTTP 403 with ``err_ip_not_allowed``.
    """
    # This test cannot pass until the enforcement middleware exists.
    # Placeholder assertion that forces xfail.
    raise AssertionError(
        "IP enforcement middleware not implemented — "
        "request from 192.168.1.1 to a key restricted to 10.0.0.0/24 "
        "should return 403"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ip_violation_count increment on allowlist violation is NOT implemented. "
        "The ApiKey.ip_violation_count column exists but no middleware increments "
        "it when a request comes from an unlisted IP. FR-081 specifies auto-revoke "
        "at 3 violations. Implement counter logic in a future task."
    ),
)
@pytest.mark.asyncio
async def test_ip_violation_increments_counter(
    db_session: Any,
) -> None:
    """Each IP-allowlist violation MUST increment ``api_keys.ip_violation_count``.

    After the enforcement middleware is implemented, a request from a
    non-allowlisted IP should atomically increment the counter column so the
    auto-revoke trigger (FR-081: 3 violations → revoke) has reliable data.
    """
    raise AssertionError(
        "ip_violation_count increment not implemented — "
        "after 3 violations the key should be auto-revoked per FR-081"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Auto-revoke at 3 IP violations (FR-081) is NOT implemented. "
        "ip_violation_count column exists but no enforcement logic triggers "
        "revocation when the count reaches 3. Implement auto-revoke in future task."
    ),
)
@pytest.mark.asyncio
async def test_three_ip_violations_auto_revokes_key(
    db_session: Any,
) -> None:
    """After 3 IP-allowlist violations the API key MUST be auto-revoked (FR-081).

    ``revoked_at`` should be set and subsequent requests — even from the
    allowlisted IP — should return 401 (key revoked).
    """
    raise AssertionError(
        "Auto-revoke after 3 IP violations not implemented (FR-081)"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Audit log entry on IP violation is NOT implemented. "
        "The outer enforcement middleware should write an audit log row "
        "when it rejects a request due to IP-allowlist mismatch. "
        "Implement audit logging in the enforcement middleware."
    ),
)
@pytest.mark.asyncio
async def test_ip_violation_creates_audit_log_entry(
    db_session: Any,
) -> None:
    """An IP-allowlist violation MUST produce an audit log entry.

    The audit record should include:
    - ``action``: ``api_key.ip_violation`` or similar.
    - ``actor_id``: the user owning the key.
    - ``resource_id``: the ``api_key_id``.
    - ``detail``: the source IP and the allowlist.
    """
    raise AssertionError(
        "Audit log entry on IP violation not implemented"
    )


# ---------------------------------------------------------------------------
# Allowlisted IP path: verify() should succeed (existing behaviour)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_returns_record_regardless_of_allowed_ip_cidrs() -> None:
    """``DbApiKeyVerifier.verify()`` returns ``ApiKeyRecord`` regardless of
    ``allowed_ip_cidrs`` — IP enforcement is the outer middleware's job.

    This test pins the existing (phase 15) contract: the verifier does NOT
    perform IP checking; the CIDR list is carried on the ORM row for the
    middleware to inspect.
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


__all__ = [
    "test_admin_schema_validates_cidr_strings",
    "test_api_key_allowed_ip_cidrs_stores_cidr_list",
    "test_api_key_model_has_allowed_ip_cidrs_column",
    "test_empty_allowed_ip_cidrs_means_no_restriction",
    "test_ip_in_cidr_stdlib_logic",
    "test_ip_violation_creates_audit_log_entry",
    "test_ip_violation_increments_counter",
    "test_new_api_key_allowed_ip_cidrs_defaults_to_none",
    "test_request_from_non_allowlisted_ip_returns_403",
    "test_three_ip_violations_auto_revokes_key",
    "test_verifier_returns_record_regardless_of_allowed_ip_cidrs",
]
