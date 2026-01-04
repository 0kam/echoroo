import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from echoroo.system.boot import echoroo_init
from echoroo.system.database import create_async_db_engine, get_database_url
from echoroo.system.settings import Settings

__all__ = ["lifespan"]

logger = logging.getLogger(__name__)

# Global worker instances
_species_detection_worker = None
_species_filter_worker = None


@asynccontextmanager
async def lifespan(settings: Settings, _: FastAPI):
    """Context manager to run startup and shutdown events."""
    global _species_detection_worker, _species_filter_worker

    await echoroo_init(settings)

    # Create shared session factory for workers
    db_url = get_database_url(settings)
    engine = create_async_db_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Start species detection worker
    try:
        from echoroo.ml import SpeciesDetectionWorker

        _species_detection_worker = SpeciesDetectionWorker(
            audio_dir=settings.audio_dir,
            model_dir=None,  # Uses default model directory
            poll_interval=5.0,
            gpu_batch_size=settings.ml_gpu_batch_size,
            feeders=settings.ml_feeders,
            workers=settings.ml_workers,
        )

        await _species_detection_worker.start(session_factory)
        logger.info("Species detection worker started")

    except ImportError as e:
        logger.warning("Species detection worker not available: %s", e)
    except Exception as e:
        logger.error("Failed to start species detection worker: %s", e)

    # Start species filter worker
    try:
        from echoroo.ml import SpeciesFilterWorker

        _species_filter_worker = SpeciesFilterWorker(
            poll_interval=5.0,
        )

        await _species_filter_worker.start(session_factory)
        logger.info("Species filter worker started")

    except ImportError as e:
        logger.warning("Species filter worker not available: %s", e)
    except Exception as e:
        logger.error("Failed to start species filter worker: %s", e)

    yield

    # Stop species filter worker on shutdown
    if _species_filter_worker is not None:
        try:
            await _species_filter_worker.stop()
            logger.info("Species filter worker stopped")
        except Exception as e:
            logger.error("Error stopping species filter worker: %s", e)

    # Stop species detection worker on shutdown
    if _species_detection_worker is not None:
        try:
            await _species_detection_worker.stop()
            logger.info("Species detection worker stopped")
        except Exception as e:
            logger.error("Error stopping species detection worker: %s", e)
