"""ML worker tasks package.

Re-exports all Celery tasks from sub-modules for backward compatibility.
Task names are preserved as ``echoroo.workers.ml_tasks.*`` so existing
Celery queues and routes continue to work without changes.

Sub-modules:
- utils.py     : shared helper functions (embedding ops, DB bulk insert, etc.)
- detection.py : BirdNET / generic detection tasks
- embedding.py : embedding generation tasks
"""

from echoroo.workers.ml.detection import run_birdnet_detection, run_detection
from echoroo.workers.ml.embedding import run_embedding_generation
from echoroo.workers.ml.utils import (
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
