"""AnnotationComment repository for comment database operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from echoroo.models.annotation_comment import AnnotationComment
from echoroo.models.enums import AnnotationVoteSource
from echoroo.repositories.base import BaseRepository


class AnnotationCommentRepository(BaseRepository[AnnotationComment]):
    """Repository for AnnotationComment entity operations."""

    model = AnnotationComment

    async def list_by_annotation(
        self,
        annotation_id: UUID,
        project_id: UUID,
    ) -> list[AnnotationComment]:
        """List comments for an annotation within a project."""
        result = await self.db.execute(
            select(AnnotationComment)
            .where(
                AnnotationComment.annotation_id == annotation_id,
                AnnotationComment.project_id == project_id,
            )
            .order_by(AnnotationComment.created_at.asc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        annotation_id: UUID,
        project_id: UUID,
        commenter_user_id: UUID,
        body: str,
        source: AnnotationVoteSource,
    ) -> AnnotationComment:
        """Create a comment for an annotation."""
        comment = AnnotationComment(
            annotation_id=annotation_id,
            project_id=project_id,
            commenter_user_id=commenter_user_id,
            body=body,
            source=source,
        )
        self.db.add(comment)
        await self.db.flush()
        await self.db.refresh(comment)
        return comment

    async def get_by_id_in_project(
        self,
        comment_id: UUID,
        project_id: UUID,
    ) -> AnnotationComment | None:
        """Get a comment by ID, restricted to the given project."""
        result = await self.db.execute(
            select(AnnotationComment).where(
                AnnotationComment.id == comment_id,
                AnnotationComment.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()
