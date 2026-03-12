"""Similarity search API endpoints.

Provides vector similarity search over stored embeddings using pgvector.
All endpoints are scoped to a project_id for data isolation.
"""

from __future__ import annotations

import json
import logging
import tempfile
import uuid as uuid_module
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import String, bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.models.annotation import Annotation
from echoroo.models.enums import DetectionSource, DetectionStatus
from echoroo.repositories.project import ProjectRepository
from echoroo.schemas.detection import DetectionResponse
from echoroo.schemas.search import (
    BatchSearchRequest,
    BatchSearchResponse,
    EmbeddingStatsResponse,
    SearchJobAcceptedResponse,
    SearchJobStatusResponse,
    SearchSessionListItem,
    SearchSessionListResponse,
    SearchSessionResponse,
    SimilaritySearchRequest,
    SimilaritySearchResponse,
    SpeciesMatchResult,
)
from echoroo.services.search import SimilaritySearchService
from echoroo.services.search_session import SearchSessionService, get_search_session_service

logger = logging.getLogger(__name__)

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
SearchSessionServiceDep = Annotated[SearchSessionService, Depends(get_search_session_service)]


# ---------------------------------------------------------------------------
# Search session endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/sessions",
    response_model=SearchSessionListResponse,
    summary="List search sessions",
    description="List paginated batch search sessions for a project, ordered by creation date descending.",
)
async def list_search_sessions(
    project_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SearchSessionListResponse:
    """List search sessions for a project.

    Args:
        project_id: Project UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service
        limit: Maximum number of results
        offset: Number of results to skip

    Returns:
        Paginated list of search sessions

    Raises:
        403: Access denied to project
    """
    await check_project_access(project_id, current_user.id, db)
    sessions, total = await session_service.list_sessions(project_id, limit, offset)
    return SearchSessionListResponse(
        sessions=[SearchSessionListItem.model_validate(s) for s in sessions],
        total=total,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SearchSessionResponse,
    summary="Get search session detail",
    description="Get full search session detail with review status merged into results.",
)
async def get_search_session(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
) -> SearchSessionResponse:
    """Get a search session with review status merged into results.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service

    Returns:
        SearchSessionResponse with live review status merged into results

    Raises:
        403: Access denied to project
        404: Session not found
    """
    await check_project_access(project_id, current_user.id, db)
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    merged_results = await session_service.get_session_results_with_review_status(session_id, project_id)

    response = SearchSessionResponse.model_validate(session)
    if merged_results is not None:
        response.results = merged_results
    return response


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Delete search session",
    description="Delete a search session. S3 reference audio files are cleaned up on a best-effort basis.",
)
async def delete_search_session(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
) -> Response:
    """Delete a search session and attempt S3 cleanup of reference audio.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service

    Returns:
        204 No Content

    Raises:
        403: Access denied to project
        404: Session not found
    """
    await check_project_access(project_id, current_user.id, db)
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    # Clean up S3 reference audio files (best effort)
    if session.reference_audio_keys:
        import contextlib

        from echoroo.core.s3 import delete_object

        for key in session.reference_audio_keys:
            with contextlib.suppress(Exception):
                delete_object(key)

    await session_service.delete_session(session_id, project_id)
    await db.commit()
    return Response(status_code=204)


@router.get(
    "/sessions/{session_id}/export/csv",
    summary="Export session annotations as CSV",
    description="Export all annotations linked to a search session as a CSV file.",
)
async def export_search_session_csv(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
) -> StreamingResponse:
    """Export search session annotations as CSV.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service

    Returns:
        CSV file as streaming response

    Raises:
        403: Access denied to project
        404: Session not found
    """
    await check_project_access(project_id, current_user.id, db)
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    from echoroo.services.detection_export import DetectionExportService

    export_service = DetectionExportService(db)
    csv_content = await export_service.export_csv(project_id, search_session_id=session_id)

    date_str = datetime.now(UTC).strftime("%Y%m%d")
    safe_name = (session.name or str(session_id)).replace(" ", "_").replace("/", "-")
    filename = f"search_session_{safe_name}_{date_str}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()


@router.post(
    "/batch",
    response_model=SearchJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Batch species search by uploaded audio (async)",
    description=(
        "Upload reference audio clips for multiple species and find similar sounds "
        "across the project simultaneously. Returns immediately with a job_id; "
        "poll GET /jobs/{job_id} for status and results. "
        "Send as multipart/form-data with a 'metadata' JSON field and audio files "
        "named source_0, source_1, etc. Supports up to 20 species and 10 sources each."
    ),
)
async def batch_search(
    project_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    request: Request,
    metadata: str = Form(
        ...,
        description="JSON string of BatchSearchRequest",
    ),
) -> SearchJobAcceptedResponse:
    """Queue a batch species search job and return immediately.

    Accepts multipart/form-data where:
    - ``metadata`` is a JSON-encoded BatchSearchRequest
    - ``source_0``, ``source_1``, etc. are uploaded audio files referenced by
      the ``file_key`` fields inside the metadata JSON

    Files are saved to /data/search_tmp/{job_id}/ and a manifest.json is written.
    The Celery worker picks up the job and processes it asynchronously.

    Args:
        project_id: Project UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        request: Raw FastAPI request (to access multipart form data)
        metadata: JSON string encoding a BatchSearchRequest

    Returns:
        202 Accepted with job_id and "pending" status

    Raises:
        400: Malformed metadata JSON
        403: Access denied to project
        413: One or more uploaded files exceed 10 MB
        422: Constraint violation (too many species/sources), invalid model, or missing source_url
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
            if src.type == "url" and not src.source_url:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Species '{sp.scientific_name}' has a URL source with no source_url set"
                    ),
                )

    # Generate job ID and create temp directory
    job_id = str(uuid_module.uuid4())
    tmp_dir = Path(f"/data/search_tmp/{job_id}")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Read and persist all uploaded audio files to the job temp directory
    form = await request.form()
    audio_files: dict[str, str] = {}  # file_key -> relative path within tmp_dir

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

            # Save file with field_name as filename (e.g. source_0.wav)
            file_name = f"{field_name}{suffix}"
            dest_path = tmp_dir / file_name
            dest_path.write_bytes(content)
            audio_files[field_name] = file_name  # relative path

    except HTTPException:
        # Clean up temp dir on validation error
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Write manifest JSON for the worker
    manifest = {
        "request": batch_request.model_dump(),
        "audio_files": audio_files,
        "project_id": str(project_id),
        "user_id": str(current_user.id),
    }
    (tmp_dir / "manifest.json").write_text(json.dumps(manifest))

    # Dispatch Celery task
    from echoroo.workers.search_tasks import run_batch_search

    run_batch_search.apply_async(
        args=[job_id, str(project_id)],
        task_id=job_id,
    )

    # Create SearchSession DB record for persistence
    session_service = SearchSessionService(db)
    species_config_list = [sp.model_dump() for sp in batch_request.species]
    parameters: dict[str, object] = {
        "min_similarity": batch_request.min_similarity,
        "limit_per_species": batch_request.limit_per_species,
        "dataset_id": batch_request.dataset_id,
    }
    search_session = await session_service.create_session(
        project_id=project_id,
        user_id=current_user.id,
        model_name=batch_request.model_name,
        species_config=species_config_list,
        parameters=parameters,
        celery_job_id=job_id,
        reference_audio_keys=None,
    )
    await db.commit()

    return SearchJobAcceptedResponse(job_id=job_id, status="pending", session_id=search_session.id)


async def _resolve_vernacular_via_gbif(
    scientific_name: str,
    locale: str,
    db: DbSession,
) -> str | None:
    """Resolve vernacular name for a species not found in the local taxa table.

    Performs the following steps:
    1. Match the scientific name via GBIF /species/match to get a usageKey.
    2. Fetch vernacular names via GBIF /species/{key}/vernacularNames.
    3. Insert the taxon and its vernacular names into the local database for
       future lookups (so subsequent searches are fast).

    Args:
        scientific_name: Canonical scientific name to look up.
        locale: Locale code (e.g. "ja", "en").
        db: Database session for caching the resolved taxon.

    Returns:
        The vernacular name in the requested locale, or None if not found.
    """
    import datetime

    from echoroo.models.taxon import Taxon
    from echoroo.models.taxon_vernacular_name import TaxonVernacularName
    from echoroo.services.gbif import GBIFService

    gbif = GBIFService()

    # Step 1: resolve scientific name to GBIF taxon key
    resolve_result = await gbif.resolve_taxon(scientific_name)
    if resolve_result is None:
        logger.debug("GBIF could not resolve scientific name=%r", scientific_name)
        return None

    taxon_key = resolve_result.taxon_key
    logger.debug("GBIF resolved %r -> taxon_key=%d", scientific_name, taxon_key)

    # Step 2: fetch vernacular names from GBIF
    vernacular_entries = await gbif.get_vernacular_names(taxon_key)
    logger.debug(
        "GBIF vernacular names for key=%d: %d entries", taxon_key, len(vernacular_entries)
    )

    # Step 3: persist to local DB for future lookups
    try:
        taxon = Taxon(
            scientific_name=resolve_result.scientific_name,
            gbif_taxon_key=taxon_key,
            rank=resolve_result.rank,
            gbif_metadata=resolve_result.metadata,
            gbif_resolved_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(taxon)
        await db.flush()  # populate taxon.id

        for entry in vernacular_entries:
            vn = TaxonVernacularName(
                taxon_id=taxon.id,
                locale=entry["locale"],
                name=entry["name"],
                source="gbif",
                is_primary=False,
            )
            db.add(vn)

        await db.commit()
        logger.debug(
            "Cached taxon %r (id=%s) with %d vernacular names",
            scientific_name,
            taxon.id,
            len(vernacular_entries),
        )
    except Exception:
        # If insertion fails (e.g. race condition / duplicate), roll back and continue
        await db.rollback()
        logger.debug(
            "Could not cache taxon for %r (may already exist); continuing without caching",
            scientific_name,
        )

    # Find the requested locale in vernacular_entries (resolved just above)
    for entry in vernacular_entries:
        if entry["locale"] == locale:
            return entry["name"]

    return None


async def _enrich_search_results_with_locale(
    response: BatchSearchResponse,
    locale: str,
    db: DbSession,
) -> BatchSearchResponse:
    """Enrich batch search results with locale-specific vernacular names.

    For each species in the results, looks up the tag by tag_id, finds its
    taxon_id, then queries TaxonVernacularName for a locale-specific common name.
    Falls back to the stored common_name if no vernacular name is found.

    For species with no tag_id (e.g. searched directly from GBIF without being
    detected by BirdNET), falls back to a direct taxa table lookup by scientific
    name, and finally to a live GBIF API call if the taxon is not yet cached
    locally.  The GBIF result is persisted for future lookups.

    Uses a single batch query to avoid N+1 database calls.

    Note: asyncpg does not support inline PostgreSQL type casts (e.g. ``::uuid[]``)
    in parameterised queries.  We use ``bindparam(..., type_=ARRAY(PGUUID()))``
    so that SQLAlchemy emits the correct ``$1::UUID[]`` syntax at the driver level.

    Args:
        response: Batch search response to enrich
        locale: Locale code (e.g. "en", "ja")
        db: Database session

    Returns:
        New BatchSearchResponse with common_name fields enriched for the locale
    """
    if locale == "en":
        # common_name is already stored in English; nothing to enrich.
        logger.debug("Skipping locale enrichment: locale=en")
        return response

    # Collect all tag_ids from results (skip None values)
    tag_id_strings = [v.tag_id for v in response.results.values() if v.tag_id is not None]
    logger.debug(
        "Locale enrichment requested for locale=%r, found %d tag_ids: %s",
        locale,
        len(tag_id_strings),
        tag_id_strings,
    )

    # -----------------------------------------------------------------------
    # Phase 1: tag_id -> taxon_id -> vernacular lookup (existing detected species)
    # -----------------------------------------------------------------------
    taxon_id_by_tag: dict[str, str | None] = {}
    fallback_common_name_by_tag: dict[str, str | None] = {}

    if tag_id_strings:
        # Convert string tag_ids to UUID objects for proper asyncpg binding
        try:
            tag_ids_uuid = [uuid_module.UUID(tid) for tid in tag_id_strings]
        except ValueError:
            logger.warning(
                "Could not parse one or more tag_ids as UUID; skipping enrichment. tag_ids=%s",
                tag_id_strings,
            )
            return response

        # Batch fetch tag -> taxon_id mapping.
        # asyncpg requires ARRAY(PGUUID()) binding — inline ::uuid[] cast is not supported.
        tag_sql = text(
            """
            SELECT t.id AS tag_id, t.common_name, tx.id AS taxon_id
            FROM tags t
            LEFT JOIN taxa tx ON t.taxon_id = tx.id
            WHERE t.id = ANY(:tag_ids)
            """
        ).bindparams(bindparam("tag_ids", value=tag_ids_uuid, type_=ARRAY(PGUUID())))
        tag_rows = (await db.execute(tag_sql)).fetchall()
        logger.debug(
            "Tag query returned %d rows for %d requested tag_ids",
            len(tag_rows),
            len(tag_ids_uuid),
        )

        for row in tag_rows:
            tag_id_str = str(row.tag_id)
            taxon_id_by_tag[tag_id_str] = str(row.taxon_id) if row.taxon_id else None
            fallback_common_name_by_tag[tag_id_str] = row.common_name

    # Batch fetch vernacular names for all taxon IDs found via tags
    taxon_id_strings = [tid for tid in taxon_id_by_tag.values() if tid is not None]
    vernacular_by_taxon: dict[str, str] = {}
    if taxon_id_strings:
        taxon_ids_uuid = [uuid_module.UUID(tid) for tid in taxon_id_strings]
        vn_sql = text(
            """
            SELECT taxon_id, name
            FROM taxon_vernacular_names
            WHERE taxon_id = ANY(:taxon_ids)
              AND locale = :locale
            ORDER BY taxon_id, is_primary DESC
            """
        ).bindparams(bindparam("taxon_ids", value=taxon_ids_uuid, type_=ARRAY(PGUUID())))
        vn_rows = (await db.execute(vn_sql, {"locale": locale})).fetchall()
        logger.debug(
            "Vernacular name query returned %d rows for locale=%r, taxon_count=%d",
            len(vn_rows),
            locale,
            len(taxon_ids_uuid),
        )
        # Keep first (highest priority) per taxon_id
        for row in vn_rows:
            taxon_id_str = str(row.taxon_id)
            if taxon_id_str not in vernacular_by_taxon:
                vernacular_by_taxon[taxon_id_str] = row.name
    else:
        logger.debug("No taxon_ids found for the given tag_ids; vernacular lookup skipped")

    logger.debug(
        "Vernacular names resolved: %d/%d taxon_ids have a %r name",
        len(vernacular_by_taxon),
        len(taxon_id_strings),
        locale,
    )

    # -----------------------------------------------------------------------
    # Phase 2: For species still missing a locale name, try taxa by scientific_name
    # -----------------------------------------------------------------------
    # Build set of scientific names that need further enrichment:
    # - no tag_id (GBIF-only species), OR
    # - tag_id present but no vernacular name found above
    sci_names_needing_enrichment: set[str] = set()
    for species_result in response.results.values():
        tag_id = species_result.tag_id
        if tag_id is None:
            sci_names_needing_enrichment.add(species_result.scientific_name)
        else:
            taxon_id = taxon_id_by_tag.get(tag_id)
            if taxon_id is None or taxon_id not in vernacular_by_taxon:
                sci_names_needing_enrichment.add(species_result.scientific_name)

    vernacular_by_sci_name: dict[str, str] = {}
    if sci_names_needing_enrichment:
        # Look up taxa by scientific_name and join vernacular names in one query
        sci_name_list = list(sci_names_needing_enrichment)
        taxa_vn_sql = text(
            """
            SELECT tx.scientific_name, tvn.taxon_id, tvn.name
            FROM taxa tx
            JOIN taxon_vernacular_names tvn ON tvn.taxon_id = tx.id
            WHERE tx.scientific_name = ANY(:sci_names)
              AND tvn.locale = :locale
            ORDER BY tx.scientific_name, tvn.is_primary DESC
            """
        ).bindparams(bindparam("sci_names", value=sci_name_list, type_=ARRAY(String())))
        try:
            taxa_vn_rows = (await db.execute(taxa_vn_sql, {"locale": locale})).fetchall()
        except Exception:
            logger.warning("taxa vernacular name lookup failed", exc_info=True)
            taxa_vn_rows = []

        for row in taxa_vn_rows:
            sci = row.scientific_name
            if sci not in vernacular_by_sci_name:
                vernacular_by_sci_name[sci] = row.name

        logger.debug(
            "Direct taxa lookup resolved %d/%d scientific names for locale=%r",
            len(vernacular_by_sci_name),
            len(sci_names_needing_enrichment),
            locale,
        )

        # Phase 3: For species still not resolved, call GBIF API and cache results
        still_unresolved = sci_names_needing_enrichment - vernacular_by_sci_name.keys()
        for sci_name in still_unresolved:
            logger.debug(
                "Falling back to GBIF API for locale=%r enrichment of %r", locale, sci_name
            )
            resolved = await _resolve_vernacular_via_gbif(sci_name, locale, db)
            if resolved:
                vernacular_by_sci_name[sci_name] = resolved
                logger.debug("GBIF resolved %r -> %r in locale=%r", sci_name, resolved, locale)
            else:
                logger.debug("GBIF could not provide %r name for %r", locale, sci_name)

    # -----------------------------------------------------------------------
    # Rebuild results with enriched common names
    # -----------------------------------------------------------------------
    enriched_results: dict[str, SpeciesMatchResult] = {}
    for key, species_result in response.results.items():
        tag_id = species_result.tag_id
        resolved_name: str | None

        if tag_id is not None:
            taxon_id = taxon_id_by_tag.get(tag_id)
            if taxon_id is not None and taxon_id in vernacular_by_taxon:
                resolved_name = vernacular_by_taxon[taxon_id]
                logger.debug(
                    "Enriched %r (%s) via tag->taxon -> %r",
                    species_result.scientific_name,
                    tag_id,
                    resolved_name,
                )
            else:
                # Try scientific name fallback (phase 2/3)
                resolved_name = (
                    vernacular_by_sci_name.get(species_result.scientific_name)
                    or fallback_common_name_by_tag.get(tag_id)
                    or species_result.common_name
                )
                logger.debug(
                    "No tag->taxon vernacular for %r; using sci_name/fallback %r",
                    species_result.scientific_name,
                    resolved_name,
                )
        else:
            # No tag_id: use scientific name lookup (phase 2/3)
            resolved_name = (
                vernacular_by_sci_name.get(species_result.scientific_name)
                or species_result.common_name
            )
            logger.debug(
                "No tag_id for %r; resolved via sci_name -> %r",
                species_result.scientific_name,
                resolved_name,
            )

        enriched_results[key] = SpeciesMatchResult(
            tag_id=species_result.tag_id,
            scientific_name=species_result.scientific_name,
            common_name=resolved_name,
            matches=species_result.matches,
        )

    return BatchSearchResponse(
        results=enriched_results,
        total_matches=response.total_matches,
        search_duration_ms=response.search_duration_ms,
    )


def _clamp_similarity_in_raw(raw: object) -> None:
    """Clamp similarity values in a Celery result dict to the valid [0.0, 1.0] range.

    pgvector cosine similarity can produce values slightly above 1.0 (e.g. 1.0000001)
    due to floating-point rounding.  ``SimilarityResult.similarity`` has a ``le=1.0``
    constraint, so we clamp in-place before passing the raw dict to ``model_validate``.

    Mutates *raw* directly; safe because the dict is a freshly-deserialized Celery result
    and is never reused elsewhere.

    Args:
        raw: The raw Celery task result dict to normalise.
    """
    if not isinstance(raw, dict):
        return
    results = raw.get("results")
    if not isinstance(results, dict):
        return
    for species_data in results.values():
        if not isinstance(species_data, dict):
            continue
        matches = species_data.get("matches")
        if not isinstance(matches, list):
            continue
        for match in matches:
            if isinstance(match, dict) and "similarity" in match:
                import contextlib
                with contextlib.suppress(TypeError, ValueError):
                    match["similarity"] = max(0.0, min(1.0, float(match["similarity"])))


@router.get(
    "/jobs/{job_id}",
    response_model=SearchJobStatusResponse,
    summary="Get batch search job status",
    description=(
        "Poll the status of an async batch search job. "
        "Returns progress while processing, and full results when completed. "
        "Pass ?locale=ja to receive locale-specific common names in results."
    ),
)
async def get_search_job(
    project_id: UUID,
    job_id: str,
    current_user: CurrentUser,
    db: DbSession,
    locale: str = "en",
) -> SearchJobStatusResponse:
    """Get the status and results of an async batch search job.

    Maps Celery task states to API status values:
    - PENDING -> "pending"
    - PROCESSING (custom state) -> "processing"
    - SUCCESS -> "completed"
    - FAILURE -> "failed"

    When locale is provided (e.g. "ja"), common names in the results are
    enriched with locale-specific vernacular names looked up from the
    taxon_vernacular_names table. Enrichment happens at read time in this
    endpoint; the Celery task stores only raw English names.

    Args:
        project_id: Project UUID (path parameter)
        job_id: Job UUID string returned from POST /batch
        current_user: Current authenticated user
        db: Database session
        locale: Locale code for common name resolution (default: "en")

    Returns:
        SearchJobStatusResponse with current status and results if completed

    Raises:
        403: Access denied to project
    """
    await check_project_access(project_id, current_user.id, db)

    from celery.result import AsyncResult

    from echoroo.workers.celery_app import app as celery_app

    result = AsyncResult(job_id, app=celery_app)
    state = result.state

    # Look up the associated search session
    from echoroo.models.search_session import SearchSession

    session_result = await db.execute(
        select(SearchSession).where(
            SearchSession.celery_job_id == job_id,
            SearchSession.project_id == project_id,
        )
    )
    search_session = session_result.scalar_one_or_none()
    session_id = search_session.id if search_session else None

    if state == "PENDING":
        return SearchJobStatusResponse(job_id=job_id, status="pending", session_id=session_id)

    if state == "PROCESSING":
        meta = result.info or {}
        return SearchJobStatusResponse(
            job_id=job_id,
            status="processing",
            progress={
                "species_completed": meta.get("species_completed", 0),
                "species_total": meta.get("species_total", 0),
            },
            session_id=session_id,
        )

    if state == "SUCCESS":
        raw = result.result
        response: BatchSearchResponse | None = None
        try:
            # Pydantic v2 coerces string UUIDs to UUID objects automatically.
            # Clamp similarity values to [0.0, 1.0] before validation because
            # pgvector cosine similarity can return values like 1.0000001 due to
            # floating-point rounding, which would fail the le=1.0 constraint.
            _clamp_similarity_in_raw(raw)
            response = BatchSearchResponse.model_validate(raw)
            response = await _enrich_search_results_with_locale(response, locale, db)
        except Exception:
            logger.exception(
                "Failed to parse BatchSearchResponse from Celery result for job %s. "
                "Raw result keys: %s",
                job_id,
                list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__,
            )

        # Update session status to COMPLETED if not already done by the Celery task
        if search_session is not None and raw is not None:
            from echoroo.models.enums import SearchSessionStatus

            if search_session.status != SearchSessionStatus.COMPLETED:
                search_session.status = SearchSessionStatus.COMPLETED
                search_session.results = raw if isinstance(raw, dict) else None
                search_session.result_count = raw.get("total_matches", 0) if isinstance(raw, dict) else 0
                search_session.completed_at = datetime.now(UTC)
                try:
                    await db.commit()
                except Exception:
                    logger.exception("Failed to update search session status for job %s", job_id)
                    await db.rollback()

        return SearchJobStatusResponse(
            job_id=job_id,
            status="completed",
            results=response,
            session_id=session_id,
        )

    if state == "FAILURE":
        # Update session status to FAILED if not already done by the Celery task
        if search_session is not None:
            from echoroo.models.enums import SearchSessionStatus

            if search_session.status != SearchSessionStatus.FAILED:
                search_session.status = SearchSessionStatus.FAILED
                search_session.error_message = str(result.result)
                search_session.completed_at = datetime.now(UTC)
                try:
                    await db.commit()
                except Exception:
                    logger.exception("Failed to update search session failure status for job %s", job_id)
                    await db.rollback()

        return SearchJobStatusResponse(
            job_id=job_id,
            status="failed",
            error=str(result.result),
            session_id=session_id,
        )

    # STARTED, RETRY, or any other unknown state — treat as processing
    return SearchJobStatusResponse(job_id=job_id, status="processing", session_id=session_id)


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


# ---------------------------------------------------------------------------
# Annotation creation from search matches
# ---------------------------------------------------------------------------

annotations_router = APIRouter(prefix="/projects/{project_id}/annotations", tags=["search"])


class SearchAnnotationCreate(BaseModel):
    """Request schema for creating an annotation from a search match."""

    recording_id: UUID
    tag_id: UUID
    start_time: float
    end_time: float
    confidence: float | None = None
    review_status: str = "confirmed"
    source: str = "similarity_search"
    search_session_id: uuid_module.UUID | None = None


@annotations_router.post(
    "",
    response_model=DetectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation from search match",
    description=(
        "Create an annotation record from a similarity search match. "
        "If an annotation already exists for the same recording, tag, and time range "
        "(within 0.1 s tolerance), the existing annotation is returned instead of "
        "creating a duplicate."
    ),
)
async def create_search_annotation(
    project_id: UUID,
    request: SearchAnnotationCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> DetectionResponse:
    """Create an annotation from a similarity search match.

    Checks for an existing annotation with the same recording_id, tag_id, and
    overlapping time range (start_time and end_time within 0.1 s) to avoid
    duplicate records. Returns the existing annotation if a duplicate is found.

    Args:
        project_id: Project UUID (path parameter)
        request: Annotation creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created or existing annotation

    Raises:
        403: Access denied to project
        422: Invalid source or status value
    """
    await check_project_access(project_id, current_user.id, db)

    # Validate source enum
    try:
        source = DetectionSource(request.source)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid source value: {request.source!r}. "
            f"Valid values: {[e.value for e in DetectionSource]}",
        ) from err

    # Validate review_status enum
    try:
        ann_status = DetectionStatus(request.review_status)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid review_status value: {request.review_status!r}. "
            f"Valid values: {[e.value for e in DetectionStatus]}",
        ) from err

    # Check for existing annotation with same recording, tag, and time range
    # (within 0.1 s tolerance to avoid floating point issues)
    TOLERANCE = 0.1
    from sqlalchemy.orm import selectinload

    duplicate_check = await db.execute(
        select(Annotation)
        .where(Annotation.recording_id == request.recording_id)
        .where(Annotation.tag_id == request.tag_id)
        .where(Annotation.start_time >= request.start_time - TOLERANCE)
        .where(Annotation.start_time <= request.start_time + TOLERANCE)
        .where(Annotation.end_time >= request.end_time - TOLERANCE)
        .where(Annotation.end_time <= request.end_time + TOLERANCE)
        .options(
            selectinload(Annotation.recording),
            selectinload(Annotation.tag),
            selectinload(Annotation.detection_run),
            selectinload(Annotation.reviewed_by),
        )
        .limit(1)
    )
    existing = duplicate_check.scalar_one_or_none()

    if existing is not None:
        return _annotation_to_detection_response(existing)

    # Create new annotation
    annotation = Annotation(
        recording_id=request.recording_id,
        tag_id=request.tag_id,
        detection_run_id=None,
        source=source,
        status=ann_status,
        confidence=request.confidence,
        start_time=request.start_time,
        end_time=request.end_time,
        search_session_id=request.search_session_id,
    )
    db.add(annotation)
    await db.flush()
    await db.refresh(
        annotation, ["recording", "tag", "detection_run", "reviewed_by"]
    )
    await db.commit()

    # Update review counts for the linked search session
    if request.search_session_id is not None:
        session_svc = SearchSessionService(db)
        await session_svc.update_review_counts(request.search_session_id)
        await db.commit()

    return _annotation_to_detection_response(annotation)


def _annotation_to_detection_response(annotation: Annotation) -> DetectionResponse:
    """Convert an Annotation ORM instance to a DetectionResponse schema.

    Args:
        annotation: Annotation ORM instance with relationships loaded

    Returns:
        DetectionResponse schema instance
    """
    from echoroo.schemas.tag import TagResponse

    tag_resp = None
    if annotation.tag is not None:
        tag_resp = TagResponse.model_validate(annotation.tag)

    return DetectionResponse(
        id=annotation.id,
        recording_id=annotation.recording_id,
        tag_id=annotation.tag_id,
        detection_run_id=annotation.detection_run_id,
        source=annotation.source,
        status=annotation.status,
        confidence=annotation.confidence,
        start_time=annotation.start_time,
        end_time=annotation.end_time,
        freq_low=annotation.freq_low,
        freq_high=annotation.freq_high,
        reviewed_by_id=annotation.reviewed_by_id,
        reviewed_at=annotation.reviewed_at,
        created_at=annotation.created_at,
        updated_at=annotation.updated_at,
        tag=tag_resp,
    )
