"""Repository for SamplingRound and SamplingRoundItem database operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.annotation import Annotation
from echoroo.models.embedding import Embedding
from echoroo.models.sampling_round import SamplingRound, SamplingRoundItem


class SamplingRoundRepository:
    """Repository for SamplingRound and SamplingRoundItem entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def create_round(
        self,
        custom_model_id: UUID,
        round_number: int,
        round_type: str,
        sampling_config: dict[str, Any] | None = None,
    ) -> SamplingRound:
        """Create a new SamplingRound record with status 'pending'.

        Args:
            custom_model_id: UUID of the owning CustomModel
            round_number: Sequential round number (0 for seed round)
            round_type: Sampling type ('seed' or 'active_learning')
            sampling_config: Optional JSONB configuration for the sampling strategy

        Returns:
            Newly created SamplingRound instance with populated id and timestamps
        """
        round_ = SamplingRound(
            custom_model_id=custom_model_id,
            round_number=round_number,
            round_type=round_type,
            sampling_config=sampling_config,
            sample_count=0,
            status="pending",
        )
        self.db.add(round_)
        await self.db.flush()
        await self.db.refresh(round_)
        return round_

    async def get_round(self, round_id: UUID) -> SamplingRound | None:
        """Fetch a SamplingRound by primary key (items not loaded).

        Args:
            round_id: SamplingRound UUID

        Returns:
            SamplingRound instance or None if not found
        """
        result = await self.db.execute(
            select(SamplingRound).where(SamplingRound.id == round_id)
        )
        return result.scalar_one_or_none()

    async def list_rounds(self, custom_model_id: UUID) -> list[SamplingRound]:
        """Return all sampling rounds for a custom model, ordered by round_number.

        Items are not eagerly loaded; use get_round_with_items when items are needed.

        Args:
            custom_model_id: UUID of the owning CustomModel

        Returns:
            List of SamplingRound instances ordered by round_number ascending
        """
        result = await self.db.execute(
            select(SamplingRound)
            .where(SamplingRound.custom_model_id == custom_model_id)
            .order_by(SamplingRound.round_number.asc())
        )
        return list(result.scalars().all())

    async def update_round_status(
        self,
        round_id: UUID,
        status: str,
        error_message: str | None = None,
        sample_count: int | None = None,
    ) -> SamplingRound | None:
        """Update the status (and optionally sample_count) of a SamplingRound.

        Sets completed_at automatically when status is 'completed' or 'failed'.

        Args:
            round_id: SamplingRound UUID
            status: New status value ('pending', 'running', 'completed', or 'failed')
            error_message: Error details to store when status is 'failed'
            sample_count: Updated sample count to store alongside the status change

        Returns:
            Updated SamplingRound instance, or None if the round was not found
        """
        round_ = await self.get_round(round_id)
        if round_ is None:
            return None

        round_.status = status

        if error_message is not None:
            round_.error_message = error_message

        if sample_count is not None:
            round_.sample_count = sample_count

        if status in ("completed", "failed"):
            round_.completed_at = datetime.now(tz=timezone.utc)

        await self.db.flush()
        await self.db.refresh(round_)
        return round_

    async def add_items(
        self,
        round_id: UUID,
        items: list[dict[str, Any]],
    ) -> list[SamplingRoundItem]:
        """Bulk-insert SamplingRoundItem records for a sampling round.

        Each item dict must contain:
            - embedding_id (UUID)
            - sample_type (str)
            - annotation_id (UUID)
        Optional keys: similarity (float), decision_distance (float)

        Args:
            round_id: UUID of the owning SamplingRound
            items: List of item attribute dicts

        Returns:
            List of created SamplingRoundItem instances
        """
        new_items = [
            SamplingRoundItem(
                sampling_round_id=round_id,
                embedding_id=item["embedding_id"],
                sample_type=item["sample_type"],
                annotation_id=item["annotation_id"],
                similarity=item.get("similarity"),
                decision_distance=item.get("decision_distance"),
            )
            for item in items
        ]
        self.db.add_all(new_items)
        await self.db.flush()
        return new_items

    async def get_round_with_items(self, round_id: UUID) -> SamplingRound | None:
        """Fetch a SamplingRound with items, annotations, and embeddings eagerly loaded.

        Loads the item list joined with Annotation (for review_status) and
        Embedding (for recording_id, start_time, end_time) to avoid N+1 queries
        when serialising items for API responses.

        Args:
            round_id: SamplingRound UUID

        Returns:
            SamplingRound instance with items populated, or None if not found
        """
        result = await self.db.execute(
            select(SamplingRound)
            .where(SamplingRound.id == round_id)
            .options(
                selectinload(SamplingRound.items).options(
                    selectinload(SamplingRoundItem.annotation),
                    selectinload(SamplingRoundItem.embedding),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_round_by_number(
        self,
        custom_model_id: UUID,
        round_number: int,
    ) -> SamplingRound | None:
        """Fetch a SamplingRound by model ID and round number.

        Args:
            custom_model_id: UUID of the owning CustomModel
            round_number: Round number to look up (0 for seed round)

        Returns:
            SamplingRound instance or None if not found
        """
        result = await self.db.execute(
            select(SamplingRound).where(
                SamplingRound.custom_model_id == custom_model_id,
                SamplingRound.round_number == round_number,
            )
        )
        return result.scalar_one_or_none()

    async def get_existing_embedding_ids(self, custom_model_id: UUID) -> set[UUID]:
        """Return the set of embedding IDs already sampled for a custom model.

        Used for cross-round deduplication so that the same embedding is not
        selected in more than one sampling round for the same model.

        Args:
            custom_model_id: UUID of the owning CustomModel

        Returns:
            Set of embedding UUIDs that appear in any round for the model
        """
        result = await self.db.execute(
            select(SamplingRoundItem.embedding_id)
            .join(
                SamplingRound,
                SamplingRoundItem.sampling_round_id == SamplingRound.id,
            )
            .where(SamplingRound.custom_model_id == custom_model_id)
        )
        return set(result.scalars().all())
