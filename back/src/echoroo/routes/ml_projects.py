"""REST API routes for ML Projects.

ML Projects provide a complete workflow for finding and classifying
specific sounds in audio datasets using embedding-based similarity search
and custom model training.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from echoroo import api, models, schemas
from echoroo.core import images
from echoroo.filters.ml_projects import MLProjectFilter
from echoroo.routes.dependencies import (
    Session,
    EchorooSettings,
    get_current_user_dependency,
    get_optional_current_user_dependency,
)
from echoroo.routes.types import Limit, Offset

__all__ = ["get_ml_projects_router"]


def get_ml_projects_router(settings: EchorooSettings) -> APIRouter:
    """Create a router with ML Project endpoints wired with authentication."""
    current_user_dep = get_current_user_dependency(settings)
    optional_user_dep = get_optional_current_user_dependency(settings)

    router = APIRouter()

    # =========================================================================
    # ML Project CRUD
    # =========================================================================

    @router.get(
        "/",
        response_model=schemas.Page[schemas.MLProject],
    )
    async def get_ml_projects(
        session: Session,
        filter: Annotated[MLProjectFilter, Depends(MLProjectFilter)],  # type: ignore
        limit: Limit = 10,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.MLProject]:
        """Get a paginated list of ML projects."""
        projects, total = await api.ml_projects.get_many(
            session,
            limit=limit,
            offset=offset,
            filters=[filter],
            user=user,
        )
        return schemas.Page(
            items=projects,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/",
        response_model=schemas.MLProject,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_ml_project(
        session: Session,
        data: schemas.MLProjectCreate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.MLProject:
        """Create a new ML project."""
        ml_project = await api.ml_projects.create(
            session,
            data,
            user=user,
        )
        await session.commit()
        return ml_project

    @router.get(
        "/{ml_project_uuid}",
        response_model=schemas.MLProject,
    )
    async def get_ml_project(
        session: Session,
        ml_project_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.MLProject:
        """Get an ML project by UUID."""
        return await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )

    @router.patch(
        "/{ml_project_uuid}",
        response_model=schemas.MLProject,
    )
    async def update_ml_project(
        session: Session,
        ml_project_uuid: UUID,
        data: schemas.MLProjectUpdate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.MLProject:
        """Update an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        updated = await api.ml_projects.update(
            session,
            ml_project,
            data,
            user=user,
        )
        await session.commit()
        return updated

    @router.delete(
        "/{ml_project_uuid}",
        response_model=schemas.MLProject,
    )
    async def delete_ml_project(
        session: Session,
        ml_project_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.MLProject:
        """Delete an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        deleted = await api.ml_projects.delete(
            session,
            ml_project,
            user=user,
        )
        await session.commit()
        return deleted

    # =========================================================================
    # Target Tags
    # =========================================================================

    @router.post(
        "/{ml_project_uuid}/tags",
        response_model=schemas.MLProject,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_target_tag(
        session: Session,
        ml_project_uuid: UUID,
        tag_id: int = Query(..., description="Tag ID to add"),
        user: models.User = Depends(current_user_dep),
    ) -> schemas.MLProject:
        """Add a target tag to an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        updated = await api.ml_projects.add_target_tag(
            session,
            ml_project,
            tag_id,
            user=user,
        )
        await session.commit()
        return updated

    @router.delete(
        "/{ml_project_uuid}/tags/{tag_id}",
        response_model=schemas.MLProject,
    )
    async def remove_target_tag(
        session: Session,
        ml_project_uuid: UUID,
        tag_id: int,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.MLProject:
        """Remove a target tag from an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        updated = await api.ml_projects.remove_target_tag(
            session,
            ml_project,
            tag_id,
            user=user,
        )
        await session.commit()
        return updated

    # =========================================================================
    # Reference Sounds
    # =========================================================================

    @router.get(
        "/{ml_project_uuid}/reference_sounds",
        response_model=schemas.Page[schemas.ReferenceSound],
    )
    async def get_reference_sounds(
        session: Session,
        ml_project_uuid: UUID,
        limit: Limit = 10,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.ReferenceSound]:
        """Get all reference sounds for an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        sounds, total = await api.reference_sounds.get_many(
            session,
            ml_project.id,
            limit=limit,
            offset=offset,
            user=user,
        )
        return schemas.Page(
            items=sounds,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/{ml_project_uuid}/reference_sounds/from_xeno_canto",
        response_model=schemas.ReferenceSound,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_reference_sound_from_xeno_canto(
        session: Session,
        ml_project_uuid: UUID,
        data: schemas.ReferenceSoundFromXenoCanto,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.ReferenceSound:
        """Create a reference sound from a Xeno-Canto recording."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        reference_sound = await api.reference_sounds.create_from_xeno_canto(
            session,
            ml_project.id,
            data,
            user=user,
        )
        await session.commit()
        return reference_sound

    @router.post(
        "/{ml_project_uuid}/reference_sounds/from_clip",
        response_model=schemas.ReferenceSound,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_reference_sound_from_clip(
        session: Session,
        ml_project_uuid: UUID,
        data: schemas.ReferenceSoundFromClip,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.ReferenceSound:
        """Create a reference sound from an existing clip."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        reference_sound = await api.reference_sounds.create_from_clip(
            session,
            ml_project.id,
            data,
            user=user,
        )
        await session.commit()
        return reference_sound

    @router.get(
        "/{ml_project_uuid}/reference_sounds/xeno_canto/{xeno_canto_id}/audio",
        # Also handle trailing slash
        include_in_schema=True,
    )
    @router.get(
        "/{ml_project_uuid}/reference_sounds/xeno_canto/{xeno_canto_id}/audio/",
        include_in_schema=False,  # Hide duplicate from docs
    )
    async def proxy_xeno_canto_audio(
        session: Session,
        ml_project_uuid: UUID,
        xeno_canto_id: str,
        start_time: float | None = Query(default=None, description="Start time in seconds"),
        end_time: float | None = Query(default=None, description="End time in seconds"),
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Proxy audio download from Xeno-Canto.

        This endpoint downloads audio from Xeno-Canto and streams it to the client.
        Used for previewing Xeno-Canto recordings before creating a reference sound.

        If start_time and/or end_time are provided, only the specified time range
        will be returned. Otherwise, the full recording is returned.

        Parameters
        ----------
        ml_project_uuid
            The ML project UUID.
        xeno_canto_id
            The Xeno-Canto recording ID (e.g., "123456" or "XC123456").
        start_time
            Start time in seconds. If None, starts from the beginning.
        end_time
            End time in seconds. If None, goes to the end of the recording.
        """
        import httpx
        from fastapi.responses import Response

        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )

        # Extract numeric ID from XC format
        xc_num = xeno_canto_id.upper()
        if xc_num.startswith("XC"):
            xc_num = xc_num[2:]

        download_url = f"https://xeno-canto.org/{xc_num}/download"

        try:
            # Download full audio from Xeno-Canto
            async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
                response = await client.get(download_url)
                if response.status_code != 200:
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Failed to download Xeno-Canto recording {xeno_canto_id}",
                    )

                audio_bytes = response.content
                content_type = response.headers.get("content-type", "audio/mpeg")

            # If time range is specified, extract the segment
            if start_time is not None or end_time is not None:
                import io
                import soundfile as sf
                import numpy as np

                # Load full audio
                with io.BytesIO(audio_bytes) as audio_buffer:
                    data, samplerate = sf.read(audio_buffer, always_2d=True)

                # Determine time range
                if start_time is None:
                    start_time = 0.0
                if end_time is None:
                    end_time = len(data) / samplerate

                # Validate time range
                if start_time < 0:
                    start_time = 0.0
                if end_time > len(data) / samplerate:
                    end_time = len(data) / samplerate
                if start_time >= end_time:
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid time range: start_time ({start_time}) must be less than end_time ({end_time})",
                    )

                # Calculate sample indices
                start_sample = int(start_time * samplerate)
                end_sample = int(end_time * samplerate)

                # Clamp to valid range
                start_sample = max(0, min(start_sample, len(data)))
                end_sample = max(start_sample, min(end_sample, len(data)))

                # Extract segment
                segment = data[start_sample:end_sample]

                # Convert back to bytes (WAV format for consistency)
                output_buffer = io.BytesIO()
                sf.write(output_buffer, segment, samplerate, format='WAV')
                audio_bytes = output_buffer.getvalue()
                content_type = "audio/wav"

            return Response(
                content=audio_bytes,
                media_type=content_type,
                headers={
                    "Content-Disposition": f'inline; filename="xc_{xeno_canto_id}.audio"',
                },
            )
        except httpx.RequestError as e:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=502,
                detail=f"Failed to connect to Xeno-Canto: {str(e)}",
            )

    @router.get(
        "/{ml_project_uuid}/reference_sounds/xeno_canto/{xeno_canto_id}/spectrogram",
        include_in_schema=True,
    )
    @router.get(
        "/{ml_project_uuid}/reference_sounds/xeno_canto/{xeno_canto_id}/spectrogram/",
        include_in_schema=False,  # Hide duplicate from docs
    )
    async def get_xeno_canto_spectrogram(
        session: Session,
        ml_project_uuid: UUID,
        xeno_canto_id: str,
        audio_parameters: Annotated[
            schemas.AudioParameters, Depends(schemas.AudioParameters)
        ],
        spectrogram_parameters: Annotated[
            schemas.SpectrogramParameters,
            Depends(schemas.SpectrogramParameters),
        ],
        start_time: float = Query(default=0.0, description="Start time in seconds"),
        end_time: float | None = Query(default=None, description="End time in seconds"),
        user: models.User | None = Depends(optional_user_dep),
    ) -> Response:
        """Get a spectrogram for a Xeno-Canto recording.

        This endpoint downloads audio from Xeno-Canto and generates a spectrogram
        for the specified time range. Used for previewing Xeno-Canto recordings
        before creating a reference sound.

        Parameters
        ----------
        ml_project_uuid
            The ML project UUID.
        xeno_canto_id
            The Xeno-Canto recording ID (e.g., "123456" or "XC123456").
        start_time
            Start time in seconds (default: 0.0).
        end_time
            End time in seconds. If None, uses the entire recording from start_time.
        audio_parameters
            Audio processing parameters (resampling, filtering).
        spectrogram_parameters
            Spectrogram generation parameters (window size, overlap, colormap, etc.).

        Returns
        -------
        Response
            Spectrogram image as PNG.
        """
        import httpx

        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )

        # Extract numeric ID from XC format
        xc_num = xeno_canto_id.upper()
        if xc_num.startswith("XC"):
            xc_num = xc_num[2:]

        download_url = f"https://xeno-canto.org/{xc_num}/download"

        try:
            # Download audio from Xeno-Canto
            async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
                response = await client.get(download_url)
                if response.status_code != 200:
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Failed to download Xeno-Canto recording {xeno_canto_id}",
                    )

                audio_bytes = response.content

            # If end_time is not specified, we need to get the audio duration
            # For simplicity, we'll use a large default value or load the full audio
            if end_time is None:
                # Load audio to get duration
                import io
                import soundfile as sf
                with io.BytesIO(audio_bytes) as audio_buffer:
                    info = sf.info(audio_buffer)
                    end_time = info.duration

            # Generate spectrogram from audio bytes
            from echoroo.api import spectrograms
            data = spectrograms.compute_spectrogram_from_bytes(
                audio_bytes,
                start_time,
                end_time,
                audio_parameters,
                spectrogram_parameters,
            )

            # Normalize if requested
            if spectrogram_parameters.normalize:
                data_min = data.min()
                data_max = data.max()
                data = data - data_min
                data_range = data_max - data_min
                if data_range > 0:
                    data = data / data_range

            # Calculate resize dimensions (default 2x for better quality)
            height, width = data.shape
            time_scale = spectrogram_parameters.time_scale
            freq_scale = spectrogram_parameters.freq_scale
            resize_dims = (int(width * time_scale), int(height * freq_scale))

            # Convert to image
            image = images.array_to_image(
                data,
                cmap=spectrogram_parameters.cmap,
                resize=resize_dims,
            )

            buffer = images.image_to_buffer(image)

            return Response(
                content=buffer.read(),
                media_type="image/png",
            )

        except httpx.RequestError as e:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=502,
                detail=f"Failed to connect to Xeno-Canto: {str(e)}",
            )

    @router.get(
        "/{ml_project_uuid}/reference_sounds/{reference_sound_uuid}",
        response_model=schemas.ReferenceSound,
    )
    async def get_reference_sound(
        session: Session,
        ml_project_uuid: UUID,
        reference_sound_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.ReferenceSound:
        """Get a specific reference sound."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        return await api.reference_sounds.get(
            session,
            reference_sound_uuid,
            user=user,
        )

    @router.patch(
        "/{ml_project_uuid}/reference_sounds/{reference_sound_uuid}",
        response_model=schemas.ReferenceSound,
    )
    async def update_reference_sound(
        session: Session,
        ml_project_uuid: UUID,
        reference_sound_uuid: UUID,
        data: schemas.ReferenceSoundUpdate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.ReferenceSound:
        """Update a reference sound."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        reference_sound = await api.reference_sounds.get(
            session,
            reference_sound_uuid,
            user=user,
        )
        updated = await api.reference_sounds.update(
            session,
            reference_sound,
            data,
            user=user,
        )
        await session.commit()
        return updated

    @router.delete(
        "/{ml_project_uuid}/reference_sounds/{reference_sound_uuid}",
        response_model=schemas.ReferenceSound,
    )
    async def delete_reference_sound(
        session: Session,
        ml_project_uuid: UUID,
        reference_sound_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.ReferenceSound:
        """Delete a reference sound."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        reference_sound = await api.reference_sounds.get(
            session,
            reference_sound_uuid,
            user=user,
        )
        deleted = await api.reference_sounds.delete(
            session,
            reference_sound,
            user=user,
        )
        await session.commit()
        return deleted

    @router.post(
        "/{ml_project_uuid}/reference_sounds/{reference_sound_uuid}/compute_embedding",
        response_model=schemas.ReferenceSound,
    )
    async def compute_reference_sound_embedding(
        session: Session,
        settings: EchorooSettings,
        ml_project_uuid: UUID,
        reference_sound_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.ReferenceSound:
        """Recompute the embedding for a reference sound.

        This endpoint loads audio from the source (Xeno-Canto, dataset clip,
        or custom upload), extracts the segment defined by start_time/end_time,
        runs the Perch model to generate a 1536-dimensional embedding, and
        stores the result.

        For segments longer than 5 seconds, the audio is split into 5-second
        segments and the embeddings are averaged.
        """
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        reference_sound = await api.reference_sounds.get(
            session,
            reference_sound_uuid,
            user=user,
        )
        updated = await api.reference_sounds.compute_embedding(
            session,
            reference_sound,
            user=user,
            audio_dir=settings.audio_dir,
        )
        await session.commit()
        return updated

    @router.get(
        "/{ml_project_uuid}/reference_sounds/{reference_sound_uuid}/audio",
    )
    async def get_reference_sound_audio(
        session: Session,
        settings: EchorooSettings,
        ml_project_uuid: UUID,
        reference_sound_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Stream audio for a reference sound.

        For Xeno-Canto sources, this proxies the audio download from xeno-canto.org.
        For dataset clips and custom uploads, this serves the local audio file.

        Returns the audio with the appropriate content-type header.
        """
        from fastapi.responses import Response

        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        reference_sound = await api.reference_sounds.get(
            session,
            reference_sound_uuid,
            user=user,
        )
        audio_bytes, content_type = await api.reference_sounds.get_audio_bytes(
            session,
            reference_sound,
            user=user,
            audio_dir=settings.audio_dir,
        )
        return Response(
            content=audio_bytes,
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="reference_sound_{reference_sound_uuid}.audio"',
            },
        )

    # =========================================================================
    # Search Sessions
    # =========================================================================

    @router.get(
        "/{ml_project_uuid}/search_sessions",
        response_model=schemas.Page[schemas.SearchSession],
    )
    async def get_search_sessions(
        session: Session,
        ml_project_uuid: UUID,
        limit: Limit = 10,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.SearchSession]:
        """Get all search sessions for an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        sessions, total = await api.search_sessions.get_many(
            session,
            ml_project.id,
            limit=limit,
            offset=offset,
            user=user,
        )
        return schemas.Page(
            items=sessions,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/{ml_project_uuid}/search_sessions",
        response_model=schemas.SearchSession,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_search_session(
        session: Session,
        ml_project_uuid: UUID,
        data: schemas.SearchSessionCreate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.SearchSession:
        """Create a new search session."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        search_session = await api.search_sessions.create(
            session,
            ml_project.id,
            data,
            user=user,
        )
        await session.commit()
        return search_session

    @router.get(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}",
        response_model=schemas.SearchSession,
    )
    async def get_search_session(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.SearchSession:
        """Get a specific search session."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        return await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )

    @router.delete(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}",
        response_model=schemas.SearchSession,
    )
    async def delete_search_session(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.SearchSession:
        """Delete a search session."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        search_session = await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )
        deleted = await api.search_sessions.delete(
            session,
            search_session,
            user=user,
        )
        await session.commit()
        return deleted

    @router.post(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}/execute",
        response_model=schemas.SearchSession,
    )
    async def execute_search_session(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.SearchSession:
        """Execute initial sampling for a search session.

        Performs Active Learning initial sampling:
        - Easy Positives: Top-k most similar clips per reference
        - Boundary: Random samples from medium similarity range
        - Others: Diverse samples using farthest-first selection
        """
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        search_session = await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )
        updated = await api.search_sessions.execute_initial_sampling(
            session,
            search_session,
            user=user,
        )
        await session.commit()
        return updated

    @router.post(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}/run_iteration",
        response_model=schemas.SearchSession,
    )
    async def run_active_learning_iteration(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        request: schemas.RunIterationRequest = schemas.RunIterationRequest(),
        user: models.User = Depends(current_user_dep),
    ) -> schemas.SearchSession:
        """Run one iteration of active learning.

        Trains classifiers on labeled data and selects new samples
        from the uncertainty region.
        """
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        search_session = await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )
        updated = await api.search_sessions.run_iteration(
            session,
            search_session,
            uncertainty_low=request.uncertainty_low,
            uncertainty_high=request.uncertainty_high,
            samples_per_iteration=request.samples_per_iteration,
            selected_tag_ids=request.selected_tag_ids,
            user=user,
        )
        await session.commit()
        return updated

    @router.get(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}/results",
        response_model=schemas.Page[schemas.SearchResult],
    )
    async def get_search_results(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        limit: Limit = 10,
        offset: Offset = 0,
        assigned_tag_id: int | None = Query(
            default=None, description="Filter by assigned tag ID (frontend sends assigned_tag_id)"
        ),
        is_negative: bool | None = Query(
            default=None, description="Filter by negative label (frontend sends is_negative)"
        ),
        is_uncertain: bool | None = Query(
            default=None, description="Filter by uncertain label (frontend sends is_uncertain)"
        ),
        is_skipped: bool | None = Query(
            default=None, description="Filter by skipped label (frontend sends is_skipped)"
        ),
        is_labeled: bool | None = Query(
            default=None, description="Filter by labeled status (frontend sends is_labeled)"
        ),
        sample_type: str | None = Query(
            default=None, description="Filter by sample type (frontend sends sample_type)"
        ),
        iteration_added: int | None = Query(
            default=None, description="Filter by iteration number (frontend sends iteration_added)"
        ),
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.SearchResult]:
        """Get paginated search results for a session.

        Filters can be combined to narrow down results. If no filters
        are specified, all results are returned.
        """
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        search_session = await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )

        # Build filters based on query parameters
        filters = []

        if is_labeled is not None:
            if is_labeled:
                # Labeled = has any label
                from sqlalchemy import or_
                filters.append(
                    or_(
                        models.SearchResult.assigned_tag_id.isnot(None),
                        models.SearchResult.is_negative == True,
                        models.SearchResult.is_uncertain == True,
                        models.SearchResult.is_skipped == True,
                    )
                )
            else:
                # Unlabeled = no assigned_tag AND not negative AND not uncertain AND not skipped
                filters.append(models.SearchResult.assigned_tag_id.is_(None))
                filters.append(models.SearchResult.is_negative == False)
                filters.append(models.SearchResult.is_uncertain == False)
                filters.append(models.SearchResult.is_skipped == False)

        if is_negative is not None:
            filters.append(models.SearchResult.is_negative == is_negative)

        if is_uncertain is not None:
            filters.append(models.SearchResult.is_uncertain == is_uncertain)

        if is_skipped is not None:
            filters.append(models.SearchResult.is_skipped == is_skipped)

        if assigned_tag_id is not None:
            filters.append(models.SearchResult.assigned_tag_id == assigned_tag_id)

        if sample_type is not None:
            filters.append(models.SearchResult.sample_type == sample_type)

        if iteration_added is not None:
            filters.append(models.SearchResult.iteration_added == iteration_added)

        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Getting search results for session {search_session.id}, limit={limit}, offset={offset}")

        results, total = await api.search_sessions.get_search_results(
            session,
            search_session.id,
            limit=limit,
            offset=offset,
            filters=filters if filters else None,
            user=user,
        )
        logger.info(f"Got {len(results)} results, total={total}")
        return schemas.Page(
            items=results,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}/progress",
        response_model=schemas.SearchProgress,
    )
    async def get_search_progress(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.SearchProgress:
        """Get labeling progress for a search session."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        search_session = await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )
        return await api.search_sessions.get_search_progress(
            session,
            search_session.id,
            user=user,
        )

    @router.post(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}/results/{result_uuid}/label",
        response_model=schemas.SearchResult,
    )
    async def label_search_result(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        result_uuid: UUID,
        data: schemas.SearchResultLabelData,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.SearchResult:
        """Label a search result with Active Learning label data.

        A result can be labeled in one of several ways:
        - assigned_tag_id: Assign a specific tag (positive label)
        - is_negative: Mark as not containing any target sound
        - is_uncertain: Mark as uncertain/needs review
        - is_skipped: Skip without labeling
        """
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        # Verify session exists
        await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )
        updated = await api.search_sessions.label_result(
            session,
            result_uuid,
            data,
            user=user,
        )
        await session.commit()
        return updated

    @router.post(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}/bulk_label",
        response_model=dict,
    )
    async def bulk_label_search_results(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        data: schemas.BulkLabelRequest,
        user: models.User = Depends(current_user_dep),
    ) -> dict:
        """Bulk label multiple search results with Active Learning labels."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        # Verify session exists
        await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )
        count = await api.search_sessions.bulk_label_results(
            session,
            data.result_uuids,
            data.label_data,
            user=user,
        )
        await session.commit()
        return {"updated_count": count}

    # =========================================================================
    # Custom Models
    # =========================================================================

    @router.get(
        "/{ml_project_uuid}/custom_models",
        response_model=schemas.Page[schemas.CustomModel],
    )
    async def get_custom_models(
        session: Session,
        ml_project_uuid: UUID,
        limit: Limit = 10,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.CustomModel]:
        """Get all custom models for an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        models_list, total = await api.custom_models.get_many(
            session,
            ml_project,
            limit=limit,
            offset=offset,
            user=user,
        )
        return schemas.Page(
            items=models_list,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/{ml_project_uuid}/custom_models",
        response_model=schemas.CustomModel,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_custom_model(
        session: Session,
        ml_project_uuid: UUID,
        data: schemas.CustomModelCreate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.CustomModel:
        """Create a new custom model configuration."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        custom_model = await api.custom_models.create(
            session,
            ml_project,
            name=data.name,
            description=data.description,
            tag_id=data.tag_id,
            search_session_ids=data.search_session_ids or [],
            annotation_project_uuids=data.annotation_project_uuids or [],
            training_config=data.training_config,
            user=user,
        )
        await session.commit()
        return custom_model

    @router.get(
        "/{ml_project_uuid}/custom_models/{custom_model_uuid}",
        response_model=schemas.CustomModel,
    )
    async def get_custom_model(
        session: Session,
        ml_project_uuid: UUID,
        custom_model_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.CustomModel:
        """Get a specific custom model."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        return await api.custom_models.get(
            session,
            custom_model_uuid,
            user=user,
        )

    @router.delete(
        "/{ml_project_uuid}/custom_models/{custom_model_uuid}",
        response_model=schemas.CustomModel,
    )
    async def delete_custom_model(
        session: Session,
        ml_project_uuid: UUID,
        custom_model_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.CustomModel:
        """Delete a custom model."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        custom_model = await api.custom_models.get(
            session,
            custom_model_uuid,
            user=user,
        )
        deleted = await api.custom_models.delete(
            session,
            custom_model,
            user=user,
        )
        await session.commit()
        return deleted

    @router.post(
        "/{ml_project_uuid}/custom_models/{custom_model_uuid}/train",
        response_model=schemas.CustomModel,
    )
    async def start_training(
        session: Session,
        settings: EchorooSettings,
        ml_project_uuid: UUID,
        custom_model_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.CustomModel:
        """Start training a custom model."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        custom_model = await api.custom_models.get(
            session,
            custom_model_uuid,
            user=user,
        )
        updated = await api.custom_models.start_training(
            session,
            custom_model,
            ml_project,
            audio_dir=str(settings.audio_dir),
            user=user,
        )
        await session.commit()
        return updated

    @router.get(
        "/{ml_project_uuid}/custom_models/{custom_model_uuid}/status",
        response_model=schemas.TrainingProgress,
    )
    async def get_training_status(
        session: Session,
        ml_project_uuid: UUID,
        custom_model_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.TrainingProgress:
        """Get the training status of a custom model."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        custom_model = await api.custom_models.get(
            session,
            custom_model_uuid,
            user=user,
        )
        return await api.custom_models.get_training_status(
            session,
            custom_model,
            user=user,
        )

    # =========================================================================
    # Dataset Scopes (Multi-Dataset Support)
    # =========================================================================

    @router.get(
        "/{ml_project_uuid}/dataset_scopes",
        response_model=list[schemas.MLProjectDatasetScope],
    )
    async def get_dataset_scopes(
        session: Session,
        ml_project_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> list[schemas.MLProjectDatasetScope]:
        """Get all dataset scopes for an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        return await api.ml_projects.get_dataset_scopes(
            session,
            ml_project,
            user=user,
        )

    @router.post(
        "/{ml_project_uuid}/dataset_scopes",
        response_model=schemas.MLProjectDatasetScope,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_dataset_scope(
        session: Session,
        ml_project_uuid: UUID,
        data: schemas.MLProjectDatasetScopeCreate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.MLProjectDatasetScope:
        """Add a dataset scope to an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )

        # Get the dataset by UUID
        dataset = await api.datasets.get(
            session,
            data.dataset_uuid,
            user=user,
        )

        # Get the foundation model run by UUID
        foundation_model_run = await api.foundation_models.get_run_with_relations(
            session,
            data.foundation_model_run_uuid,
        )

        scope = await api.ml_projects.add_dataset_scope(
            session,
            ml_project,
            dataset,
            foundation_model_run,
            user=user,
        )
        await session.commit()
        return scope

    @router.get(
        "/{ml_project_uuid}/dataset_scopes/{scope_uuid}",
        response_model=schemas.MLProjectDatasetScope,
    )
    async def get_dataset_scope(
        session: Session,
        ml_project_uuid: UUID,
        scope_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.MLProjectDatasetScope:
        """Get a specific dataset scope."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        return await api.ml_projects.get_dataset_scope(
            session,
            ml_project,
            scope_uuid,
            user=user,
        )

    @router.delete(
        "/{ml_project_uuid}/dataset_scopes/{scope_uuid}",
        response_model=schemas.MLProjectDatasetScope,
    )
    async def remove_dataset_scope(
        session: Session,
        ml_project_uuid: UUID,
        scope_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.MLProjectDatasetScope:
        """Remove a dataset scope from an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        removed = await api.ml_projects.remove_dataset_scope(
            session,
            ml_project,
            scope_uuid,
            user=user,
        )
        await session.commit()
        return removed

    # =========================================================================
    # Inference Batches
    # =========================================================================

    @router.get(
        "/{ml_project_uuid}/inference_batches",
        response_model=schemas.Page[schemas.InferenceBatch],
    )
    async def get_inference_batches(
        session: Session,
        ml_project_uuid: UUID,
        limit: Limit = 10,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.InferenceBatch]:
        """Get all inference batches for an ML project."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        batches, total = await api.inference_batches.get_many(
            session,
            ml_project,
            limit=limit,
            offset=offset,
            user=user,
        )
        return schemas.Page(
            items=batches,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/{ml_project_uuid}/inference_batches",
        response_model=schemas.InferenceBatch,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_inference_batch(
        session: Session,
        ml_project_uuid: UUID,
        data: schemas.InferenceBatchCreate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.InferenceBatch:
        """Create a new inference batch."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        batch = await api.inference_batches.create(
            session,
            ml_project,
            name=data.name,
            custom_model_id=data.custom_model_id,
            confidence_threshold=data.confidence_threshold,
            clip_ids=data.clip_ids,
            include_all_clips=data.include_all_clips,
            exclude_already_labeled=data.exclude_already_labeled,
            notes=data.notes,
            user=user,
        )
        await session.commit()
        return batch

    @router.get(
        "/{ml_project_uuid}/inference_batches/{inference_batch_uuid}",
        response_model=schemas.InferenceBatch,
    )
    async def get_inference_batch(
        session: Session,
        ml_project_uuid: UUID,
        inference_batch_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.InferenceBatch:
        """Get a specific inference batch."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        return await api.inference_batches.get(
            session,
            inference_batch_uuid,
            user=user,
        )

    @router.delete(
        "/{ml_project_uuid}/inference_batches/{inference_batch_uuid}",
        response_model=schemas.InferenceBatch,
    )
    async def delete_inference_batch(
        session: Session,
        ml_project_uuid: UUID,
        inference_batch_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.InferenceBatch:
        """Delete an inference batch."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        batch = await api.inference_batches.get(
            session,
            inference_batch_uuid,
            user=user,
        )
        deleted = await api.inference_batches.delete(
            session,
            batch,
            user=user,
        )
        await session.commit()
        return deleted

    @router.post(
        "/{ml_project_uuid}/inference_batches/{inference_batch_uuid}/start",
        response_model=schemas.InferenceBatch,
    )
    async def start_inference(
        session: Session,
        settings: EchorooSettings,
        ml_project_uuid: UUID,
        inference_batch_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.InferenceBatch:
        """Start running inference for a batch."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        batch = await api.inference_batches.get(
            session,
            inference_batch_uuid,
            user=user,
        )
        updated = await api.inference_batches.start(
            session,
            batch,
            ml_project,
            audio_dir=str(settings.audio_dir),
            user=user,
        )
        await session.commit()
        return updated

    @router.get(
        "/{ml_project_uuid}/inference_batches/{inference_batch_uuid}/predictions",
        response_model=schemas.Page[schemas.InferencePrediction],
    )
    async def get_predictions(
        session: Session,
        ml_project_uuid: UUID,
        inference_batch_uuid: UUID,
        limit: Limit = 10,
        offset: Offset = 0,
        review_status: schemas.InferencePredictionReviewStatus | None = None,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.InferencePrediction]:
        """Get paginated predictions for an inference batch."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        batch = await api.inference_batches.get(
            session,
            inference_batch_uuid,
            user=user,
        )
        predictions, total = await api.inference_batches.get_predictions(
            session,
            batch,
            limit=limit,
            offset=offset,
            review_status=review_status,
            user=user,
        )
        return schemas.Page(
            items=predictions,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/{ml_project_uuid}/inference_batches/{inference_batch_uuid}/predictions/{prediction_uuid}/review",
        response_model=schemas.InferencePrediction,
    )
    async def review_prediction(
        session: Session,
        ml_project_uuid: UUID,
        inference_batch_uuid: UUID,
        prediction_uuid: UUID,
        data: schemas.InferencePredictionReview,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.InferencePrediction:
        """Review an inference prediction."""
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        # Verify batch exists
        await api.inference_batches.get(
            session,
            inference_batch_uuid,
            user=user,
        )
        prediction = await api.inference_batches.get_prediction(
            session,
            prediction_uuid,
            user=user,
        )
        updated = await api.inference_batches.review_prediction(
            session,
            prediction,
            review_status=data.review_status,
            notes=data.notes,
            user=user,
        )
        await session.commit()
        return updated

    # =========================================================================
    # Search Session Curation & Export
    # =========================================================================

    @router.post(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}/bulk_curate",
        response_model=list[schemas.SearchResult],
    )
    async def bulk_curate_search_results(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        data: schemas.BulkCurateRequest,
        user: models.User = Depends(current_user_dep),
    ) -> list[schemas.SearchResult]:
        """Bulk curate search results by assigning a tag.

        This endpoint allows selecting high-quality examples and
        assigning a specific tag to all of them.
        """
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        search_session = await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )
        curated = await api.search_sessions.bulk_curate(
            session,
            search_session,
            data.result_uuids,
            data.assigned_tag_id,
            user=user,
        )
        await session.commit()
        return curated

    @router.post(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}/export_to_annotation_project",
        response_model=schemas.ExportToAnnotationProjectResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def export_to_annotation_project(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        data: schemas.ExportToAnnotationProjectRequest,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.ExportToAnnotationProjectResponse:
        """Export labeled search results to a new annotation project.

        Creates a new annotation project and annotation tasks for clips
        with assigned tags. Can optionally filter to specific tag IDs.
        """
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        search_session = await api.search_sessions.get(
            session,
            search_session_uuid,
            user=user,
        )
        result = await api.search_sessions.export_to_annotation_project(
            session,
            search_session,
            name=data.name,
            description=data.description,
            include_labeled=data.include_labeled,
            include_tag_ids=data.include_tag_ids,
            user=user,
        )
        await session.commit()
        return result

    @router.get(
        "/{ml_project_uuid}/annotation_projects",
        response_model=list[schemas.AnnotationProject],
    )
    async def get_ml_project_annotation_projects(
        session: Session,
        ml_project_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> list[schemas.AnnotationProject]:
        """Get annotation projects created from this ML project's search sessions."""
        ml_project = await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        return await api.search_sessions.get_annotation_projects(
            session,
            ml_project.id,
            user=user,
        )

    @router.get(
        "/{ml_project_uuid}/search_sessions/{search_session_uuid}/score_distribution",
        response_model=schemas.ScoreDistributionResponse,
    )
    async def get_score_distribution(
        session: Session,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.ScoreDistributionResponse:
        """Get saved score distributions for active learning visualization.

        Returns the score distributions computed during each iteration,
        showing how the model's predictions are distributed across the
        dataset for each target tag.
        """
        # Verify project access
        await api.ml_projects.get(
            session,
            ml_project_uuid,
            user=user,
        )
        return await api.search_sessions.get_score_distribution(
            session,
            ml_project_uuid,
            search_session_uuid,
            user=user,
        )

    return router
