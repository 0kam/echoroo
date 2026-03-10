"""Similarity search API endpoints.

Provides vector similarity search over stored embeddings using pgvector.
All endpoints are scoped to a project_id for data isolation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.project import ProjectRepository
from echoroo.schemas.search import (
    BatchSearchRequest,
    BatchSearchResponse,
    EmbeddingStatsResponse,
    SimilaritySearchRequest,
    SimilaritySearchResponse,
)
from echoroo.services.search import SimilaritySearchService

router = APIRouter(prefix="/projects/{project_id}/search", tags=["search"])

# Upload size and type limits for audio search queries
MAX_AUDIO_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".opus"}


async def check_project_access(project_id: UUID, user_id: UUID, db: DbSession) -> None:
    """Verify that the current user has access to the given project.

    Args:
        project_id: Project UUID to check access for
        user_id: Current user's UUID
        db: Database session

    Raises:
        HTTPException: 403 if the user does not have access to the project
    """
    project_repo = ProjectRepository(db)
    has_access = await project_repo.has_project_access(project_id, user_id)
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to project",
        )


def get_search_service(db: DbSession) -> SimilaritySearchService:
    """Get SimilaritySearchService instance.

    Args:
        db: Database session

    Returns:
        SimilaritySearchService instance
    """
    return SimilaritySearchService(db)


SearchServiceDep = Annotated[SimilaritySearchService, Depends(get_search_service)]


@router.post(
    "/similar",
    response_model=SimilaritySearchResponse,
    summary="Search by embedding ID",
    description=(
        "Find audio segments similar to an existing stored embedding. "
        "Uses pgvector cosine similarity, scoped to the project."
    ),
)
async def search_similar(
    project_id: UUID,
    request: SimilaritySearchRequest,
    current_user: CurrentUser,
    service: SearchServiceDep,
    db: DbSession,
) -> SimilaritySearchResponse:
    """Search for similar audio segments using an existing embedding.

    Retrieves the embedding vector for the given embedding_id, then finds
    the nearest neighbours in the project's embedding space.

    Args:
        project_id: Project UUID (path parameter)
        request: Search parameters including embedding_id and filters
        current_user: Current authenticated user
        service: Search service instance
        db: Database session

    Returns:
        Similarity search response ordered by descending similarity

    Raises:
        401: Not authenticated
        403: Access denied to project
        404: Embedding not found in project
    """
    await check_project_access(project_id, current_user.id, db)
    try:
        return await service.search_by_embedding_id(
            project_id=project_id,
            embedding_id=request.embedding_id,
            model_name=request.model_name,
            limit=request.limit,
            min_similarity=request.min_similarity,
            dataset_id=request.dataset_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/similar-by-audio",
    response_model=SimilaritySearchResponse,
    summary="Search by uploaded audio",
    description=(
        "Upload a short audio clip, generate its embedding with the specified model, "
        "and find similar sounds across the project."
    ),
)
async def search_similar_by_audio(
    project_id: UUID,
    current_user: CurrentUser,
    service: SearchServiceDep,
    db: DbSession,
    audio_file: UploadFile = File(..., description="Audio file to use as search query"),
    model_name: str = Form(default="perch", description="Model to generate the embedding"),
    limit: int = Form(default=20, ge=1, le=100, description="Maximum results"),
    min_similarity: float = Form(
        default=0.5, ge=0.0, le=1.0, description="Minimum similarity threshold"
    ),
    dataset_id: UUID | None = Form(default=None, description="Optional dataset filter"),
) -> SimilaritySearchResponse:
    """Search for similar audio segments by uploading an audio clip.

    Saves the uploaded file to a temporary location, generates an embedding
    using the requested model, performs a similarity search, then cleans up
    the temporary file.

    Args:
        project_id: Project UUID (path parameter)
        current_user: Current authenticated user
        service: Search service instance
        db: Database session
        audio_file: Uploaded audio file
        model_name: Model name for embedding generation
        limit: Maximum number of results
        min_similarity: Minimum cosine similarity threshold
        dataset_id: Optional dataset filter

    Returns:
        Similarity search response ordered by descending similarity

    Raises:
        400: Unsupported file type
        401: Not authenticated
        403: Access denied to project
        413: File too large (max 50 MB)
        422: Model not registered or invalid parameters
    """
    await check_project_access(project_id, current_user.id, db)

    # Read and validate upload before writing to disk
    content = await audio_file.read()

    if len(content) > MAX_AUDIO_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 50 MB)",
        )

    suffix = Path(audio_file.filename or "upload.wav").suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {suffix}. Allowed: {sorted(ALLOWED_AUDIO_EXTENSIONS)}",
        )

    # Write validated upload to a temporary file for inference
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write(content)

    try:
        return await service.search_by_audio_file(
            project_id=project_id,
            audio_path=tmp_path,
            model_name=model_name,
            limit=limit,
            min_similarity=min_similarity,
            dataset_id=dataset_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    finally:
        # Always remove the temporary file
        import contextlib
        import os

        with contextlib.suppress(OSError):
            os.unlink(tmp_path)


@router.post(
    "/batch",
    response_model=BatchSearchResponse,
    summary="Batch species search by uploaded audio",
    description=(
        "Upload reference audio clips for multiple species and find similar sounds "
        "across the project simultaneously. "
        "Send as multipart/form-data with a 'metadata' JSON field and audio files "
        "named source_0, source_1, etc. Supports up to 20 species and 10 sources each."
    ),
)
async def batch_search(
    project_id: UUID,
    current_user: CurrentUser,
    service: SearchServiceDep,
    db: DbSession,
    request: Request,
    metadata: str = Form(
        ...,
        description="JSON string of BatchSearchRequest",
    ),
) -> BatchSearchResponse:
    """Search for multiple species simultaneously using reference audio clips.

    Accepts multipart/form-data where:
    - ``metadata`` is a JSON-encoded BatchSearchRequest
    - ``source_0``, ``source_1``, etc. are uploaded audio files referenced by
      the ``file_key`` fields inside the metadata JSON

    Args:
        project_id: Project UUID (path parameter)
        current_user: Current authenticated user
        service: Search service instance
        db: Database session
        request: Raw FastAPI request (to access multipart form data)
        metadata: JSON string encoding a BatchSearchRequest

    Returns:
        BatchSearchResponse with per-species results and timing metadata

    Raises:
        400: Malformed metadata JSON
        403: Access denied to project
        413: One or more uploaded files exceed 10 MB
        422: Constraint violation (too many species/sources) or invalid model
        501: URL sources are not yet supported
    """
    await check_project_access(project_id, current_user.id, db)

    # Parse the metadata JSON field
    try:
        batch_request = BatchSearchRequest.model_validate(json.loads(metadata))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid metadata JSON: {exc}",
        ) from exc

    # Validate constraints
    MAX_SPECIES = 20
    MAX_SOURCES_PER_SPECIES = 10
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    BATCH_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".opus"}

    if len(batch_request.species) > MAX_SPECIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Too many species: {len(batch_request.species)} (max {MAX_SPECIES})",
        )

    for sp in batch_request.species:
        if len(sp.sources) > MAX_SOURCES_PER_SPECIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Species '{sp.scientific_name}' has {len(sp.sources)} sources "
                    f"(max {MAX_SOURCES_PER_SPECIES})"
                ),
            )
        for src in sp.sources:
            if src.type == "url":
                raise HTTPException(
                    status_code=status.HTTP_501_NOT_IMPLEMENTED,
                    detail="URL sources are not yet supported (Phase 2)",
                )

    # Read and persist all uploaded audio files
    form = await request.form()
    audio_files: dict[str, str] = {}  # file_key -> temp file path
    tmp_paths: list[str] = []

    try:
        for field_name, field_value in form.items():
            if field_name == "metadata":
                continue

            if not hasattr(field_value, "read"):
                # Not a file upload — skip
                continue

            upload: UploadFile = field_value  # type: ignore[assignment]
            content = await upload.read()

            if len(content) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File '{field_name}' exceeds 10 MB limit",
                )

            suffix = Path(upload.filename or "upload.wav").suffix.lower()
            if suffix not in BATCH_AUDIO_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Unsupported file type for '{field_name}': {suffix}. "
                        f"Allowed: {sorted(BATCH_AUDIO_EXTENSIONS)}"
                    ),
                )

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
                tmp_path = tmp_file.name
                tmp_file.write(content)

            audio_files[field_name] = tmp_path
            tmp_paths.append(tmp_path)

        try:
            return await service.batch_search(
                project_id=project_id,
                request=batch_request,
                audio_files=audio_files,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    finally:
        # Always clean up uploaded temp files
        import contextlib
        import os

        for p in tmp_paths:
            with contextlib.suppress(OSError):
                os.unlink(p)


@router.get(
    "/embedding-stats",
    response_model=EmbeddingStatsResponse,
    summary="Embedding statistics",
    description=(
        "Get statistics about stored embeddings for a project, "
        "broken down by model and dataset."
    ),
)
async def get_embedding_stats(
    project_id: UUID,
    current_user: CurrentUser,
    service: SearchServiceDep,
    db: DbSession,
    dataset_id: UUID | None = None,
) -> EmbeddingStatsResponse:
    """Get embedding statistics for a project.

    Returns total count and per-model / per-dataset breakdowns. Useful
    for checking whether embeddings have been generated before attempting
    a similarity search.

    Args:
        project_id: Project UUID (path parameter)
        current_user: Current authenticated user
        service: Search service instance
        db: Database session
        dataset_id: Optional dataset filter

    Returns:
        EmbeddingStatsResponse with counts by model and dataset

    Raises:
        401: Not authenticated
        403: Access denied to project
    """
    await check_project_access(project_id, current_user.id, db)
    return await service.get_embedding_stats(
        project_id=project_id,
        dataset_id=dataset_id,
    )
