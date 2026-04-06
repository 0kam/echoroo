"""Shared utility functions for ML worker tasks.

Contains helper functions used by both detection and embedding pipelines:
- Embedding manipulation (padding, extraction, masking)
- S3 download helpers
- Species collection and DB cache building
- Bulk annotation insertion
- DetectionRun failure marking
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation import Annotation
from echoroo.models.enums import DetectionRunStatus
from echoroo.models.tag import Tag
from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.services.audio import AudioService
from echoroo.services.gbif import NON_SPECIES_LABELS
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DetectionRun failure helper
# ---------------------------------------------------------------------------


async def _mark_detection_run_failed(run_id: UUID, error: str) -> None:
    """Mark a detection run as FAILED with an error message.

    Args:
        run_id: DetectionRun's UUID.
        error: Error message to store on the run.
    """
    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            run_repo = DetectionRunRepository(db)
            run = await run_repo.get_by_id(run_id)
            if run is not None:
                run.status = DetectionRunStatus.FAILED
                run.completed_at = datetime.now(UTC)
                run.error_message = error
                await run_repo.update(run)
                await db.commit()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Storage dimension for embedding vectors (max across all supported models)
# ---------------------------------------------------------------------------

_STORAGE_EMBEDDING_DIM = 1536  # Perch V2 dimension; BirdNET (1024) is zero-padded


def _pad_embedding(
    embedding: np.ndarray[Any, np.dtype[np.float32]], target_dim: int
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Zero-pad an embedding vector to the target dimension.

    Args:
        embedding: 1-D float32 array of shape (source_dim,).
        target_dim: Target dimension to pad to.

    Returns:
        1-D float32 array of shape (target_dim,).
        If embedding.shape[0] >= target_dim, returned as-is (truncated if needed).
    """
    source_dim = embedding.shape[0]
    if source_dim == target_dim:
        return embedding
    if source_dim > target_dim:
        return embedding[:target_dim]
    padded: np.ndarray[Any, np.dtype[np.float32]] = np.pad(
        embedding, (0, target_dim - source_dim), mode="constant"
    ).astype(np.float32)
    return padded


# ---------------------------------------------------------------------------
# Embedding extraction helpers
# ---------------------------------------------------------------------------


def _extract_batch_embeddings(
    batch_result: Any,
) -> tuple[np.ndarray[Any, np.dtype[np.float32]], np.ndarray[Any, Any] | None]:
    """Extract embeddings array and optional mask from a batch encode/predict result.

    Converts the ``embeddings`` attribute (which may be a torch Tensor or
    numpy array) to a float32 numpy array.  Also extracts the
    ``embeddings_masked`` attribute if present (Perch only).

    Args:
        batch_result: Result object from ``encode_batch()`` or
            ``predict_files_batch()`` that carries ``.embeddings`` and
            optionally ``.embeddings_masked``.

    Returns:
        Tuple of (embeddings_array, mask_or_None).
    """
    raw = batch_result.embeddings
    if hasattr(raw, "numpy"):
        raw = raw.numpy()
    embeddings: np.ndarray[Any, np.dtype[np.float32]] = np.asarray(raw, dtype=np.float32)

    mask: np.ndarray[Any, Any] | None = None
    if hasattr(batch_result, "embeddings_masked"):
        raw_masked = batch_result.embeddings_masked
        if hasattr(raw_masked, "numpy"):
            raw_masked = raw_masked.numpy()
        mask = np.asarray(raw_masked)

    return embeddings, mask


def _extract_file_embeddings(
    all_embeddings: np.ndarray[Any, np.dtype[np.float32]],
    all_mask: np.ndarray[Any, Any] | None,
    file_index: int,
) -> tuple[np.ndarray[Any, np.dtype[np.float32]], np.ndarray[Any, Any] | None]:
    """Extract a single file's embeddings and mask from batch result arrays.

    Handles both 4-D ``(n_files, 1, n_segments, dim)`` and 3-D
    ``(n_files, n_segments, dim)`` shapes produced by different model versions.

    Args:
        all_embeddings: Full batch embeddings array.
        all_mask: Full batch mask array, or *None*.
        file_index: Index of the file within the batch.

    Returns:
        Tuple of (file_embeddings, file_mask_or_None) where
        ``file_embeddings`` has shape ``(n_segments, dim)``.
    """
    file_mask: np.ndarray[Any, Any] | None = None

    if all_embeddings.ndim == 4:
        file_embeddings = all_embeddings[file_index, 0]
        if all_mask is not None:
            file_mask = all_mask[file_index, 0]
    elif all_embeddings.ndim == 3:
        file_embeddings = all_embeddings[file_index]
        if all_mask is not None:
            file_mask = all_mask[file_index]
    else:
        # Single-file fallback (should not occur in batch mode)
        file_embeddings = all_embeddings
        file_mask = all_mask

    return file_embeddings, file_mask


def _apply_embedding_mask(
    file_embeddings: np.ndarray[Any, np.dtype[np.float32]],
    file_mask: np.ndarray[Any, Any] | None,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Apply per-element mask to filter valid segments.

    Reduces a per-element boolean mask to a per-segment boolean and
    removes masked (invalid) segments from the embeddings array.

    Args:
        file_embeddings: Embeddings for one file, shape ``(n_segments, dim)``.
        file_mask: Per-element mask for the same file, or *None*.

    Returns:
        Filtered embeddings array containing only valid segments.
    """
    if file_mask is None:
        return file_embeddings

    seg_masked = file_mask.all(axis=1) if file_mask.ndim == 2 else file_mask.flatten()
    keep = ~seg_masked
    return file_embeddings[keep]


# ---------------------------------------------------------------------------
# S3 download helper
# ---------------------------------------------------------------------------


def _download_recordings_to_local(
    recordings: list[Any],
    audio_service: AudioService,
) -> tuple[list[tuple[Any, Path]], int]:
    """Download recording files from S3 and return list of (recording, local_path) tuples.

    Skips recordings whose files cannot be downloaded, logging warnings for
    each failure.

    Args:
        recordings: List of Recording ORM objects.
        audio_service: AudioService instance for file access.

    Returns:
        Tuple of (recording_paths, failed_count) where *recording_paths* is
        a list of ``(recording_orm, local_path)`` pairs and *failed_count*
        is the number of recordings that could not be downloaded.
    """
    recording_paths: list[tuple[Any, Path]] = []
    failed = 0
    for recording in recordings:
        try:
            local_path = audio_service.ensure_file_local(recording.path)
            if local_path:
                recording_paths.append((recording, Path(local_path)))
            else:
                logger.warning(
                    "Audio file not found for recording %s (%s)",
                    recording.id,
                    recording.filename,
                )
                failed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to download audio for recording %s (%s): %s",
                recording.id,
                recording.filename,
                exc,
            )
            failed += 1
    return recording_paths, failed


# ---------------------------------------------------------------------------
# Species collection helpers
# ---------------------------------------------------------------------------


def _collect_unique_species_from_batch(
    predictions_result: Any,
    inference_engine: Any,
) -> dict[str, tuple[str, str, bool]]:
    """Collect all unique species names predicted across all files in a batch result.

    Parses the raw batch prediction result to find every unique species that
    appears with confidence above threshold. Returns a mapping from scientific_name
    to (scientific_name, common_name, is_non_biological) so callers can build DB caches.

    Args:
        predictions_result: Raw result from ``predict_files_batch()``.
        inference_engine: The inference engine instance (used for _filter_predictions).

    Returns:
        Dict mapping scientific_name -> (scientific_name, common_name, is_non_biological).
    """
    unique_species: dict[str, tuple[str, str, bool]] = {}

    all_probs = getattr(predictions_result, "species_probs", None)
    all_ids = getattr(predictions_result, "species_ids", None)
    if all_probs is None or all_ids is None or all_probs.size == 0:
        return unique_species

    # Flatten to 3D: (n_files, n_segments, n_species_candidates)
    if all_probs.ndim == 4:
        probs_3d = all_probs[:, 0, :, :]
        ids_3d = all_ids[:, 0, :, :]
    elif all_probs.ndim == 3:
        probs_3d = all_probs
        ids_3d = all_ids
    else:
        return unique_species

    n_files = probs_3d.shape[0]
    has_filter = hasattr(inference_engine, "_filter_predictions")
    species_list = getattr(getattr(inference_engine, "_model", None), "species_list", [])

    for file_idx in range(n_files):
        file_probs = probs_3d[file_idx]
        file_ids = ids_3d[file_idx]
        for seg_idx in range(len(file_probs)):
            if has_filter and species_list:
                preds = inference_engine._filter_predictions(
                    file_probs[seg_idx].astype(np.float32),
                    file_ids[seg_idx],
                    species_list,
                )
            else:
                preds = []
            for species_name, _conf in preds:
                parts = species_name.split("_", 1)
                scientific_name = parts[0] if parts else species_name
                common_name = parts[1] if len(parts) > 1 else ""
                is_non_bio = common_name in NON_SPECIES_LABELS
                if scientific_name not in unique_species:
                    unique_species[scientific_name] = (scientific_name, common_name, is_non_bio)

    return unique_species


async def _build_taxon_tag_caches(
    db: AsyncSession,
    project_uuid: UUID,
    unique_species: dict[str, tuple[str, str, bool]],
) -> tuple[dict[str, Taxon], dict[str, Tag]]:
    """Batch-fetch taxons and tags for all known species, returning in-memory caches.

    Queries the DB once for all species names rather than one query per species.
    New taxons and tags for species not yet in the DB are created in bulk and
    added to the caches.

    Args:
        db: SQLAlchemy async session (must be inside an active transaction).
        project_uuid: Project UUID used to scope tag lookups.
        unique_species: Mapping from scientific_name -> (sci, common, is_non_bio).

    Returns:
        Tuple of (taxon_cache, tag_cache) where keys are scientific_name strings.
    """
    if not unique_species:
        return {}, {}

    sci_names = list(unique_species.keys())

    # Batch-fetch existing taxons
    taxon_result = await db.execute(
        select(Taxon).where(Taxon.scientific_name.in_(sci_names))
    )
    taxon_cache: dict[str, Taxon] = {t.scientific_name: t for t in taxon_result.scalars().all()}

    # Create missing taxons one-by-one (rare: only new species)
    for sci_name, (_, common_name, is_non_bio) in unique_species.items():
        if sci_name not in taxon_cache:
            taxon = Taxon(
                scientific_name=sci_name,
                is_non_biological=is_non_bio,
            )
            db.add(taxon)
            await db.flush()
            if common_name:
                vn = TaxonVernacularName(
                    taxon_id=taxon.id,
                    locale="en",
                    name=common_name,
                    source="birdnet",
                    is_primary=True,
                )
                db.add(vn)
                await db.flush()
            taxon_cache[sci_name] = taxon

    # Batch-fetch existing tags for this project
    tag_result = await db.execute(
        select(Tag).where(
            Tag.project_id == project_uuid,
            Tag.scientific_name.in_(sci_names),
        )
    )
    tag_cache: dict[str, Tag] = {
        t.scientific_name: t for t in tag_result.scalars().all() if t.scientific_name
    }

    # Create missing tags one-by-one (rare: only new species)
    from echoroo.models.enums import TagCategory

    for sci_name, (_, common_name, _is_non_bio) in unique_species.items():
        if sci_name not in tag_cache:
            maybe_taxon: Taxon | None = taxon_cache.get(sci_name)
            tag = Tag(
                project_id=project_uuid,
                name=sci_name,
                category=TagCategory.SPECIES,
                scientific_name=sci_name,
                common_name=common_name,
                taxon_id=maybe_taxon.id if maybe_taxon else None,
            )
            db.add(tag)
            await db.flush()
            tag_cache[sci_name] = tag
        else:
            # Update taxon_id if missing
            existing_tag = tag_cache[sci_name]
            if existing_tag.taxon_id is None:
                update_taxon: Taxon | None = taxon_cache.get(sci_name)
                if update_taxon:
                    existing_tag.taxon_id = update_taxon.id
                    await db.flush()

    return taxon_cache, tag_cache


# ---------------------------------------------------------------------------
# Bulk annotation insertion
# ---------------------------------------------------------------------------


async def _bulk_insert_annotations(
    db: AsyncSession,
    annotation_dicts: list[dict[str, Any]],
) -> int:
    """Bulk-insert annotations using raw SQL, skipping any duplicates.

    Much faster than ORM create_batch() because it avoids per-row refresh
    and relationship loading. Uses INSERT ... ON CONFLICT DO NOTHING to
    handle any potential duplicates from retries.

    Args:
        db: SQLAlchemy async session.
        annotation_dicts: List of dicts with annotation field values.

    Returns:
        Number of rows actually inserted.
    """
    if not annotation_dicts:
        return 0

    # PostgreSQL limits query parameters to 32767. Each annotation has ~11 columns,
    # so chunk to 2000 rows per batch (2000 * 11 = 22000, safely under the limit).
    BATCH_CHUNK_SIZE = 2000
    total_inserted = 0
    for i in range(0, len(annotation_dicts), BATCH_CHUNK_SIZE):
        chunk = annotation_dicts[i : i + BATCH_CHUNK_SIZE]
        stmt = pg_insert(Annotation).values(chunk).on_conflict_do_nothing()
        cursor: CursorResult[tuple[()]] = await db.execute(stmt)  # type: ignore[assignment]
        total_inserted += cursor.rowcount
    return total_inserted
