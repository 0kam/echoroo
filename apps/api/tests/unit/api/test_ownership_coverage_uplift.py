"""Coverage uplift unit tests for ``echoroo.api.web_v1.projects._ownership``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers helper functions and
transfer_project_ownership handler including 401, 400 blank key,
idempotency replay, gate_action, InvalidTransferTargetError (400),
TransferConflictError (409), and ProjectNotFoundError (404) paths,
so the module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.api.web_v1.projects import _ownership as mod
from echoroo.services.ownership_service import (
    InvalidTransferTargetError,
    ProjectNotFoundError,
    TransferConflictError,
)


def _make_request(
    *,
    forwarded: str | None = None,
    ua: str = "TestAgent/1.0",
    request_id: str = "req-123",
    host: str = "127.0.0.1",
) -> MagicMock:
    req = MagicMock()
    headers = {
        "x-forwarded-for": forwarded,
        "user-agent": ua,
        "x-request-id": request_id,
    }
    req.headers.get = MagicMock(side_effect=lambda k: headers.get(k))
    client = MagicMock()
    client.host = host
    req.client = client
    return req


def _make_user(user_id: object = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid4()
    return user


def _make_db() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_payload(new_owner_user_id: object = None) -> mod.TransferOwnershipRequest:
    return mod.TransferOwnershipRequest(new_owner_user_id=new_owner_user_id or uuid4())


class TestHelperFunctions:
    """Tests for _client_ip, _user_agent, _request_id helpers (lines 66-73)."""

    def test_client_ip_returns_forwarded_ip(self) -> None:
        req = _make_request(forwarded="10.0.0.1, 10.0.0.2")
        assert mod._client_ip(req) == "10.0.0.1"

    def test_client_ip_returns_client_host_when_no_forwarded(self) -> None:
        req = _make_request(forwarded=None)
        assert mod._client_ip(req) == "127.0.0.1"

    def test_user_agent_returns_ua_header(self) -> None:
        req = _make_request(ua="Mozilla/5.0")
        assert mod._user_agent(req) == "Mozilla/5.0"

    def test_request_id_returns_header(self) -> None:
        req = _make_request(request_id="req-abc")
        assert mod._request_id(req) == "req-abc"


@pytest.mark.asyncio
async def test_transfer_ownership_raises_401_when_no_user() -> None:
    """Handler raises 401 when current_user is None (lines 152-155)."""
    db = _make_db()
    request = _make_request()
    payload = _make_payload()

    with pytest.raises(HTTPException) as exc_info:
        await mod.transfer_project_ownership(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=None,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_transfer_ownership_raises_400_when_blank_key() -> None:
    """Handler raises 400 when idempotency key is blank (lines 158-163)."""
    db = _make_db()
    request = _make_request()
    payload = _make_payload()
    user = _make_user()

    with pytest.raises(HTTPException) as exc_info:
        await mod.transfer_project_ownership(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=user,
            db=db,
            idempotency_key="   ",
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_transfer_ownership_returns_cached_outcome_on_replay() -> None:
    """Handler returns cached outcome when idempotency replay detected (lines 175-186)."""
    db = _make_db()
    request = _make_request()
    payload = _make_payload()
    user = _make_user()
    project_id = uuid4()

    cached = MagicMock()
    cached.project_id = project_id
    cached.previous_owner_id = uuid4()
    cached.new_owner_id = payload.new_owner_user_id

    with patch.object(mod, "peek_replay_outcome", AsyncMock(return_value=cached)):
        result = await mod.transfer_project_ownership(
            project_id=project_id,
            payload=payload,
            request=request,
            current_user=user,
            db=db,
            idempotency_key="key-123",
        )

    assert result.replayed is True
    assert result.project_id == project_id


@pytest.mark.asyncio
async def test_transfer_ownership_raises_409_on_replay_conflict() -> None:
    """Handler raises 409 when idempotency key has different target (lines 175-179)."""
    db = _make_db()
    request = _make_request()
    payload = _make_payload()
    user = _make_user()

    with (
        patch.object(
            mod, "peek_replay_outcome",
            AsyncMock(side_effect=TransferConflictError("key reuse with different target")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.transfer_project_ownership(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=user,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_transfer_ownership_raises_400_on_invalid_target() -> None:
    """Handler raises 400 on InvalidTransferTargetError (lines 214-220)."""
    db = _make_db()
    request = _make_request()
    payload = _make_payload()
    user = _make_user()
    project_id = uuid4()

    with (
        patch.object(mod, "peek_replay_outcome", AsyncMock(return_value=None)),
        patch.object(mod, "gate_action", AsyncMock()),
        patch.object(
            mod, "transfer_ownership",
            AsyncMock(side_effect=InvalidTransferTargetError("not an admin")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.transfer_project_ownership(
            project_id=project_id,
            payload=payload,
            request=request,
            current_user=user,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_transfer_ownership_raises_409_on_conflict() -> None:
    """Handler raises 409 on TransferConflictError from transfer_ownership (lines 225-232)."""
    db = _make_db()
    request = _make_request()
    payload = _make_payload()
    user = _make_user()
    project_id = uuid4()

    with (
        patch.object(mod, "peek_replay_outcome", AsyncMock(return_value=None)),
        patch.object(mod, "gate_action", AsyncMock()),
        patch.object(
            mod, "transfer_ownership",
            AsyncMock(side_effect=TransferConflictError("conflict")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.transfer_project_ownership(
            project_id=project_id,
            payload=payload,
            request=request,
            current_user=user,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_transfer_ownership_raises_404_on_project_not_found() -> None:
    """Handler raises 404 on ProjectNotFoundError (lines 234-239)."""
    db = _make_db()
    request = _make_request()
    payload = _make_payload()
    user = _make_user()
    project_id = uuid4()

    with (
        patch.object(mod, "peek_replay_outcome", AsyncMock(return_value=None)),
        patch.object(mod, "gate_action", AsyncMock()),
        patch.object(
            mod, "transfer_ownership",
            AsyncMock(side_effect=ProjectNotFoundError("project missing")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.transfer_project_ownership(
            project_id=project_id,
            payload=payload,
            request=request,
            current_user=user,
            db=db,
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_transfer_ownership_success() -> None:
    """Handler returns TransferOwnershipResponse on success (lines 241-255)."""
    db = _make_db()
    request = _make_request()
    new_owner_id = uuid4()
    previous_owner_id = uuid4()
    payload = _make_payload(new_owner_user_id=new_owner_id)
    user = _make_user()
    project_id = uuid4()

    outcome = MagicMock()
    outcome.project_id = project_id
    outcome.previous_owner_id = previous_owner_id
    outcome.new_owner_id = new_owner_id
    outcome.replayed = False

    with (
        patch.object(mod, "peek_replay_outcome", AsyncMock(return_value=None)),
        patch.object(mod, "gate_action", AsyncMock()),
        patch.object(mod, "transfer_ownership", AsyncMock(return_value=outcome)),
        patch.object(mod.ownership_service, "trigger_post_commit_side_effects", AsyncMock()),
    ):
        result = await mod.transfer_project_ownership(
            project_id=project_id,
            payload=payload,
            request=request,
            current_user=user,
            db=db,
            idempotency_key="key-123",
        )

    assert result.project_id == project_id
    assert result.previous_owner_id == previous_owner_id
    assert result.new_owner_id == new_owner_id
    assert result.replayed is False
    db.commit.assert_awaited_once()
