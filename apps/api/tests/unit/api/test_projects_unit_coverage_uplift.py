"""Coverage uplift unit tests for ``echoroo.api.v1.projects``.

Phase 17 §C easy-win batch 1: covers the `commit + return` tail of
several mutating endpoints (lines 167, 274, 706, 759), the project
overview happy path (lines 597, 604), and the license-history list
(lines 428, 435-436) using mocked services / gates so the module clears
the 85% threshold without touching production code.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.api.v1 import projects as mod
from echoroo.models.enums import (
    ProjectLicense,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.schemas.project import (
    ProjectCreateRequest,
    ProjectMemberAddRequest,
    ProjectMemberUpdateRequest,
    ProjectUpdateRequest,
)


@pytest.mark.asyncio
async def test_create_project_commits_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_project commits and returns the new project (line 167)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.create_project = AsyncMock(return_value=sentinel)
    db = MagicMock()
    db.commit = AsyncMock()
    current_user = MagicMock()
    current_user.id = uuid4()

    request = ProjectCreateRequest(
        name="Alpha",
        visibility=ProjectVisibility.PUBLIC,
        license=ProjectLicense.CC0,
    )
    result = await mod.create_project(
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
    assert result is sentinel
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_project_commits_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update_project commits and returns the updated project (line 274)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.update_project = AsyncMock(return_value=sentinel)
    db = MagicMock()
    db.commit = AsyncMock()
    monkeypatch.setattr(mod, "gate_action", AsyncMock())

    current_user = MagicMock()
    current_user.id = uuid4()
    http_request = MagicMock()

    result = await mod.update_project(
        project_id=uuid4(),
        request=ProjectUpdateRequest(name="Beta"),
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )
    assert result is sentinel
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_project_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_project commits after the service call."""
    service = MagicMock()
    service.delete_project = AsyncMock()
    db = MagicMock()
    db.commit = AsyncMock()
    monkeypatch.setattr(mod, "gate_action", AsyncMock())

    current_user = MagicMock()
    current_user.id = uuid4()
    request = MagicMock()

    await mod.delete_project(
        project_id=uuid4(),
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_project_overview_invokes_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_project_overview() forwards to the service (lines 597, 604)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.get_project_overview = AsyncMock(return_value=sentinel)
    db = MagicMock()
    monkeypatch.setattr(mod, "gate_action", AsyncMock())

    current_user = MagicMock()
    current_user.id = uuid4()
    request = MagicMock()
    project_id = uuid4()

    result = await mod.get_project_overview(
        project_id=project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
    assert result is sentinel
    service.get_project_overview.assert_awaited_once_with(current_user.id, project_id)


@pytest.mark.asyncio
async def test_add_project_member_commits_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """add_project_member commits and returns the new member (line 706)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.add_member = AsyncMock(return_value=sentinel)
    db = MagicMock()
    db.commit = AsyncMock()
    monkeypatch.setattr(mod, "gate_action", AsyncMock())

    current_user = MagicMock()
    current_user.id = uuid4()
    http_request = MagicMock()

    request = ProjectMemberAddRequest(
        email="member@example.com",
        role=ProjectMemberRole.MEMBER,
    )
    result = await mod.add_project_member(
        project_id=uuid4(),
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )
    assert result is sentinel
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_project_member_role_commits_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update_project_member_role commits and returns the updated member
    (line 759).
    """
    sentinel = MagicMock()
    service = MagicMock()
    service.update_member_role = AsyncMock(return_value=sentinel)
    db = MagicMock()
    db.commit = AsyncMock()
    monkeypatch.setattr(mod, "gate_action", AsyncMock())

    current_user = MagicMock()
    current_user.id = uuid4()
    http_request = MagicMock()

    request = ProjectMemberUpdateRequest(role=ProjectMemberRole.ADMIN)
    result = await mod.update_project_member_role(
        project_id=uuid4(),
        user_id=uuid4(),
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )
    assert result is sentinel
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_project_license_history_returns_validated_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_project_license_history returns the formatted history list
    (lines 428, 435-436).
    """
    from datetime import UTC, datetime

    monkeypatch.setattr(mod, "gate_action", AsyncMock())
    fake_row = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        old_license=ProjectLicense.CC0,
        new_license=ProjectLicense.CC_BY,
        changed_at=datetime.now(UTC),
        changed_by_id=uuid4(),
    )
    monkeypatch.setattr(mod, "list_license_history", AsyncMock(return_value=[fake_row]))

    db = MagicMock()
    current_user = MagicMock()
    current_user.id = uuid4()
    request = MagicMock()

    result = await mod.get_project_license_history(
        project_id=uuid4(),
        request=request,
        current_user=current_user,
        db=db,
    )
    assert len(result.items) == 1
    assert result.items[0].new_license == ProjectLicense.CC_BY


def test_get_project_service_factory_returns_service() -> None:
    """get_project_service builds a ProjectService bound to ``db``."""
    db = MagicMock()
    service = mod.get_project_service(db)
    assert service is not None
