"""Coverage uplift unit tests for ``echoroo.api.web_v1.projects._ownership``.

Phase 17 §C Batch 9a (35-50pp gap range): covers the transfer_project_ownership
handler and helper functions so the module clears the 85% threshold.

Missing lines: 66-69,73,77,152-153,158-159,175-176,186-187,194-195,206,
              214-215,225-227,234-236,243,247-248,253-254,256
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.api.web_v1.projects._ownership import (
    TransferOwnershipRequest,
    _client_ip,
    _request_id,
    _user_agent,
    transfer_project_ownership,
)
from echoroo.services.ownership_service import (
    InvalidTransferTargetError,
    ProjectNotFoundError,
    TransferConflictError,
)


def _make_request(
    ip: str = "127.0.0.1",
    ua: str = "test-agent",
    req_id: str = "req-123",
    forwarded: str | None = None,
) -> MagicMock:
    req = MagicMock()
    headers: dict[str, str] = {}
    if forwarded:
        headers["x-forwarded-for"] = forwarded
    headers["user-agent"] = ua
    headers["x-request-id"] = req_id
    req.headers = headers
    req.client = MagicMock()
    req.client.host = ip
    return req


def test_client_ip_uses_forwarded_header() -> None:
    """_client_ip returns first IP from X-Forwarded-For (line 66-67)."""
    request = _make_request(forwarded="10.0.0.1, 10.0.0.2")
    assert _client_ip(request) == "10.0.0.1"


def test_client_ip_uses_client_host_when_no_forwarded() -> None:
    """_client_ip uses request.client.host when no forwarded header (lines 68-69)."""
    request = _make_request(ip="192.168.1.1")
    assert _client_ip(request) == "192.168.1.1"


def test_client_ip_returns_unknown_when_no_client() -> None:
    """_client_ip returns 'unknown' when client is None (line 69)."""
    request = _make_request()
    request.client = None
    assert _client_ip(request) == "unknown"


def test_user_agent_returns_header_value() -> None:
    """_user_agent returns user-agent header value (line 73)."""
    request = _make_request(ua="Mozilla/5.0")
    assert _user_agent(request) == "Mozilla/5.0"


def test_request_id_returns_header_value() -> None:
    """_request_id returns x-request-id header value (line 77)."""
    request = _make_request(req_id="abc-123")
    assert _request_id(request) == "abc-123"


@pytest.mark.asyncio
async def test_transfer_project_ownership_raises_401_when_unauthenticated() -> None:
    """transfer_project_ownership raises 401 when current_user is None (lines 152-153)."""
    request = _make_request()
    payload = TransferOwnershipRequest(new_owner_user_id=uuid4())
    db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await transfer_project_ownership(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=None,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_transfer_project_ownership_raises_400_for_blank_idempotency_key() -> None:
    """transfer_project_ownership raises 400 for blank idempotency key (lines 158-159)."""
    request = _make_request()
    payload = TransferOwnershipRequest(new_owner_user_id=uuid4())
    db = MagicMock()
    current_user = MagicMock()
    current_user.id = uuid4()

    with (
        patch(
            "echoroo.api.web_v1.projects._ownership.peek_replay_outcome",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await transfer_project_ownership(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=current_user,
            db=db,
            idempotency_key="   ",  # blank
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_transfer_project_ownership_returns_cached_on_replay() -> None:
    """transfer_project_ownership returns cached outcome when peek returns hit (lines 175-176)."""
    project_id = uuid4()
    prev_owner_id = uuid4()
    new_owner_id = uuid4()

    cached_outcome = MagicMock()
    cached_outcome.project_id = project_id
    cached_outcome.previous_owner_id = prev_owner_id
    cached_outcome.new_owner_id = new_owner_id

    request = _make_request()
    payload = TransferOwnershipRequest(new_owner_user_id=new_owner_id)
    db = MagicMock()
    current_user = MagicMock()
    current_user.id = uuid4()

    with patch(
        "echoroo.api.web_v1.projects._ownership.peek_replay_outcome",
        new=AsyncMock(return_value=cached_outcome),
    ):
        result = await transfer_project_ownership(
            project_id=project_id,
            payload=payload,
            request=request,
            current_user=current_user,
            db=db,
            idempotency_key="idempotency-key",
        )

    assert result.replayed is True
    assert result.project_id == project_id


@pytest.mark.asyncio
async def test_transfer_project_ownership_raises_409_on_conflict_from_peek() -> None:
    """transfer_project_ownership raises 409 when peek raises TransferConflictError (lines 186-187)."""
    request = _make_request()
    payload = TransferOwnershipRequest(new_owner_user_id=uuid4())
    db = MagicMock()
    current_user = MagicMock()
    current_user.id = uuid4()

    with (
        patch(
            "echoroo.api.web_v1.projects._ownership.peek_replay_outcome",
            new=AsyncMock(side_effect=TransferConflictError("conflict")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await transfer_project_ownership(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=current_user,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_transfer_project_ownership_happy_path() -> None:
    """transfer_project_ownership calls transfer_ownership and commits (lines 194-256)."""
    project_id = uuid4()
    prev_owner = uuid4()
    new_owner = uuid4()

    outcome = MagicMock()
    outcome.project_id = project_id
    outcome.previous_owner_id = prev_owner
    outcome.new_owner_id = new_owner
    outcome.replayed = False

    request = _make_request()
    payload = TransferOwnershipRequest(new_owner_user_id=new_owner)
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    current_user = MagicMock()
    current_user.id = uuid4()

    with (
        patch(
            "echoroo.api.web_v1.projects._ownership.peek_replay_outcome",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "echoroo.api.web_v1.projects._ownership.gate_action",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._ownership.transfer_ownership",
            new=AsyncMock(return_value=outcome),
        ),
        patch(
            "echoroo.api.web_v1.projects._ownership.ownership_service.trigger_post_commit_side_effects",
            new=AsyncMock(),
        ),
    ):
        result = await transfer_project_ownership(
            project_id=project_id,
            payload=payload,
            request=request,
            current_user=current_user,
            db=db,
            idempotency_key="key-123",
        )

    assert result.replayed is False
    assert result.new_owner_id == new_owner


@pytest.mark.asyncio
async def test_transfer_project_ownership_raises_400_on_invalid_target() -> None:
    """transfer_project_ownership raises 400 on InvalidTransferTargetError (lines 225-227)."""
    request = _make_request()
    payload = TransferOwnershipRequest(new_owner_user_id=uuid4())
    db = MagicMock()
    db.rollback = AsyncMock()
    current_user = MagicMock()
    current_user.id = uuid4()

    with (
        patch(
            "echoroo.api.web_v1.projects._ownership.peek_replay_outcome",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "echoroo.api.web_v1.projects._ownership.gate_action",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._ownership.transfer_ownership",
            new=AsyncMock(side_effect=InvalidTransferTargetError("not an admin")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await transfer_project_ownership(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=current_user,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_transfer_project_ownership_raises_409_on_conflict_from_transfer() -> None:
    """transfer_project_ownership raises 409 on TransferConflictError from service (lines 234-236)."""
    request = _make_request()
    payload = TransferOwnershipRequest(new_owner_user_id=uuid4())
    db = MagicMock()
    db.rollback = AsyncMock()
    current_user = MagicMock()
    current_user.id = uuid4()

    with (
        patch(
            "echoroo.api.web_v1.projects._ownership.peek_replay_outcome",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "echoroo.api.web_v1.projects._ownership.gate_action",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._ownership.transfer_ownership",
            new=AsyncMock(side_effect=TransferConflictError("conflict")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await transfer_project_ownership(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=current_user,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_transfer_project_ownership_raises_404_on_project_not_found() -> None:
    """transfer_project_ownership raises 404 on ProjectNotFoundError (lines 243,247-248)."""
    request = _make_request()
    payload = TransferOwnershipRequest(new_owner_user_id=uuid4())
    db = MagicMock()
    db.rollback = AsyncMock()
    current_user = MagicMock()
    current_user.id = uuid4()

    with (
        patch(
            "echoroo.api.web_v1.projects._ownership.peek_replay_outcome",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "echoroo.api.web_v1.projects._ownership.gate_action",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._ownership.transfer_ownership",
            new=AsyncMock(side_effect=ProjectNotFoundError("not found")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await transfer_project_ownership(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=current_user,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 404
