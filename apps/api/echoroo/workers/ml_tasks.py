"""Celery worker tasks for ML-based audio species detection.

This module is now a thin re-export shim. The actual implementation has been
split into the ``echoroo.workers.ml`` package:

- echoroo.workers.ml.detection  : BirdNET / generic detection tasks
- echoroo.workers.ml.embedding  : embedding generation tasks
- echoroo.workers.ml.utils      : shared helper functions

All Celery task names are preserved as ``echoroo.workers.ml_tasks.*`` so
existing queue routing and scheduled tasks continue to work without changes.

Tasks run outside FastAPI's async event loop, so async database calls
are executed via asyncio.run() in a sync Celery task context.
"""

from __future__ import annotations

# Re-export Celery tasks so that ``from echoroo.workers.ml_tasks import X``
# continues to work for existing callers (e.g. services/detection_run.py).
from echoroo.workers.ml.detection import run_birdnet_detection, run_detection
from echoroo.workers.ml.embedding import run_embedding_generation

# Re-export internal helpers for any code that imports them directly.
from echoroo.workers.ml.utils import (
    _STORAGE_EMBEDDING_DIM,
    _apply_embedding_mask,
    _build_taxon_tag_caches,
    _bulk_insert_annotations,
    _collect_unique_species_from_batch,
    _download_recordings_to_local,
    _extract_batch_embeddings,
    _extract_file_embeddings,
    _mark_detection_run_failed,
    _pad_embedding,
)

__all__ = [
    "run_birdnet_detection",
    "run_detection",
    "run_embedding_generation",
    "_STORAGE_EMBEDDING_DIM",
    "_apply_embedding_mask",
    "_build_taxon_tag_caches",
    "_bulk_insert_annotations",
    "_collect_unique_species_from_batch",
    "_download_recordings_to_local",
    "_extract_batch_embeddings",
    "_extract_file_embeddings",
    "_mark_detection_run_failed",
    "_pad_embedding",
]
