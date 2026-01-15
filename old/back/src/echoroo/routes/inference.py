"""REST API routes for inference jobs and embeddings."""

import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from echoroo import api, schemas
from echoroo.filters.inference_jobs import InferenceJobFilter
from echoroo.routes.dependencies import Session
from echoroo.routes.types import Limit, Offset

__all__ = [
    "inference_router",
]


inference_router = APIRouter()


# ============================================
# Inference Jobs
# ============================================


@inference_router.get(
    "/jobs/",
    response_model=schemas.Page[schemas.InferenceJob],
)
async def get_inference_jobs(
    session: Session,
    filter: Annotated[
        InferenceJobFilter,  # type: ignore
        Depends(InferenceJobFilter),
    ],
    limit: Limit = 100,
    offset: Offset = 0,
) -> schemas.Page[schemas.InferenceJob]:
    """Get list of inference jobs."""
    jobs, total = await api.inference_jobs.get_many(
        session,
        limit=limit,
        offset=offset,
        filters=[filter],
    )
    return schemas.Page(
        items=jobs,
        total=total,
        offset=offset,
        limit=limit,
    )


@inference_router.post(
    "/jobs/",
    response_model=schemas.InferenceJob,
)
async def create_inference_job(
    session: Session,
    data: schemas.InferenceJobCreate,
) -> schemas.InferenceJob:
    """Create a new inference job.

    Either dataset_uuid or recording_uuid must be provided, but not both.
    """
    if data.dataset_uuid is None and data.recording_uuid is None:
        raise HTTPException(
            status_code=400,
            detail="Either dataset_uuid or recording_uuid must be provided.",
        )

    if data.dataset_uuid is not None and data.recording_uuid is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot specify both dataset_uuid and recording_uuid.",
        )

    # Resolve dataset and recording IDs
    dataset_id = None
    recording_id = None
    total_items = 0

    if data.dataset_uuid is not None:
        dataset = await api.datasets.get(session, data.dataset_uuid)
        dataset_id = dataset.id
        # Get recording count for the dataset
        recordings, count = await api.recordings.get_many(
            session,
            filters=[],  # TODO: Add dataset filter
            limit=0,
        )
        total_items = count

    if data.recording_uuid is not None:
        recording = await api.recordings.get(session, data.recording_uuid)
        recording_id = recording.id
        total_items = 1

    # Create the inference job
    job = await api.inference_jobs.create(
        session,
        data,
        dataset_id=dataset_id,
        recording_id=recording_id,
    )

    # Update total items
    if total_items > 0:
        job = await api.inference_jobs.update(
            session,
            job,
            schemas.InferenceJobUpdate(progress=0.0),
        )
        # Update total_items directly since it's not in the update schema
        from echoroo.api.common import update_object
        from echoroo import models
        await update_object(
            session,
            models.InferenceJob,
            models.InferenceJob.uuid == job.uuid,
            total_items=total_items,
        )
        # Refresh the job
        job = await api.inference_jobs.get(session, job.uuid)

    await session.commit()
    return job


@inference_router.get(
    "/jobs/detail/",
    response_model=schemas.InferenceJob,
)
async def get_inference_job(
    session: Session,
    inference_job_uuid: UUID,
) -> schemas.InferenceJob:
    """Get inference job details."""
    return await api.inference_jobs.get(session, inference_job_uuid)


@inference_router.patch(
    "/jobs/detail/",
    response_model=schemas.InferenceJob,
)
async def update_inference_job(
    session: Session,
    inference_job_uuid: UUID,
    data: schemas.InferenceJobUpdate,
) -> schemas.InferenceJob:
    """Update an inference job."""
    job = await api.inference_jobs.get(session, inference_job_uuid)
    job = await api.inference_jobs.update(session, job, data)
    await session.commit()
    return job


@inference_router.delete(
    "/jobs/detail/",
    response_model=schemas.InferenceJob,
)
async def cancel_inference_job(
    session: Session,
    inference_job_uuid: UUID,
) -> schemas.InferenceJob:
    """Cancel an inference job.

    Only jobs with status 'pending' or 'running' can be cancelled.
    """
    job = await api.inference_jobs.get(session, inference_job_uuid)

    try:
        job = await api.inference_jobs.cancel(session, job)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await session.commit()
    return job


# ============================================
# Embeddings Search
# ============================================


@inference_router.post(
    "/embeddings/search/",
    response_model=schemas.EmbeddingSearchResponse,
)
async def search_similar_embeddings(
    session: Session,
    request: schemas.EmbeddingSearchRequest,
) -> schemas.EmbeddingSearchResponse:
    """Search for similar clips/sound events by embedding.

    You can search by providing:
    - A raw embedding vector
    - A clip_uuid (uses that clip's embedding)
    - A sound_event_uuid (uses that sound event's embedding)
    """
    embedding = request.embedding
    query_embedding = None

    # Get embedding from clip if specified
    if request.clip_uuid is not None:
        clip_embedding = await api.clip_embeddings.get_by_clip_and_model_run(
            session,
            request.clip_uuid,
            # We need to find the model run by name
            # For now, search for any embedding of this clip
        )
        if clip_embedding is None:
            raise HTTPException(
                status_code=404,
                detail=f"No embedding found for clip {request.clip_uuid}",
            )
        embedding = clip_embedding.embedding
        query_embedding = embedding

    # Get embedding from sound event if specified
    if request.sound_event_uuid is not None:
        sound_event_embedding = (
            await api.sound_event_embeddings.get_by_sound_event_and_model_run(
                session,
                request.sound_event_uuid,
                # Same issue as above
            )
        )
        if sound_event_embedding is None:
            raise HTTPException(
                status_code=404,
                detail=f"No embedding found for sound event {request.sound_event_uuid}",
            )
        embedding = sound_event_embedding.embedding
        query_embedding = embedding

    if embedding is None:
        raise HTTPException(
            status_code=400,
            detail="Must provide embedding, clip_uuid, or sound_event_uuid",
        )

    # Search for similar clips
    results = await api.search_similar_clips(
        session,
        embedding=embedding,
        model_name=request.model_name,
        limit=request.limit,
        min_similarity=request.min_similarity,
    )

    return schemas.EmbeddingSearchResponse(
        results=list(results),
        query_embedding=query_embedding,
    )


@inference_router.get(
    "/embeddings/clips/",
    response_model=schemas.Page[schemas.ClipEmbedding],
)
async def get_clip_embeddings(
    session: Session,
    clip_uuid: UUID | None = None,
    model_run_uuid: UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> schemas.Page[schemas.ClipEmbedding]:
    """Get clip embeddings with optional filters."""
    from echoroo import models

    filters = []

    if clip_uuid is not None:
        filters.append(models.Clip.uuid == clip_uuid)

    if model_run_uuid is not None:
        filters.append(models.ModelRun.uuid == model_run_uuid)

    embeddings, total = await api.clip_embeddings.get_many(
        session,
        limit=limit,
        offset=offset,
        filters=filters if filters else None,
    )

    return schemas.Page(
        items=embeddings,
        total=total,
        offset=offset,
        limit=limit,
    )


@inference_router.get(
    "/embeddings/sound_events/",
    response_model=schemas.Page[schemas.SoundEventEmbedding],
)
async def get_sound_event_embeddings(
    session: Session,
    sound_event_uuid: UUID | None = None,
    model_run_uuid: UUID | None = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> schemas.Page[schemas.SoundEventEmbedding]:
    """Get sound event embeddings with optional filters."""
    from echoroo import models

    filters = []

    if sound_event_uuid is not None:
        filters.append(models.SoundEvent.uuid == sound_event_uuid)

    if model_run_uuid is not None:
        filters.append(models.ModelRun.uuid == model_run_uuid)

    embeddings, total = await api.sound_event_embeddings.get_many(
        session,
        limit=limit,
        offset=offset,
        filters=filters if filters else None,
    )

    return schemas.Page(
        items=embeddings,
        total=total,
        offset=offset,
        limit=limit,
    )


# ============================================
# Advanced Search Endpoints
# ============================================


@inference_router.post(
    "/embeddings/search/advanced/",
    response_model=schemas.AdvancedSearchResponse,
)
async def advanced_embedding_search(
    session: Session,
    request: schemas.AdvancedSearchRequest,
) -> schemas.AdvancedSearchResponse:
    """Advanced search for similar clips with filters.

    Search for similar clips/sound events by embedding with additional
    filtering options for datasets and recordings.

    You can search by providing:
    - A raw embedding vector
    - A clip_uuid (uses that clip's embedding)

    Optionally filter results by:
    - dataset_uuids: Only include clips from these datasets
    - recording_uuids: Only include clips from these recordings
    """
    start_time = time.perf_counter()
    embedding = request.embedding

    # Get embedding from clip if specified
    if request.clip_uuid is not None:
        clip_embedding = await api.clip_embeddings.get_by_clip_and_model_run(
            session,
            request.clip_uuid,
        )
        if clip_embedding is None:
            raise HTTPException(
                status_code=404,
                detail=f"No embedding found for clip {request.clip_uuid}",
            )
        embedding = clip_embedding.embedding

    if embedding is None:
        raise HTTPException(
            status_code=400,
            detail="Must provide embedding or clip_uuid",
        )

    # Perform advanced search with filters
    results, total_searched = await api.search_similar_clips_advanced(
        session,
        embedding=embedding,
        model_name=request.model_name,
        dataset_uuids=request.dataset_uuids,
        recording_uuids=request.recording_uuids,
        limit=request.limit,
        min_similarity=request.min_similarity,
    )

    query_time_ms = (time.perf_counter() - start_time) * 1000

    return schemas.AdvancedSearchResponse(
        results=results,
        total_searched=total_searched,
        query_time_ms=query_time_ms,
    )


@inference_router.post(
    "/embeddings/search/by-clip/",
    response_model=schemas.AdvancedSearchResponse,
)
async def search_by_clip(
    session: Session,
    clip_uuid: UUID,
    model_name: str,
    limit: int = Query(default=20, ge=1, le=100),
    min_similarity: float = Query(default=0.7, ge=0.0, le=1.0),
    dataset_uuids: list[UUID] | None = Query(default=None),
) -> schemas.AdvancedSearchResponse:
    """Search for similar clips using an existing clip's embedding.

    This is a convenience endpoint that finds clips similar to a given clip.
    It uses the clip's embedding from the specified model to perform the search.

    Parameters
    ----------
    clip_uuid
        UUID of the clip to use as the query.
    model_name
        Name of the model whose embeddings to search.
    limit
        Maximum number of results to return (1-100).
    min_similarity
        Minimum cosine similarity threshold (0.0-1.0).
    dataset_uuids
        Optional list of dataset UUIDs to filter results.
    """
    start_time = time.perf_counter()

    # Get the clip's embedding
    clip_embedding = await api.clip_embeddings.get_by_clip_and_model_run(
        session,
        clip_uuid,
    )
    if clip_embedding is None:
        raise HTTPException(
            status_code=404,
            detail=f"No embedding found for clip {clip_uuid}",
        )

    # Perform search
    results, total_searched = await api.search_similar_clips_advanced(
        session,
        embedding=clip_embedding.embedding,
        model_name=model_name,
        dataset_uuids=dataset_uuids,
        limit=limit,
        min_similarity=min_similarity,
    )

    query_time_ms = (time.perf_counter() - start_time) * 1000

    return schemas.AdvancedSearchResponse(
        results=results,
        total_searched=total_searched,
        query_time_ms=query_time_ms,
    )


@inference_router.get(
    "/embeddings/search/random/",
    response_model=schemas.RandomClipsResponse,
)
async def get_random_clips(
    session: Session,
    model_name: str,
    limit: int = Query(default=10, ge=1, le=50),
    dataset_uuids: list[UUID] | None = Query(default=None),
) -> schemas.RandomClipsResponse:
    """Get random clips with embeddings for exploration.

    This endpoint returns random clips that have embeddings for a given model.
    Useful for:
    - Initial exploration of the embedding space
    - Finding seed clips for similarity search
    - Random sampling for quality checks

    Parameters
    ----------
    model_name
        Name of the model whose embeddings to sample from.
    limit
        Number of random clips to return (1-50).
    dataset_uuids
        Optional list of dataset UUIDs to filter results.
    """
    clips, total_available = await api.get_random_clips_with_embeddings(
        session,
        model_name=model_name,
        dataset_uuids=dataset_uuids,
        limit=limit,
    )

    return schemas.RandomClipsResponse(
        clips=clips,
        total_available=total_available,
    )
