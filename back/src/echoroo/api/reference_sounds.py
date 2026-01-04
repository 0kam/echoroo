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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI
from echoroo.api.ml_projects import can_edit_ml_project, can_view_ml_project
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
            "has_embedding": db_obj.embedding is not None,
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

        This downloads audio metadata from Xeno-Canto and stores
        the reference. The embedding will be computed asynchronously.
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

        # Fetch Xeno-Canto recording metadata (optional - for validation)
        xc_id = data.xeno_canto_id.upper()
        if xc_id.startswith("XC"):
            xc_id_num = xc_id[2:]
        else:
            xc_id_num = xc_id
            xc_id = f"XC{xc_id_num}"

        xc_url = f"https://xeno-canto.org/{xc_id_num}"

        # Create the reference sound
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

        # Check if clip exists
        clip = await session.get(models.Clip, data.clip_id)
        if clip is None:
            raise exceptions.NotFoundError(f"Clip with id {data.clip_id} not found")

        # Try to get clip embedding if ML project has an embedding model run
        embedding = None
        if ml_project.embedding_model_run_id:
            embedding_query = select(models.ClipEmbedding).where(
                models.ClipEmbedding.clip_id == clip.id,
                models.ClipEmbedding.model_run_id == ml_project.embedding_model_run_id,
            )
            result = await session.execute(embedding_query)
            clip_embedding = result.scalar_one_or_none()
            if clip_embedding:
                embedding = clip_embedding.embedding

        # Create the reference sound
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
            embedding=embedding,
            is_active=True,
            created_by_id=db_user.id,
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

        # Determine which model to use from ML project's embedding_model_run
        embedding_model_run = ml_project.embedding_model_run
        if embedding_model_run is None:
            raise exceptions.InvalidDataError(
                "ML Project does not have an embedding model configured. "
                "Please run foundation model detection on the datasets first."
            )

        model_name = embedding_model_run.name.lower()

        # Get audio directory from settings if not provided
        if audio_dir is None:
            settings = get_settings()
            audio_dir = settings.audio_dir

        # Load audio from the source
        audio_data = await self._load_audio_from_source(
            session, db_obj, audio_dir
        )

        # Compute embedding using the appropriate model
        if "birdnet" in model_name:
            from echoroo.ml.birdnet.constants import SAMPLE_RATE as BIRDNET_SAMPLE_RATE

            # Extract the segment at BirdNET's sample rate (48kHz)
            segment_audio = self._extract_segment(
                audio_data["samples"],
                audio_data["samplerate"],
                db_obj.start_time,
                db_obj.end_time,
                target_samplerate=BIRDNET_SAMPLE_RATE,
            )
            embedding = await self._compute_birdnet_embedding(segment_audio)
        elif "perch" in model_name:
            from echoroo.ml.perch.constants import SAMPLE_RATE as PERCH_SAMPLE_RATE

            # Extract the segment at Perch's sample rate (32kHz)
            segment_audio = self._extract_segment(
                audio_data["samples"],
                audio_data["samplerate"],
                db_obj.start_time,
                db_obj.end_time,
                target_samplerate=PERCH_SAMPLE_RATE,
            )
            embedding = await self._compute_perch_embedding(segment_audio)
        else:
            raise exceptions.InvalidDataError(
                f"Unknown embedding model: {model_name}. "
                "Supported models are 'birdnet' and 'perch'."
            )

        # Store the embedding
        db_obj = await common.update_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
            embedding=embedding.tolist(),
        )

        logger.info(
            f"Computed embedding for reference sound {obj.uuid} "
            f"using {model_name} model (dimension: {len(embedding)})"
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

    async def _compute_perch_embedding(
        self,
        audio: NDArray[np.float32],
    ) -> NDArray[np.float32]:
        """Compute embedding using Perch model.

        For segments longer than 5 seconds, splits into 5-second segments
        and averages the embeddings.

        Parameters
        ----------
        audio
            Audio samples at 32kHz sample rate.

        Returns
        -------
        NDArray[np.float32]
            1536-dimensional embedding vector.
        """
        from echoroo.ml.perch.constants import (
            EMBEDDING_DIM,
            SAMPLE_RATE,
            SEGMENT_DURATION,
            SEGMENT_SAMPLES,
        )
        from echoroo.ml.perch.loader import PerchLoader
        from echoroo.ml.perch.inference import PerchInference
        from echoroo.system.settings import get_settings

        from typing import Literal

        # Get device setting
        settings = get_settings()
        device: Literal["GPU", "CPU"] = "GPU" if settings.ml_use_gpu else "CPU"

        # Load Perch model (lazy loading with caching would be better in production)
        loader = PerchLoader(device=device)
        loader.load()

        inference = PerchInference(
            loader,
            confidence_threshold=0.1,
            device=device,
        )

        # Determine number of 5-second segments
        total_samples = len(audio)
        num_segments = max(1, int(np.ceil(total_samples / SEGMENT_SAMPLES)))

        embeddings = []

        for i in range(num_segments):
            start_idx = i * SEGMENT_SAMPLES
            end_idx = min(start_idx + SEGMENT_SAMPLES, total_samples)

            segment = audio[start_idx:end_idx]

            # Pad if necessary (must be exactly 5 seconds = 160000 samples)
            if len(segment) < SEGMENT_SAMPLES:
                padded = np.zeros(SEGMENT_SAMPLES, dtype=np.float32)
                padded[:len(segment)] = segment
                segment = padded

            # Get embedding for this segment
            result = inference.predict_segment(segment, start_time=0.0)
            embeddings.append(result.embedding)

        # Average embeddings if multiple segments
        if len(embeddings) == 1:
            embedding = embeddings[0]
        else:
            embeddings_array = np.stack(embeddings)
            embedding = np.mean(embeddings_array, axis=0)

        return embedding.astype(np.float32)

    async def _compute_birdnet_embedding(
        self,
        audio: NDArray[np.float32],
    ) -> NDArray[np.float32]:
        """Compute embedding using BirdNET model.

        For segments longer than 3 seconds, splits into 3-second segments
        and averages the embeddings.

        Parameters
        ----------
        audio
            Audio samples at 48kHz sample rate.

        Returns
        -------
        NDArray[np.float32]
            1024-dimensional embedding vector.
        """
        from echoroo.ml.birdnet.constants import (
            EMBEDDING_DIM,
            SAMPLE_RATE,
            SEGMENT_DURATION,
            SEGMENT_SAMPLES,
        )
        from echoroo.ml.birdnet.loader import BirdNETLoader
        from echoroo.ml.birdnet.inference import BirdNETInference
        from echoroo.system.settings import get_settings

        from typing import Literal

        # Get device setting
        settings = get_settings()
        device: Literal["GPU", "CPU"] = "GPU" if settings.ml_use_gpu else "CPU"

        # Load BirdNET model
        loader = BirdNETLoader(device=device)
        loader.load()

        inference = BirdNETInference(
            loader,
            confidence_threshold=0.1,
            device=device,
        )

        # Determine number of 3-second segments
        total_samples = len(audio)
        num_segments = max(1, int(np.ceil(total_samples / SEGMENT_SAMPLES)))

        embeddings = []

        for i in range(num_segments):
            start_idx = i * SEGMENT_SAMPLES
            end_idx = min(start_idx + SEGMENT_SAMPLES, total_samples)

            segment = audio[start_idx:end_idx]

            # Pad if necessary (must be exactly 3 seconds = 144000 samples)
            if len(segment) < SEGMENT_SAMPLES:
                padded = np.zeros(SEGMENT_SAMPLES, dtype=np.float32)
                padded[:len(segment)] = segment
                segment = padded

            # Get embedding for this segment
            result = inference.predict_segment(segment, start_time=0.0)
            embeddings.append(result.embedding)

        # Average embeddings if multiple segments
        if len(embeddings) == 1:
            embedding = embeddings[0]
        else:
            embeddings_array = np.stack(embeddings)
            embedding = np.mean(embeddings_array, axis=0)

        return embedding.astype(np.float32)

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
