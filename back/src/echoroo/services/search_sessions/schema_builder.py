"""Search session schema builder service."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo import models, schemas

if TYPE_CHECKING:
    pass

__all__ = ["SearchSessionSchemaBuilder"]


class SearchSessionSchemaBuilder:
    """Service for building SearchSession schemas with aggregated data."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _eager_load_relationships(
        self,
        db_obj: models.SearchSession,
    ) -> models.SearchSession:
        """Eagerly load relationships needed for SearchSession schema validation."""
        stmt = (
            select(models.SearchSession)
            .where(models.SearchSession.uuid == db_obj.uuid)
            .options(
                selectinload(models.SearchSession.target_tags).selectinload(
                    models.SearchSessionTargetTag.tag
                ),
                selectinload(models.SearchSession.ml_project),
                selectinload(models.SearchSession.created_by),
                selectinload(models.SearchSession.reference_sounds).selectinload(
                    models.ReferenceSound.ml_project
                ),
                selectinload(models.SearchSession.reference_sounds).selectinload(
                    models.ReferenceSound.tag
                ),
                selectinload(models.SearchSession.reference_sounds).selectinload(
                    models.ReferenceSound.clip
                ),
                selectinload(models.SearchSession.reference_sounds).selectinload(
                    models.ReferenceSound.embeddings
                ),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def build_schema(
        self,
        db_obj: models.SearchSession,
        include_counts: bool = True,
    ) -> schemas.SearchSession:
        """Build SearchSession schema with all related data.

        Args:
            db_obj: SearchSession model instance
            include_counts: Whether to include result/tag counts

        Returns:
            Complete SearchSession schema
        """
        # Eager load relationships
        db_obj = await self._eager_load_relationships(db_obj)

        # Base schema data
        schema_dict = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "description": db_obj.description,
            "ml_project_id": db_obj.ml_project_id,
            "ml_project_uuid": db_obj.ml_project.uuid if db_obj.ml_project else None,
            "easy_positive_k": db_obj.easy_positive_k,
            "boundary_n": db_obj.boundary_n,
            "boundary_m": db_obj.boundary_m,
            "others_p": db_obj.others_p,
            "distance_metric": db_obj.distance_metric,
            "current_iteration": db_obj.current_iteration,
            "is_search_complete": db_obj.is_search_complete,
            "notes": db_obj.description,
            "created_by_id": db_obj.created_by_id,
            "created_on": db_obj.created_on,
        }

        # Build target tags list
        target_tags = []
        for tt in db_obj.target_tags:
            target_tags.append(
                schemas.SearchSessionTargetTag(
                    tag_id=tt.tag_id,
                    tag=schemas.Tag.model_validate(tt.tag),
                    shortcut_key=tt.shortcut_key,
                )
            )
        schema_dict["target_tags"] = target_tags

        # Build reference sounds list
        reference_sounds = self._build_reference_sounds(db_obj)
        schema_dict["reference_sounds"] = reference_sounds

        if include_counts:
            # Get aggregated counts
            result_counts = await self._get_result_counts(db_obj.id)
            tag_counts = await self._get_tag_counts(db_obj.id)

            schema_dict.update({
                "total_results": result_counts["total"],
                "labeled_count": result_counts["labeled"],
                "unlabeled_count": result_counts["total"] - result_counts["labeled"],
                "negative_count": result_counts["negative"],
                "uncertain_count": result_counts["uncertain"],
                "skipped_count": result_counts["skipped"],
                "tag_counts": tag_counts,
            })

        return schemas.SearchSession.model_validate(schema_dict)

    def _build_reference_sounds(
        self,
        db_obj: models.SearchSession,
    ) -> list:
        """Build reference sounds list from database object.

        Args:
            db_obj: SearchSession model instance with loaded relationships

        Returns:
            List of reference sound schemas
        """
        from echoroo.schemas.reference_sounds import ReferenceSound

        reference_sounds = []
        if hasattr(db_obj, "reference_sounds") and db_obj.reference_sounds:
            for ref_sound in db_obj.reference_sounds:
                # Map source enum
                source_map = {
                    models.ReferenceSoundSource.XENO_CANTO: schemas.ReferenceSoundSource.XENO_CANTO,
                    models.ReferenceSoundSource.CUSTOM_UPLOAD: schemas.ReferenceSoundSource.UPLOAD,
                    models.ReferenceSoundSource.DATASET_CLIP: schemas.ReferenceSoundSource.CLIP,
                }
                source = source_map.get(
                    ref_sound.source, schemas.ReferenceSoundSource.UPLOAD
                )

                ref_data = {
                    "uuid": ref_sound.uuid,
                    "id": ref_sound.id,
                    "name": ref_sound.name,
                    "ml_project_id": ref_sound.ml_project_id,
                    "ml_project_uuid": (
                        ref_sound.ml_project.uuid if ref_sound.ml_project else None
                    ),
                    "source": source,
                    "tag_id": ref_sound.tag_id,
                    "tag": (
                        schemas.Tag.model_validate(ref_sound.tag)
                        if ref_sound.tag
                        else None
                    ),
                    "start_time": ref_sound.start_time,
                    "end_time": ref_sound.end_time,
                    "duration": ref_sound.end_time - ref_sound.start_time,
                    "xeno_canto_id": ref_sound.xeno_canto_id,
                    "clip_id": ref_sound.clip_id,
                    "clip": (
                        schemas.Clip.model_validate(ref_sound.clip)
                        if ref_sound.clip
                        else None
                    ),
                    "audio_path": ref_sound.audio_path,
                    "embedding_count": len(ref_sound.embeddings) if ref_sound.embeddings else 0,
                    "is_active": ref_sound.is_active,
                    "created_by_id": ref_sound.created_by_id,
                    "created_on": ref_sound.created_on,
                }
                reference_sounds.append(ReferenceSound.model_validate(ref_data))

        return reference_sounds

    async def _get_result_counts(
        self,
        search_session_id: int,
    ) -> dict[str, int]:
        """Get result counts for a search session.

        Args:
            search_session_id: Search session database ID

        Returns:
            Dict with 'total', 'labeled', 'negative', 'uncertain', 'skipped' counts
        """
        # Check if any tags are assigned via junction table
        has_tags_subquery = (
            select(models.SearchResultTag.search_result_id)
            .where(
                models.SearchResultTag.search_result_id == models.SearchResult.id
            )
            .exists()
        )

        # Single query to get all counts
        stmt = select(
            func.count(models.SearchResult.id).label("total"),
            func.sum(
                sa.case(
                    (
                        has_tags_subquery
                        | (models.SearchResult.is_negative == True)
                        | (models.SearchResult.is_uncertain == True)
                        | (models.SearchResult.is_skipped == True),
                        1,
                    ),
                    else_=0,
                )
            ).label("labeled"),
            func.sum(
                sa.case((models.SearchResult.is_negative == True, 1), else_=0)
            ).label("negative"),
            func.sum(
                sa.case((models.SearchResult.is_uncertain == True, 1), else_=0)
            ).label("uncertain"),
            func.sum(
                sa.case((models.SearchResult.is_skipped == True, 1), else_=0)
            ).label("skipped"),
        ).where(
            models.SearchResult.search_session_id == search_session_id
        )

        result = await self.session.execute(stmt)
        row = result.one()

        return {
            "total": row.total or 0,
            "labeled": int(row.labeled or 0),
            "negative": int(row.negative or 0),
            "uncertain": int(row.uncertain or 0),
            "skipped": int(row.skipped or 0),
        }

    async def _get_tag_counts(
        self,
        search_session_id: int,
    ) -> dict[int, int]:
        """Get tag assignment counts for a search session.

        Args:
            search_session_id: Search session database ID

        Returns:
            Dict mapping tag_id to count
        """
        stmt = (
            select(
                models.SearchResultTag.tag_id,
                func.count(func.distinct(models.SearchResultTag.search_result_id)).label("count"),
            )
            .join(
                models.SearchResult,
                models.SearchResultTag.search_result_id == models.SearchResult.id,
            )
            .where(models.SearchResult.search_session_id == search_session_id)
            .group_by(models.SearchResultTag.tag_id)
        )

        result = await self.session.execute(stmt)
        return {tag_id: count for tag_id, count in result.all()}
