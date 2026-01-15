"""PostgreSQL-based model cache for trained ML models during active learning."""

import io
import logging
from typing import Any
from uuid import UUID

import joblib
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.cached_model import CachedModel

logger = logging.getLogger(__name__)

__all__ = ["ModelCache", "get_model_cache"]


class ModelCache:
    """PostgreSQL-based cache for storing trained models.

    This replaces Redis-based caching with PostgreSQL storage,
    using the cached_model table to store serialized models.
    """

    def __init__(self, session: AsyncSession):
        """Initialize model cache with database session.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession for database operations.
        """
        self.session = session

    async def set_model(
        self,
        session_uuid: str | UUID,
        iteration: int,
        model_data: Any,
    ) -> bool:
        """Store a trained model in the database.

        Parameters
        ----------
        session_uuid
            UUID of the search session.
        iteration
            Active learning iteration number.
        model_data
            Trained model object (will be serialized with joblib).

        Returns
        -------
        bool
            True if successful, False otherwise.
        """
        try:
            # Convert string UUID to UUID object if needed
            if isinstance(session_uuid, str):
                session_uuid = UUID(session_uuid)

            # Serialize model data using joblib
            buffer = io.BytesIO()
            joblib.dump(model_data, buffer)
            serialized = buffer.getvalue()

            # Check if model already exists for this session and iteration
            existing = await self.session.scalar(
                select(CachedModel)
                .where(CachedModel.session_uuid == session_uuid)
                .where(CachedModel.iteration == iteration)
            )

            if existing:
                # Update existing model
                existing.model_data = serialized
                logger.info(
                    f"Model cache updated: session={session_uuid}, iteration={iteration}, "
                    f"size={len(serialized)} bytes"
                )
            else:
                # Create new cached model
                cached_model = CachedModel(
                    session_uuid=session_uuid,
                    iteration=iteration,
                    model_data=serialized,
                )
                self.session.add(cached_model)
                logger.info(
                    f"Model cached: session={session_uuid}, iteration={iteration}, "
                    f"size={len(serialized)} bytes"
                )

            # Flush to database (caller will commit)
            await self.session.flush()
            return True

        except Exception as e:
            logger.error(
                f"Failed to cache model: session={session_uuid}, iteration={iteration}, error={e}"
            )
            return False

    async def get_model(
        self,
        session_uuid: str | UUID,
        iteration: int,
    ) -> Any | None:
        """Retrieve a trained model from the database.

        Parameters
        ----------
        session_uuid
            UUID of the search session.
        iteration
            Active learning iteration number.

        Returns
        -------
        Any | None
            Deserialized model object, or None if not found or error.
        """
        try:
            # Convert string UUID to UUID object if needed
            if isinstance(session_uuid, str):
                session_uuid = UUID(session_uuid)

            # Query cached model
            cached_model = await self.session.scalar(
                select(CachedModel)
                .where(CachedModel.session_uuid == session_uuid)
                .where(CachedModel.iteration == iteration)
            )

            if cached_model is None:
                logger.warning(
                    f"Model not found in cache: session={session_uuid}, iteration={iteration}"
                )
                return None

            # Deserialize model data
            buffer = io.BytesIO(cached_model.model_data)
            model_data = joblib.load(buffer)

            logger.info(
                f"Model loaded from cache: session={session_uuid}, iteration={iteration}"
            )
            return model_data

        except Exception as e:
            logger.error(
                f"Failed to load model: session={session_uuid}, iteration={iteration}, error={e}"
            )
            return None

    async def delete_model(
        self,
        session_uuid: str | UUID,
        iteration: int,
    ) -> bool:
        """Delete a cached model from the database.

        Parameters
        ----------
        session_uuid
            UUID of the search session.
        iteration
            Active learning iteration number.

        Returns
        -------
        bool
            True if deleted, False if not found or error.
        """
        try:
            # Convert string UUID to UUID object if needed
            if isinstance(session_uuid, str):
                session_uuid = UUID(session_uuid)

            # Delete cached model
            result = await self.session.execute(
                delete(CachedModel)
                .where(CachedModel.session_uuid == session_uuid)
                .where(CachedModel.iteration == iteration)
            )

            deleted_count = result.rowcount

            if deleted_count > 0:
                logger.info(
                    f"Model deleted from cache: session={session_uuid}, iteration={iteration}"
                )
                await self.session.flush()
                return True
            else:
                logger.warning(
                    f"Model not found for deletion: session={session_uuid}, iteration={iteration}"
                )
                return False

        except Exception as e:
            logger.error(
                f"Failed to delete model: session={session_uuid}, iteration={iteration}, error={e}"
            )
            return False

    async def delete_all_models(
        self,
        session_uuid: str | UUID,
    ) -> int:
        """Delete all cached models for a search session.

        Parameters
        ----------
        session_uuid
            UUID of the search session.

        Returns
        -------
        int
            Number of models deleted.
        """
        try:
            # Convert string UUID to UUID object if needed
            if isinstance(session_uuid, str):
                session_uuid = UUID(session_uuid)

            # Delete all cached models for this session
            result = await self.session.execute(
                delete(CachedModel)
                .where(CachedModel.session_uuid == session_uuid)
            )

            deleted_count = result.rowcount

            if deleted_count > 0:
                logger.info(
                    f"Deleted {deleted_count} cached models for session={session_uuid}"
                )
                await self.session.flush()

            return deleted_count

        except Exception as e:
            logger.error(
                f"Failed to delete all models: session={session_uuid}, error={e}"
            )
            return 0


def get_model_cache(session: AsyncSession) -> ModelCache:
    """Get model cache instance for the given database session.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession for database operations.

    Returns
    -------
    ModelCache
        Configured model cache instance.
    """
    return ModelCache(session)
