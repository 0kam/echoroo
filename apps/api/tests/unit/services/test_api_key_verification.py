"""Unit tests for echoroo.services.api_key_verification (T995, PR-004).

These tests cover the pure-function surface of the api_key_verification
module to achieve >= 80% mutation score for T995:

* parse_api_key — wire-format splitter
* hash_api_key_secret — SHA-256 digest helper
* DbApiKeyVerifier.verify — lifecycle checks (revoked, expired, hash mismatch)
* DbApiKeyVerifier._maybe_bump_last_used — debounce logic

Tests use MagicMock/AsyncMock stubs for the SQLAlchemy session so there is
no live-DB requirement. Integration-level coverage (real DB lookups) is
provided by tests/performance/test_api_key_verify_p95.py and the contract
suite.

Mutation-score focus: boundary conditions (None vs non-None, <= vs <,
is vs is not) are explicitly tested so common operator mutations are killed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.services.api_key_verification import (
    KEY_NAMESPACE,
    LAST_USED_DEBOUNCE,
    STORED_PREFIX_LEN,
    DbApiKeyVerifier,
    hash_api_key_secret,
    parse_api_key,
)

# ---------------------------------------------------------------------------
# parse_api_key — wire format
# ---------------------------------------------------------------------------


class TestParseApiKey:
    """Tests for the parse_api_key wire-format splitter."""

    def _valid_key(self, prefix_suffix: str = "abcdefgh", secret: str = "mysecret123") -> str:
        return f"{KEY_NAMESPACE}{prefix_suffix}_{secret}"

    def test_valid_key_returns_prefix_and_secret(self) -> None:
        raw = self._valid_key()
        result = parse_api_key(raw)
        assert result is not None
        stored_prefix, secret = result
        assert stored_prefix == f"{KEY_NAMESPACE}abcdefgh"
        assert secret == "mysecret123"

    def test_stored_prefix_length(self) -> None:
        raw = self._valid_key()
        result = parse_api_key(raw)
        assert result is not None
        assert len(result[0]) == STORED_PREFIX_LEN

    def test_empty_string_returns_none(self) -> None:
        assert parse_api_key("") is None

    def test_no_namespace_returns_none(self) -> None:
        assert parse_api_key("notechoroo_abcdefgh_secret") is None

    def test_prefix_too_short_returns_none(self) -> None:
        # 7 chars instead of 8
        assert parse_api_key(f"{KEY_NAMESPACE}abcdefg_secret") is None

    def test_prefix_too_long_returns_none(self) -> None:
        # 9 chars instead of 8
        assert parse_api_key(f"{KEY_NAMESPACE}abcdefghi_secret") is None

    def test_missing_secret_returns_none(self) -> None:
        # No underscore after prefix
        assert parse_api_key(f"{KEY_NAMESPACE}abcdefgh") is None

    def test_empty_secret_returns_none(self) -> None:
        # Trailing underscore but no secret content
        assert parse_api_key(f"{KEY_NAMESPACE}abcdefgh_") is None

    def test_non_alphanumeric_prefix_returns_none(self) -> None:
        # Special chars in prefix segment
        assert parse_api_key(f"{KEY_NAMESPACE}abc!efgh_secret") is None

    def test_uppercase_in_prefix_accepted(self) -> None:
        raw = f"{KEY_NAMESPACE}ABCDEFgh_mysecret"
        result = parse_api_key(raw)
        assert result is not None

    def test_secret_with_hyphens_and_underscores_accepted(self) -> None:
        raw = self._valid_key(secret="abc-def_ghi123")
        result = parse_api_key(raw)
        assert result is not None
        assert result[1] == "abc-def_ghi123"

    def test_none_like_input_raises_or_returns_none(self) -> None:
        # Passing None explicitly (type: ignore for mypy)
        result = parse_api_key(None)  # type: ignore[arg-type]
        assert result is None

    def test_multipart_secret_with_multiple_underscores(self) -> None:
        # Secret itself may contain underscores; only the FIRST underscore after
        # the 8-char prefix is the separator.
        raw = f"{KEY_NAMESPACE}abcdefgh_secret_with_underscores"
        result = parse_api_key(raw)
        assert result is not None
        # The regex is greedy on the secret group, so the full remainder is secret.
        assert "secret" in result[1]


# ---------------------------------------------------------------------------
# hash_api_key_secret
# ---------------------------------------------------------------------------


class TestHashApiKeySecret:
    def test_returns_sha256_hex(self) -> None:
        secret = "testpassword"
        expected = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        assert hash_api_key_secret(secret) == expected

    def test_length_is_64_chars(self) -> None:
        assert len(hash_api_key_secret("x")) == 64

    def test_empty_string(self) -> None:
        expected = hashlib.sha256(b"").hexdigest()
        assert hash_api_key_secret("") == expected

    def test_different_secrets_produce_different_hashes(self) -> None:
        h1 = hash_api_key_secret("secret1")
        h2 = hash_api_key_secret("secret2")
        assert h1 != h2

    def test_same_secret_is_deterministic(self) -> None:
        s = "reproducible"
        assert hash_api_key_secret(s) == hash_api_key_secret(s)


# ---------------------------------------------------------------------------
# DbApiKeyVerifier.verify — lifecycle checks via mock session
# ---------------------------------------------------------------------------


def _build_fake_row(
    *,
    hashed_secret: str = "",
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
    last_used_at: datetime | None = None,
    granted_permissions: list[str] | None = None,
    project_id: object | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.user_id = uuid4()
    row.hashed_secret = hashed_secret
    row.revoked_at = revoked_at
    row.expires_at = expires_at
    row.last_used_at = last_used_at
    row.granted_permissions = granted_permissions or []
    row.project_id = project_id
    row.prefix = "echoroo_abcdefgh"
    # Phase 17 A-4: ``DbApiKeyVerifier`` now consults ``created_at`` for
    # the lazy scope-degradation safety net. Default to "fresh" so the
    # existing lifecycle tests (which only care about revoked / expired
    # branches) keep their original semantics.
    row.created_at = created_at or (datetime.now(UTC) - timedelta(days=1))
    return row


def _build_verifier_with_row(row: MagicMock | None) -> tuple[DbApiKeyVerifier, AsyncMock]:
    """Build a DbApiKeyVerifier whose session returns `row` from _load_by_prefix."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)
    # Make the factory usable as an async context manager
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    verifier = DbApiKeyVerifier(mock_factory)
    return verifier, mock_session


@pytest.mark.asyncio
class TestDbApiKeyVerifier:
    _VALID_SECRET = "validsecret99"
    _VALID_PREFIX = "abcdefgh"
    _RAW_KEY = f"{KEY_NAMESPACE}{_VALID_PREFIX}_{_VALID_SECRET}"

    def _make_row_with_correct_hash(
        self,
        *,
        revoked_at: datetime | None = None,
        expires_at: datetime | None = None,
        last_used_at: datetime | None = None,
        granted_permissions: list[str] | None = None,
        project_id: object | None = None,
    ) -> MagicMock:
        hashed = hash_api_key_secret(self._VALID_SECRET)
        return _build_fake_row(
            hashed_secret=hashed,
            revoked_at=revoked_at,
            expires_at=expires_at,
            last_used_at=last_used_at,
            granted_permissions=granted_permissions,
            project_id=project_id,
        )

    async def test_malformed_key_returns_none(self) -> None:
        verifier, _ = _build_verifier_with_row(None)
        result = await verifier.verify("not_a_valid_key")
        assert result is None

    async def test_prefix_not_found_returns_none(self) -> None:
        verifier, _ = _build_verifier_with_row(None)
        result = await verifier.verify(self._RAW_KEY)
        assert result is None

    async def test_hash_mismatch_returns_none(self) -> None:
        row = _build_fake_row(
            hashed_secret=hash_api_key_secret("wrong_secret"),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        verifier, _ = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is None

    async def test_revoked_key_returns_none(self) -> None:
        row = self._make_row_with_correct_hash(
            revoked_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        verifier, _ = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is None

    async def test_expired_key_returns_none(self) -> None:
        row = self._make_row_with_correct_hash(
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        verifier, _ = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is None

    async def test_none_expires_at_returns_none(self) -> None:
        """Defensive: missing expires_at column treats key as invalid."""
        row = self._make_row_with_correct_hash(expires_at=None)
        verifier, _ = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is None

    async def test_valid_key_returns_record(self) -> None:
        row = self._make_row_with_correct_hash(
            expires_at=datetime.now(UTC) + timedelta(days=30),
            granted_permissions=["view_detection"],
        )
        verifier, _ = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is not None
        assert result.user_id == row.user_id
        assert result.api_key_id == row.id
        assert "view_detection" in result.granted_permissions

    async def test_project_id_threaded_through(self) -> None:
        pid = uuid4()
        row = self._make_row_with_correct_hash(
            expires_at=datetime.now(UTC) + timedelta(days=30),
            project_id=pid,
        )
        verifier, _ = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is not None
        assert result.project_id == pid

    async def test_naive_expires_at_treated_as_utc(self) -> None:
        """A naive expires_at (no tzinfo) is treated as UTC and validated correctly."""
        # Naive datetime 30 days in future should be valid
        row = self._make_row_with_correct_hash(
            expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
        )
        verifier, _ = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is not None

    async def test_naive_expires_at_past_returns_none(self) -> None:
        """A naive expires_at in the past is treated as UTC and rejected."""
        row = self._make_row_with_correct_hash(
            expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
        )
        verifier, _ = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is None

    async def test_exactly_at_expiry_returns_none(self) -> None:
        """Boundary: key expiring exactly at 'now' is not valid (FR-082)."""
        now = datetime.now(UTC)
        row = self._make_row_with_correct_hash(expires_at=now)
        verifier, _ = _build_verifier_with_row(row)
        with patch("echoroo.services.api_key_verification.datetime") as mock_dt:
            mock_dt.now.return_value = now
            result = await verifier.verify(self._RAW_KEY)
        assert result is None

    async def test_bump_last_used_skipped_within_debounce(self) -> None:
        """Within the debounce window the UPDATE should be skipped."""
        recent = datetime.now(UTC) - timedelta(seconds=30)  # within 60s debounce
        row = self._make_row_with_correct_hash(
            expires_at=datetime.now(UTC) + timedelta(days=30),
            last_used_at=recent,
        )
        verifier, mock_session = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is not None
        # The session.execute should only be called once (the SELECT).
        # A debounced bump would call execute a second time for the UPDATE.
        assert mock_session.execute.call_count == 1

    async def test_bump_last_used_issued_when_debounce_expired(self) -> None:
        """Outside the debounce window the UPDATE should be issued."""
        old_used = datetime.now(UTC) - (LAST_USED_DEBOUNCE + timedelta(seconds=1))
        row = self._make_row_with_correct_hash(
            expires_at=datetime.now(UTC) + timedelta(days=30),
            last_used_at=old_used,
        )
        verifier, mock_session = _build_verifier_with_row(row)
        result = await verifier.verify(self._RAW_KEY)
        assert result is not None
        # Two execute calls: SELECT + UPDATE
        assert mock_session.execute.call_count == 2

    async def test_bump_failure_does_not_fail_verification(self) -> None:
        """A commit failure on last_used_at bump must NOT block the result."""
        row = self._make_row_with_correct_hash(
            expires_at=datetime.now(UTC) + timedelta(days=30),
            last_used_at=None,  # never used → bump will be attempted
        )
        verifier, mock_session = _build_verifier_with_row(row)
        # Make commit raise to simulate DB error
        mock_session.commit = AsyncMock(side_effect=RuntimeError("db error"))
        result = await verifier.verify(self._RAW_KEY)
        # Should still return a valid ApiKeyRecord despite the bump failure
        assert result is not None
        mock_session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# DbApiKeyVerifier._maybe_bump_last_used — debounce boundary unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMaybeBumpLastUsed:
    """Isolated tests for the debounce boundary logic in _maybe_bump_last_used."""

    def _verifier(self) -> DbApiKeyVerifier:
        return DbApiKeyVerifier(MagicMock(), last_used_debounce=timedelta(minutes=1))

    async def test_no_last_used_triggers_update(self) -> None:
        verifier = self._verifier()
        row = MagicMock()
        row.id = uuid4()
        row.last_used_at = None
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        now = datetime.now(UTC)
        await verifier._maybe_bump_last_used(mock_session, row, now=now)
        mock_session.execute.assert_called_once()

    async def test_within_debounce_skips_update(self) -> None:
        verifier = self._verifier()
        row = MagicMock()
        row.id = uuid4()
        now = datetime.now(UTC)
        row.last_used_at = now - timedelta(seconds=30)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        await verifier._maybe_bump_last_used(mock_session, row, now=now)
        mock_session.execute.assert_not_called()

    async def test_exactly_at_debounce_boundary_triggers_update(self) -> None:
        """Exactly at the debounce boundary (diff == debounce) → UPDATE issued.

        The implementation uses `< self._last_used_debounce` so equal-to-debounce
        is NOT within the window and triggers an UPDATE (boundary exclusive).
        """
        verifier = self._verifier()
        row = MagicMock()
        row.id = uuid4()
        now = datetime.now(UTC)
        row.last_used_at = now - timedelta(minutes=1)  # exactly equal to debounce
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        await verifier._maybe_bump_last_used(mock_session, row, now=now)
        mock_session.execute.assert_called_once()

    async def test_just_past_debounce_triggers_update(self) -> None:
        """One second past the debounce window → UPDATE issued."""
        verifier = self._verifier()
        row = MagicMock()
        row.id = uuid4()
        now = datetime.now(UTC)
        row.last_used_at = now - timedelta(minutes=1) - timedelta(seconds=1)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        await verifier._maybe_bump_last_used(mock_session, row, now=now)
        mock_session.execute.assert_called_once()

    async def test_naive_last_used_at_treated_as_utc(self) -> None:
        """A naive last_used_at (no tzinfo) should be promoted to UTC."""
        verifier = self._verifier()
        row = MagicMock()
        row.id = uuid4()
        now = datetime.now(UTC)
        # Naive datetime 30s ago — within debounce
        row.last_used_at = (now - timedelta(seconds=30)).replace(tzinfo=None)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        await verifier._maybe_bump_last_used(mock_session, row, now=now)
        mock_session.execute.assert_not_called()
