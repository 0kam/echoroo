"""Custom classifier worker tasks package.

Re-exports the four Celery tasks and shared helpers from sub-modules for
backward compatibility. Task names are preserved as
``echoroo.workers.classifier_tasks.*`` so existing Celery queues and routes
continue to work without changes.

Sub-modules:
- utils.py           : embedding fetch/parse + S3 model-artifact helpers
- training.py        : train_custom_model task
- inference.py       : run_custom_model_inference task
- seed_sampling.py   : generate_seed_samples task
- active_learning.py : run_al_iteration task
"""

from echoroo.workers.classifier.active_learning import (
    _run_al_iteration,
    run_al_iteration,
)
from echoroo.workers.classifier.inference import (
    _run_custom_model_inference,
    run_custom_model_inference,
)
from echoroo.workers.classifier.seed_sampling import (
    _generate_seed_samples,
    generate_seed_samples,
)
from echoroo.workers.classifier.training import (
    _run_training,
    _train_custom_model,
    train_custom_model,
)
from echoroo.workers.classifier.utils import (
    _download_model_from_s3,
    _fetch_training_embeddings,
    _fetch_unlabeled_embeddings,
    _parse_vectors,
    _upload_model_to_s3,
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
