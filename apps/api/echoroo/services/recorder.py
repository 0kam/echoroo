"""Recorder service for business logic."""

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.repositories.recorder import RecorderRepository
from echoroo.schemas.recorder import (
    RecorderCreate,
    RecorderListResponse,
    RecorderResponse,
    RecorderUpdate,
)


class RecorderService:
    """Service for recorder management operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize recorder service with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self.recorder_repo = RecorderRepository(db)

    async def list_recorders(
        self,
        page: int = 1,
        limit: int = 20,
    ) -> RecorderListResponse:
        """List all recorders with pagination.

        Args:
            page: Page number (1-indexed)
            limit: Number of items per page

        Returns:
            Paginated recorder list with total count
        """
        # Calculate offset
        offset = (page - 1) * limit

        # Get recorders and total count
        recorders = await self.recorder_repo.get_all(offset=offset, limit=limit)
        total = await self.recorder_repo.count()

        # Convert to response schemas
        items = [RecorderResponse.model_validate(recorder) for recorder in recorders]

        return RecorderListResponse(
            items=items,
            total=total,
            page=page,
            limit=limit,
        )

    async def get_recorder(self, recorder_id: str) -> RecorderResponse:
        """Get a recorder by ID.

        Args:
            recorder_id: Recorder's unique identifier

        Returns:
            Recorder response

        Raises:
            HTTPException: If recorder not found
        """
        recorder = await self.recorder_repo.get_by_id(recorder_id)
        if not recorder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Recorder with id '{recorder_id}' not found",
            )

        return RecorderResponse.model_validate(recorder)

    async def create_recorder(self, data: RecorderCreate) -> RecorderResponse:
        """Create a new recorder.

        Args:
            data: Recorder creation data

        Returns:
            Created recorder response

        Raises:
            HTTPException: If recorder with same ID already exists
        """
        try:
            recorder = await self.recorder_repo.create(data)
            await self.db.commit()
            return RecorderResponse.model_validate(recorder)
        except IntegrityError as e:
            await self.db.rollback()
            # Check if it's a duplicate ID error
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Recorder with id '{data.id}' already exists",
                ) from e
            # Re-raise for other integrity errors
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create recorder due to data integrity error",
            ) from e

    async def update_recorder(
        self,
        recorder_id: str,
        data: RecorderUpdate,
    ) -> RecorderResponse:
        """Update a recorder.

        Args:
            recorder_id: Recorder's unique identifier
            data: Recorder update data

        Returns:
            Updated recorder response

        Raises:
            HTTPException: If recorder not found
        """
        recorder = await self.recorder_repo.update(recorder_id, data)
        if not recorder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Recorder with id '{recorder_id}' not found",
            )

        await self.db.commit()
        return RecorderResponse.model_validate(recorder)

    async def delete_recorder(self, recorder_id: str) -> None:
        """Delete a recorder.

        Args:
            recorder_id: Recorder's unique identifier

        Raises:
            HTTPException: If recorder not found
        """
        deleted = await self.recorder_repo.delete(recorder_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Recorder with id '{recorder_id}' not found",
            )

        await self.db.commit()
