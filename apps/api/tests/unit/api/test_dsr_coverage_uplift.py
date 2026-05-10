"""Coverage uplift unit tests for ``echoroo.api.web_v1.account.dsr``.

Phase 17 §C Batch 9a (35-50pp gap range): covers the DSR export and delete
handlers plus helper functions so the module clears the 85% threshold.

Missing lines: 76-79,83,87,98-99,103,108,118,143-145,168,171-172,203,209-210,
              230,233-234,277,279-280,289,303,312,352,354-356,358-359,366,372,
              376,379,388,397,408-409,411,416
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.api.web_v1.account.dsr import (
    _client_ip,
    _isoformat,
    _request_id,
    _require_authenticated,
    _user_agent,
    dsr_delete,
    dsr_export,
)

# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_client_ip_uses_forwarded_header() -> None:
    """_client_ip extracts first IP from X-Forwarded-For (lines 76-77)."""
    req = MagicMock()
    req.headers = {"x-forwarded-for": "10.0.0.1, 10.0.0.2"}
    assert _client_ip(req) == "10.0.0.1"


def test_client_ip_returns_client_host_when_no_forwarded() -> None:
    """_client_ip uses request.client.host when no forwarded header (line 78)."""
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock()
    req.client.host = "192.168.1.1"
    assert _client_ip(req) == "192.168.1.1"


def test_client_ip_returns_unknown_when_no_client() -> None:
    """_client_ip returns 'unknown' when client is None (line 79)."""
    req = MagicMock()
    req.headers = {}
    req.client = None
    assert _client_ip(req) == "unknown"


def test_user_agent_returns_header() -> None:
    """_user_agent returns the user-agent header (line 83)."""
    req = MagicMock()
    req.headers = {"user-agent": "test-agent"}
    assert _user_agent(req) == "test-agent"


def test_request_id_returns_header() -> None:
    """_request_id returns x-request-id header (line 87)."""
    req = MagicMock()
    req.headers = {"x-request-id": "req-456"}
    assert _request_id(req) == "req-456"


def test_require_authenticated_raises_401_when_none() -> None:
    """_require_authenticated raises 401 when current_user is None (lines 98-99)."""
    with pytest.raises(HTTPException) as exc_info:
        _require_authenticated(None)
    assert exc_info.value.status_code == 401


def test_require_authenticated_raises_401_when_deleted() -> None:
    """_require_authenticated raises 401 when user has deleted_at set (lines 98-99)."""
    user = MagicMock()
    user.deleted_at = datetime.now(UTC)
    with pytest.raises(HTTPException) as exc_info:
        _require_authenticated(user)
    assert exc_info.value.status_code == 401


def test_require_authenticated_returns_user_when_valid() -> None:
    """_require_authenticated returns user when authenticated and not deleted (line 103)."""
    user = MagicMock()
    user.deleted_at = None
    result = _require_authenticated(user)
    assert result is user


def test_isoformat_returns_iso_string() -> None:
    """_isoformat serialises a datetime to ISO-8601 (line 108)."""
    dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    result = _isoformat(dt)
    assert "2026-01-15" in result


def test_isoformat_returns_none_for_none() -> None:
    """_isoformat passes None through (line 108)."""
    assert _isoformat(None) is None


# ---------------------------------------------------------------------------
# dsr_export endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dsr_export_raises_401_when_unauthenticated() -> None:
    """dsr_export raises 401 when current_user is None (lines 352-353)."""
    db = MagicMock()
    request = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await dsr_export(request=request, db=db, current_user=None)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_dsr_export_returns_payload() -> None:
    """dsr_export returns full data payload for authenticated user (lines 354-416)."""
    user_id = uuid4()
    user = MagicMock()
    user.deleted_at = None
    user.id = user_id
    user.email = "user@example.com"
    user.display_name = "Test User"
    user.two_factor_enabled = False
    user.last_login_at = None
    user.last_first_party_activity_at = None
    user.registered_timezone = "UTC"
    user.created_at = datetime.now(UTC)
    user.deleted_at = None

    db = MagicMock()
    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=scalars_result)

    request = MagicMock()
    request.headers = {}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    with patch(
        "echoroo.api.web_v1.account.dsr.get_settings"
    ) as mock_settings:
        mock_settings.return_value.web_session_secret = "test_secret"

        with patch(
            "echoroo.api.web_v1.account.dsr.hash_email",
            return_value="hashed@email",
        ):
            result = await dsr_export(
                request=request,
                db=db,
                current_user=user,
            )

    assert "generated_at" in result
    assert "user" in result
    assert result["user"]["email"] == "user@example.com"
    assert "project_memberships" in result
    assert "annotation_votes" in result


# ---------------------------------------------------------------------------
# dsr_delete endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dsr_delete_raises_401_when_unauthenticated() -> None:
    """dsr_delete raises 401 when current_user is None (lines 372-376)."""
    db = MagicMock()
    request = MagicMock()
    response = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await dsr_delete(request=request, response=response, db=db, current_user=None)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_dsr_delete_happy_path() -> None:
    """dsr_delete soft-deletes user and clears cookies (lines 379-416)."""
    from echoroo.services.user_deletion_service import UserSoftDeleteOutcome

    user_id = uuid4()
    user = MagicMock()
    user.deleted_at = None
    user.id = user_id

    outcome = UserSoftDeleteOutcome(
        user_id=user_id,
        deleted_at=datetime.now(UTC),
        request_id="req-123",
    )

    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    request = MagicMock()
    request.headers = {
        "x-request-id": "req-123",
        "user-agent": "test-agent",
    }
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    response = MagicMock()

    with (
        patch(
            "echoroo.api.web_v1.account.dsr.soft_delete_user",
            new=AsyncMock(return_value=outcome),
        ),
        patch(
            "echoroo.api.web_v1.account.dsr._clear_session_cookies",
        ) as mock_clear,
        patch(
            "echoroo.api.web_v1.account.dsr.trigger_post_commit_audit",
            new=AsyncMock(),
        ),
    ):
        result = await dsr_delete(
            request=request,
            response=response,
            db=db,
            current_user=user,
        )

    assert "user_id" in result
    assert "deleted_at" in result
    mock_clear.assert_called_once_with(response)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_dsr_delete_raises_401_on_already_deleted_user() -> None:
    """dsr_delete returns 401 when user was already deleted (lines 388-392)."""
    from echoroo.services.user_deletion_service import UserAlreadyDeletedError

    user = MagicMock()
    user.deleted_at = None
    user.id = uuid4()

    db = MagicMock()
    request = MagicMock()
    request.headers = {"x-request-id": "", "user-agent": ""}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    response = MagicMock()

    with (
        patch(
            "echoroo.api.web_v1.account.dsr.soft_delete_user",
            new=AsyncMock(side_effect=UserAlreadyDeletedError("already deleted")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await dsr_delete(request=request, response=response, db=db, current_user=user)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_dsr_delete_raises_401_on_user_not_found() -> None:
    """dsr_delete returns 401 when user not found (lines 397)."""
    from echoroo.services.user_deletion_service import UserNotFoundError

    user = MagicMock()
    user.deleted_at = None
    user.id = uuid4()

    db = MagicMock()
    request = MagicMock()
    request.headers = {"x-request-id": "", "user-agent": ""}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    response = MagicMock()

    with (
        patch(
            "echoroo.api.web_v1.account.dsr.soft_delete_user",
            new=AsyncMock(side_effect=UserNotFoundError("not found")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await dsr_delete(request=request, response=response, db=db, current_user=user)

    assert exc_info.value.status_code == 401
