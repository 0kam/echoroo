"""Celery worker tasks for training custom SVM classifiers.

This module is now a thin re-export shim. The actual implementation has been
split into the ``echoroo.workers.classifier`` package:

- echoroo.workers.classifier.training        : train_custom_model task
- echoroo.workers.classifier.inference       : run_custom_model_inference task
- echoroo.workers.classifier.seed_sampling   : generate_seed_samples task
- echoroo.workers.classifier.active_learning : run_al_iteration task
- echoroo.workers.classifier.utils           : shared helper functions

All Celery task names are preserved as ``echoroo.workers.classifier_tasks.*``
so existing queue routing and scheduled tasks continue to work without
changes. Importing this module keeps the four tasks registered on the Celery
app (referenced by ``celery_app.py`` ``app.conf.include``).

Note: to mock these tasks in tests, patch the concrete sub-modules
(e.g. ``echoroo.workers.classifier.training``), not this façade.

Tasks run outside FastAPI's async event loop, so async database calls are
executed via asyncio.run() in a sync Celery task context.
"""

from __future__ import annotations

from echoroo.workers.classifier import (
    _download_model_from_s3,
    _fetch_training_embeddings,
    _fetch_unlabeled_embeddings,
    _generate_seed_samples,
    _parse_vectors,
    _run_al_iteration,
    _run_custom_model_inference,
    _run_training,
    _train_custom_model,
    _upload_model_to_s3,
    generate_seed_samples,
    run_al_iteration,
    run_custom_model_inference,
    train_custom_model,
)

__all__ = [
    "train_custom_model",
    "run_custom_model_inference",
    "generate_seed_samples",
    "run_al_iteration",
    "_train_custom_model",
    "_run_training",
    "_run_custom_model_inference",
    "_generate_seed_samples",
    "_run_al_iteration",
    "_fetch_training_embeddings",
    "_fetch_unlabeled_embeddings",
    "_download_model_from_s3",
    "_upload_model_to_s3",
    "_parse_vectors",
]
