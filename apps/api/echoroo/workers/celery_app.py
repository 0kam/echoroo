"""Celery application configuration."""

from __future__ import annotations

import multiprocessing

# Set spawn start method before any TensorFlow/BirdNET imports.
# On Linux the default is 'fork', which copies the parent's CUDA context into
# child processes. The child then fails to reinitialize CUDA:
#   CUDA error: Failed call to cuDeviceGet: CUDA_ERROR_NOT_INITIALIZED
# Using 'spawn' creates a fresh Python interpreter that can initialize CUDA
# cleanly. force=True allows calling this even if already set elsewhere.
multiprocessing.set_start_method("spawn", force=True)

from celery import Celery
from celery.schedules import crontab

from echoroo.core.settings import get_settings

_settings = get_settings()

app = Celery(
    "echoroo",
    broker=_settings.CELERY_BROKER_URL,
    backend=_settings.CELERY_RESULT_BACKEND,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,  # 10 min hard limit
    task_soft_time_limit=540,  # 9 min soft limit
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (prevent memory leaks)
    worker_prefetch_multiplier=1,  # Fair scheduling
)

# Explicitly include task modules (autodiscover looks for 'tasks.py' by default)
app.conf.include = [
    "echoroo.workers.upload_tasks",
    "echoroo.workers.import_task",
    "echoroo.workers.annotation_tasks",
    "echoroo.workers.ml_tasks",
    "echoroo.workers.taxon_tasks",
    "echoroo.workers.search_tasks",
]

# Periodic tasks (beat schedule)
app.conf.beat_schedule = {
    "cleanup-orphan-uploads": {
        "task": "echoroo.workers.upload_tasks.cleanup_orphan_uploads",
        "schedule": crontab(minute=0),  # Every hour
    },
    "fetch-japanese-vernacular-names-weekly": {
        "task": "echoroo.workers.taxon_tasks.fetch_japanese_vernacular_names",
        "schedule": crontab(hour=2, minute=0, day_of_week=0),  # Every Sunday at 02:00 UTC
        "kwargs": {"batch_size": 100},
    },
}
