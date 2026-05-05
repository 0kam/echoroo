"""FR-083: 180-day API key scope degradation policy tests (T978).

The spec (``specs/006-permissions-redesign/spec.md`` line ~898) states:
  "API key: 離脱同一 TX revoke (60s 以内)、180 日経過 scope 縮退、
   allowed_ips 違反別カウンタ"

FR-083 further specifies a "推奨 rotation 90 日、UI warning バナー、上限 2 年".

The 180-day scope-degradation policy means that a key older than 180 days
should have its write-scoped permissions stripped — only read-only permissions
survive past the 180-day window. Past 270 days (180 + 90 grace) the key
should be treated as having no effective permissions.

**Current implementation status (Phase 17 backlog A-4):**
Implemented. ``DbApiKeyVerifier.verify()`` now applies the lazy
safety-net path via :func:`echoroo.services.api_key_lifecycle.
effective_permissions_for_age`, and the daily eager sweep lives in
:mod:`echoroo.workers.api_key_age_check` (01:15 UTC). Both paths share
the canonical write-scope catalogue
:data:`echoroo.services.api_key_lifecycle.API_KEY_WRITE_PERMISSIONS`.

The xfail markers were lifted as part of the A-4 ship; the assertions
below now run as live regression coverage.

Tests that exercise the *model* layer (attribute presence, counter columns)
and verifier correctness (non-degradation for fresh keys) run as normal
passing tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers — build an in-memory ApiKey-like record
# ---------------------------------------------------------------------------

_WRITE_PERMISSIONS = ["recordings:write", "detections:write"]
_READ_PERMISSIONS = ["recordings:read", "detections:read"]
_FULL_PERMISSIONS = _READ_PERMISSIONS + _WRITE_PERMISSIONS


def _build_fake_api_key_row(
    *,
    created_at: datetime,
    expires_at: datetime | None = None,
    granted_permissions: list[str] | None = None,
    revoked_at: datetime | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics ``ApiKey`` ORM columns."""
    row = MagicMock()
    row.id = uuid4()
    row.user_id = uuid4()
    row.project_id = None
    row.prefix = "echoroo_testpref"
    row.hashed_secret = "deadbeef" * 8  # 64-char hex placeholder
    row.granted_permissions = granted_permissions or list(_FULL_PERMISSIONS)
    row.revoked_at = revoked_at
    row.last_used_at = None
    # Default: key expires 2 years from creation
    row.expires_at = expires_at or (created_at + timedelta(days=730))
    row.created_at = created_at
    return row


# ---------------------------------------------------------------------------
# 1. Model layer: ApiKey has created_at, granted_permissions, ip_violation_count.
# ---------------------------------------------------------------------------


def test_api_key_model_has_required_scope_degradation_fields() -> None:
    """``ApiKey`` model MUST expose ``created_at`` and ``granted_permissions``
    so a scope-degradation check can be implemented without a schema migration.
    """
    from echoroo.models.api_key import ApiKey

    mapper = ApiKey.__mapper__
    col_names = {c.key for c in mapper.column_attrs}
    assert "created_at" in col_names, "ApiKey.created_at must exist"
    assert "granted_permissions" in col_names, "ApiKey.granted_permissions must exist"
    assert "ip_violation_count" in col_names, "ApiKey.ip_violation_count must exist"


# ---------------------------------------------------------------------------
# 2. Verifier returns full scope for a fresh key (< 90 days).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_key_returns_full_scope() -> None:
    """A key created 30 days ago MUST return all granted_permissions verbatim.

    This is the current (non-degraded) verifier behaviour. This test MUST
    remain passing even after the 180-day degradation is implemented.
    """
    from echoroo.services.api_key_verification import (
        DbApiKeyVerifier,
        hash_api_key_secret,
    )

    raw_secret = "freshsecret123"
    hashed = hash_api_key_secret(raw_secret)
    now = datetime.now(UTC)
    created_30_days_ago = now - timedelta(days=30)

    row = _build_fake_api_key_row(
        created_at=created_30_days_ago,
        granted_permissions=list(_FULL_PERMISSIONS),
    )
    row.hashed_secret = hashed
    row.expires_at = now + timedelta(days=700)

    verifier = DbApiKeyVerifier(session_factory=MagicMock())

    with patch.object(
        verifier, "_load_by_prefix", new=AsyncMock(return_value=row)
    ), patch.object(
        verifier, "_maybe_bump_last_used", new=AsyncMock()
    ):
        # Patch session.commit to be a no-op
        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        verifier._session_factory = MagicMock(return_value=mock_cm)

        raw_key = f"echoroo_testpref_{raw_secret}"
        # This relies on the prefix matching the row
        with patch.object(
            verifier,
            "_load_by_prefix",
            new=AsyncMock(return_value=row),
        ):
            record = await verifier.verify(raw_key)

    assert record is not None, "Fresh key should verify successfully"
    for perm in _FULL_PERMISSIONS:
        assert perm in record.granted_permissions, (
            f"Fresh key should retain permission '{perm}'"
        )


# ---------------------------------------------------------------------------
# 3. Key 180+ days old: write-scope permissions SHOULD be stripped.
#    xfail(strict=True) — not yet implemented.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_180d_old_key_loses_write_scope() -> None:
    """A key created 181 days ago MUST have write permissions stripped.

    After the scope-degradation is implemented the verifier (or a wrapping
    middleware) should inspect ``created_at`` and, when
    ``now - created_at > 180 days``, filter out any write-scoped permissions
    from ``ApiKeyRecord.granted_permissions``, leaving only read-only scopes.
    """
    from echoroo.services.api_key_verification import (
        DbApiKeyVerifier,
        hash_api_key_secret,
    )

    raw_secret = "oldsecret456"
    hashed = hash_api_key_secret(raw_secret)
    now = datetime.now(UTC)
    created_181_days_ago = now - timedelta(days=181)

    row = _build_fake_api_key_row(
        created_at=created_181_days_ago,
        granted_permissions=list(_FULL_PERMISSIONS),
    )
    row.hashed_secret = hashed
    row.expires_at = now + timedelta(days=549)  # still within 2-year window

    verifier = DbApiKeyVerifier(session_factory=MagicMock())
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    verifier._session_factory = MagicMock(return_value=mock_cm)

    raw_key = f"echoroo_testpref_{raw_secret}"
    with patch.object(
        verifier, "_load_by_prefix", new=AsyncMock(return_value=row)
    ), patch.object(verifier, "_maybe_bump_last_used", new=AsyncMock()):
        record = await verifier.verify(raw_key)

    assert record is not None
    # After degradation: write permissions should be absent.
    for perm in _WRITE_PERMISSIONS:
        assert perm not in record.granted_permissions, (
            f"Write permission '{perm}' should be stripped for 181-day-old key"
        )
    # Read permissions should survive.
    for perm in _READ_PERMISSIONS:
        assert perm in record.granted_permissions, (
            f"Read permission '{perm}' should survive scope degradation"
        )


# ---------------------------------------------------------------------------
# 4. Key 270+ days old: ALL permissions revoked / verifier returns None.
#    xfail(strict=True) — not yet implemented.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_270d_old_key_returns_no_permissions_or_none() -> None:
    """A key created 270+ days ago MUST return None or empty permissions.

    The 90-day grace period after the 180-day soft cut-off means that at
    270 days the key should be effectively dead — the verifier should return
    ``None`` (forcing a 401) or return an ``ApiKeyRecord`` with an empty
    ``granted_permissions`` tuple so the gate denies all actions.
    """
    from echoroo.services.api_key_verification import (
        DbApiKeyVerifier,
        hash_api_key_secret,
    )

    raw_secret = "verystalesecret"
    hashed = hash_api_key_secret(raw_secret)
    now = datetime.now(UTC)
    created_271_days_ago = now - timedelta(days=271)

    row = _build_fake_api_key_row(
        created_at=created_271_days_ago,
        granted_permissions=list(_FULL_PERMISSIONS),
    )
    row.hashed_secret = hashed
    row.expires_at = now + timedelta(days=459)

    verifier = DbApiKeyVerifier(session_factory=MagicMock())
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    verifier._session_factory = MagicMock(return_value=mock_cm)

    raw_key = f"echoroo_testpref_{raw_secret}"
    with patch.object(
        verifier, "_load_by_prefix", new=AsyncMock(return_value=row)
    ), patch.object(verifier, "_maybe_bump_last_used", new=AsyncMock()):
        record = await verifier.verify(raw_key)

    # Either None or empty permissions is acceptable.
    if record is not None:
        assert record.granted_permissions == (), (
            "270-day-old key should have no effective permissions"
        )


# ---------------------------------------------------------------------------
# 5. Rotated (newly created) key gets full scope back.
#    This tests the model-level invariant; actual rotation endpoint is
#    tested in the contract suite.
# ---------------------------------------------------------------------------


def test_new_key_after_rotation_starts_with_full_scope() -> None:
    """A freshly-created key MUST start with full ``granted_permissions``.

    After key rotation the new row has ``created_at = now`` and
    ``granted_permissions`` as specified. The scope-degradation clock
    resets to zero. This test pins the model-level invariant.
    """
    from echoroo.models.api_key import ApiKey

    now = datetime.now(UTC)
    key = ApiKey(
        user_id=uuid4(),
        prefix="echoroo_newprefix",
        hashed_secret="a" * 64,
        granted_permissions=list(_FULL_PERMISSIONS),
        expires_at=now + timedelta(days=365),
    )
    assert key.granted_permissions == list(_FULL_PERMISSIONS), (
        "New key should have the full set of granted permissions on creation"
    )


# ---------------------------------------------------------------------------
# 6. ip_violation_count column is zero-defaulted on new keys.
# ---------------------------------------------------------------------------


def test_new_api_key_ip_violation_count_is_zero() -> None:
    """``ip_violation_count`` MUST be 0 (or None until DB flush) on new ApiKey rows.

    The column has ``server_default=text("0")`` which is applied at the DB
    level on INSERT. Before the row is flushed to the DB, the Python-side
    value may be ``None`` (SQLAlchemy defers server defaults). After a flush
    or commit the column is ``0``. Both ``None`` and ``0`` are acceptable
    at construction time.
    """
    from echoroo.models.api_key import ApiKey

    now = datetime.now(UTC)
    key = ApiKey(
        user_id=uuid4(),
        prefix="echoroo_zeroviols",
        hashed_secret="b" * 64,
        granted_permissions=["recordings:read"],
        expires_at=now + timedelta(days=365),
    )
    # Before DB flush: server_default hasn't fired yet; Python-side value
    # is None or 0 depending on ORM version and column default handling.
    assert key.ip_violation_count in (None, 0), (
        f"ip_violation_count should be None (pre-flush) or 0 (post-flush), "
        f"got {key.ip_violation_count!r}"
    )


# ---------------------------------------------------------------------------
# 7. Round 2 Fix R1-I1 — last_used_at MUST NOT be bumped for a key that
#    the verifier ultimately rejects via the age-based revoke branch.
#
#    Before the fix, ``_maybe_bump_last_used`` ran BEFORE
#    ``effective_permissions_for_age``, so a 270-day-old key would have
#    its ``last_used_at`` advanced even though ``verify()`` returned
#    ``None``. That created forensic drift with the FR-083 model that
#    "270-day keys do not authenticate".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_age_revoked_key_does_not_bump_last_used_at() -> None:
    """A 271-day-old key MUST be rejected (verify → None) AND its
    ``last_used_at`` MUST stay untouched (no UPDATE issued).

    Round 2 Fix R1-I1 regression net.
    """
    from echoroo.services.api_key_verification import (
        DbApiKeyVerifier,
        hash_api_key_secret,
    )

    raw_secret = "agedrejectsecret"
    hashed = hash_api_key_secret(raw_secret)
    now = datetime.now(UTC)
    created_271_days_ago = now - timedelta(days=271)

    row = _build_fake_api_key_row(
        created_at=created_271_days_ago,
        granted_permissions=list(_FULL_PERMISSIONS),
    )
    row.hashed_secret = hashed
    row.expires_at = now + timedelta(days=459)
    row.last_used_at = None  # never used → bump WOULD be attempted if reached

    verifier = DbApiKeyVerifier(session_factory=MagicMock())
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    verifier._session_factory = MagicMock(return_value=mock_cm)

    bump_spy = AsyncMock()
    raw_key = f"echoroo_testpref_{raw_secret}"
    with patch.object(
        verifier, "_load_by_prefix", new=AsyncMock(return_value=row)
    ), patch.object(verifier, "_maybe_bump_last_used", new=bump_spy):
        record = await verifier.verify(raw_key)

    # Verifier MUST reject the aged key.
    assert record is None, "270+ day old key MUST not authenticate"

    # CRITICAL: the bump MUST NOT have been called for an
    # ultimately-rejected key. Calling it would advance ``last_used_at``
    # on a key the verifier treats as "did not authenticate", breaking
    # the FR-083 forensic model.
    bump_spy.assert_not_called()

    # And the session MUST NOT have been told to commit a stray UPDATE.
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_age_degraded_key_still_bumps_last_used_at() -> None:
    """A 181-day-old key authenticates (read-only) → ``last_used_at``
    bump MAY proceed. This pins the converse of Fix R1-I1: degradation
    is NOT a rejection, so the forensic timestamp should still advance.
    """
    from echoroo.services.api_key_verification import (
        DbApiKeyVerifier,
        hash_api_key_secret,
    )

    raw_secret = "agedreadonlysecret"
    hashed = hash_api_key_secret(raw_secret)
    now = datetime.now(UTC)
    created_181_days_ago = now - timedelta(days=181)

    row = _build_fake_api_key_row(
        created_at=created_181_days_ago,
        granted_permissions=list(_FULL_PERMISSIONS),
    )
    row.hashed_secret = hashed
    row.expires_at = now + timedelta(days=549)
    row.last_used_at = None

    verifier = DbApiKeyVerifier(session_factory=MagicMock())
    mock_session = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    verifier._session_factory = MagicMock(return_value=mock_cm)

    bump_spy = AsyncMock()
    raw_key = f"echoroo_testpref_{raw_secret}"
    with patch.object(
        verifier, "_load_by_prefix", new=AsyncMock(return_value=row)
    ), patch.object(verifier, "_maybe_bump_last_used", new=bump_spy):
        record = await verifier.verify(raw_key)

    assert record is not None, "181-day-old key MUST still authenticate"
    bump_spy.assert_called_once()


__all__ = [
    "test_180d_old_key_loses_write_scope",
    "test_270d_old_key_returns_no_permissions_or_none",
    "test_age_degraded_key_still_bumps_last_used_at",
    "test_age_revoked_key_does_not_bump_last_used_at",
    "test_api_key_model_has_required_scope_degradation_fields",
    "test_fresh_key_returns_full_scope",
    "test_new_api_key_ip_violation_count_is_zero",
    "test_new_key_after_rotation_starts_with_full_scope",
]
