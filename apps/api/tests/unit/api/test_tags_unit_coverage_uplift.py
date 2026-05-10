"""Coverage uplift unit tests for ``echoroo.api.v1.tags``.

Phase 17 §C easy-win batch 1: covers the create-tag commit path
(line 157), the update-tag 404 + happy branches (lines 315-316, 320),
and the delete-tag 404 branch (lines 361-362) using mocked services /
gates so the module clears the 85% threshold without touching production
code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.api.v1 import tags as mod
from echoroo.models.enums import TagCategory
from echoroo.schemas.tag import TagCreate, TagUpdate


@pytest.mark.asyncio
async def test_create_tag_commits_db_and_returns_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_tag() awaits gate_action, calls service.create, commits and returns
    the created tag (line 157).
    """
    sentinel_tag = MagicMock()
    service = MagicMock()
    service.create = AsyncMock(return_value=sentinel_tag)
    db = MagicMock()
    db.commit = AsyncMock()
    http_request = MagicMock()
    current_user = MagicMock()

    monkeypatch.setattr(mod, "gate_action", AsyncMock())

    request = TagCreate(name="bird", category=TagCategory.SPECIES)
    project_id = uuid4()
    result = await mod.create_tag(
        project_id=project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
        locale="en",
    )

    assert result is sentinel_tag
    db.commit.assert_awaited_once()
    service.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_tag_returns_404_when_tag_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update_tag() raises 404 when the project lookup yields None
    (lines 315-316).
    """
    service = MagicMock()
    service.tag_repo = MagicMock()
    service.tag_repo.get_by_id_in_project = AsyncMock(return_value=None)
    db = MagicMock()
    db.commit = AsyncMock()
    http_request = MagicMock()
    current_user = MagicMock()
    monkeypatch.setattr(mod, "gate_action", AsyncMock())

    with pytest.raises(HTTPException) as excinfo:
        await mod.update_tag(
            project_id=uuid4(),
            tag_id=uuid4(),
            request=TagUpdate(name="renamed"),
            http_request=http_request,
            current_user=current_user,
            service=service,
            db=db,
            locale="en",
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_update_tag_commits_and_returns_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update_tag() commits and returns the updated tag (line 320)."""
    existing = MagicMock()
    sentinel = MagicMock()
    service = MagicMock()
    service.tag_repo = MagicMock()
    service.tag_repo.get_by_id_in_project = AsyncMock(return_value=existing)
    service.update = AsyncMock(return_value=sentinel)
    db = MagicMock()
    db.commit = AsyncMock()
    http_request = MagicMock()
    current_user = MagicMock()
    monkeypatch.setattr(mod, "gate_action", AsyncMock())

    result = await mod.update_tag(
        project_id=uuid4(),
        tag_id=uuid4(),
        request=TagUpdate(name="renamed"),
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
        locale="en",
    )
    assert result is sentinel
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_tag_returns_404_when_tag_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delete_tag() raises 404 when the project lookup yields None
    (lines 361-362).
    """
    service = MagicMock()
    service.tag_repo = MagicMock()
    service.tag_repo.get_by_id_in_project = AsyncMock(return_value=None)
    db = MagicMock()
    db.commit = AsyncMock()
    http_request = MagicMock()
    current_user = MagicMock()
    monkeypatch.setattr(mod, "gate_action", AsyncMock())

    with pytest.raises(HTTPException) as excinfo:
        await mod.delete_tag(
            project_id=uuid4(),
            tag_id=uuid4(),
            http_request=http_request,
            current_user=current_user,
            service=service,
            db=db,
        )
    assert excinfo.value.status_code == 404
