"""Batch species search and job status endpoints.

Handles asynchronous batch search (queuing Celery tasks) and polling
job status with optional locale enrichment.
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import uuid as uuid_module
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple
from uuid import UUID

from fastapi import (
    APIRouter,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.v1.search.utils import _clamp_similarity_in_raw, _enrich_search_results_with_locale
from echoroo.core.database import DbSession
from echoroo.core.permissions import check_project_access
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.search import (
    BatchSearchRequest,
    BatchSearchResponse,
    SearchJobAcceptedResponse,
    SearchJobStatusResponse,
    SourceConfig,
    SpeciesSearchConfig,
)
from echoroo.services.search_session import SearchSessionService

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared batch-job preparation helper
# ---------------------------------------------------------------------------

# Validation constants shared between POST /batch and PUT /sessions/{id}/rerun.
_MAX_SPECIES = 20
_MAX_SOURCES_PER_SPECIES = 10
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_BATCH_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".opus"}


class BatchJobArtifacts(NamedTuple):
    """Outputs of :func:`_prepare_batch_job` — the ready-to-dispatch batch job.

    The five fields together capture everything a caller needs to either create
    a new ``SearchSession`` (POST /batch) or reset an existing one
    (PUT /sessions/{id}/rerun). Returned as a NamedTuple rather than a bare
    tuple because > 3 fields is past the threshold where positional unpacking
    at call sites starts to hurt readability.
    """

    job_id: str
    batch_request: BatchSearchRequest
    all_s3_keys: list[str]
    species_config_with_s3: list[dict[str, Any]]
    s3_prefix: str


async def _prepare_batch_job(
    db: AsyncSession,
    project_id: UUID,
    current_user_id: UUID,
    request: Request,
    metadata: str,
    *,
    log_tag: str,
) -> BatchJobArtifacts:
    """Validate multipart input, stage reference audio to S3, write a manifest.

    Performs the mechanical batch-job setup shared by ``POST /batch`` and
    ``PUT /sessions/{session_id}/rerun``:

    1. Parses ``metadata`` as a :class:`BatchSearchRequest` JSON blob.
    2. Strips any client-injected ``s3_key`` values (security invariant —
       ``s3_key`` is server-internal only).
    3. Validates species/sources/file-size/extension constraints.
    4. Copies S3 sources from ``source_session_id`` (if set) into the new
       job's S3 prefix.
    5. Reads uploaded files from the multipart form, validates them, and
       persists them to ``/data/search_tmp/{job_id}/``.
    6. Uploads the files to S3 under ``search_reference/{project_id}/{job_id}``.
    7. Collects the final ``s3_keys`` list and builds the enriched
       ``species_config_with_s3`` manifest, writing ``manifest.json`` to the
       temp dir.

    On mid-upload failure the partial S3 uploads under the job's prefix are
    cleaned up via ``delete_objects_by_prefix``, the temp directory is
    removed, and an HTTPException is re-raised.

    Args:
        db: Async DB session (used for parent session lookup when
            ``source_session_id`` is supplied).
        project_id: Owning project UUID (path parameter from the route).
        current_user_id: Authenticated user ID (recorded in the manifest).
        request: Raw FastAPI request — the multipart form is read off this.
        metadata: JSON-encoded BatchSearchRequest from the ``metadata`` form
            field.
        log_tag: Short string embedded in log lines (``"job"`` or
            ``"rerun job"``) so the source route is obvious in logs.

    Returns:
        BatchJobArtifacts ready for the caller to persist via the session
        service and dispatch to the Celery worker.

    Raises:
        HTTPException: 400 for malformed metadata / bad ``source_session_id``
            / unsupported file extension; 404 for missing parent session;
            413 for oversized files; 422 for constraint violations; 500 for
            S3 upload failures.
    """
    from echoroo.core.s3 import copy_object, delete_objects_by_prefix

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

    # Validate constraints
    if len(batch_request.species) > _MAX_SPECIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Too many species: {len(batch_request.species)} (max {_MAX_SPECIES})",
        )

    for sp in batch_request.species:
        if len(sp.sources) > _MAX_SOURCES_PER_SPECIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Species '{sp.scientific_name}' has {len(sp.sources)} sources "
                    f"(max {_MAX_SOURCES_PER_SPECIES})"
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

    # Handle re-execution: copy sources from parent session if source_session_id is set
    if batch_request.source_session_id:
        session_service_inner = SearchSessionService(db)
        try:
            parent_session_id = UUID(batch_request.source_session_id)
        except ValueError as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid source_session_id: {batch_request.source_session_id}",
            ) from exc

        parent_session = await session_service_inner.get_session(parent_session_id, project_id)
        if not parent_session:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source session not found: {batch_request.source_session_id}",
            )

        # Merge parent species configs into the current request
        if parent_session.species_config:
            # Build lookup for new request species by scientific_name
            new_species_by_name: dict[str, SpeciesSearchConfig] = {
                sp.scientific_name: sp for sp in batch_request.species
            }

            for _raw_sp in parent_session.species_config:
                # species_config is stored as list[object] in the ORM model;
                # we know at runtime each element is a dict from JSONB
                parent_sp_dict: dict[str, object] = _raw_sp  # type: ignore[assignment]
                parent_sci_name = str(parent_sp_dict.get("scientific_name", ""))
                if not parent_sci_name:
                    continue

                # Copy each parent source with s3_key to the new job's S3 prefix
                parent_sources_with_keys: list[SourceConfig] = []
                raw_sources = parent_sp_dict.get("sources", [])
                sources_list: list[dict[str, object]] = raw_sources  # type: ignore[assignment]
                for src_dict in sources_list:
                    old_s3_key = src_dict.get("s3_key")
                    if not old_s3_key:
                        continue
                    old_s3_key_str = str(old_s3_key)
                    # Derive new key: replace old job prefix with new job prefix
                    # old key format: search_reference/{project_id}/{old_job_id}/{file}
                    old_file_part = Path(old_s3_key_str).name
                    new_s3_key = f"search_reference/{project_id}/{job_id}/{old_file_part}"
                    try:
                        copy_object(old_s3_key_str, new_s3_key)
                    except Exception:
                        logger.warning(
                            "Failed to copy S3 object %s -> %s for %s, skipping",
                            old_s3_key_str,
                            new_s3_key,
                            log_tag,
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
                    # Merge parent sources into existing species
                    existing_sp = new_species_by_name[parent_sci_name]
                    existing_sp.sources = list(existing_sp.sources) + parent_sources_with_keys
                else:
                    # Add parent species as a new species in the request
                    _raw_tag_id = parent_sp_dict.get("tag_id")
                    merged_sp = SpeciesSearchConfig(
                        tag_id=str(_raw_tag_id) if _raw_tag_id is not None else None,
                        scientific_name=parent_sci_name,
                        sources=parent_sources_with_keys,
                    )
                    batch_request.species.append(merged_sp)

    # Read and persist all uploaded audio files to the job temp directory
    form = await request.form()
    audio_files: dict[str, str] = {}  # file_key -> relative path within tmp_dir

    # Track uploaded file contents for S3 upload (key -> bytes)
    uploaded_file_bytes: dict[str, bytes] = {}
    uploaded_file_suffixes: dict[str, str] = {}

    try:
        for field_name, field_value in form.items():
            if field_name == "metadata":
                continue

            if not hasattr(field_value, "read"):
                # Not a file upload — skip
                continue

            upload: UploadFile = field_value  # type: ignore[assignment]
            content = await upload.read()

            if len(content) > _MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File '{field_name}' exceeds 10 MB limit",
                )

            suffix = Path(upload.filename or "upload.wav").suffix.lower()
            if suffix not in _BATCH_AUDIO_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Unsupported file type for '{field_name}': {suffix}. "
                        f"Allowed: {sorted(_BATCH_AUDIO_EXTENSIONS)}"
                    ),
                )

            # Save file with field_name as filename (e.g. source_0.wav)
            file_name = f"{field_name}{suffix}"
            dest_path = tmp_dir / file_name
            dest_path.write_bytes(content)
            audio_files[field_name] = file_name  # relative path

            # Store bytes for S3 upload
            uploaded_file_bytes[field_name] = content
            uploaded_file_suffixes[field_name] = suffix

    except HTTPException:
        # Clean up temp dir on validation error
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Upload new files to S3 and set s3_key on each matching source
    s3_prefix = f"search_reference/{project_id}/{job_id}"
    try:
        from echoroo.core.s3 import get_s3_client
        from echoroo.core.settings import get_settings as _get_settings

        s3_settings = _get_settings()
        s3_client = get_s3_client()

        # FR-028e: route every PutObject kwargs dict through the GPS metadata
        # sanitizer (defense in depth — caller controls Metadata today, but a
        # later refactor adding it cannot regress).
        from echoroo.services.s3_upload_sanitizer import sanitize_put_object_kwargs

        for field_name, content in uploaded_file_bytes.items():
            suffix = uploaded_file_suffixes[field_name]
            s3_key = f"{s3_prefix}/{field_name}{suffix}"
            put_kwargs = sanitize_put_object_kwargs(
                {
                    "Bucket": s3_settings.S3_BUCKET,
                    "Key": s3_key,
                    "Body": content,
                }
            )
            s3_client.put_object(**put_kwargs)

            # Assign s3_key to all matching sources across species
            for sp in batch_request.species:
                for src in sp.sources:
                    if src.file_key == field_name and src.s3_key is None:
                        src.s3_key = s3_key

    except Exception as _s3_exc:
        logger.exception("Failed to upload reference audio to S3 for %s %s", log_tag, job_id)
        # Roll back S3 uploads
        with contextlib.suppress(Exception):
            delete_objects_by_prefix(s3_prefix)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist reference audio to storage",
        ) from _s3_exc

    # Collect all s3_keys (newly uploaded + copied from parent)
    all_s3_keys: list[str] = []
    for sp in batch_request.species:
        for src in sp.sources:
            if src.s3_key and src.s3_key not in all_s3_keys:
                all_s3_keys.append(src.s3_key)

    # Build enriched species config list (with s3_keys) for worker manifest and DB storage
    species_config_with_s3: list[dict[str, Any]] = [sp.model_dump() for sp in batch_request.species]

    # Write manifest JSON for the worker
    # species_config_with_s3 is stored separately so the worker gets s3_keys intact
    # (BatchSearchRequest validator would strip them if parsed via model_validate)
    manifest = {
        "request": batch_request.model_dump(exclude={"source_session_id"}),
        "audio_files": audio_files,
        "project_id": str(project_id),
        "user_id": str(current_user_id),
        "species_config_with_s3": species_config_with_s3,
    }
    (tmp_dir / "manifest.json").write_text(json.dumps(manifest))

    return BatchJobArtifacts(
        job_id=job_id,
        batch_request=batch_request,
        all_s3_keys=all_s3_keys,
        species_config_with_s3=species_config_with_s3,
        s3_prefix=s3_prefix,
    )


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

    from echoroo.core.s3 import delete_objects_by_prefix

    artifacts = await _prepare_batch_job(
        db=db,
        project_id=project_id,
        current_user_id=current_user.id,
        request=request,
        metadata=metadata,
        log_tag="job",
    )

    # Create SearchSession DB record and commit before dispatching the Celery task.
    # This ensures the session row exists in the DB before the worker starts, so
    # the worker can reliably update it.  If the commit fails the S3 objects are
    # cleaned up and no task is dispatched.
    session_service = SearchSessionService(db)
    parameters: dict[str, object] = {
        "min_similarity": artifacts.batch_request.min_similarity,
        "limit_per_species": artifacts.batch_request.limit_per_species,
        "dataset_id": artifacts.batch_request.dataset_id,
    }
    search_session = await session_service.create_session(
        project_id=project_id,
        user_id=current_user.id,
        model_name=artifacts.batch_request.model_name,
        species_config=artifacts.species_config_with_s3,
        parameters=parameters,
        celery_job_id=artifacts.job_id,
        reference_audio_keys=artifacts.all_s3_keys if artifacts.all_s3_keys else None,
    )
    try:
        await db.commit()
    except Exception as _db_exc:
        logger.exception(
            "Failed to persist search session for job %s; rolling back S3 uploads",
            artifacts.job_id,
        )
        with contextlib.suppress(Exception):
            delete_objects_by_prefix(artifacts.s3_prefix)
        shutil.rmtree(Path(f"/data/search_tmp/{artifacts.job_id}"), ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create search session",
        ) from _db_exc

    # Dispatch Celery task only after the DB record is committed.
    from echoroo.workers.search_tasks import run_batch_search

    run_batch_search.apply_async(
        args=[artifacts.job_id, str(project_id)],
        task_id=artifacts.job_id,
    )

    return SearchJobAcceptedResponse(
        job_id=artifacts.job_id, status="pending", session_id=search_session.id
    )


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

            await db.refresh(search_session)
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
