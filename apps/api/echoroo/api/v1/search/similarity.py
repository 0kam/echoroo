"""Single-query similarity search endpoints.

Handles searching for similar audio segments by embedding ID or uploaded audio clip.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from echoroo.api.v1.search.deps import AuthorizedSearchServiceDep
from echoroo.schemas.search import (
    EmbeddingStatsResponse,
    SimilaritySearchRequest,
    SimilaritySearchResponse,
)

logger = logging.getLogger(__name__)

# Upload size and type limits for audio search queries
MAX_AUDIO_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".opus"}

router = APIRouter()


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
    service: AuthorizedSearchServiceDep,
) -> SimilaritySearchResponse:
    """Search for similar audio segments using an existing embedding.

    Retrieves the embedding vector for the given embedding_id, then finds
    the nearest neighbours in the project's embedding space.

    Args:
        project_id: Project UUID (path parameter)
        request: Search parameters including embedding_id and filters
        service: Authorized search service (verifies project access)

    Returns:
        Similarity search response ordered by descending similarity

    Raises:
        401: Not authenticated
        403: Access denied to project
        404: Embedding not found in project
    """
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
    service: AuthorizedSearchServiceDep,
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
        service: Authorized search service (verifies project access)
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

        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()


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
    service: AuthorizedSearchServiceDep,
    dataset_id: UUID | None = None,
) -> EmbeddingStatsResponse:
    """Get embedding statistics for a project.

    Returns total count and per-model / per-dataset breakdowns. Useful
    for checking whether embeddings have been generated before attempting
    a similarity search.

    Args:
        project_id: Project UUID (path parameter)
        service: Authorized search service (verifies project access)
        dataset_id: Optional dataset filter

    Returns:
        EmbeddingStatsResponse with counts by model and dataset

    Raises:
        401: Not authenticated
        403: Access denied to project
    """
    return await service.get_embedding_stats(
        project_id=project_id,
        dataset_id=dataset_id,
    )
