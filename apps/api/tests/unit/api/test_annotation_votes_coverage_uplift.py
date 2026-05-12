"""Coverage uplift unit tests for ``echoroo.api.v1.annotation_votes``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers get_annotation_votes,
cast_annotation_vote, and delete_annotation_vote handlers including
404 paths so the module clears the 85% threshold without touching
production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.api.v1 import annotation_votes as mod
from echoroo.schemas.annotation_vote import VoteCastRequest


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    return user


def _make_db() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
    return db


def _make_project(project_id: object = None) -> MagicMock:
    proj = MagicMock()
    proj.id = project_id or uuid4()
    proj.review_min_votes = 2
    proj.review_consensus_threshold = 0.667
    return proj


def _make_vote_service() -> MagicMock:
    svc = MagicMock()
    svc.get_vote_summary = AsyncMock()
    svc.cast_vote = AsyncMock()
    svc.delete_vote = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_get_annotation_votes_raises_404_when_annotation_missing() -> None:
    """get_annotation_votes raises 404 when annotation not in project (lines 125-127)."""
    user = _make_user()
    db = _make_db()
    project = _make_project()
    request = MagicMock()
    vote_service = _make_vote_service()

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=False)

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_votes.AnnotationRepository", return_value=annot_repo),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.get_annotation_votes(
            project_id=project.id,
            annotation_id=uuid4(),
            request=request,
            current_user=user,
            vote_service=vote_service,
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_annotation_votes_returns_summary() -> None:
    """get_annotation_votes returns vote summary (lines 134-141)."""
    user = _make_user()
    db = _make_db()
    project = _make_project()
    request = MagicMock()
    vote_service = _make_vote_service()
    summary = MagicMock()
    vote_service.get_vote_summary = AsyncMock(return_value=summary)
    annotation_id = uuid4()

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=True)

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_votes.AnnotationRepository", return_value=annot_repo),
        patch.object(mod, "resolve_viewer_role", AsyncMock(return_value="member")),
    ):
        result = await mod.get_annotation_votes(
            project_id=project.id,
            annotation_id=annotation_id,
            request=request,
            current_user=user,
            vote_service=vote_service,
            db=db,
        )

    assert result is summary


@pytest.mark.asyncio
async def test_cast_annotation_vote_raises_404_when_annotation_missing() -> None:
    """cast_annotation_vote raises 404 when annotation not in project (lines 212-214)."""
    user = _make_user()
    db = _make_db()
    project = _make_project()
    http_request = MagicMock()
    http_request.state = MagicMock()
    vote_service = _make_vote_service()
    from echoroo.models.enums import VoteType

    request = VoteCastRequest(vote=VoteType.AGREE)

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=False)

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_votes.AnnotationRepository", return_value=annot_repo),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.cast_annotation_vote(
            project_id=project.id,
            annotation_id=uuid4(),
            request=request,
            http_request=http_request,
            current_user=user,
            vote_service=vote_service,
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_cast_annotation_vote_returns_summary_on_success() -> None:
    """cast_annotation_vote returns updated summary on success (lines 228-242)."""
    user = _make_user()
    db = _make_db()
    project = _make_project()
    http_request = MagicMock()
    http_request.state = MagicMock()
    vote_service = _make_vote_service()
    from echoroo.models.enums import AnnotationVoteSource, VoteType

    request = VoteCastRequest(vote=VoteType.AGREE)
    summary = MagicMock()
    vote_service.cast_vote = AsyncMock(return_value=summary)

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=True)

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_votes.AnnotationRepository", return_value=annot_repo),
        patch.object(
            mod, "classify_voter_source",
            AsyncMock(return_value=(AnnotationVoteSource.MEMBER, "owner")),
        ),
        patch.object(mod, "resolve_viewer_role", AsyncMock(return_value="owner")),
    ):
        result = await mod.cast_annotation_vote(
            project_id=project.id,
            annotation_id=uuid4(),
            request=request,
            http_request=http_request,
            current_user=user,
            vote_service=vote_service,
            db=db,
        )

    assert result is summary
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_annotation_vote_raises_404_when_annotation_missing() -> None:
    """delete_annotation_vote raises 404 when annotation not in project (lines 309-311)."""
    user = _make_user()
    db = _make_db()
    project = _make_project()
    request = MagicMock()
    vote_service = _make_vote_service()

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=False)

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_votes.AnnotationRepository", return_value=annot_repo),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.delete_annotation_vote(
            project_id=project.id,
            annotation_id=uuid4(),
            request=request,
            current_user=user,
            vote_service=vote_service,
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_annotation_vote_returns_summary_on_success() -> None:
    """delete_annotation_vote returns updated summary on success (lines 316-334)."""
    user = _make_user()
    db = _make_db()
    project = _make_project()
    request = MagicMock()
    vote_service = _make_vote_service()
    summary = MagicMock()
    vote_service.delete_vote = AsyncMock(return_value=summary)

    annot_repo = MagicMock()
    annot_repo.exists_in_project = AsyncMock(return_value=True)

    with (
        patch.object(mod, "gate_action", AsyncMock(return_value=project)),
        patch("echoroo.api.v1.annotation_votes.AnnotationRepository", return_value=annot_repo),
        patch.object(mod, "resolve_viewer_role", AsyncMock(return_value="owner")),
    ):
        result = await mod.delete_annotation_vote(
            project_id=project.id,
            annotation_id=uuid4(),
            request=request,
            current_user=user,
            vote_service=vote_service,
            db=db,
        )

    assert result is summary
    db.commit.assert_awaited_once()
