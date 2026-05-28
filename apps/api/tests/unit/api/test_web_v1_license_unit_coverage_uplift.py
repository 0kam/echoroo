"""Coverage uplift unit tests for ``echoroo.api.web_v1.projects._license``.

Phase 17 §C medium-gap batch: targets ``_client_ip`` (line 62), the
``update_project_license`` early-401 branch (lines 144-148), the audit
write helper exception path (line 178), and the
``get_project_license_history`` early-401 branch (lines 244-248) so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.api.web_v1.projects import _license as mod


def _request_with(headers: dict[str, str] | None = None) -> MagicMock:
    req = MagicMock()
    req.headers = headers or {}
    req.client = SimpleNamespace(host="1.2.3.4")
    return req


def test_client_ip_uses_forwarded_for_first_value() -> None:
    """``_client_ip`` returns the first hop in X-Forwarded-For (line 62)."""
    req = _request_with({"x-forwarded-for": "10.0.0.1, 10.0.0.2"})
    assert mod._client_ip(req) == "10.0.0.1"


def test_client_ip_falls_back_to_request_client_host() -> None:
    """``_client_ip`` falls back to request.client.host."""
    req = _request_with({})
    assert mod._client_ip(req) == "1.2.3.4"


def test_user_agent_returns_value_or_empty() -> None:
    """``_user_agent`` returns header or empty string."""
    assert mod._user_agent(_request_with({"user-agent": "ua"})) == "ua"
    assert mod._user_agent(_request_with({})) == ""


def test_request_id_returns_value_or_empty() -> None:
    """``_request_id`` returns header or empty string."""
    assert mod._request_id(_request_with({"x-request-id": "abc"})) == "abc"
    assert mod._request_id(_request_with({})) == ""


@pytest.mark.asyncio
async def test_update_project_license_rejects_unauthenticated() -> None:
    """No current_user → 401 (lines 144-148)."""
    db = MagicMock()
    request = _request_with()
    payload = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        await mod.update_project_license(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=None,
            db=db,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_project_license_history_rejects_unauthenticated() -> None:
    """No current_user → 401 (lines 244-248)."""
    db = MagicMock()
    request = _request_with()
    with pytest.raises(HTTPException) as exc_info:
        await mod.get_project_license_history(
            project_id=uuid4(),
            request=request,
            current_user=None,
            db=db,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_project_license_history_returns_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated path delegates to list_license_history (line 257).

    The body builds a ``ProjectLicenseHistoryResponse`` from validated rows;
    we patch both the row validator AND the response constructor so the
    happy path runs without needing a real ORM row.
    """
    db = MagicMock()
    user = MagicMock()
    user.id = uuid4()
    request = _request_with()

    history_row = MagicMock()
    sentinel_entry = MagicMock()
    sentinel_response = MagicMock()

    fake_response_cls = MagicMock(return_value=sentinel_response)

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=MagicMock())), \
            patch.object(mod, "list_license_history", new=AsyncMock(return_value=[history_row])), \
            patch.object(mod.ProjectLicenseHistoryEntry, "model_validate", return_value=sentinel_entry), \
            patch.object(mod, "ProjectLicenseHistoryResponse", fake_response_cls):
        result = await mod.get_project_license_history(
            project_id=uuid4(),
            request=request,
            current_user=user,
            db=db,
        )
    assert result is sentinel_response
    fake_response_cls.assert_called_once_with(items=[sentinel_entry])


@pytest.mark.asyncio
async def test_update_project_license_happy_path() -> None:
    """Authenticated path traverses gate + change_license + audit
    (lines 150, 158-166, 178-179, 191-192, 203, 208, 211, 214)."""
    project = MagicMock()
    project.id = uuid4()
    project.license = "CC-BY"

    user = MagicMock()
    user.id = uuid4()
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    request = _request_with({"x-request-id": "req-2"})

    payload = MagicMock()
    payload.license = "CC-BY-NC"

    history_row = MagicMock()
    history_row.id = uuid4()

    sentinel_response = MagicMock()
    fake_response_cls = MagicMock()
    fake_response_cls.model_validate = MagicMock(return_value=sentinel_response)

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=project)), \
            patch.object(mod, "change_license", new=AsyncMock(return_value=history_row)), \
            patch.object(mod, "_write_license_audit", new=AsyncMock()), \
            patch.object(mod, "scrub_owner_email_for_visibility"), \
            patch.object(mod, "resolve_current_user_role", new=AsyncMock(return_value="Owner")), \
            patch.object(mod, "ProjectResponse", fake_response_cls):
        result = await mod.update_project_license(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=user,
            db=db,
        )
    assert result is sentinel_response
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_project_license_swallows_audit_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Audit write failure is logged + swallowed (lines 191-201)."""
    project = MagicMock()
    project.id = uuid4()
    project.license = None  # also covers the ``before_license = None`` branch

    user = MagicMock()
    user.id = uuid4()
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    request = _request_with()

    payload = MagicMock()
    payload.license = "CC0"

    history_row = MagicMock()
    history_row.id = uuid4()

    sentinel_response = MagicMock()
    fake_response_cls = MagicMock()
    fake_response_cls.model_validate = MagicMock(return_value=sentinel_response)

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=project)), \
            patch.object(mod, "change_license", new=AsyncMock(return_value=history_row)), \
            patch.object(
                mod, "_write_license_audit", new=AsyncMock(side_effect=RuntimeError("audit-down"))
            ), \
            patch.object(mod, "scrub_owner_email_for_visibility"), \
            patch.object(mod, "resolve_current_user_role", new=AsyncMock(return_value="Owner")), \
            patch.object(mod, "ProjectResponse", fake_response_cls):
        result = await mod.update_project_license(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=user,
            db=db,
        )
    # The mutation succeeded even though the audit failed.
    assert result is sentinel_response


@pytest.mark.asyncio
async def test_write_license_audit_swallows_session_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_write_license_audit`` opens fresh session and rolls back on failure
    (lines 90-107)."""
    from contextlib import asynccontextmanager

    rollback_calls: list[Any] = []

    class _FakeSession:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            rollback_calls.append(True)

    @asynccontextmanager
    async def _factory() -> Any:
        yield _FakeSession()

    monkeypatch.setattr(mod, "AsyncSessionLocal", _factory)

    fake_audit_service = MagicMock()
    fake_audit_service.write_project_event = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(mod, "AuditLogService", lambda _s: fake_audit_service)

    request = _request_with()
    with pytest.raises(RuntimeError):
        await mod._write_license_audit(
            actor_user_id=uuid4(),
            project_id=uuid4(),
            request=request,
            detail={"k": "v"},
            before=None,
            after=None,
        )
    assert rollback_calls == [True]


@pytest.mark.asyncio
async def test_write_license_audit_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_write_license_audit`` commits when write succeeds (line 104)."""
    from contextlib import asynccontextmanager

    commit_calls: list[Any] = []

    class _FakeSession:
        async def commit(self) -> None:
            commit_calls.append(True)

        async def rollback(self) -> None:
            return None

    @asynccontextmanager
    async def _factory() -> Any:
        yield _FakeSession()

    monkeypatch.setattr(mod, "AsyncSessionLocal", _factory)

    fake_audit_service = MagicMock()
    fake_audit_service.write_project_event = AsyncMock()
    monkeypatch.setattr(mod, "AuditLogService", lambda _s: fake_audit_service)

    request = _request_with()
    await mod._write_license_audit(
        actor_user_id=uuid4(),
        project_id=uuid4(),
        request=request,
        detail={"k": "v"},
        before=None,
        after=None,
    )
    assert commit_calls == [True]
