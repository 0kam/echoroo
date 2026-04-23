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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.s3 import (
    S3ObjectMeta,
    delete_objects_batch,
    delete_objects_by_prefix,
    list_objects_paginated,
)
from echoroo.core.settings import get_settings
from echoroo.workers.celery_app import app
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)


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
    engine, session_factory = get_worker_engine_and_session_factory()

    try:
        async with session_factory() as db:
            from echoroo.models.enums import SearchSessionStatus
            from echoroo.models.search_session import SearchSession
            from echoroo.services.search import SimilaritySearchService

            service = SimilaritySearchService(db)

            # Update session status to RUNNING
            # Scope lookup by (celery_job_id, project_id) to match other call sites
            # (api/v1/search/batch.py, services/search_session.py) and provide
            # defence-in-depth beyond the unique constraint on celery_job_id.
            session_result = await db.execute(
                select(SearchSession).where(
                    SearchSession.celery_job_id == job_id,
                    SearchSession.project_id == UUID(project_id),
                )
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
                    search_session=search_session,
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
    search_session: Any = None,
) -> dict[str, Any]:
    """Run batch search with per-species progress updates.

    Reuses SimilaritySearchService internals but adds Celery progress reporting.

    For each species, audio preparation (download/clip) is separated from model
    inference. All prepared files are passed to ``predict_files_batch()`` in a
    single call so that XLA compilation happens only once instead of once per file.

    Args:
        task: Celery task for update_state calls
        service: SimilaritySearchService instance
        project_id: Project UUID
        request: BatchSearchRequest instance
        audio_files: Mapping of file_key to absolute local file paths
        job_id: Job ID used to locate the temp directory for S3 downloads
        search_session: Optional SearchSession ORM object for persisting query embeddings

    Returns:
        Dict matching BatchSearchResponse schema with string UUIDs
    """
    import contextlib
    import os

    import numpy as np
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

        # ------------------------------------------------------------------
        # Phase 1: Download / clip ALL reference audio files for this species.
        # Each entry in reference_paths corresponds to one source; inference
        # is deferred to Phase 2 so that all files can be submitted as a
        # single batch call.
        # ------------------------------------------------------------------
        # reference_paths: list of (audio_path_for_inference, [clipped_tmp_paths])
        reference_paths: list[str] = []
        # Track per-source temp files for cleanup after inference
        all_clipped_tmp_paths: list[str] = []
        # For each reference_paths entry, record its source label for logging
        source_labels: list[str] = []
        # Track sources that failed during download/clip (no entry in reference_paths)
        skipped_sources: list[str] = []

        for source in species_cfg.sources:
            if source.type == "url":
                if not source.source_url:
                    logger.warning(
                        "URL source for species '%s' has no source_url, skipping",
                        species_cfg.scientific_name,
                    )
                    skipped_sources.append("url:no_url")
                    continue

                downloaded_path = await _download_audio_url_fn(source.source_url)
                if downloaded_path is None:
                    logger.warning(
                        "Failed to download audio from URL '%s' for species '%s', skipping",
                        source.source_url,
                        species_cfg.scientific_name,
                    )
                    skipped_sources.append(f"url:{source.source_url}")
                    continue

                all_clipped_tmp_paths.append(downloaded_path)
                audio_path_for_inference = downloaded_path

                if source.start_time is not None or source.end_time is not None:
                    clipped_path = _clip_audio(
                        downloaded_path,
                        start_time=source.start_time,
                        end_time=source.end_time,
                    )
                    if clipped_path is not None:
                        all_clipped_tmp_paths.append(clipped_path)
                        audio_path_for_inference = clipped_path

                reference_paths.append(audio_path_for_inference)
                source_labels.append(f"url:{source.source_url}")
                continue

            # Resolve upload / S3 source to a local file path
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
                    skipped_sources.append(f"s3:{source.s3_key}")
                    continue
            elif source.file_key is None or source.file_key not in audio_files:
                logger.warning(
                    "Missing audio file for key '%s', skipping source",
                    source.file_key,
                )
                skipped_sources.append(f"upload:{source.file_key}")
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
                    all_clipped_tmp_paths.append(clipped_path)
                    audio_path_for_inference = clipped_path

            reference_paths.append(audio_path_for_inference)
            source_labels.append(f"upload:{source.file_key}")

        # ------------------------------------------------------------------
        # Phase 2: Inference — embed all reference files to query vectors.
        #
        # Fast path (perch model only): use PerchDirectInference which calls
        # the TF SavedModel directly, bypassing birdnet's multiprocess pipeline.
        # This reduces latency from ~38s to ~0.007s per segment (warm).
        #
        # Fallback path 1: birdnet predict_files_batch() — single batch call.
        # Fallback path 2: per-file predict_file() — original behaviour.
        # ------------------------------------------------------------------
        query_vectors: list[list[float]] = []

        if reference_paths:
            from echoroo.workers.model_preloader import get_direct_perch

            direct_perch = get_direct_perch()
            used_direct = False

            # Fast path: direct TF inference (perch only, engine must be loaded)
            if direct_perch is not None and request.model_name == "perch":
                try:
                    for file_path in reference_paths:
                        file_embeddings = direct_perch.encode_audio_file(str(file_path))
                        # file_embeddings shape: (n_segments, EMBEDDING_DIM)
                        for seg_emb in file_embeddings:
                            emb_list: list[float] = seg_emb.tolist()
                            if len(emb_list) < _STORAGE_EMBEDDING_DIM:
                                emb_list.extend(
                                    [0.0] * (_STORAGE_EMBEDDING_DIM - len(emb_list))
                                )
                            query_vectors.append(emb_list[:_STORAGE_EMBEDDING_DIM])

                    logger.info(
                        "Direct TF inference for species='%s': %d files -> %d query vectors",
                        species_cfg.scientific_name,
                        len(reference_paths),
                        len(query_vectors),
                    )
                    used_direct = True
                except Exception:
                    logger.exception(
                        "Direct TF inference failed for species '%s', "
                        "falling back to birdnet pipeline",
                        species_cfg.scientific_name,
                    )
                    query_vectors = []

            if not used_direct:
                # Fallback path 1: birdnet predict_files_batch() when available
                use_batch = hasattr(engine, "predict_files_batch")
                if use_batch:
                    # Cast to Any so mypy does not require predict_files_batch on the
                    # base InferenceEngine type — the hasattr guard above ensures safety.
                    _batch_engine: Any = engine
                    try:
                        embeddings_result, _predictions_result = _batch_engine.predict_files_batch(
                            reference_paths
                        )
                        # Extract raw embeddings array: shape (n_files, [1,] n_segments, dim)
                        raw_emb_arr = embeddings_result.embeddings
                        if hasattr(raw_emb_arr, "numpy"):
                            raw_emb_arr = raw_emb_arr.numpy()
                        all_embeddings: np.ndarray[Any, np.dtype[np.float32]] = np.asarray(
                            raw_emb_arr, dtype=np.float32
                        )

                        # Extract optional per-element mask (Perch only)
                        all_mask: np.ndarray[Any, Any] | None = None
                        if hasattr(embeddings_result, "embeddings_masked"):
                            raw_masked = embeddings_result.embeddings_masked
                            if hasattr(raw_masked, "numpy"):
                                raw_masked = raw_masked.numpy()
                            all_mask = np.asarray(raw_masked)

                        for file_index, _file_path in enumerate(reference_paths):
                            # Slice this file's embeddings from the batch array.
                            # Batch shape: (n_files, 1, n_segments, dim) or (n_files, n_segments, dim)
                            if all_embeddings.ndim == 4:
                                file_embeddings_b = all_embeddings[file_index, 0]  # (n_seg, dim)
                                file_mask = (
                                    all_mask[file_index, 0]
                                    if all_mask is not None
                                    else None
                                )
                            elif all_embeddings.ndim == 3:
                                file_embeddings_b = all_embeddings[file_index]  # (n_seg, dim)
                                file_mask = (
                                    all_mask[file_index] if all_mask is not None else None
                                )
                            else:
                                # Single-file fallback (should not occur in batch mode)
                                file_embeddings_b = all_embeddings
                                file_mask = all_mask

                            # Apply masking to filter silent/invalid segments
                            if file_mask is not None:
                                seg_masked = (
                                    file_mask.all(axis=1)
                                    if file_mask.ndim == 2
                                    else file_mask.flatten()
                                )
                                keep = ~seg_masked
                                file_embeddings_b = file_embeddings_b[keep]

                            # Accumulate one embedding vector per segment
                            for seg_emb_b in file_embeddings_b:
                                emb_list_b: list[float] = seg_emb_b.tolist()
                                if len(emb_list_b) < _STORAGE_EMBEDDING_DIM:
                                    emb_list_b.extend(
                                        [0.0] * (_STORAGE_EMBEDDING_DIM - len(emb_list_b))
                                    )
                                query_vectors.append(emb_list_b[:_STORAGE_EMBEDDING_DIM])

                        logger.info(
                            "Batch inference for species='%s': %d files -> %d query vectors",
                            species_cfg.scientific_name,
                            len(reference_paths),
                            len(query_vectors),
                        )
                    except Exception:
                        logger.exception(
                            "Batch inference failed for species '%s', falling back to per-file",
                            species_cfg.scientific_name,
                        )
                        # Reset and fall through to per-file fallback
                        query_vectors = []
                        use_batch = False

                if not use_batch:
                    # Fallback path 2: per-file — preserved original behaviour
                    for file_path, label in zip(reference_paths, source_labels, strict=False):
                        try:
                            inference_results = engine.predict_file(Path(file_path))
                        except Exception:
                            logger.exception(
                                "Inference failed for source '%s', skipping", label
                            )
                            continue
                        for inf_res in inference_results:
                            emb_list_pf: list[float] = inf_res.embedding.tolist()
                            if len(emb_list_pf) < _STORAGE_EMBEDDING_DIM:
                                emb_list_pf.extend(
                                    [0.0] * (_STORAGE_EMBEDDING_DIM - len(emb_list_pf))
                                )
                            query_vectors.append(emb_list_pf[:_STORAGE_EMBEDDING_DIM])

        # Clean up all clipped/downloaded temp files for this species
        for tmp_p in all_clipped_tmp_paths:
            with contextlib.suppress(OSError):
                os.unlink(tmp_p)

        # Persist query vectors to the database for later reuse as training examples.
        # This runs regardless of whether vectors were found, so we only save when
        # there are vectors and a search session is associated with the job.
        if query_vectors and search_session is not None:
            from echoroo.models.search_query_embedding import SearchQueryEmbedding

            source_label: str | None = (
                species_cfg.scientific_name
                if hasattr(species_cfg, "scientific_name")
                else None
            )
            for qv in query_vectors:
                service.db.add(
                    SearchQueryEmbedding(
                        search_session_id=search_session.id,
                        species_key=tag_id_key,
                        source_label=source_label,
                        vector=qv,
                    )
                )
            try:
                await service.db.flush()
            except Exception:
                logger.exception(
                    "Failed to persist query embeddings for species='%s' session=%s",
                    species_cfg.scientific_name,
                    search_session.id,
                )

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
                        "recording_datetime": (
                            sim_result.recording_datetime.isoformat()
                            if sim_result.recording_datetime is not None
                            else None
                        ),
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


# ---------------------------------------------------------------------------
# Orphan S3 janitor for search_reference/ prefix
# ---------------------------------------------------------------------------

SEARCH_REFERENCE_PREFIX = "search_reference/"


def _parse_search_reference_key(key: str) -> tuple[UUID, str, str] | None:
    """Parse a search_reference/{project_uuid}/{job_id}/{file} key.

    Returns (project_id, job_id, file_part) or None if the key does not match
    the expected layout or has a non-UUID project_id. Non-UUID project_id
    values are treated as malformed and skipped to avoid accidental deletion
    of unrelated legacy keys.
    """
    if not key.startswith(SEARCH_REFERENCE_PREFIX):
        return None
    remainder = key[len(SEARCH_REFERENCE_PREFIX) :]
    parts = remainder.split("/", 2)
    if len(parts) < 3:
        return None
    try:
        project_id = UUID(parts[0])
    except ValueError:
        return None
    job_id = parts[1]
    if not job_id:
        return None
    return (project_id, job_id, parts[2])


def _extract_species_config_s3_keys(species_config: Any) -> list[str]:
    """Extract all s3_key values from a species_config JSONB structure.

    Expected shape: list[{"sources": [{"s3_key": "..."}, ...], ...}, ...].
    Defensive against None / non-list inputs and malformed nested shapes.
    """
    if not species_config or not isinstance(species_config, list):
        return []
    keys: list[str] = []
    for species in species_config:
        if not isinstance(species, dict):
            continue
        sources = species.get("sources")
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            s3_key = source.get("s3_key")
            if isinstance(s3_key, str) and s3_key:
                keys.append(s3_key)
    return keys


async def _collect_db_reference_state(
    db: AsyncSession,
) -> tuple[set[str], set[tuple[UUID, str]]]:
    """Collect known S3 keys and (project_id, celery_job_id) tuples from the DB.

    Returns:
        Tuple of ``(known_keys, known_job_prefixes)`` where:
          - ``known_keys``: all S3 keys referenced by any SearchSession (via
            ``reference_audio_keys`` or ``species_config[*].sources[*].s3_key``).
          - ``known_job_prefixes``: ``(project_id, celery_job_id)`` pairs for
            sessions that have a celery_job_id, used to short-circuit Case A
            prefix-level deletion so we never delete the prefix of an active /
            recorded session.
    """
    from echoroo.models.search_session import SearchSession

    stmt = select(
        SearchSession.project_id,
        SearchSession.celery_job_id,
        SearchSession.reference_audio_keys,
        SearchSession.species_config,
    )
    result = await db.execute(stmt)
    known_keys: set[str] = set()
    known_job_prefixes: set[tuple[UUID, str]] = set()
    for project_id, celery_job_id, ref_keys, species_config in result.all():
        if ref_keys:
            for key in ref_keys:
                if isinstance(key, str) and key:
                    known_keys.add(key)
        known_keys.update(_extract_species_config_s3_keys(species_config))
        if celery_job_id:
            known_job_prefixes.add((project_id, str(celery_job_id)))
    return known_keys, known_job_prefixes


def _classify_orphans(
    aged_objects: list[S3ObjectMeta],
    known_keys: set[str],
    known_job_prefixes: set[tuple[UUID, str]],
) -> tuple[dict[tuple[UUID, str], list[S3ObjectMeta]], list[S3ObjectMeta]]:
    """Classify orphan S3 objects into prefix-level and individual deletions.

    Prefix-level candidates are job prefixes where:
      - ``(project_id, job_id)`` is not in ``known_job_prefixes`` (no session
        with this celery_job_id exists), AND
      - none of the keys under this prefix are in ``known_keys``.

    Individual candidates are orphan keys under prefixes that have at least
    some DB-referenced keys (Case B/C mixed-state prefixes), or whose job
    prefix matches an active session.

    Keys whose prefix cannot be parsed are skipped entirely — they are not
    considered orphans and are not deleted by this janitor.
    """
    grouped: dict[tuple[UUID, str], list[S3ObjectMeta]] = {}
    for obj in aged_objects:
        parsed = _parse_search_reference_key(obj.key)
        if parsed is None:
            logger.debug("janitor: skipping unparseable key: %s", obj.key)
            continue
        project_id, job_id, _ = parsed
        grouped.setdefault((project_id, job_id), []).append(obj)

    prefix_groups: dict[tuple[UUID, str], list[S3ObjectMeta]] = {}
    individual: list[S3ObjectMeta] = []
    for (project_id, job_id), objs in grouped.items():
        if (project_id, job_id) in known_job_prefixes:
            # A session exists for this job; delete only keys NOT referenced.
            for obj in objs:
                if obj.key not in known_keys:
                    individual.append(obj)
            continue
        # No session with this celery_job_id. If ANY key under this prefix is
        # still referenced (e.g. a rerun copied it forward) keep safely and
        # delete only the unreferenced subset individually.
        any_referenced = any(obj.key in known_keys for obj in objs)
        if any_referenced:
            for obj in objs:
                if obj.key not in known_keys:
                    individual.append(obj)
        else:
            prefix_groups[(project_id, job_id)] = objs
    return prefix_groups, individual


async def _run_orphan_search_reference_cleanup() -> dict[str, Any]:
    """Async implementation of the orphan janitor for search_reference/ prefix.

    Ordering:
      1. List S3 objects under ``search_reference/`` BEFORE reading the DB.
         This biases the race toward false NEGATIVES (miss some orphans this
         run, pick them up next run) rather than false positives (deleting
         a key that was just committed to the DB).
      2. Read DB reference state.
      3. Age filter (default ``JANITOR_AGE_HOURS`` = 24h).
      4. Classify into prefix-level vs individual deletions.
      5. Delete (or log-only when ``JANITOR_DRY_RUN`` is true).
    """
    settings = get_settings()
    dry_run = settings.JANITOR_DRY_RUN
    cutoff = datetime.now(UTC) - timedelta(hours=settings.JANITOR_AGE_HOURS)

    # Step 1: list S3 objects FIRST (before DB read).
    all_objects = list(list_objects_paginated(SEARCH_REFERENCE_PREFIX))
    total_scanned = len(all_objects)

    # Step 2: read DB reference state AFTER the S3 list has been materialised.
    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            known_keys, known_job_prefixes = await _collect_db_reference_state(db)
    finally:
        await engine.dispose()

    # Step 3: age filter.
    aged = [obj for obj in all_objects if obj.last_modified < cutoff]

    # Step 4: classify.
    prefix_groups, individual_orphans = _classify_orphans(
        aged, known_keys, known_job_prefixes
    )

    prefix_delete_count = sum(len(objs) for objs in prefix_groups.values())
    total_orphan_keys = prefix_delete_count + len(individual_orphans)

    if dry_run:
        logger.info(
            "janitor: DRY RUN -- would delete %d prefix groups (%d keys) + %d individual keys",
            len(prefix_groups),
            prefix_delete_count,
            len(individual_orphans),
        )
        for (pid, jid), objs in prefix_groups.items():
            logger.info(
                "janitor: DRY RUN prefix delete search_reference/%s/%s/ (%d keys)",
                pid,
                jid,
                len(objs),
            )
        for obj in individual_orphans[:50]:  # truncate log volume
            logger.info("janitor: DRY RUN individual delete %s", obj.key)
        return {
            "dry_run": True,
            "total_scanned": total_scanned,
            "prefix_groups": len(prefix_groups),
            "prefix_keys": prefix_delete_count,
            "individual_keys": len(individual_orphans),
            "deleted": 0,
            "failed": 0,
        }

    deleted_count = 0
    failed_count = 0

    # Case A optimisation: prefix-level bulk delete.
    for (pid, jid), objs in prefix_groups.items():
        try:
            n = delete_objects_by_prefix(f"{SEARCH_REFERENCE_PREFIX}{pid}/{jid}/")
            deleted_count += n
            logger.info(
                "janitor: prefix deleted search_reference/%s/%s/ (%d keys)",
                pid,
                jid,
                n,
            )
        except Exception as exc:  # best-effort; next run picks it up
            failed_count += len(objs)
            logger.warning(
                "janitor: prefix delete failed for search_reference/%s/%s/: %s",
                pid,
                jid,
                exc,
            )

    # Case B/C: individual keys, chunked to 1000 per s3:DeleteObjects call.
    chunk_size = 1000
    for i in range(0, len(individual_orphans), chunk_size):
        chunk = individual_orphans[i : i + chunk_size]
        keys = [obj.key for obj in chunk]
        try:
            result = delete_objects_batch(keys)
            deleted_count += len(result.deleted)
            failed_count += len(result.errors)
            if result.errors:
                sample = [(e.key, e.code, e.message) for e in result.errors[:10]]
                logger.warning(
                    "janitor: partial batch deletion failure (%d errors); sample=%s",
                    len(result.errors),
                    sample,
                )
        except Exception as exc:
            failed_count += len(chunk)
            logger.warning("janitor: batch delete raised: %s", exc)

    logger.info(
        "janitor: complete. scanned=%d total_orphans=%d deleted=%d failed=%d",
        total_scanned,
        total_orphan_keys,
        deleted_count,
        failed_count,
    )

    return {
        "dry_run": False,
        "total_scanned": total_scanned,
        "prefix_groups": len(prefix_groups),
        "prefix_keys": prefix_delete_count,
        "individual_keys": len(individual_orphans),
        "deleted": deleted_count,
        "failed": failed_count,
    }


@app.task(name="echoroo.workers.search_tasks.cleanup_orphan_search_reference")  # type: ignore[untyped-decorator]
def cleanup_orphan_search_reference() -> dict[str, Any]:
    """Remove orphan S3 objects under the ``search_reference/`` prefix.

    Detects keys that:
      - match ``search_reference/{valid_project_uuid}/{job_id}/{file}``
      - are older than ``JANITOR_AGE_HOURS`` (default 24h)
      - are not referenced by any SearchSession (via ``reference_audio_keys``
        or ``species_config[*].sources[*].s3_key``) AND whose
        ``(project_id, job_id)`` is not present in the known_job_prefixes set.

    For job prefixes where no key is DB-referenced AND celery_job_id is
    unknown, deletes the entire prefix in one batch (Case A optimisation).
    Otherwise deletes individual orphan keys via s3:DeleteObjects (chunked
    to 1000 keys per call).

    Honours ``JANITOR_DRY_RUN`` (default true) to log candidates without
    deleting.
    """
    logger.info("Starting orphan search_reference cleanup")
    return asyncio.run(_run_orphan_search_reference_cleanup())
