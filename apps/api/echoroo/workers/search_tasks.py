"""Celery worker tasks for batch similarity search.

Tasks run outside FastAPI's async event loop, so async database calls
are executed via asyncio.run() in a sync Celery task context.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from echoroo.core.settings import get_settings
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async session factory
# ---------------------------------------------------------------------------


def _get_engine_and_session_factory() -> tuple[Any, async_sessionmaker[AsyncSession]]:
    """Create a fresh async engine and session factory for each task invocation.

    Each Celery task calls ``asyncio.run()`` which creates a new event loop.
    Reusing a cached engine across loops causes "Future attached to a different
    loop" errors, so we create a fresh engine every time.

    Returns the engine separately so the caller can dispose it in a finally
    block after the task completes, releasing all pooled connections.
    """
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Celery task definition
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.search_tasks.run_batch_search",
    time_limit=300,
    soft_time_limit=270,
)
def run_batch_search(self: Any, job_id: str, project_id: str) -> dict[str, Any]:
    """Run batch similarity search as an async Celery task.

    Reads the search manifest from /data/search_tmp/{job_id}/manifest.json,
    processes each species configuration, runs model inference and pgvector
    similarity search, and returns aggregated results.

    Args:
        job_id: UUID string identifying the job and its temp directory
        project_id: UUID string of the project to search within

    Returns:
        Dict matching BatchSearchResponse schema with string UUIDs for JSON serialization

    Raises:
        Exception: Re-raises any exception after cleaning up temp files
    """
    try:
        return asyncio.run(_run_batch_search(self, job_id, project_id))
    except Exception:
        # Clean up temp files on failure
        tmp_dir = Path(f"/data/search_tmp/{job_id}")
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _run_batch_search(
    task: Any,
    job_id: str,
    project_id: str,
) -> dict[str, Any]:
    """Async implementation of batch similarity search.

    Args:
        task: Celery task instance (for update_state)
        job_id: UUID string for the job
        project_id: UUID string for the project

    Returns:
        Dict matching BatchSearchResponse schema
    """
    tmp_dir = Path(f"/data/search_tmp/{job_id}")
    manifest_path = tmp_dir / "manifest.json"

    # Read manifest
    if not manifest_path.exists():
        raise FileNotFoundError(f"Search manifest not found: {manifest_path}")

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Reconstruct request data from manifest
    # Use species_config_with_s3 when available (contains s3_keys for persisted reference audio).
    # Fall back to manifest["request"] species for backwards compatibility.
    from echoroo.schemas.search import BatchSearchRequest, SpeciesSearchConfig

    batch_request = BatchSearchRequest.model_validate(manifest["request"])
    audio_files: dict[str, str] = manifest["audio_files"]  # file_key -> relative path

    # Override species list with enriched config (includes s3_keys) if present
    if "species_config_with_s3" in manifest:
        enriched_species = []
        for sp_dict in manifest["species_config_with_s3"]:
            enriched_species.append(SpeciesSearchConfig.model_validate(sp_dict))
        batch_request.species = enriched_species

    # Resolve relative paths to absolute paths within tmp_dir
    audio_files_abs: dict[str, str] = {}
    for key, rel_path in audio_files.items():
        abs_path = str(tmp_dir / rel_path)
        audio_files_abs[key] = abs_path

    # Create DB session
    engine, session_factory = _get_engine_and_session_factory()

    try:
        async with session_factory() as db:
            from echoroo.models.enums import SearchSessionStatus
            from echoroo.models.search_session import SearchSession
            from echoroo.services.search import SimilaritySearchService

            service = SimilaritySearchService(db)

            # Update session status to RUNNING
            session_result = await db.execute(
                select(SearchSession).where(SearchSession.celery_job_id == job_id)
            )
            search_session = session_result.scalar_one_or_none()
            if search_session is not None:
                search_session.status = SearchSessionStatus.RUNNING
                search_session.started_at = datetime.now(UTC)
                await db.commit()

            try:
                # Run batch search with progress updates
                result = await _run_batch_search_with_progress(
                    task=task,
                    service=service,
                    project_id=UUID(project_id),
                    request=batch_request,
                    audio_files=audio_files_abs,
                    job_id=job_id,
                )
            except Exception as e:
                # Update session to FAILED
                if search_session is not None:
                    search_session.status = SearchSessionStatus.FAILED
                    search_session.error_message = str(e)
                    search_session.completed_at = datetime.now(UTC)
                    try:
                        await db.commit()
                    except Exception:
                        logger.exception("Failed to persist FAILED status for session job_id=%s", job_id)
                raise

            # Update session to COMPLETED
            if search_session is not None:
                search_session.status = SearchSessionStatus.COMPLETED
                search_session.results = result
                search_session.result_count = result.get("total_matches", 0)
                search_session.completed_at = datetime.now(UTC)
                try:
                    await db.commit()
                except Exception:
                    logger.exception("Failed to persist COMPLETED status for session job_id=%s", job_id)

        # Clean up temp files on success
        shutil.rmtree(tmp_dir, ignore_errors=True)

        return result

    finally:
        await engine.dispose()


async def _run_batch_search_with_progress(
    task: Any,
    service: Any,
    project_id: UUID,
    request: Any,
    audio_files: dict[str, str],
    job_id: str = "",
) -> dict[str, Any]:
    """Run batch search with per-species progress updates.

    Reuses SimilaritySearchService internals but adds Celery progress reporting.

    Args:
        task: Celery task for update_state calls
        service: SimilaritySearchService instance
        project_id: Project UUID
        request: BatchSearchRequest instance
        audio_files: Mapping of file_key to absolute local file paths
        job_id: Job ID used to locate the temp directory for S3 downloads

    Returns:
        Dict matching BatchSearchResponse schema with string UUIDs
    """
    import contextlib
    import os

    from sqlalchemy import text

    from echoroo.repositories.tag import TagRepository
    from echoroo.services.search import _STORAGE_EMBEDDING_DIM, _clip_audio, _get_or_load_model
    from echoroo.services.search import _download_audio_url as _download_audio_url_fn

    start_ts = time.monotonic()
    total_species = len(request.species)

    dataset_id: UUID | None = None
    if request.dataset_id is not None and request.dataset_id.strip() != "":
        try:
            dataset_id = UUID(request.dataset_id)
        except ValueError as exc:
            raise ValueError(f"Invalid dataset_id: {request.dataset_id!r}") from exc

    # Load model once for all species
    from echoroo.ml.registry import ModelNotFoundError, ModelRegistry

    try:
        _, engine = _get_or_load_model(request.model_name)
    except ModelNotFoundError as exc:
        available = ModelRegistry.available_models()
        raise ValueError(
            f"Model '{request.model_name}' not registered. Available: {available}"
        ) from exc

    results: dict[str, dict[str, Any]] = {}
    total_matches = 0

    for species_idx, species_cfg in enumerate(request.species):
        # Report progress before processing each species
        task.update_state(
            state="PROCESSING",
            meta={
                "species_completed": species_idx,
                "species_total": total_species,
            },
        )

        # Resolve or create the tag for this species
        tag_id_key: str
        common_name: str | None = None

        if species_cfg.tag_id is not None:
            tag_id_key = species_cfg.tag_id
            tag_sql = text("SELECT common_name FROM tags WHERE id = :tag_id LIMIT 1")
            tag_row = (
                await service.db.execute(tag_sql, {"tag_id": str(species_cfg.tag_id)})
            ).fetchone()
            if tag_row is not None:
                common_name = tag_row.common_name
        else:
            tag_repo = TagRepository(service.db)
            tag = await tag_repo.get_or_create_species(
                project_id=project_id,
                scientific_name=species_cfg.scientific_name,
                common_name=species_cfg.scientific_name,
            )
            tag_id_key = str(tag.id)
            common_name = tag.common_name

        # Collect all query vectors for this species across all sources
        query_vectors: list[list[float]] = []
        clipped_tmp_paths: list[str] = []

        for source in species_cfg.sources:
            if source.type == "url":
                if not source.source_url:
                    logger.warning(
                        "URL source for species '%s' has no source_url, skipping",
                        species_cfg.scientific_name,
                    )
                    continue

                downloaded_path = await _download_audio_url_fn(source.source_url)
                if downloaded_path is None:
                    logger.warning(
                        "Failed to download audio from URL '%s' for species '%s', skipping",
                        source.source_url,
                        species_cfg.scientific_name,
                    )
                    continue

                clipped_tmp_paths.append(downloaded_path)

                audio_path_for_inference = downloaded_path
                if source.start_time is not None or source.end_time is not None:
                    clipped_path = _clip_audio(
                        downloaded_path,
                        start_time=source.start_time,
                        end_time=source.end_time,
                    )
                    if clipped_path is not None:
                        clipped_tmp_paths.append(clipped_path)
                        audio_path_for_inference = clipped_path

                try:
                    inference_results = engine.predict_file(Path(audio_path_for_inference))
                except Exception:
                    logger.exception(
                        "Inference failed for URL source '%s', skipping",
                        source.source_url,
                    )
                    continue

                for inf_res in inference_results:
                    raw_emb: list[float] = inf_res.embedding.tolist()
                    if len(raw_emb) < _STORAGE_EMBEDDING_DIM:
                        raw_emb.extend([0.0] * (_STORAGE_EMBEDDING_DIM - len(raw_emb)))
                    query_vectors.append(raw_emb[:_STORAGE_EMBEDDING_DIM])

                continue

            # If source has an s3_key and no local file, download from S3
            if source.s3_key and (
                source.file_key is None or source.file_key not in audio_files
            ):
                from echoroo.core.s3 import get_s3_client as _get_s3_client

                _s3_client = _get_s3_client()
                _s3_settings = get_settings()
                _s3_tmp_dir = Path(f"/data/search_tmp/{job_id}") if job_id else Path("/tmp")
                _local_path = _s3_tmp_dir / Path(source.s3_key).name
                try:
                    _s3_client.download_file(
                        _s3_settings.S3_BUCKET, source.s3_key, str(_local_path)
                    )
                    src_path = str(_local_path)
                except Exception:
                    logger.exception(
                        "Failed to download S3 reference audio key='%s', skipping",
                        source.s3_key,
                    )
                    continue
            elif source.file_key is None or source.file_key not in audio_files:
                logger.warning(
                    "Missing audio file for key '%s', skipping source",
                    source.file_key,
                )
                continue
            else:
                src_path = audio_files[source.file_key]

            audio_path_for_inference = src_path
            if source.start_time is not None or source.end_time is not None:
                clipped_path = _clip_audio(
                    src_path,
                    start_time=source.start_time,
                    end_time=source.end_time,
                )
                if clipped_path is not None:
                    clipped_tmp_paths.append(clipped_path)
                    audio_path_for_inference = clipped_path

            try:
                inference_results = engine.predict_file(Path(audio_path_for_inference))
            except Exception:
                logger.exception(
                    "Inference failed for source '%s', skipping",
                    source.file_key,
                )
                continue

            for inf_res in inference_results:
                upload_emb: list[float] = inf_res.embedding.tolist()
                if len(upload_emb) < _STORAGE_EMBEDDING_DIM:
                    upload_emb.extend([0.0] * (_STORAGE_EMBEDDING_DIM - len(upload_emb)))
                query_vectors.append(upload_emb[:_STORAGE_EMBEDDING_DIM])

        # Clean up clipped temp files for this source set
        for tmp_p in clipped_tmp_paths:
            with contextlib.suppress(OSError):
                os.unlink(tmp_p)

        if not query_vectors:
            logger.warning(
                "No valid query vectors generated for species '%s', skipping",
                species_cfg.scientific_name,
            )
            results[tag_id_key] = {
                "tag_id": tag_id_key,
                "scientific_name": species_cfg.scientific_name,
                "common_name": common_name,
                "matches": [],
            }
            continue

        # Search using each query vector and aggregate by max similarity
        best_by_candidate: dict[str, dict[str, Any]] = {}

        for qv in query_vectors:
            vec_results = await service.search_by_vector(
                project_id=project_id,
                query_vector=qv,
                model_name=request.model_name,
                limit=request.limit_per_species * 3,
                min_similarity=request.min_similarity,
                dataset_id=dataset_id,
            )
            for sim_result in vec_results:
                candidate_key = str(sim_result.embedding_id)
                existing = best_by_candidate.get(candidate_key)
                if existing is None or sim_result.similarity > existing["similarity"]:
                    best_by_candidate[candidate_key] = {
                        "embedding_id": str(sim_result.embedding_id),
                        "recording_id": str(sim_result.recording_id),
                        "recording_filename": sim_result.recording_filename,
                        "dataset_id": str(sim_result.dataset_id),
                        "start_time": sim_result.start_time,
                        "end_time": sim_result.end_time,
                        "similarity": sim_result.similarity,
                    }

        # Sort by descending similarity and truncate
        sorted_matches = sorted(
            best_by_candidate.values(),
            key=lambda r: r["similarity"],
            reverse=True,
        )[: request.limit_per_species]

        total_matches += len(sorted_matches)
        results[tag_id_key] = {
            "tag_id": tag_id_key,
            "scientific_name": species_cfg.scientific_name,
            "common_name": common_name,
            "matches": sorted_matches,
        }

        logger.info(
            "Batch search: species='%s' query_vectors=%d matches=%d",
            species_cfg.scientific_name,
            len(query_vectors),
            len(sorted_matches),
        )

    elapsed_ms = int((time.monotonic() - start_ts) * 1000)

    return {
        "results": results,
        "total_matches": total_matches,
        "search_duration_ms": elapsed_ms,
    }
