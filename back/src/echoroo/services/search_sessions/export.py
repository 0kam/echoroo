"""Search session export service for annotation projects."""

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import exists

from echoroo import exceptions, models, schemas

if TYPE_CHECKING:
    pass

__all__ = ["SearchSessionExportService"]

logger = logging.getLogger(__name__)


class SearchSessionExportService:
    """Service for exporting search sessions to annotation projects."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def export_to_annotation_project(
        self,
        search_session: models.SearchSession,
        data: schemas.ExportToAnnotationProjectRequest,
        user: models.User,
        ml_project: models.MLProject,
    ) -> schemas.ExportToAnnotationProjectResponse:
        """Export search results to annotation project.

        Args:
            search_session: SearchSession to export from
            data: Export request data
            user: User performing the export
            ml_project: ML project owning the search session

        Returns:
            Export response with annotation project info

        Raises:
            ValidationError: If no results to export or missing dataset
        """
        from echoroo.api.annotation_projects import annotation_projects
        from echoroo.api.clips import clips

        # Get results to export
        db_results = await self._get_results_to_export(
            search_session_id=search_session.id,
            include_labeled=data.include_labeled,
            include_tag_ids=data.include_tag_ids,
        )

        if not db_results:
            raise exceptions.InvalidDataError(
                "No results found matching the export criteria"
            )

        # Get dataset_id from ML project
        dataset_id = await self._get_dataset_id(ml_project)

        # Create annotation project
        annotation_project = await annotation_projects.create(
            self.session,
            name=data.name,
            description=data.description,
            annotation_instructions=(
                f"Review clips from search session: {search_session.name}. "
            ),
            user=user,
            dataset_id=dataset_id,
        )

        # Add target tags to annotation project
        await self._add_target_tags(
            annotation_project=annotation_project,
            search_session=search_session,
            user=user,
        )

        # Create annotation tasks from results
        exported_count = await self._create_annotation_tasks(
            annotation_project=annotation_project,
            db_results=db_results,
            user=user,
        )

        logger.info(
            f"Exported {exported_count} results from search session "
            f"{search_session.uuid} to annotation project {annotation_project.uuid}"
        )

        return schemas.ExportToAnnotationProjectResponse(
            annotation_project_uuid=annotation_project.uuid,
            annotation_project_name=annotation_project.name,
            exported_count=exported_count,
            message=(
                f"Successfully exported {exported_count} clips "
                f"to annotation project '{data.name}'"
            ),
        )

    async def _get_results_to_export(
        self,
        search_session_id: int,
        include_labeled: bool,
        include_tag_ids: list[int] | None,
    ) -> list[models.SearchResult]:
        """Get search results to export based on filters.

        Args:
            search_session_id: Search session database ID
            include_labeled: Whether to include labeled results
            include_tag_ids: Optional list of specific tag IDs to include

        Returns:
            List of SearchResult instances
        """
        results_query = select(models.SearchResult).where(
            models.SearchResult.search_session_id == search_session_id
        )

        if include_labeled:
            if include_tag_ids:
                # Filter to specific tags via junction table
                has_specific_tags = exists(
                    select(1).where(
                        models.SearchResultTag.search_result_id
                        == models.SearchResult.id,
                        models.SearchResultTag.tag_id.in_(include_tag_ids),
                    )
                )
                results_query = results_query.where(has_specific_tags)
            else:
                # Include all results with assigned tags via junction table
                has_any_tags = exists(
                    select(1).where(
                        models.SearchResultTag.search_result_id
                        == models.SearchResult.id
                    )
                )
                results_query = results_query.where(has_any_tags)

        result = await self.session.execute(results_query)
        return list(result.scalars().all())

    async def _get_dataset_id(self, ml_project: models.MLProject) -> int:
        """Get dataset ID from ML project.

        Args:
            ml_project: ML project instance

        Returns:
            Dataset ID

        Raises:
            InvalidDataError: If no dataset is associated with ML project
        """
        dataset_id = ml_project.dataset_id
        if dataset_id is None:
            # Try to get from dataset scopes
            if ml_project.dataset_scopes:
                dataset_id = ml_project.dataset_scopes[0].dataset_id
            else:
                raise exceptions.InvalidDataError(
                    "ML Project has no associated dataset"
                )
        return dataset_id

    async def _add_target_tags(
        self,
        annotation_project: schemas.AnnotationProject,
        search_session: models.SearchSession,
        user: models.User,
    ) -> None:
        """Add target tags to annotation project.

        Args:
            annotation_project: Created annotation project
            search_session: Source search session
            user: User performing the export
        """
        from echoroo.api.annotation_projects import annotation_projects

        for tt in search_session.target_tags:
            tag_schema = schemas.Tag.model_validate(tt.tag)
            await annotation_projects.add_tag(
                self.session,
                annotation_project,
                tag_schema,
                user=user,
            )

    async def _create_annotation_tasks(
        self,
        annotation_project: schemas.AnnotationProject,
        db_results: list[models.SearchResult],
        user: models.User,
    ) -> int:
        """Create annotation tasks from search results.

        Args:
            annotation_project: Target annotation project
            db_results: Search results to convert to tasks
            user: User performing the export

        Returns:
            Number of tasks created
        """
        from echoroo.api.annotation_projects import annotation_projects
        from echoroo.api.clips import clips
        from echoroo.api.common import update_object

        exported_count = 0

        for db_result in db_results:
            try:
                # Load the clip
                await self.session.refresh(db_result, ["clip"])

                # Get the clip schema
                clip = await clips.get(self.session, db_result.clip.uuid)

                # Add task to annotation project
                await annotation_projects.add_task(
                    self.session,
                    annotation_project,
                    clip,
                    user=user,
                )

                # Update the search result to track which AP it was exported to
                await update_object(
                    self.session,
                    models.SearchResult,
                    models.SearchResult.uuid == db_result.uuid,
                    {"saved_to_annotation_project_id": annotation_project.id},
                )

                exported_count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to export result {db_result.uuid} "
                    f"to annotation project: {e}"
                )

        return exported_count
