"""Unit tests for echoroo.api.web_v1.auth_confirm_identity (Phase 17 coverage uplift).

Targets the uncovered lines from 74% → ≥85%:
  - Line 68: _client_ip() — X-Forwarded-For header present
  - Line 77: _request_id() — returns X-Request-Id header
  - Lines 91-92: _rate_limit_check() — rate limit triggered (return True)
  - Line 100: _normalize_email() — non-string input returns None
  - Line 103: _normalize_email() — control characters returns None
  - Lines 172-179: request endpoint rate-limit drop path
  - Line 192: endpoint — deleted user / no-2fa path (user.deleted_at is not None)
  - Lines 212-216: user_id_for_audit assignment + try block start
  - Lines 224-226: exception path (db.rollback + logger.exception)
  - Lines 279-280, 288, 305: redeem endpoint success and MagicLinkInvalidError
  - Lines 324->exit: _sleep_for_minimum when remaining > 0
  - Lines 335-351: _write_audit inner body via mocked AsyncSessionLocal

These tests are unit-level: no real database, no network.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import echoroo.api.web_v1.auth_confirm_identity as ci_mod
from echoroo.api.web_v1.auth_confirm_identity import (
    _client_ip,
    _normalize_email,
    _rate_limit_check,
    _request_id,
    _request_windows,
    _sleep_for_minimum,
    _write_audit,
    router,
)
from echoroo.core.database import get_db


def _stub_pii_hash(value: Any) -> str:
    """Deterministic PII hash stub that bypasses KMS."""
    import hashlib
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Helper: minimal FastAPI app mounting only the confirm-identity router
# ---------------------------------------------------------------------------


def _make_app(db_override: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/web-api/v1")

    async def _db() -> AsyncGenerator[Any, None]:
        yield db_override

    app.dependency_overrides[get_db] = _db
    return app


# ---------------------------------------------------------------------------
# _client_ip — X-Forwarded-For header present (line 68)
# ---------------------------------------------------------------------------


def test_client_ip_uses_x_forwarded_for_header_unit() -> None:
    """_client_ip returns the first IP from X-Forwarded-For (line 68) — unit test."""
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-forwarded-for": "203.0.113.5, 10.0.0.1, 172.16.0.1"}
    mock_request.client = None

    result = _client_ip(mock_request)
    assert result == "203.0.113.5"


def test_client_ip_returns_first_ip_from_forwarded_for() -> None:
    """_client_ip with X-Forwarded-For header returns first IP (line 68)."""
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-forwarded-for": "203.0.113.5, 10.0.0.1"}
    mock_request.client = None

    result = _client_ip(mock_request)
    assert result == "203.0.113.5"


def test_client_ip_returns_unknown_when_forwarded_for_is_empty_after_strip() -> None:
    """_client_ip with blank X-Forwarded-For falls back to 'unknown' (line 68)."""
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-forwarded-for": "  "}
    mock_request.client = None

    result = _client_ip(mock_request)
    assert result == "unknown"


def test_client_ip_returns_client_host_when_no_forwarded_for() -> None:
    """_client_ip without X-Forwarded-For returns request.client.host."""
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"

    result = _client_ip(mock_request)
    assert result == "127.0.0.1"


# ---------------------------------------------------------------------------
# _request_id — returns X-Request-Id header (line 77)
# ---------------------------------------------------------------------------


def test_request_id_returns_header_value() -> None:
    """_request_id must return the X-Request-Id header value (line 77)."""
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {"x-request-id": "req-abc123"}

    result = _request_id(mock_request)
    assert result == "req-abc123"


def test_request_id_returns_empty_string_when_absent() -> None:
    """_request_id returns empty string when header is absent."""
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}

    result = _request_id(mock_request)
    assert result == ""


# ---------------------------------------------------------------------------
# _rate_limit_check — rate limit triggered (lines 91-92)
# ---------------------------------------------------------------------------


def test_rate_limit_check_returns_true_when_ip_limit_exceeded() -> None:
    """_rate_limit_check returns True when IP rate limit is exceeded (lines 91-92).

    Spec: ``_REQUEST_IP_LIMIT == 10`` (10 attempts per 10-minute window).
    The literal is repeated here so a silent value change in the
    implementation (e.g. 10 → 20) trips this drift assertion before the
    boundary test pretends to still pass.
    """
    from echoroo.api.web_v1.auth_confirm_identity import (
        _REQUEST_IP_LIMIT,
    )

    EXPECTED_IP_LIMIT = 10
    assert _REQUEST_IP_LIMIT == EXPECTED_IP_LIMIT, (
        f"Spec drift: _REQUEST_IP_LIMIT changed to {_REQUEST_IP_LIMIT}, "
        f"update the rate-limit boundary tests to match the new value."
    )

    # Use a unique IP to avoid polluting other tests
    test_ip = f"test_rate_ip_{uuid4().hex[:8]}"
    email_hash = "test-email-hash-" + uuid4().hex[:8]

    ip_key = f"2fa_reset_request:ip:{test_ip}"
    email_key = f"2fa_reset_request:email:{email_hash}"

    now = time.monotonic()
    try:
        # Pre-fill the window with exactly the literal limit (10)
        _request_windows[ip_key] = [now - 1.0] * EXPECTED_IP_LIMIT

        result = _rate_limit_check(ip=test_ip, email_hash=email_hash)
        assert result is True
    finally:
        # Cleanup both potential keys (defensive — the email key would
        # only get appended if ip_key did not trigger first, but the
        # global state must be tidy regardless of branch).
        _request_windows.pop(ip_key, None)
        _request_windows.pop(email_key, None)


def test_rate_limit_check_ip_at_one_below_limit_allows_one_more() -> None:
    """One slot below ``_REQUEST_IP_LIMIT`` must still allow the request.

    Boundary check: this guards against off-by-one drift such as
    ``len(window) > limit`` instead of ``len(window) >= limit``.
    """
    from echoroo.api.web_v1.auth_confirm_identity import (
        _REQUEST_IP_LIMIT,
    )

    EXPECTED_IP_LIMIT = 10
    assert _REQUEST_IP_LIMIT == EXPECTED_IP_LIMIT, (
        f"Spec drift: _REQUEST_IP_LIMIT changed to {_REQUEST_IP_LIMIT}."
    )

    test_ip = f"test_rate_ip_off_{uuid4().hex[:8]}"
    email_hash = "test-email-off-" + uuid4().hex[:8]
    ip_key = f"2fa_reset_request:ip:{test_ip}"
    email_key = f"2fa_reset_request:email:{email_hash}"

    now = time.monotonic()
    try:
        _request_windows[ip_key] = [now - 1.0] * (EXPECTED_IP_LIMIT - 1)
        result = _rate_limit_check(ip=test_ip, email_hash=email_hash)
        assert result is False
    finally:
        _request_windows.pop(ip_key, None)
        _request_windows.pop(email_key, None)


def test_rate_limit_check_returns_true_when_email_limit_exceeded() -> None:
    """_rate_limit_check returns True when email rate limit is exceeded (lines 91-92).

    Spec: ``_REQUEST_EMAIL_LIMIT == 3`` (3 attempts per 10-minute window).
    The literal is repeated so a silent change (e.g. 3 → 5) is caught
    before the boundary check below silently follows it.
    """
    from echoroo.api.web_v1.auth_confirm_identity import (
        _REQUEST_EMAIL_LIMIT,
    )

    EXPECTED_EMAIL_LIMIT = 3
    assert _REQUEST_EMAIL_LIMIT == EXPECTED_EMAIL_LIMIT, (
        f"Spec drift: _REQUEST_EMAIL_LIMIT changed to {_REQUEST_EMAIL_LIMIT}, "
        f"update the rate-limit boundary tests to match the new value."
    )

    # Use a unique IP that hasn't hit the IP limit
    test_ip = f"test_rate_ip2_{uuid4().hex[:8]}"
    email_hash = "test-email-hash2-" + uuid4().hex[:8]

    ip_key = f"2fa_reset_request:ip:{test_ip}"
    email_key = f"2fa_reset_request:email:{email_hash}"

    now = time.monotonic()
    try:
        # Pre-fill email window with exactly the literal email limit (3)
        _request_windows[email_key] = [now - 1.0] * EXPECTED_EMAIL_LIMIT

        result = _rate_limit_check(ip=test_ip, email_hash=email_hash)
        assert result is True
    finally:
        # Cleanup both keys to keep global state clean
        _request_windows.pop(ip_key, None)
        _request_windows.pop(email_key, None)


def test_rate_limit_check_email_at_one_below_limit_allows_one_more() -> None:
    """One slot below ``_REQUEST_EMAIL_LIMIT`` must still allow the request.

    Boundary check: guards against off-by-one drift on the email scope.
    """
    from echoroo.api.web_v1.auth_confirm_identity import (
        _REQUEST_EMAIL_LIMIT,
    )

    EXPECTED_EMAIL_LIMIT = 3
    assert _REQUEST_EMAIL_LIMIT == EXPECTED_EMAIL_LIMIT, (
        f"Spec drift: _REQUEST_EMAIL_LIMIT changed to {_REQUEST_EMAIL_LIMIT}."
    )

    test_ip = f"test_rate_ip_off_email_{uuid4().hex[:8]}"
    email_hash = "test-email-off-email-" + uuid4().hex[:8]
    ip_key = f"2fa_reset_request:ip:{test_ip}"
    email_key = f"2fa_reset_request:email:{email_hash}"

    now = time.monotonic()
    try:
        _request_windows[email_key] = [now - 1.0] * (EXPECTED_EMAIL_LIMIT - 1)
        result = _rate_limit_check(ip=test_ip, email_hash=email_hash)
        assert result is False
    finally:
        _request_windows.pop(ip_key, None)
        _request_windows.pop(email_key, None)


def test_rate_limit_check_returns_false_when_under_limit() -> None:
    """_rate_limit_check returns False when no limit is exceeded."""
    test_ip = f"test_rate_fresh_{uuid4().hex[:8]}"
    email_hash = "test-email-fresh-" + uuid4().hex[:8]

    result = _rate_limit_check(ip=test_ip, email_hash=email_hash)
    assert result is False


# ---------------------------------------------------------------------------
# _normalize_email — non-string and control char paths (lines 100, 103)
# ---------------------------------------------------------------------------


def test_normalize_email_non_string_returns_none() -> None:
    """_normalize_email with non-string input must return None (line 100)."""
    result = _normalize_email(None)  # type: ignore[arg-type]
    assert result is None


def test_normalize_email_integer_returns_none() -> None:
    """_normalize_email with integer returns None (line 100)."""
    result = _normalize_email(42)  # type: ignore[arg-type]
    assert result is None


def test_normalize_email_control_chars_returns_none() -> None:
    """_normalize_email with control characters returns None (line 103)."""
    # Embed a control character that has_control_chars will catch
    result = _normalize_email("user\x01@example.com")
    assert result is None


def test_normalize_email_null_byte_returns_none() -> None:
    """_normalize_email with NUL byte returns None (line 103)."""
    result = _normalize_email("user\x00@example.com")
    assert result is None


def test_normalize_email_valid_email_returns_normalized() -> None:
    """_normalize_email with valid email returns normalized lowercased string.

    Pin the exact post-normalization value so a mutation that drops the
    ``.lower()`` (or the NFKC normalize) is caught — ``result == result.lower()``
    alone would still pass against the bug since ``result`` would just be
    its un-mutated self.
    """
    result = _normalize_email("User@Example.COM")
    assert result == "user@example.com"


def test_normalize_email_invalid_format_returns_none() -> None:
    """_normalize_email with syntactically invalid email returns None."""
    result = _normalize_email("not-an-email")
    assert result is None


# ---------------------------------------------------------------------------
# _sleep_for_minimum — asyncio.sleep when remaining > 0 (lines 324->exit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sleep_for_minimum_sleeps_when_started_just_now() -> None:
    """_sleep_for_minimum sleeps when started_at is very recent (lines 324->exit)."""
    sleep_calls: list[float] = []

    async def _fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    with patch("asyncio.sleep", side_effect=_fake_sleep):
        await _sleep_for_minimum(time.monotonic())  # just started

    assert len(sleep_calls) == 1
    assert sleep_calls[0] > 0


@pytest.mark.asyncio
async def test_sleep_for_minimum_skips_when_already_elapsed() -> None:
    """_sleep_for_minimum skips sleep when started_at is long ago."""
    sleep_calls: list[float] = []

    async def _fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    # Pass a started_at from 10 seconds ago — well past the minimum
    with patch("asyncio.sleep", side_effect=_fake_sleep):
        await _sleep_for_minimum(time.monotonic() - 10.0)

    assert len(sleep_calls) == 0


# ---------------------------------------------------------------------------
# _write_audit — inner body (lines 335-351)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_audit_calls_audit_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """_write_audit must call AuditLogService.write_platform_event (lines 335-351)."""
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_audit_service = AsyncMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_session_local = MagicMock(return_value=mock_session)

    with (
        patch.object(ci_mod, "AsyncSessionLocal", mock_session_local),
        patch.object(ci_mod, "AuditLogService", return_value=mock_audit_service),
    ):
        await _write_audit(
            request=mock_request,
            actor_user_id=None,
            action="test.action",
            detail={"key": "value"},
        )

    mock_audit_service.write_platform_event.assert_called_once()


@pytest.mark.asyncio
async def test_write_audit_swallows_exception_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_write_audit must catch and log exceptions, not propagate them (lines 350-351)."""
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB connection failed"))

    mock_session_local = MagicMock(return_value=mock_session)

    with patch.object(ci_mod, "AsyncSessionLocal", mock_session_local):
        # Must NOT raise — exception is swallowed
        await _write_audit(
            request=mock_request,
            actor_user_id=None,
            action="test.action.fail",
            detail={"key": "value"},
        )


@pytest.mark.asyncio
async def test_write_audit_inner_exception_rolls_back_and_swallows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_write_audit inner exception triggers rollback + outer swallow (lines 347-351)."""
    from fastapi import Request

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_audit_service = AsyncMock()
    mock_audit_service.write_platform_event = AsyncMock(
        side_effect=RuntimeError("commit failed")
    )
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_session_local = MagicMock(return_value=mock_session)

    with (
        patch.object(ci_mod, "AsyncSessionLocal", mock_session_local),
        patch.object(ci_mod, "AuditLogService", return_value=mock_audit_service),
    ):
        # Must NOT raise — outer except swallows it
        await _write_audit(
            request=mock_request,
            actor_user_id=uuid4(),
            action="test.action.inner.fail",
            detail={"key": "value"},
        )

    mock_session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# Endpoint tests using fully-mocked DB and service layer
# ---------------------------------------------------------------------------


def _make_mock_db() -> AsyncMock:
    """Return a minimal mock AsyncSession for endpoint tests."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_request_endpoint_invalid_email_returns_202(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid email normalizes to None → 202 with request_invalid_email audit (lines 182-189)."""
    db = _make_mock_db()
    app = _make_app(db)

    monkeypatch.setattr(ci_mod, "_rate_limit_check", lambda *, ip, email_hash: False)  # noqa: ARG005

    stub_audit = AsyncMock()
    monkeypatch.setattr(ci_mod, "_write_audit", stub_audit)
    stub_sleep = AsyncMock()
    monkeypatch.setattr(ci_mod, "_sleep_for_minimum", stub_sleep)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/confirm-identity-for-2fa-reset",
            json={"email": "not-an-email-format!!!"},
        )

    assert resp.status_code == 202
    stub_audit.assert_called_once()
    call_kwargs = stub_audit.call_args.kwargs
    assert call_kwargs["action"] == "two_factor_reset.request_invalid_email"
    # Timing-oracle defence: the invalid-email branch MUST enforce the
    # minimum-response-time delay so an attacker cannot distinguish a
    # parse-failure from a successful unknown-email lookup.
    stub_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_endpoint_rate_limited_returns_202(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rate-limited request must return 202 (lines 172-179).

    Strengthened: ``issue_magic_link`` must NOT be called when the
    rate-limit branch fires (otherwise a brute-force attacker could
    bypass the limiter by triggering it themselves), and the audit
    detail must include the email_hash for correlation.
    """
    db = _make_mock_db()
    app = _make_app(db)

    # Force _rate_limit_check to return True (simulate rate limit hit)
    monkeypatch.setattr(ci_mod, "_rate_limit_check", lambda *, ip, email_hash: True)  # noqa: ARG005
    monkeypatch.setattr(ci_mod, "compute_pii_hash", _stub_pii_hash)

    stub_audit = AsyncMock()
    monkeypatch.setattr(ci_mod, "_write_audit", stub_audit)

    stub_sleep = AsyncMock()
    monkeypatch.setattr(ci_mod, "_sleep_for_minimum", stub_sleep)

    stub_issue = AsyncMock()
    monkeypatch.setattr(ci_mod, "issue_magic_link", stub_issue)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/confirm-identity-for-2fa-reset",
            json={"email": "rate-limited@example.com"},
        )

    assert resp.status_code == 202
    # Audit must have been written for the rate-limit event
    stub_audit.assert_called_once()
    call_kwargs = stub_audit.call_args.kwargs
    assert call_kwargs["action"] == "two_factor_reset.request_rate_limited"
    assert call_kwargs["actor_user_id"] is None
    assert "email_hash" in call_kwargs["detail"]
    assert call_kwargs["detail"]["email_hash"] == _stub_pii_hash(
        "rate-limited@example.com"
    )

    # Critical: the rate-limit branch must short-circuit BEFORE
    # ``issue_magic_link`` is dispatched.
    stub_issue.assert_not_called()
    # And the request must enforce the minimum-response-time delay so
    # timing oracle cannot distinguish rate-limit from invalid-email.
    stub_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_endpoint_deleted_user_returns_202(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleted user must return 202 without sending a magic link (line 192).

    Strengthened: ineligible (deleted) users MUST NOT have ``issue_magic_link``
    called. A regression that flips the predicate from
    ``deleted_at is not None`` to e.g. ``deleted_at is None`` would
    silently start sending magic links to soft-deleted accounts.
    """
    db = _make_mock_db()
    app = _make_app(db)

    # User exists but has deleted_at set
    mock_user = MagicMock()
    mock_user.deleted_at = datetime.now(UTC)
    mock_user.two_factor_enabled = True
    mock_user.id = uuid4()

    mock_repo = AsyncMock()
    mock_repo.get_by_email = AsyncMock(return_value=mock_user)

    monkeypatch.setattr(ci_mod, "UserRepository", lambda db: mock_repo)  # noqa: ARG005
    monkeypatch.setattr(ci_mod, "_rate_limit_check", lambda *, ip, email_hash: False)  # noqa: ARG005
    monkeypatch.setattr(ci_mod, "compute_pii_hash", _stub_pii_hash)

    stub_issue = AsyncMock()
    monkeypatch.setattr(ci_mod, "issue_magic_link", stub_issue)

    stub_audit = AsyncMock()
    monkeypatch.setattr(ci_mod, "_write_audit", stub_audit)
    stub_sleep = AsyncMock()
    monkeypatch.setattr(ci_mod, "_sleep_for_minimum", stub_sleep)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/confirm-identity-for-2fa-reset",
            json={"email": "deleted@example.com"},
        )

    assert resp.status_code == 202
    stub_audit.assert_called_once()
    call_kwargs = stub_audit.call_args.kwargs
    assert call_kwargs["action"] == "two_factor_reset.request_unknown_or_ineligible"
    # Critical: do not leak existence of soft-deleted account by
    # actually issuing a magic link for it.
    stub_issue.assert_not_called()
    # Audit must NOT include the user_id (enumeration defence).
    assert call_kwargs["actor_user_id"] is None
    # Timing-oracle defence: the ineligible (soft-deleted) branch MUST
    # enforce the minimum-response-time delay so an attacker cannot
    # distinguish a deleted account from an active one by latency.
    stub_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_endpoint_magic_link_exception_returns_202(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exception in issue_magic_link must return 202 with rollback (lines 224-226)."""
    db = _make_mock_db()
    app = _make_app(db)

    mock_user = MagicMock()
    mock_user.deleted_at = None
    mock_user.two_factor_enabled = True
    mock_user.id = uuid4()

    mock_repo = AsyncMock()
    mock_repo.get_by_email = AsyncMock(return_value=mock_user)

    monkeypatch.setattr(ci_mod, "UserRepository", lambda db: mock_repo)  # noqa: ARG005
    monkeypatch.setattr(ci_mod, "_rate_limit_check", lambda *, ip, email_hash: False)  # noqa: ARG005
    monkeypatch.setattr(ci_mod, "compute_pii_hash", _stub_pii_hash)

    # issue_magic_link raises an exception
    monkeypatch.setattr(
        ci_mod,
        "issue_magic_link",
        AsyncMock(side_effect=RuntimeError("email service down")),
    )

    stub_audit = AsyncMock()
    monkeypatch.setattr(ci_mod, "_write_audit", stub_audit)
    stub_sleep = AsyncMock()
    monkeypatch.setattr(ci_mod, "_sleep_for_minimum", stub_sleep)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/confirm-identity-for-2fa-reset",
            json={"email": "exception@example.com"},
        )

    assert resp.status_code == 202
    # db.rollback must have been called
    db.rollback.assert_called_once()
    # Audit must record the failure
    stub_audit.assert_called_once()
    call_kwargs = stub_audit.call_args.kwargs
    assert call_kwargs["action"] == "two_factor_reset.email_notification_failed"
    # Timing-oracle defence: even when issue_magic_link raises, the
    # error branch MUST enforce the minimum-response-time delay so the
    # caller cannot detect downstream email-service failures by latency.
    stub_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_endpoint_success_path_returns_202(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful magic link issuance must return 202 (lines 212-216, 241-252).

    Strengthened: pin the exact ``issue_magic_link`` invocation
    (normalized email-bearing user, request IP, request UA) and the
    audit envelope (actor_user_id == user.id, detail.user_id matches,
    stage == 'magic_link_dispatched').
    """
    db = _make_mock_db()
    app = _make_app(db)

    user_id = uuid4()
    mock_user = MagicMock()
    mock_user.deleted_at = None
    mock_user.two_factor_enabled = True
    mock_user.id = user_id
    mock_user.email = "success@example.com"

    mock_repo = AsyncMock()
    mock_repo.get_by_email = AsyncMock(return_value=mock_user)

    monkeypatch.setattr(ci_mod, "UserRepository", lambda db: mock_repo)  # noqa: ARG005
    monkeypatch.setattr(ci_mod, "_rate_limit_check", lambda *, ip, email_hash: False)  # noqa: ARG005
    monkeypatch.setattr(ci_mod, "compute_pii_hash", _stub_pii_hash)
    stub_issue = AsyncMock(return_value="raw-magic-token-redacted")
    monkeypatch.setattr(ci_mod, "issue_magic_link", stub_issue)

    stub_audit = AsyncMock()
    monkeypatch.setattr(ci_mod, "_write_audit", stub_audit)
    stub_sleep = AsyncMock()
    monkeypatch.setattr(ci_mod, "_sleep_for_minimum", stub_sleep)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/confirm-identity-for-2fa-reset",
            json={"email": "success@example.com"},
            headers={
                "User-Agent": "pytest-ua/1.0",
                "X-Forwarded-For": "203.0.113.42",
            },
        )

    assert resp.status_code == 202
    db.commit.assert_called_once()

    # Repository was queried with the *normalized* (lowercased) email
    mock_repo.get_by_email.assert_awaited_once_with("success@example.com")

    # issue_magic_link was called exactly once with the resolved user
    # and the request IP / UA captured at the entrypoint. Pin the
    # exact IP value so a regression that drops the X-Forwarded-For
    # extraction (and falls back to ``""`` / ``"unknown"`` / the
    # transport peer) is caught by mutation testing.
    stub_issue.assert_awaited_once()
    issue_kwargs = stub_issue.call_args.kwargs
    assert issue_kwargs["user"] is mock_user
    assert issue_kwargs["ip"] == "203.0.113.42"
    assert issue_kwargs["user_agent"] == "pytest-ua/1.0"

    # Timing-oracle defence: the success branch MUST also enforce the
    # minimum-response-time delay before returning 202.
    stub_sleep.assert_awaited_once()

    stub_audit.assert_called_once()
    call_kwargs = stub_audit.call_args.kwargs
    assert call_kwargs["action"] == "two_factor_reset.requested"
    # The success branch MUST attach the user UUID for support correlation
    assert call_kwargs["actor_user_id"] == user_id
    assert call_kwargs["detail"]["stage"] == "magic_link_dispatched"
    assert call_kwargs["detail"]["user_id"] == str(user_id)
    assert call_kwargs["detail"]["email_hash"] == _stub_pii_hash(
        "success@example.com"
    )


@pytest.mark.asyncio
async def test_redeem_endpoint_success_returns_confirmation_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful redeem must return 200 with confirmation_token (lines 279-280, 305)."""

    db = _make_mock_db()
    app = _make_app(db)

    mock_outcome = MagicMock()
    mock_outcome.confirmation_token = "test-confirmation-token-abc123"
    mock_outcome.expires_at = datetime.now(UTC) + timedelta(minutes=5)
    mock_outcome.user_id = uuid4()

    monkeypatch.setattr(
        ci_mod,
        "redeem_magic_link",
        AsyncMock(return_value=mock_outcome),
    )

    stub_audit = AsyncMock()
    monkeypatch.setattr(ci_mod, "_write_audit", stub_audit)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
            json={"magic_token": "valid-magic-token"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmation_token"] == "test-confirmation-token-abc123"
    db.commit.assert_called_once()
    stub_audit.assert_called_once()


@pytest.mark.asyncio
async def test_redeem_endpoint_invalid_token_returns_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid magic token must return 400 with ERR_INVALID_MAGIC_LINK (line 288)."""
    from echoroo.services.two_factor_reset_service import MagicLinkInvalidError

    db = _make_mock_db()
    app = _make_app(db)

    monkeypatch.setattr(
        ci_mod,
        "redeem_magic_link",
        AsyncMock(side_effect=MagicLinkInvalidError("invalid token")),
    )

    stub_audit = AsyncMock()
    monkeypatch.setattr(ci_mod, "_write_audit", stub_audit)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
            json={"magic_token": "invalid-magic-token"},
        )

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["error"] == "ERR_INVALID_MAGIC_LINK"
    db.rollback.assert_called_once()
    stub_audit.assert_called_once()
    call_kwargs = stub_audit.call_args.kwargs
    assert call_kwargs["action"] == "two_factor_reset.confirmation_token_redeem_failed"
