"""Coverage uplift unit tests for ``echoroo.api.v1.annotation_comments``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers _determine_comment_source,
list_annotation_comments, and create_annotation_comment handlers so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.api.v1 import annotation_comments as mod
from echoroo.models.enums import AnnotationVoteSource
from echoroo.schemas.annotation_comment import AnnotationCommentCreate


def _make_user(user_id: object = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid4()
    return user


def _make_db() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
    return db


def _make_project() -> MagicMock:
    proj = MagicMock()
    proj.id = uuid4()
    return proj


@pytest.mark.asyncio
async def test_determine_comment_source_owner_returns_member() -> None:
    """_determine_comment_source returns MEMBER for project owner (lines 65-66)."""
    db = _make_db()
    project = _make_project()
    project_id = uuid4()
    user_id = uuid4()

    with patch("echoroo.api.v1.annotation_comments.ProjectRepository") as MockRepo:
        repo = MagicMock()
        repo.is_project_owner = AsyncMock(return_value=True)
        MockRepo.return_value = repo

        source = await mod._determine_comment_source(
            project_id=project_id,
            project=project,
            user_id=user_id,
            db=db,
        )

    assert source == AnnotationVoteSource.MEMBER


@pytest.mark.asyncio
async def test_determine_comment_source_member_returns_member() -> None:
    """_determine_comment_source returns MEMBER for project member (lines 67-69)."""
    db = _make_db()
    project = _make_project()
    project_id = uuid4()
    user_id = uuid4()

    mock_member = MagicMock()

    with patch("echoroo.api.v1.annotation_comments.ProjectRepository") as MockRepo:
        repo = MagicMock()
        repo.is_project_owner = AsyncMock(return_value=False)
        repo.get_member = AsyncMock(return_value=mock_member)
        MockRepo.return_value = repo

        source = await mod._determine_comment_source(
            project_id=project_id,
            project=project,
            user_id=user_id,
            db=db,
        )

    assert source == AnnotationVoteSource.MEMBER


@pytest.mark.asyncio
async def test_determine_comment_source_non_member_returns_guest_authenticated() -> None:
    """_determine_comment_source returns GUEST_AUTHENTICATED for non-member (lines 74-75)."""
    db = _make_db()
    project = _make_project()
    project_id = uuid4()
    user_id = uuid4()

    with patch("echoroo.api.v1.annotation_comments.ProjectRepository") as MockRepo:
        repo = MagicMock()
        repo.is_project_owner = AsyncMock(return_value=False)
        repo.get_member = AsyncMock(return_value=None)
        MockRepo.return_value = repo

        source = await mod._determine_comment_source(
            project_id=project_id,
            project=project,
            user_id=user_id,
            db=db,
        )

    assert source == AnnotationVoteSource.GUEST_AUTHENTICATED


@pytest.mark.asyncio
async def test_list_annotation_comments_returns_404_when_annotation_missing() -> None:
    """list_annotation_comments raises 404 when annotation not found (lines 125-127)."""
    user = _make_user()
    db = _make_db()
    project_id = uuid4()
    annotation_id = uuid4()
    request = MagicMock()
    project = _make_project()

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=False)

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_comments.AnnotationRepository", return_value=annot_repo),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.list_annotation_comments(
            project_id=project_id,
            annotation_id=annotation_id,
            request=request,
            current_user=user,
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_list_annotation_comments_returns_comments_list() -> None:
    """list_annotation_comments returns comments when annotation exists (lines 132-134)."""
    user = _make_user()
    db = _make_db()
    project_id = uuid4()
    annotation_id = uuid4()
    request = MagicMock()
    project = _make_project()

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=True)

    comment_repo = MagicMock()
    # Return empty list — simplest way to exercise the code path
    comment_repo.list_by_annotation = AsyncMock(return_value=[])

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_comments.AnnotationRepository", return_value=annot_repo),
        patch(
            "echoroo.api.v1.annotation_comments.AnnotationCommentRepository",
            return_value=comment_repo,
        ),
    ):
        result = await mod.list_annotation_comments(
            project_id=project_id,
            annotation_id=annotation_id,
            request=request,
            current_user=user,
            db=db,
        )

    assert result.items == []
    comment_repo.list_by_annotation.assert_awaited_once_with(annotation_id, project_id)


@pytest.mark.asyncio
async def test_create_annotation_comment_raises_404_when_annotation_missing() -> None:
    """create_annotation_comment raises 404 when annotation missing (lines 186-188)."""
    user = _make_user()
    db = _make_db()
    project_id = uuid4()
    annotation_id = uuid4()
    payload = AnnotationCommentCreate(body="my comment")
    request = MagicMock()
    request.state = MagicMock()
    project = _make_project()

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=False)

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_comments.AnnotationRepository", return_value=annot_repo),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.create_annotation_comment(
            project_id=project_id,
            annotation_id=annotation_id,
            payload=payload,
            request=request,
            current_user=user,
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_create_annotation_comment_creates_and_returns_comment() -> None:
    """create_annotation_comment creates and returns comment (lines 201-212)."""
    user = _make_user()
    db = _make_db()
    project_id = uuid4()
    annotation_id = uuid4()
    payload = AnnotationCommentCreate(body="  my comment  ")
    request = MagicMock()
    request.state = MagicMock()
    project = _make_project()
    created_comment = MagicMock()

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=True)

    comment_repo = MagicMock()
    comment_repo.create = AsyncMock(return_value=created_comment)

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_comments.AnnotationRepository", return_value=annot_repo),
        patch.object(
            mod, "_determine_comment_source",
            AsyncMock(return_value=AnnotationVoteSource.MEMBER),
        ),
        patch(
            "echoroo.api.v1.annotation_comments.AnnotationCommentRepository",
            return_value=comment_repo,
        ),
        patch("echoroo.api.v1.annotation_comments.AnnotationCommentResponse") as MockResp,
    ):
        MockResp.model_validate.return_value = created_comment

        result = await mod.create_annotation_comment(
            project_id=project_id,
            annotation_id=annotation_id,
            payload=payload,
            request=request,
            current_user=user,
            db=db,
        )

    db.commit.assert_awaited_once()
    assert result is created_comment
