"""Python API for Reference Sounds."""

import io
import logging
import tempfile
from pathlib import Path
from typing import Sequence
from uuid import UUID

import httpx
import numpy as np
import soundfile as sf
from numpy.typing import NDArray
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI
from echoroo.api.ml_projects import can_edit_ml_project, can_view_ml_project
from echoroo.api.species import get_gbif_vernacular_name
from echoroo.filters.base import Filter

__all__ = [
    "ReferenceSoundAPI",
    "reference_sounds",
]

logger = logging.getLogger(__name__)

XENO_CANTO_API_URL = "https://xeno-canto.org/api/2/recordings"


class ReferenceSoundAPI(
    BaseAPI[
        UUID,
        models.ReferenceSound,
        schemas.ReferenceSound,
        schemas.ReferenceSoundCreate,
        schemas.ReferenceSoundUpdate,
    ]
):
    """API for managing Reference Sounds."""

    _model = models.ReferenceSound
    _schema = schemas.ReferenceSound

    async def _resolve_user(
        self,
        session: AsyncSession,
        user: models.User | schemas.SimpleUser | None,
    ) -> models.User | None:
        """Resolve a user schema to a user model."""
        if user is None:
            return None
        if isinstance(user, models.User):
            return user
        db_user = await session.get(models.User, user.id)
        if db_user is None:
            raise exceptions.NotFoundError(f"User with id {user.id} not found")
        return db_user

    async def _get_ml_project(
        self,
        session: AsyncSession,
        ml_project_id: int,
    ) -> models.MLProject:
        """Get ML project by ID with embedding_model_run loaded."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(models.MLProject)
            .where(models.MLProject.id == ml_project_id)
            .options(selectinload(models.MLProject.embedding_model_run))
        )
        result = await session.execute(stmt)
        ml_project = result.unique().scalar_one_or_none()
        if ml_project is None:
            raise exceptions.NotFoundError(
                f"ML Project with id {ml_project_id} not found"
            )
        return ml_project

    async def _eager_load_relationships(
        self,
        session: AsyncSession,
        db_obj: models.ReferenceSound,
    ) -> models.ReferenceSound:
        """Eagerly load relationships needed for ReferenceSound schema validation."""
        stmt = (
            select(self._model)
            .where(self._model.uuid == db_obj.uuid)
            .options(
                selectinload(self._model.tag),
                selectinload(self._model.clip),
                selectinload(self._model.ml_project),
                selectinload(self._model.created_by),
                selectinload(self._model.embeddings),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _build_schema(
        self,
        session: AsyncSession,
        db_obj: models.ReferenceSound,
    ) -> schemas.ReferenceSound:
        """Build schema from database object."""
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Map source enum
        source_map = {
            models.ReferenceSoundSource.XENO_CANTO: schemas.ReferenceSoundSource.XENO_CANTO,
            models.ReferenceSoundSource.CUSTOM_UPLOAD: schemas.ReferenceSoundSource.UPLOAD,
            models.ReferenceSoundSource.DATASET_CLIP: schemas.ReferenceSoundSource.CLIP,
        }
        source = source_map.get(
            db_obj.source, schemas.ReferenceSoundSource.UPLOAD
        )

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "ml_project_id": db_obj.ml_project_id,
            "ml_project_uuid": db_obj.ml_project.uuid if db_obj.ml_project else None,
            "source": source,
            "tag_id": db_obj.tag_id,
            "tag": schemas.Tag.model_validate(db_obj.tag) if db_obj.tag else None,
            "start_time": db_obj.start_time,
            "end_time": db_obj.end_time,
            "duration": db_obj.end_time - db_obj.start_time,
            "xeno_canto_id": db_obj.xeno_canto_id,
            "clip_id": db_obj.clip_id,
            "clip": (
                schemas.Clip.model_validate(db_obj.clip) if db_obj.clip else None
            ),
            "audio_path": db_obj.audio_path,
            "embedding_count": len(db_obj.embeddings) if db_obj.embeddings else 0,
            "is_active": db_obj.is_active,
            "created_by_id": db_obj.created_by_id,
            "created_on": db_obj.created_on,
        }

        return schemas.ReferenceSound.model_validate(data)

    async def get(
        self,
        session: AsyncSession,
        pk: UUID,
        user: models.User | None = None,
    ) -> schemas.ReferenceSound:
        """Get a reference sound by UUID."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(pk),
        )

        # Check access via ML project
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Reference sound with uuid {pk} not found"
            )

        return await self._build_schema(session, db_obj)

    async def get_many(
        self,
        session: AsyncSession,
        ml_project_id: int,
        *,
        limit: int | None = 1000,
        offset: int | None = 0,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = "-created_on",
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.ReferenceSound], int]:
        """Get reference sounds for an ML project."""
        db_user = await self._resolve_user(session, user)

        # Check access to the ML project
        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"ML Project with id {ml_project_id} not found"
            )

        # Add filter for ml_project_id
        combined_filters: list[Filter | ColumnExpressionArgument] = [
            self._model.ml_project_id == ml_project_id
        ]
        if filters:
            combined_filters.extend(filters)

        db_objs, count = await common.get_objects(
            session,
            self._model,
            limit=limit,
            offset=offset,
            filters=combined_filters,
            sort_by=sort_by,
        )

        results = []
        for db_obj in db_objs:
            schema_obj = await self._build_schema(session, db_obj)
            results.append(schema_obj)

        return results, count

    async def create_from_xeno_canto(
        self,
        session: AsyncSession,
        ml_project_id: int,
        data: schemas.ReferenceSoundFromXenoCanto,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.ReferenceSound:
        """Create a reference sound from a Xeno-Canto recording.

        This downloads audio from Xeno-Canto, extracts the specified segment,
        computes the embedding using the ML project's embedding model, and
        stores the reference sound with embedding.
        """
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create reference sounds"
            )

        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to add reference sounds to this ML project"
            )

        # Verify ML project has an embedding model configured
        if ml_project.embedding_model_run is None:
            raise exceptions.InvalidDataError(
                "ML Project does not have an embedding model configured. "
                "Please add a dataset scope with foundation model detection first."
            )

        # Check if tag exists
        tag = await session.get(models.Tag, data.tag_id)
        if tag is None:
            raise exceptions.NotFoundError(f"Tag with id {data.tag_id} not found")

        # If tag has no vernacular_name and has a species key, try to fetch from GBIF
        if tag.vernacular_name is None and tag.key == "species" and tag.value:
            try:
                vernacular = await get_gbif_vernacular_name(tag.value, locale="ja")
                if vernacular:
                    tag.vernacular_name = vernacular
                    await session.flush()
                    logger.info(f"Updated tag {tag.id} with vernacular name: {vernacular}")
            except Exception as e:
                logger.warning(f"Failed to fetch vernacular name for tag {tag.id}: {e}")

        # Fetch Xeno-Canto recording metadata (optional - for validation)
        xc_id = data.xeno_canto_id.upper()
        if xc_id.startswith("XC"):
            xc_id_num = xc_id[2:]
        else:
            xc_id_num = xc_id
            xc_id = f"XC{xc_id_num}"

        xc_url = f"https://xeno-canto.org/{xc_id_num}"

        # Load audio from Xeno-Canto and compute sliding window embeddings
        audio_data = await self._load_xeno_canto_audio(xc_id_num)
        embeddings = await self._compute_embedding_for_segment(
            ml_project,
            audio_data["samples"],
            audio_data["samplerate"],
            data.start_time,
            data.end_time,
        )

        # Create the reference sound without embedding (it's stored separately now)
        db_obj = await common.create_object(
            session,
            self._model,
            name=data.name,
            description=getattr(data, "notes", None),
            ml_project_id=ml_project_id,
            source=models.ReferenceSoundSource.XENO_CANTO,
            xeno_canto_id=xc_id,
            xeno_canto_url=xc_url,
            tag_id=data.tag_id,
            start_time=data.start_time,
            end_time=data.end_time,
            is_active=True,
            created_by_id=db_user.id,
        )

        # Create ReferenceSoundEmbedding objects for each sliding window
        for window_start, window_end, embedding in embeddings:
            embedding_obj = models.ReferenceSoundEmbedding(
                reference_sound_id=db_obj.id,
                embedding=embedding.tolist(),
                window_start_time=window_start,
                window_end_time=window_end,
            )
            session.add(embedding_obj)

        await session.flush()

        if embeddings:
            logger.info(
                f"Created reference sound from Xeno-Canto {xc_id} "
                f"with {len(embeddings)} embeddings ({len(embeddings[0][2])}-dim each)"
            )
        else:
            logger.warning(
                f"Created reference sound from Xeno-Canto {xc_id} "
                "but no embeddings were generated"
            )

        return await self._build_schema(session, db_obj)

    async def create_from_clip(
        self,
        session: AsyncSession,
        ml_project_id: int,
        data: schemas.ReferenceSoundFromClip,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.ReferenceSound:
        """Create a reference sound from an existing dataset clip.

        Uses the clip's embedding if available.
        """
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create reference sounds"
            )

        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to add reference sounds to this ML project"
            )

        # Check if tag exists
        tag = await session.get(models.Tag, data.tag_id)
        if tag is None:
            raise exceptions.NotFoundError(f"Tag with id {data.tag_id} not found")

        # If tag has no vernacular_name and has a species key, try to fetch from GBIF
        if tag.vernacular_name is None and tag.key == "species" and tag.value:
            try:
                vernacular = await get_gbif_vernacular_name(tag.value, locale="ja")
                if vernacular:
                    tag.vernacular_name = vernacular
                    await session.flush()
                    logger.info(f"Updated tag {tag.id} with vernacular name: {vernacular}")
            except Exception as e:
                logger.warning(f"Failed to fetch vernacular name for tag {tag.id}: {e}")

        # Check if clip exists
        clip = await session.get(models.Clip, data.clip_id)
        if clip is None:
            raise exceptions.NotFoundError(f"Clip with id {data.clip_id} not found")

        # Verify ML project has an embedding model configured
        if ml_project.embedding_model_run is None:
            raise exceptions.InvalidDataError(
                "ML Project does not have an embedding model configured. "
                "Please add a dataset scope with foundation model detection first."
            )

        # Load audio from clip and compute sliding window embeddings
        from echoroo.system.settings import get_settings
        settings = get_settings()
        audio_dir = settings.audio_dir

        audio_data = await self._load_clip_audio(session, clip.id, audio_dir)
        embeddings = await self._compute_embedding_for_segment(
            ml_project,
            audio_data["samples"],
            audio_data["samplerate"],
            data.start_time,
            data.end_time,
        )

        # Create the reference sound without embedding (it's stored separately now)
        db_obj = await common.create_object(
            session,
            self._model,
            name=data.name,
            description=getattr(data, "notes", None),
            ml_project_id=ml_project_id,
            source=models.ReferenceSoundSource.DATASET_CLIP,
            clip_id=clip.id,
            tag_id=data.tag_id,
            start_time=data.start_time,
            end_time=data.end_time,
            is_active=True,
            created_by_id=db_user.id,
        )

        # Create ReferenceSoundEmbedding objects for each sliding window
        for window_start, window_end, embedding in embeddings:
            embedding_obj = models.ReferenceSoundEmbedding(
                reference_sound_id=db_obj.id,
                embedding=embedding.tolist(),
                window_start_time=window_start,
                window_end_time=window_end,
            )
            session.add(embedding_obj)

        await session.flush()

        if embeddings:
            logger.info(
                f"Created reference sound from clip {clip.id} "
                f"with {len(embeddings)} embeddings ({len(embeddings[0][2])}-dim each)"
            )
        else:
            logger.warning(
                f"Created reference sound from clip {clip.id} "
                "but no embeddings were generated"
            )

        return await self._build_schema(session, db_obj)

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.ReferenceSound,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.ReferenceSound:
        """Delete a reference sound."""
        db_user = await self._resolve_user(session, user)

        # Get the ML project for permission check
        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this reference sound"
            )

        # Build the result before deletion
        result = await self._build_schema(session, db_obj)

        # Delete
        await common.delete_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        return result

    async def compute_embedding(
        self,
        session: AsyncSession,
        obj: schemas.ReferenceSound,
        *,
        user: models.User | schemas.SimpleUser | None = None,
        audio_dir: Path | None = None,
    ) -> schemas.ReferenceSound:
        """Compute or recompute embedding for a reference sound.

        This method loads audio from the source (Xeno-Canto, dataset clip,
        or custom upload), extracts the segment defined by start_time/end_time,
        runs the appropriate model (BirdNET or Perch) based on the ML project's
        embedding_model_run to generate embeddings, and stores the result.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        obj
            The reference sound to compute embedding for.
        user
            The user performing the operation.
        audio_dir
            Directory containing audio files (required for dataset clips).

        Returns
        -------
        schemas.ReferenceSound
            Updated reference sound with embedding.

        Raises
        ------
        PermissionDeniedError
            If user doesn't have edit permission.
        InvalidDataError
            If audio cannot be loaded from the source or model is not configured.
        """
        from echoroo.system.settings import get_settings

        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this reference sound"
            )

        # Verify ML project has an embedding model configured
        if ml_project.embedding_model_run is None:
            raise exceptions.InvalidDataError(
                "ML Project does not have an embedding model configured. "
                "Please run foundation model detection on the datasets first."
            )

        # Get audio directory from settings if not provided
        if audio_dir is None:
            settings = get_settings()
            audio_dir = settings.audio_dir

        # Load audio from the source
        audio_data = await self._load_audio_from_source(
            session, db_obj, audio_dir
        )

        # Compute sliding window embeddings using the ML project's model
        embeddings = await self._compute_embedding_for_segment(
            ml_project,
            audio_data["samples"],
            audio_data["samplerate"],
            db_obj.start_time,
            db_obj.end_time,
        )

        # Delete existing embeddings
        await session.execute(
            delete(models.ReferenceSoundEmbedding).where(
                models.ReferenceSoundEmbedding.reference_sound_id == db_obj.id
            )
        )

        # Create new ReferenceSoundEmbedding objects for each sliding window
        for window_start, window_end, embedding in embeddings:
            embedding_obj = models.ReferenceSoundEmbedding(
                reference_sound_id=db_obj.id,
                embedding=embedding.tolist(),
                window_start_time=window_start,
                window_end_time=window_end,
            )
            session.add(embedding_obj)

        await session.flush()

        model_name = ml_project.embedding_model_run.name.lower()
        logger.info(
            f"Computed {len(embeddings)} embeddings for reference sound {obj.uuid} "
            f"using {model_name} model (dimension: {len(embeddings[0][2])})"
        )

        return await self._build_schema(session, db_obj)

    async def _load_audio_from_source(
        self,
        session: AsyncSession,
        db_obj: models.ReferenceSound,
        audio_dir: Path,
    ) -> dict:
        """Load audio data from the reference sound's source.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        db_obj
            The reference sound database object.
        audio_dir
            Directory containing audio files.

        Returns
        -------
        dict
            Dictionary with 'samples' (np.ndarray) and 'samplerate' (int).

        Raises
        ------
        InvalidDataError
            If audio cannot be loaded from the source.
        """
        source = db_obj.source

        if source == models.ReferenceSoundSource.XENO_CANTO:
            return await self._load_xeno_canto_audio(db_obj.xeno_canto_id)

        elif source == models.ReferenceSoundSource.DATASET_CLIP:
            return await self._load_clip_audio(session, db_obj.clip_id, audio_dir)

        elif source == models.ReferenceSoundSource.CUSTOM_UPLOAD:
            return await self._load_custom_upload_audio(db_obj.audio_path, audio_dir)

        else:
            raise exceptions.InvalidDataError(
                f"Unknown reference sound source: {source}"
            )

    async def _load_xeno_canto_audio(self, xc_id: str | None) -> dict:
        """Download audio from Xeno-Canto.

        Parameters
        ----------
        xc_id
            Xeno-Canto recording ID (e.g., 'XC123456').

        Returns
        -------
        dict
            Dictionary with 'samples' and 'samplerate'.
        """
        if not xc_id:
            raise exceptions.InvalidDataError(
                "Xeno-Canto ID is required for Xeno-Canto reference sounds"
            )

        # Extract numeric ID from XC format
        xc_num = xc_id.upper()
        if xc_num.startswith("XC"):
            xc_num = xc_num[2:]

        download_url = f"https://xeno-canto.org/{xc_num}/download"

        logger.info(f"Downloading Xeno-Canto audio from {download_url}")

        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            response = await client.get(download_url)
            if response.status_code != 200:
                raise exceptions.InvalidDataError(
                    f"Failed to download Xeno-Canto recording {xc_id}: "
                    f"HTTP {response.status_code}"
                )

            audio_bytes = response.content

        # Load audio from bytes
        with io.BytesIO(audio_bytes) as audio_buffer:
            samples, samplerate = sf.read(audio_buffer)

        # Ensure mono
        if len(samples.shape) > 1:
            samples = np.mean(samples, axis=1)

        return {"samples": samples.astype(np.float32), "samplerate": samplerate}

    async def _load_clip_audio(
        self,
        session: AsyncSession,
        clip_id: int | None,
        audio_dir: Path,
    ) -> dict:
        """Load audio from a dataset clip.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        clip_id
            The clip database ID.
        audio_dir
            Directory containing audio files.

        Returns
        -------
        dict
            Dictionary with 'samples' and 'samplerate'.
        """
        if not clip_id:
            raise exceptions.InvalidDataError(
                "Clip ID is required for dataset clip reference sounds"
            )

        # Load clip with recording relationship
        stmt = (
            select(models.Clip)
            .options(selectinload(models.Clip.recording))
            .where(models.Clip.id == clip_id)
        )
        result = await session.execute(stmt)
        clip = result.scalar_one_or_none()

        if clip is None:
            raise exceptions.NotFoundError(f"Clip with id {clip_id} not found")

        recording = clip.recording
        if recording is None:
            raise exceptions.InvalidDataError(
                f"Clip {clip_id} has no associated recording"
            )

        # Load audio from recording file
        audio_path = audio_dir / recording.path
        if not audio_path.exists():
            raise exceptions.InvalidDataError(
                f"Audio file not found: {audio_path}"
            )

        samples, samplerate = sf.read(str(audio_path))

        # Ensure mono
        if len(samples.shape) > 1:
            samples = np.mean(samples, axis=1)

        return {"samples": samples.astype(np.float32), "samplerate": samplerate}

    async def _load_custom_upload_audio(
        self,
        audio_path: str | None,
        audio_dir: Path,
    ) -> dict:
        """Load audio from a custom upload.

        Parameters
        ----------
        audio_path
            Relative path to the uploaded audio file.
        audio_dir
            Directory containing audio files.

        Returns
        -------
        dict
            Dictionary with 'samples' and 'samplerate'.
        """
        if not audio_path:
            raise exceptions.InvalidDataError(
                "Audio path is required for custom upload reference sounds"
            )

        full_path = audio_dir / audio_path
        if not full_path.exists():
            raise exceptions.InvalidDataError(
                f"Audio file not found: {full_path}"
            )

        samples, samplerate = sf.read(str(full_path))

        # Ensure mono
        if len(samples.shape) > 1:
            samples = np.mean(samples, axis=1)

        return {"samples": samples.astype(np.float32), "samplerate": samplerate}

    def _compute_sliding_window_embeddings(
        self,
        samples: NDArray[np.float32],
        samplerate: int,
        start_time: float,
        end_time: float,
        window_size: float,
        overlap_rate: float = 0.7,
    ) -> list[tuple[float, float, NDArray[np.float32]]]:
        """Compute embeddings using sliding windows that cover at least 50% of the selected segment.

        Parameters
        ----------
        samples
            Full audio samples array.
        samplerate
            Sample rate of the input audio.
        start_time
            Start time of the selected segment in seconds.
        end_time
            End time of the selected segment in seconds.
        window_size
            Size of each window in seconds (3s for BirdNET, 5s for Perch).
        overlap_rate
            Overlap rate between consecutive windows (default 0.7 = 70%).

        Returns
        -------
        list[tuple[float, float, NDArray[np.float32]]]
            List of tuples (window_start, window_end, embedding) for each window
            that overlaps at least 50% with the selected segment.
        """
        # Calculate hop size
        hop_size = window_size * (1.0 - overlap_rate)

        # Calculate minimum overlap required (50% of window)
        min_overlap = window_size * 0.5

        # Get audio duration
        audio_duration = len(samples) / samplerate

        # Selected segment duration
        segment_duration = end_time - start_time

        results = []

        # Start from 0 and iterate with hop_size
        window_start = 0.0
        while window_start < audio_duration:
            window_end = window_start + window_size

            # Clamp window to audio boundaries
            window_end = min(window_end, audio_duration)

            # Calculate overlap with selected segment
            overlap_start = max(window_start, start_time)
            overlap_end = min(window_end, end_time)
            overlap_duration = max(0.0, overlap_end - overlap_start)

            # Check if overlap is at least 50% of window size
            if overlap_duration >= min_overlap:
                # Extract this window's audio
                start_sample = int(window_start * samplerate)
                end_sample = int(window_end * samplerate)

                # Clamp to valid sample range
                start_sample = max(0, start_sample)
                end_sample = min(len(samples), end_sample)

                window_audio = samples[start_sample:end_sample]

                # Store for later embedding computation
                results.append((window_start, window_end, window_audio))

            # Move to next window
            window_start += hop_size

            # Stop if we've passed beyond the segment with enough margin
            if window_start > end_time and overlap_duration < min_overlap:
                break

        # If no windows found (segment too short), create one centered on the segment
        if not results and segment_duration > 0:
            # Center the window on the segment
            segment_center = (start_time + end_time) / 2
            window_start = max(0.0, segment_center - window_size / 2)
            window_end = min(audio_duration, window_start + window_size)

            # Adjust start if end was clamped
            if window_end - window_start < window_size:
                window_start = max(0.0, window_end - window_size)

            start_sample = int(window_start * samplerate)
            end_sample = int(window_end * samplerate)
            start_sample = max(0, start_sample)
            end_sample = min(len(samples), end_sample)

            window_audio = samples[start_sample:end_sample]
            results.append((window_start, window_end, window_audio))

        return results

    async def _compute_embedding_for_segment(
        self,
        ml_project: models.MLProject,
        samples: NDArray[np.float32],
        samplerate: int,
        start_time: float,
        end_time: float,
    ) -> list[tuple[float, float, NDArray[np.float32]]]:
        """Compute sliding window embeddings for an audio segment using the ML project's model.

        Automatically selects BirdNET or Perch based on the ML project's
        embedding_model_run configuration.

        Parameters
        ----------
        ml_project
            ML project with embedding_model_run loaded.
        samples
            Audio samples as numpy array.
        samplerate
            Sample rate of the input audio.
        start_time
            Start time of the segment in seconds.
        end_time
            End time of the segment in seconds.

        Returns
        -------
        list[tuple[float, float, NDArray[np.float32]]]
            List of tuples (window_start, window_end, embedding) for each sliding window.
        """
        model_name = ml_project.embedding_model_run.name.lower()

        if "birdnet" in model_name:
            from echoroo.ml.birdnet.constants import (
                SAMPLE_RATE as BIRDNET_SAMPLE_RATE,
                SEGMENT_DURATION,
                SEGMENT_SAMPLES,
            )

            # Resample to target sample rate if necessary
            resampled_samples = samples
            if samplerate != BIRDNET_SAMPLE_RATE:
                import torch
                import torchaudio.functional as taF

                samples_tensor = torch.from_numpy(samples).unsqueeze(0)
                resampled_tensor = taF.resample(samples_tensor, samplerate, BIRDNET_SAMPLE_RATE)
                resampled_samples = resampled_tensor.squeeze(0).numpy().astype(np.float32)
                resampled_samplerate = BIRDNET_SAMPLE_RATE
            else:
                resampled_samplerate = samplerate

            # Adjust start/end times for resampled audio
            time_scale = resampled_samplerate / samplerate
            adjusted_start = start_time * time_scale
            adjusted_end = end_time * time_scale

            # Get sliding windows
            windows = self._compute_sliding_window_embeddings(
                resampled_samples,
                resampled_samplerate,
                adjusted_start,
                adjusted_end,
                window_size=SEGMENT_DURATION,
                overlap_rate=0.7,
            )

            if not windows:
                return []

            # Load model once for all windows
            embeddings = await self._compute_birdnet_embeddings_batch(
                [w[2] for w in windows],  # Extract audio arrays
                SEGMENT_SAMPLES,
            )

            # Combine with time info
            results = []
            for i, (window_start, window_end, _) in enumerate(windows):
                original_start = window_start / time_scale
                original_end = window_end / time_scale
                results.append((original_start, original_end, embeddings[i]))

            return results

        elif "perch" in model_name:
            from echoroo.ml.perch.constants import (
                SAMPLE_RATE as PERCH_SAMPLE_RATE,
                SEGMENT_DURATION,
                SEGMENT_SAMPLES,
            )

            # Resample to target sample rate if necessary
            resampled_samples = samples
            if samplerate != PERCH_SAMPLE_RATE:
                import torch
                import torchaudio.functional as taF

                samples_tensor = torch.from_numpy(samples).unsqueeze(0)
                resampled_tensor = taF.resample(samples_tensor, samplerate, PERCH_SAMPLE_RATE)
                resampled_samples = resampled_tensor.squeeze(0).numpy().astype(np.float32)
                resampled_samplerate = PERCH_SAMPLE_RATE
            else:
                resampled_samplerate = samplerate

            # Adjust start/end times for resampled audio
            time_scale = resampled_samplerate / samplerate
            adjusted_start = start_time * time_scale
            adjusted_end = end_time * time_scale

            # Get sliding windows
            windows = self._compute_sliding_window_embeddings(
                resampled_samples,
                resampled_samplerate,
                adjusted_start,
                adjusted_end,
                window_size=SEGMENT_DURATION,
                overlap_rate=0.7,
            )

            if not windows:
                return []

            # Load model once for all windows
            embeddings = await self._compute_perch_embeddings_batch(
                [w[2] for w in windows],  # Extract audio arrays
                SEGMENT_SAMPLES,
            )

            # Combine with time info
            results = []
            for i, (window_start, window_end, _) in enumerate(windows):
                original_start = window_start / time_scale
                original_end = window_end / time_scale
                results.append((original_start, original_end, embeddings[i]))

            return results

        else:
            raise exceptions.InvalidDataError(
                f"Unknown embedding model: {model_name}. "
                "Supported models are 'birdnet' and 'perch'."
            )

    def _extract_segment(
        self,
        samples: NDArray[np.float32],
        samplerate: int,
        start_time: float,
        end_time: float,
        target_samplerate: int = 32000,
    ) -> NDArray[np.float32]:
        """Extract and resample a segment of audio.

        Parameters
        ----------
        samples
            Audio samples as numpy array.
        samplerate
            Sample rate of the input audio.
        start_time
            Start time in seconds.
        end_time
            End time in seconds.
        target_samplerate
            Target sample rate for output. Default is 32kHz (Perch requirement).

        Returns
        -------
        NDArray[np.float32]
            Extracted and resampled audio segment.
        """
        import torchaudio.functional as taF
        import torch

        # Calculate sample indices
        start_sample = int(start_time * samplerate)
        end_sample = int(end_time * samplerate)

        # Clamp to valid range
        start_sample = max(0, start_sample)
        end_sample = min(len(samples), end_sample)

        if start_sample >= end_sample:
            raise exceptions.InvalidDataError(
                f"Invalid time range: start={start_time}s, end={end_time}s"
            )

        # Extract segment
        segment = samples[start_sample:end_sample]

        # Resample if necessary
        if samplerate != target_samplerate:
            segment_tensor = torch.from_numpy(segment).unsqueeze(0)
            resampled = taF.resample(segment_tensor, samplerate, target_samplerate)
            segment = resampled.squeeze(0).numpy()

        return segment.astype(np.float32)

    async def _compute_perch_embeddings_batch(
        self,
        audio_segments: list[NDArray[np.float32]],
        segment_samples: int,
    ) -> list[NDArray[np.float32]]:
        """Compute embeddings for multiple audio segments using Perch model.

        Concatenates all segments into a single file and processes in one call
        to avoid multiple model loads.

        Parameters
        ----------
        audio_segments
            List of audio samples at 32kHz sample rate.
        segment_samples
            Expected number of samples per segment (160000 for 5 seconds).

        Returns
        -------
        list[NDArray[np.float32]]
            List of 1536-dimensional embedding vectors.
        """
        from echoroo.ml.perch.loader import PerchLoader
        from echoroo.ml.perch.constants import SAMPLE_RATE, EMBEDDING_DIM
        from echoroo.system.settings import get_settings
        from typing import Literal

        if not audio_segments:
            return []

        # Get device setting
        settings = get_settings()
        device: Literal["GPU", "CPU"] = "GPU" if settings.ml_use_gpu else "CPU"

        # Pad/truncate all segments to exact length
        processed_segments = []
        for audio in audio_segments:
            if len(audio) < segment_samples:
                padded = np.zeros(segment_samples, dtype=np.float32)
                padded[:len(audio)] = audio
                processed_segments.append(padded)
            elif len(audio) > segment_samples:
                processed_segments.append(audio[:segment_samples])
            else:
                processed_segments.append(audio)

        # Concatenate all segments into one audio array
        concatenated_audio = np.concatenate(processed_segments, axis=0)

        # Load Perch model once
        loader = PerchLoader(device=device)
        loader.load()
        model = loader.get_model()

        # Write concatenated audio to a single temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, concatenated_audio, SAMPLE_RATE)
            tmp_path = tmp.name

        try:
            # Build inference kwargs
            infer_kwargs = {"device": device}
            if device != "CPU":
                infer_kwargs["batch_size"] = min(len(audio_segments), 16)

            # Call encode once for all segments
            embeddings_result = model.encode(tmp_path, **infer_kwargs)

            # Extract embeddings
            if hasattr(embeddings_result, "embeddings"):
                embeddings = embeddings_result.embeddings
            else:
                embeddings = embeddings_result

            if hasattr(embeddings, "numpy"):
                embeddings = embeddings.numpy()

            embeddings = np.asarray(embeddings, dtype=np.float32)

            # Normalize shape: should be (n_segments, embedding_dim)
            if embeddings.ndim == 3:
                embeddings = embeddings[0]
            elif embeddings.ndim == 1:
                embeddings = embeddings.reshape(1, -1)

            # Return as list
            result = [embeddings[i].astype(np.float32) for i in range(len(audio_segments))]

            logger.info(
                f"Perch batch processing: {len(audio_segments)} segments processed in single call"
            )

            return result

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def _compute_birdnet_embeddings_batch(
        self,
        audio_segments: list[NDArray[np.float32]],
        segment_samples: int,
    ) -> list[NDArray[np.float32]]:
        """Compute embeddings for multiple audio segments using BirdNET model.

        Concatenates all segments into a single file and processes in one call
        to avoid multiple model loads.

        Parameters
        ----------
        audio_segments
            List of audio samples at 48kHz sample rate.
        segment_samples
            Expected number of samples per segment (144000 for 3 seconds).

        Returns
        -------
        list[NDArray[np.float32]]
            List of 1024-dimensional embedding vectors.
        """
        from echoroo.ml.birdnet.loader import BirdNETLoader
        from echoroo.ml.birdnet.constants import SAMPLE_RATE, EMBEDDING_DIM
        from echoroo.system.settings import get_settings
        from typing import Literal

        if not audio_segments:
            return []

        # Get device setting
        settings = get_settings()
        device: Literal["GPU", "CPU"] = "GPU" if settings.ml_use_gpu else "CPU"

        # Pad/truncate all segments to exact length
        processed_segments = []
        for audio in audio_segments:
            if len(audio) < segment_samples:
                padded = np.zeros(segment_samples, dtype=np.float32)
                padded[:len(audio)] = audio
                processed_segments.append(padded)
            elif len(audio) > segment_samples:
                processed_segments.append(audio[:segment_samples])
            else:
                processed_segments.append(audio)

        # Concatenate all segments into one audio array
        concatenated_audio = np.concatenate(processed_segments, axis=0)

        # Load BirdNET model once
        loader = BirdNETLoader(device=device)
        loader.load()
        model = loader.get_model()

        # Write concatenated audio to a single temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, concatenated_audio, SAMPLE_RATE)
            tmp_path = tmp.name

        try:
            # Build inference kwargs
            infer_kwargs = {"device": device}
            if device != "CPU":
                infer_kwargs["batch_size"] = min(len(audio_segments), 16)

            # Call encode once for all segments
            embeddings_result = model.encode(tmp_path, **infer_kwargs)

            # Extract embeddings
            if hasattr(embeddings_result, "embeddings"):
                embeddings = embeddings_result.embeddings
            else:
                embeddings = embeddings_result

            if hasattr(embeddings, "numpy"):
                embeddings = embeddings.numpy()

            embeddings = np.asarray(embeddings, dtype=np.float32)

            # Normalize shape: should be (n_segments, embedding_dim)
            if embeddings.ndim == 3:
                embeddings = embeddings[0]
            elif embeddings.ndim == 1:
                embeddings = embeddings.reshape(1, -1)

            # Return as list
            result = [embeddings[i].astype(np.float32) for i in range(len(audio_segments))]

            logger.info(
                f"BirdNET batch processing: {len(audio_segments)} segments processed in single call"
            )

            return result

        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def get_audio_bytes(
        self,
        session: AsyncSession,
        obj: schemas.ReferenceSound,
        *,
        user: models.User | schemas.SimpleUser | None = None,
        audio_dir: Path | None = None,
    ) -> tuple[bytes, str]:
        """Get audio bytes for a reference sound.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        obj
            The reference sound.
        user
            The user making the request.
        audio_dir
            Directory containing audio files.

        Returns
        -------
        tuple[bytes, str]
            Audio bytes and content type.
        """
        from echoroo.system.settings import get_settings

        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Reference sound with uuid {obj.uuid} not found"
            )

        # Get audio directory from settings if not provided
        if audio_dir is None:
            settings = get_settings()
            audio_dir = settings.audio_dir

        source = db_obj.source

        if source == models.ReferenceSoundSource.XENO_CANTO:
            return await self._stream_xeno_canto_audio(db_obj.xeno_canto_id)

        elif source == models.ReferenceSoundSource.DATASET_CLIP:
            return await self._get_clip_audio_bytes(
                session, db_obj.clip_id, audio_dir
            )

        elif source == models.ReferenceSoundSource.CUSTOM_UPLOAD:
            return await self._get_custom_upload_bytes(db_obj.audio_path, audio_dir)

        else:
            raise exceptions.InvalidDataError(
                f"Unknown reference sound source: {source}"
            )

    async def _stream_xeno_canto_audio(
        self,
        xc_id: str | None,
    ) -> tuple[bytes, str]:
        """Stream audio from Xeno-Canto.

        Parameters
        ----------
        xc_id
            Xeno-Canto recording ID.

        Returns
        -------
        tuple[bytes, str]
            Audio bytes and content type.
        """
        if not xc_id:
            raise exceptions.InvalidDataError(
                "Xeno-Canto ID is required for Xeno-Canto reference sounds"
            )

        # Extract numeric ID
        xc_num = xc_id.upper()
        if xc_num.startswith("XC"):
            xc_num = xc_num[2:]

        download_url = f"https://xeno-canto.org/{xc_num}/download"

        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            response = await client.get(download_url)
            if response.status_code != 200:
                raise exceptions.InvalidDataError(
                    f"Failed to download Xeno-Canto recording {xc_id}: "
                    f"HTTP {response.status_code}"
                )

            content_type = response.headers.get("content-type", "audio/mpeg")
            return response.content, content_type

    async def _get_clip_audio_bytes(
        self,
        session: AsyncSession,
        clip_id: int | None,
        audio_dir: Path,
    ) -> tuple[bytes, str]:
        """Get audio bytes from a dataset clip.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        clip_id
            The clip database ID.
        audio_dir
            Directory containing audio files.

        Returns
        -------
        tuple[bytes, str]
            Audio bytes and content type.
        """
        if not clip_id:
            raise exceptions.InvalidDataError(
                "Clip ID is required for dataset clip reference sounds"
            )

        stmt = (
            select(models.Clip)
            .options(selectinload(models.Clip.recording))
            .where(models.Clip.id == clip_id)
        )
        result = await session.execute(stmt)
        clip = result.scalar_one_or_none()

        if clip is None:
            raise exceptions.NotFoundError(f"Clip with id {clip_id} not found")

        recording = clip.recording
        if recording is None:
            raise exceptions.InvalidDataError(
                f"Clip {clip_id} has no associated recording"
            )

        audio_path = audio_dir / recording.path
        if not audio_path.exists():
            raise exceptions.InvalidDataError(f"Audio file not found: {audio_path}")

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        # Determine content type from extension
        suffix = audio_path.suffix.lower()
        content_type_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".m4a": "audio/mp4",
        }
        content_type = content_type_map.get(suffix, "audio/mpeg")

        return audio_bytes, content_type

    async def _get_custom_upload_bytes(
        self,
        audio_path: str | None,
        audio_dir: Path,
    ) -> tuple[bytes, str]:
        """Get audio bytes from a custom upload.

        Parameters
        ----------
        audio_path
            Relative path to the uploaded audio file.
        audio_dir
            Directory containing audio files.

        Returns
        -------
        tuple[bytes, str]
            Audio bytes and content type.
        """
        if not audio_path:
            raise exceptions.InvalidDataError(
                "Audio path is required for custom upload reference sounds"
            )

        full_path = audio_dir / audio_path
        if not full_path.exists():
            raise exceptions.InvalidDataError(f"Audio file not found: {full_path}")

        with open(full_path, "rb") as f:
            audio_bytes = f.read()

        # Determine content type from extension
        suffix = Path(audio_path).suffix.lower()
        content_type_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".m4a": "audio/mp4",
        }
        content_type = content_type_map.get(suffix, "audio/mpeg")

        return audio_bytes, content_type

    async def update(
        self,
        session: AsyncSession,
        obj: schemas.ReferenceSound,
        data: schemas.ReferenceSoundUpdate,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.ReferenceSound:
        """Update a reference sound."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this reference sound"
            )

        # Build update data
        update_data = {}
        if data.name is not None:
            update_data["name"] = data.name
        if data.tag_id is not None:
            # Verify tag exists
            tag = await session.get(models.Tag, data.tag_id)
            if tag is None:
                raise exceptions.NotFoundError(
                    f"Tag with id {data.tag_id} not found"
                )
            update_data["tag_id"] = data.tag_id
        if data.start_time is not None:
            update_data["start_time"] = data.start_time
        if data.end_time is not None:
            update_data["end_time"] = data.end_time
        if data.notes is not None:
            update_data["description"] = data.notes
        if data.is_active is not None:
            update_data["is_active"] = data.is_active

        if update_data:
            db_obj = await common.update_object(
                session,
                self._model,
                self._get_pk_condition(obj.uuid),
                **update_data,
            )

        return await self._build_schema(session, db_obj)


reference_sounds = ReferenceSoundAPI()
