"""Search session CRUD endpoints.

Handles listing, getting, updating, deleting, and re-running search sessions,
as well as streaming reference audio and exporting session annotations as CSV.
"""

from __future__ import annotations

import collections.abc
import contextlib
import json
import logging
import uuid as uuid_module
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from echoroo.api.v1.search.deps import SearchSessionServiceDep
from echoroo.core.database import DbSession
from echoroo.core.permissions import check_project_access
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.search import (
    BatchSearchRequest,
    SearchJobAcceptedResponse,
    SearchSessionListItem,
    SearchSessionListResponse,
    SearchSessionResponse,
    SimilarityDistributionResponse,
    SimilaritySearchResponse,
    SourceConfig,
    SpeciesSearchConfig,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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

    merged_results = await session_service.get_session_results_with_review_status(
        session_id, project_id, session=session
    )

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


@router.patch(
    "/sessions/{session_id}",
    response_model=SearchSessionResponse,
    summary="Update search session",
    description="Update a search session's name.",
)
async def update_search_session(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
    name: str = Body(..., embed=True),
) -> SearchSessionResponse:
    """Update a search session's name.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service
        name: New session name

    Returns:
        Updated SearchSessionResponse

    Raises:
        403: Access denied to project
        404: Session not found
    """
    await check_project_access(project_id, current_user.id, db)
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    session.name = name
    await db.commit()
    await db.refresh(session)
    return SearchSessionResponse.model_validate(session)


@router.put(
    "/sessions/{session_id}/rerun",
    response_model=SearchJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run a search session with updated reference sources",
    description=(
        "Update a session's species_config and re-run the search. "
        "Clears existing results and annotations, resets status to pending, "
        "and dispatches a new Celery search task. "
        "Send as multipart/form-data with a 'metadata' JSON field and optional audio files."
    ),
)
async def rerun_search_session(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
    request: Request,
    metadata: str = Form(
        ...,
        description="JSON string of BatchSearchRequest",
    ),
) -> SearchJobAcceptedResponse:
    """Re-run an existing search session with updated reference sources.

    Clears existing annotations for this session, resets status and results,
    then dispatches a new search task reusing the same session record.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service
        request: Raw FastAPI request (to access multipart form data)
        metadata: JSON string encoding a BatchSearchRequest

    Returns:
        202 Accepted with job_id and session_id

    Raises:
        400: Malformed metadata JSON
        403: Access denied to project
        404: Session not found
        413: One or more uploaded files exceed 10 MB
        422: Constraint violation or invalid model
    """
    import contextlib
    import shutil

    from echoroo.core.s3 import copy_object, delete_objects_by_prefix

    await check_project_access(project_id, current_user.id, db)

    # Fetch and validate the session
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

    # Parse the metadata JSON field
    try:
        batch_request = BatchSearchRequest.model_validate(json.loads(metadata))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid metadata JSON: {exc}",
        ) from exc

    # Strip any client-injected s3_keys (security: s3_key is server-internal only)
    for sp in batch_request.species:
        for src in sp.sources:
            src.s3_key = None

    # Validate constraints (same as batch_search)
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

    # Generate a new job ID for this re-run
    job_id = str(uuid_module.uuid4())
    tmp_dir = Path(f"/data/search_tmp/{job_id}")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Handle S3 sources from the current session (copy to new job prefix)
    if batch_request.source_session_id:
        try:
            source_session_id = UUID(batch_request.source_session_id)
        except ValueError as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source_session_id: {batch_request.source_session_id}",
            ) from exc

        source_session = await session_service.get_session(source_session_id, project_id)
        if not source_session:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source session not found: {batch_request.source_session_id}",
            )

        # Copy S3 sources from parent session (same logic as batch_search)
        if source_session.species_config:
            new_species_by_name: dict[str, SpeciesSearchConfig] = {
                sp.scientific_name: sp for sp in batch_request.species
            }

            for _raw_sp in source_session.species_config:
                parent_sp_dict: dict[str, object] = _raw_sp  # type: ignore[assignment]
                parent_sci_name = str(parent_sp_dict.get("scientific_name", ""))
                if not parent_sci_name:
                    continue

                parent_sources_with_keys: list[SourceConfig] = []
                raw_sources = parent_sp_dict.get("sources", [])
                sources_list: list[dict[str, object]] = raw_sources  # type: ignore[assignment]
                for src_dict in sources_list:
                    old_s3_key = src_dict.get("s3_key")
                    if not old_s3_key:
                        continue
                    old_s3_key_str = str(old_s3_key)
                    old_file_part = Path(old_s3_key_str).name
                    new_s3_key = f"search_reference/{project_id}/{job_id}/{old_file_part}"
                    try:
                        copy_object(old_s3_key_str, new_s3_key)
                    except Exception:
                        logger.warning(
                            "Failed to copy S3 object %s -> %s for rerun, skipping",
                            old_s3_key_str,
                            new_s3_key,
                        )
                        continue

                    _raw_file_key = src_dict.get("file_key")
                    _raw_start = src_dict.get("start_time")
                    _raw_end = src_dict.get("end_time")
                    copied_src = SourceConfig(
                        type="upload",
                        file_key=str(_raw_file_key) if _raw_file_key is not None else None,
                        start_time=float(str(_raw_start)) if _raw_start is not None else None,
                        end_time=float(str(_raw_end)) if _raw_end is not None else None,
                    )
                    copied_src.s3_key = new_s3_key
                    parent_sources_with_keys.append(copied_src)

                if not parent_sources_with_keys:
                    continue

                if parent_sci_name in new_species_by_name:
                    existing_sp = new_species_by_name[parent_sci_name]
                    existing_sp.sources = list(existing_sp.sources) + parent_sources_with_keys
                else:
                    _raw_tag_id = parent_sp_dict.get("tag_id")
                    merged_sp = SpeciesSearchConfig(
                        tag_id=str(_raw_tag_id) if _raw_tag_id is not None else None,
                        scientific_name=parent_sci_name,
                        sources=parent_sources_with_keys,
                    )
                    batch_request.species.append(merged_sp)

    # Read and persist all uploaded audio files
    form = await request.form()
    audio_files: dict[str, str] = {}
    uploaded_file_bytes: dict[str, bytes] = {}
    uploaded_file_suffixes: dict[str, str] = {}

    try:
        for field_name, field_value in form.items():
            if field_name == "metadata":
                continue
            if not hasattr(field_value, "read"):
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
            file_name = f"{field_name}{suffix}"
            dest_path = tmp_dir / file_name
            dest_path.write_bytes(content)
            audio_files[field_name] = file_name
            uploaded_file_bytes[field_name] = content
            uploaded_file_suffixes[field_name] = suffix
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Upload new files to S3
    s3_prefix = f"search_reference/{project_id}/{job_id}"
    uploaded_s3_keys: list[str] = []
    try:
        from echoroo.core.s3 import get_s3_client
        from echoroo.core.settings import get_settings as _get_settings

        s3_settings = _get_settings()
        s3_client = get_s3_client()

        for field_name, content in uploaded_file_bytes.items():
            suffix = uploaded_file_suffixes[field_name]
            s3_key = f"{s3_prefix}/{field_name}{suffix}"
            s3_client.put_object(
                Bucket=s3_settings.S3_BUCKET,
                Key=s3_key,
                Body=content,
            )
            uploaded_s3_keys.append(s3_key)
            for sp in batch_request.species:
                for src in sp.sources:
                    if src.file_key == field_name and src.s3_key is None:
                        src.s3_key = s3_key
    except Exception as _s3_exc:
        logger.exception("Failed to upload reference audio to S3 for rerun job %s", job_id)
        with contextlib.suppress(Exception):
            delete_objects_by_prefix(s3_prefix)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist reference audio to storage",
        ) from _s3_exc

    # Collect all s3_keys
    all_s3_keys: list[str] = []
    for sp in batch_request.species:
        for src in sp.sources:
            if src.s3_key and src.s3_key not in all_s3_keys:
                all_s3_keys.append(src.s3_key)

    species_config_with_s3 = [sp.model_dump() for sp in batch_request.species]

    # Write manifest for the Celery worker
    manifest = {
        "request": batch_request.model_dump(exclude={"source_session_id"}),
        "audio_files": audio_files,
        "project_id": str(project_id),
        "user_id": str(current_user.id),
        "species_config_with_s3": species_config_with_s3,
    }
    (tmp_dir / "manifest.json").write_text(json.dumps(manifest))

    # Delete existing annotations linked to this session
    await db.execute(
        text("DELETE FROM annotations WHERE search_session_id = :sid").bindparams(
            bindparam("sid", value=session_id, type_=PGUUID())
        )
    )

    # Clean up old S3 reference audio (best effort, don't block on failure)
    if session.reference_audio_keys:
        from echoroo.core.s3 import delete_object

        for key in session.reference_audio_keys:
            with contextlib.suppress(Exception):
                delete_object(key)

    # Reset session fields for the re-run
    from echoroo.models.enums import SearchSessionStatus

    session.status = SearchSessionStatus.PENDING
    session.results = None
    session.result_count = 0
    session.confirmed_count = 0
    session.rejected_count = 0
    session.error_message = None
    session.started_at = None
    session.completed_at = None
    session.celery_job_id = job_id
    session.model_name = batch_request.model_name
    session.parameters = {
        "min_similarity": batch_request.min_similarity,
        "limit_per_species": batch_request.limit_per_species,
        "dataset_id": batch_request.dataset_id,
    }
    session.species_config = species_config_with_s3
    session.reference_audio_keys = all_s3_keys if all_s3_keys else None

    # Auto-generate a new name
    species_names: list[str] = []
    for sp_cfg in species_config_with_s3:
        raw_label = sp_cfg.get("common_name") or sp_cfg.get("scientific_name", "Unknown")
        label = str(raw_label) if raw_label is not None else "Unknown"
        species_names.append(label)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    if len(species_names) > 3:
        session.name = f"{', '.join(species_names[:3])}... - {date_str}"
    else:
        session.name = f"{', '.join(species_names)} - {date_str}"

    await db.commit()

    # Dispatch Celery task
    from echoroo.workers.search_tasks import run_batch_search

    run_batch_search.apply_async(
        args=[job_id, str(project_id)],
        task_id=job_id,
    )

    return SearchJobAcceptedResponse(job_id=job_id, status="pending", session_id=session.id)


@router.get(
    "/sessions/{session_id}/reference-audio/{source_index}",
    summary="Stream reference audio for a search session",
    description=(
        "Stream a persisted reference audio file for a search session by its index "
        "in the reference_audio_keys list. Supports HTTP Range requests."
    ),
)
async def stream_reference_audio(
    project_id: UUID,
    session_id: UUID,
    source_index: int,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
    range: str | None = Header(None),
) -> StreamingResponse:
    """Stream a reference audio file stored in S3 for a search session.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        source_index: Index into the session's reference_audio_keys list
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service
        range: Optional HTTP Range header for partial content streaming

    Returns:
        StreamingResponse with audio content

    Raises:
        403: Access denied to project
        404: Session not found or source_index out of bounds
        500: S3 retrieval error
    """
    import mimetypes

    await check_project_access(project_id, current_user.id, db)
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    if not session.reference_audio_keys or source_index >= len(session.reference_audio_keys):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reference audio source index {source_index} not found",
        )

    if source_index < 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid source index",
        )

    s3_key = session.reference_audio_keys[source_index]

    try:
        from echoroo.core.s3 import get_s3_client as _get_s3_stream_client
        from echoroo.core.settings import get_settings as _get_stream_settings

        _stream_settings = _get_stream_settings()
        _stream_client = _get_s3_stream_client()
        s3_params: dict[str, Any] = {
            "Bucket": _stream_settings.S3_BUCKET,
            "Key": s3_key,
        }
        if range:
            s3_params["Range"] = range
        s3_response = _stream_client.get_object(**s3_params)
    except Exception as exc:
        logger.exception("Failed to stream reference audio key=%s", s3_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve reference audio from storage",
        ) from exc

    body = s3_response["Body"]
    content_length = s3_response.get("ContentLength")

    # Determine content type from file extension
    suffix = Path(s3_key).suffix.lower()
    content_type, _ = mimetypes.guess_type(f"file{suffix}")
    if not content_type:
        content_type = "audio/wav"

    def _iter_stream() -> collections.abc.Iterator[bytes]:
        try:
            while True:
                chunk = body.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    response_headers: dict[str, str] = {}
    if content_length is not None:
        response_headers["Content-Length"] = str(content_length)
    response_headers["Accept-Ranges"] = "bytes"

    response_status = 206 if range else 200
    if range and "ContentRange" in s3_response:
        response_headers["Content-Range"] = s3_response["ContentRange"]

    return StreamingResponse(
        _iter_stream(),
        status_code=response_status,
        media_type=content_type,
        headers=response_headers,
    )


@router.get(
    "/sessions/{session_id}/export-recordings",
    summary="Export session results aggregated by recording as CSV",
    description=(
        "Aggregate session similarity results by recording and export as CSV. "
        "Each row represents one recording with max/avg similarity, match count, "
        "and the time range of the best-matching segment."
    ),
)
async def export_search_session_recordings_csv(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
) -> StreamingResponse:
    """Export per-recording aggregated similarity results as CSV.

    Reads the stored JSON results for the session and aggregates them by
    recording_id, computing max/avg similarity, match count, and the time
    range of the highest-similarity segment per recording.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service

    Returns:
        CSV file as streaming response with columns:
        recording_filename, recording_datetime, max_similarity,
        avg_similarity, match_count, best_segment_start, best_segment_end

    Raises:
        403: Access denied to project
        404: Session not found or has no results
    """
    import csv
    import io

    await check_project_access(project_id, current_user.id, db)
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    if not session.results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to export",
        )

    # Aggregate matches across all species by recording_id
    # Structure: recording_id -> aggregated data dict
    class _RecordingAgg:
        """Accumulator for per-recording similarity statistics."""

        def __init__(
            self,
            recording_filename: str,
            recording_datetime: str | None,
            similarity: float,
            start_time: float,
            end_time: float,
        ) -> None:
            self.recording_filename = recording_filename
            self.recording_datetime = recording_datetime
            self.max_similarity = similarity
            self.total_similarity = similarity
            self.match_count = 1
            self.best_segment_start = start_time
            self.best_segment_end = end_time

        def update(self, similarity: float, start_time: float, end_time: float) -> None:
            """Update accumulator with a new match."""
            self.match_count += 1
            self.total_similarity += similarity
            if similarity > self.max_similarity:
                self.max_similarity = similarity
                self.best_segment_start = start_time
                self.best_segment_end = end_time

    agg: dict[str, _RecordingAgg] = {}

    raw_results = session.results.get("results")
    if isinstance(raw_results, dict):
        for _species_key, species_data in raw_results.items():
            if not isinstance(species_data, dict):
                continue
            matches = species_data.get("matches", [])
            if not isinstance(matches, list):
                continue
            for match in matches:
                if not isinstance(match, dict):
                    continue
                rec_id = str(match.get("recording_id", ""))
                if not rec_id:
                    continue
                similarity = float(match.get("similarity", 0.0))
                start_time = float(match.get("start_time", 0.0))
                end_time = float(match.get("end_time", 0.0))
                recording_filename = str(match.get("recording_filename", ""))
                raw_dt = match.get("recording_datetime")
                recording_datetime: str | None = str(raw_dt) if raw_dt is not None else None

                if rec_id not in agg:
                    agg[rec_id] = _RecordingAgg(
                        recording_filename=recording_filename,
                        recording_datetime=recording_datetime,
                        similarity=similarity,
                        start_time=start_time,
                        end_time=end_time,
                    )
                else:
                    agg[rec_id].update(similarity, start_time, end_time)

    # Sort by descending max_similarity
    sorted_agg = sorted(
        agg.values(),
        key=lambda r: r.max_similarity,
        reverse=True,
    )

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "recording_filename",
            "recording_datetime",
            "max_similarity",
            "avg_similarity",
            "match_count",
            "best_segment_start",
            "best_segment_end",
        ]
    )
    for row in sorted_agg:
        avg_similarity = row.total_similarity / row.match_count if row.match_count > 0 else 0.0
        writer.writerow(
            [
                row.recording_filename,
                row.recording_datetime or "",
                f"{row.max_similarity:.4f}",
                f"{avg_similarity:.4f}",
                row.match_count,
                f"{row.best_segment_start:.2f}",
                f"{row.best_segment_end:.2f}",
            ]
        )

    csv_content = output.getvalue()
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    safe_name = (session.name or str(session_id)).replace('"', '_').replace('\n', '_').replace('\r', '_').replace(' ', '_').replace('/', '-')
    filename = f"recordings_{safe_name}_{date_str}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    safe_name = (session.name or str(session_id)).replace('"', '_').replace('\n', '_').replace('\r', '_').replace(' ', '_').replace('/', '-')
    filename = f"search_session_{safe_name}_{date_str}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Similarity distribution and random sampling endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/sessions/{session_id}/distribution",
    response_model=SimilarityDistributionResponse,
    summary="Get similarity distribution for a search session",
    description=(
        "Compute a histogram of cosine similarities for all project embeddings "
        "against the session's reference vectors. Uses SQL aggregation for efficiency "
        "— individual vectors are never loaded into Python. "
        "Query vectors are derived from the top stored matches for each species."
    ),
)
async def get_session_similarity_distribution(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
    bin_width: float = Query(default=0.05, ge=0.01, le=0.5, description="Histogram bin width"),
) -> SimilarityDistributionResponse:
    """Get a similarity histogram for all project embeddings vs. the session's reference vectors.

    Retrieves the stored top-match embedding vectors from the session results and
    uses them as query vectors to compute a full-space similarity distribution.
    This approach avoids re-running model inference.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service
        bin_width: Histogram bin width (default 0.05 = 20 bins from 0.0 to 1.0)

    Returns:
        SimilarityDistributionResponse with histogram bins and total count

    Raises:
        403: Access denied to project
        404: Session not found or has no results
    """
    await check_project_access(project_id, current_user.id, db)
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    query_vectors = await _get_query_vectors_from_session(session, db)
    if not query_vectors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to compute distribution from",
        )

    dataset_id: UUID | None = None
    if session.parameters and session.parameters.get("dataset_id"):
        with contextlib.suppress(ValueError):
            dataset_id = UUID(str(session.parameters["dataset_id"]))

    from echoroo.services.search import SimilaritySearchService

    search_service = SimilaritySearchService(db)
    return await search_service.get_similarity_distribution(
        project_id=project_id,
        query_vectors=query_vectors,
        model_name=session.model_name,
        bin_width=bin_width,
        dataset_id=dataset_id,
    )


@router.get(
    "/sessions/{session_id}/sample",
    response_model=SimilaritySearchResponse,
    summary="Randomly sample embeddings within a similarity range",
    description=(
        "Return a random sample of embeddings whose cosine similarity to the "
        "session's reference vectors falls within [min_similarity, max_similarity]. "
        "Useful for exploring which sounds exist in a specific similarity band."
    ),
)
async def sample_session_similarity_range(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: SearchSessionServiceDep,
    min_similarity: float = Query(default=0.0, ge=0.0, le=1.0, description="Lower bound (inclusive)"),
    max_similarity: float = Query(default=1.0, ge=0.0, le=1.0, description="Upper bound (inclusive)"),
    limit: int = Query(default=20, ge=1, le=200, description="Maximum number of results to return"),
) -> SimilaritySearchResponse:
    """Return a random sample of embeddings within a given similarity range.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service
        min_similarity: Lower bound of similarity range
        max_similarity: Upper bound of similarity range
        limit: Maximum number of randomly sampled results

    Returns:
        SimilaritySearchResponse with randomly sampled SimilarityResult items

    Raises:
        400: min_similarity > max_similarity
        403: Access denied to project
        404: Session not found or has no results
    """
    if min_similarity > max_similarity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"min_similarity ({min_similarity}) must be <= max_similarity ({max_similarity})",
        )

    await check_project_access(project_id, current_user.id, db)
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    query_vectors = await _get_query_vectors_from_session(session, db)
    if not query_vectors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to sample from",
        )

    dataset_id: UUID | None = None
    if session.parameters and session.parameters.get("dataset_id"):
        with contextlib.suppress(ValueError):
            dataset_id = UUID(str(session.parameters["dataset_id"]))

    from echoroo.services.search import SimilaritySearchService

    search_service = SimilaritySearchService(db)
    results = await search_service.sample_by_similarity_range(
        project_id=project_id,
        query_vectors=query_vectors,
        model_name=session.model_name,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
        limit=limit,
        dataset_id=dataset_id,
    )

    return SimilaritySearchResponse(
        results=results,
        query_model=session.model_name,
        total_results=len(results),
    )


async def _get_query_vectors_from_session(
    session: Any,
    db: Any,
) -> list[list[float]]:
    """Extract query vectors from a completed session's stored match embeddings.

    Retrieves the embedding_id of the best (highest similarity) match per species
    from the stored session results, then fetches the corresponding stored vectors
    from the embeddings table. This avoids re-running model inference.

    For multi-species sessions, one representative vector per species is returned
    so the distribution reflects similarity to any of the searched species.

    Args:
        session: SearchSession ORM instance with populated results field
        db: SQLAlchemy async session

    Returns:
        List of float vectors (each of length _STORAGE_EMBEDDING_DIM), one per species.
        Empty list if session has no results or no valid embedding IDs can be resolved.
    """
    from sqlalchemy import text as _text

    if not session.results:
        return []

    raw_results = session.results.get("results")
    if not isinstance(raw_results, dict):
        return []

    # Collect the best embedding_id per species (highest similarity match)
    best_embedding_ids: list[str] = []
    for _species_key, species_data in raw_results.items():
        if not isinstance(species_data, dict):
            continue
        matches = species_data.get("matches", [])
        if not isinstance(matches, list) or not matches:
            continue
        # Matches are stored in descending similarity order; take the first one
        best_match = matches[0]
        if isinstance(best_match, dict) and best_match.get("embedding_id"):
            best_embedding_ids.append(str(best_match["embedding_id"]))

    if not best_embedding_ids:
        return []

    # Fetch vectors from the embeddings table for all collected IDs.
    # Use != ALL with an inverted query is not needed here — instead use a
    # parameterised IN list to avoid the asyncpg ::uuid[] cast syntax issue.
    # Build a parameterised set of bind variables for the IN clause.
    in_params: dict[str, str] = {f"eid_{i}": eid for i, eid in enumerate(best_embedding_ids)}
    in_clause = ", ".join(f":eid_{i}" for i in range(len(best_embedding_ids)))
    fetch_sql = _text(
        f"""
        SELECT e.vector::text AS vector_text
        FROM embeddings e
        WHERE e.id IN ({in_clause})
        """
    )
    rows = (
        await db.execute(fetch_sql, in_params)
    ).fetchall()

    from echoroo.services.search import _parse_vector_text

    query_vectors: list[list[float]] = []
    for row in rows:
        try:
            query_vectors.append(_parse_vector_text(row.vector_text))
        except ValueError:
            logger.warning("Failed to parse vector text for session query vector, skipping")

    return query_vectors
