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

# Configure the ML device / thread environment BEFORE anything can import
# TensorFlow. On a host whose GPU is unusable by TF (e.g. Blackwell /
# sm_120) ``ECHOROO_ML_USE_GPU=false`` forces CUDA_VISIBLE_DEVICES=-1 here so
# the model preloader (worker_ready signal) and every inference task run on
# CPU without exhausting RAM. Defaults preserve the GPU behaviour.
from echoroo.ml.device_env import apply_ml_device_env  # noqa: E402

apply_ml_device_env()

from celery import Celery  # noqa: E402
from celery.schedules import crontab  # noqa: E402

from echoroo.core.settings import get_settings  # noqa: E402

_settings = get_settings()

app = Celery(
    "echoroo",
    broker=_settings.CELERY_BROKER_URL,
    backend=_settings.CELERY_RESULT_BACKEND,
)

# rediss:// (TLS) URLs from settings need explicit ssl_cert_reqs because
# kombu/redis-py 5.x refuse to start without it (see
# https://github.com/redis/redis-py/issues/2622). Map the URL scheme to
# the standard ssl module constants so we keep CERT_REQUIRED in
# production while still allowing dev to relax via REDIS_TLS_INSECURE=1.
import ssl as _ssl  # noqa: E402

if _settings.CELERY_BROKER_URL.startswith("rediss://") or _settings.CELERY_RESULT_BACKEND.startswith(
    "rediss://"
):
    _redis_ssl_cert_reqs = (
        _ssl.CERT_NONE
        if getattr(_settings, "REDIS_TLS_INSECURE", False)
        else _ssl.CERT_REQUIRED
    )
    if _settings.CELERY_BROKER_URL.startswith("rediss://"):
        app.conf.broker_use_ssl = {"ssl_cert_reqs": _redis_ssl_cert_reqs}
    if _settings.CELERY_RESULT_BACKEND.startswith("rediss://"):
        app.conf.redis_backend_use_ssl = {"ssl_cert_reqs": _redis_ssl_cert_reqs}

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
    task_default_queue="default",  # Non-routed tasks go to 'default' queue
)

# Route GPU-intensive ML tasks to the dedicated GPU queue.
# All other tasks fall through to the default queue.
app.conf.task_routes = {
    "echoroo.workers.ml_tasks.run_birdnet_detection": {"queue": "gpu"},
    "echoroo.workers.ml_tasks.run_detection": {"queue": "gpu"},
    "echoroo.workers.ml_tasks.run_embedding_generation": {"queue": "gpu"},
    "echoroo.workers.search_tasks.run_batch_search": {"queue": "gpu"},
}

# Explicitly include task modules (autodiscover looks for 'tasks.py' by default).
# model_preloader is not a task module but must be included so that its
# worker_ready signal handler is registered in every worker process.
app.conf.include = [
    "echoroo.workers.upload_tasks",
    "echoroo.workers.ml_tasks",
    "echoroo.workers.taxon_tasks",
    "echoroo.workers.search_tasks",
    "echoroo.workers.classifier_tasks",
    "echoroo.workers.annotation_sampling_tasks",
    "echoroo.workers.evaluation_tasks",
    "echoroo.workers.model_preloader",
    # Outbox processor + handler registry. The dispatcher modules
    # below register themselves into ``OUTBOX_HANDLERS`` at import
    # time; without listing them here Celery would never import
    # them and the registered handlers would silently be missing
    # at row-claim time (research.md §6, FR-104).
    "echoroo.workers.outbox_processor",
    "echoroo.workers.login_notification_dispatcher",
    # spec/011 Step 10 (T116): the ``email_verification_dispatcher``
    # include was removed alongside the deleted dispatcher module +
    # producer service (FR-011-010).
    # Trusted overlay lifecycle workers (Phase 10 / FR-044, FR-045).
    # ``trusted_long_lived_invalidation`` is intentionally NOT listed here
    # — it is a coroutine started by the FastAPI lifespan, not a Celery
    # task module (see its docstring for the threading rationale).
    "echoroo.workers.trusted_auto_expire",
    "echoroo.workers.trusted_expiry_notifier",
    # Outbox dispatcher for ``trusted_user.expiry_notification``. MUST be
    # imported by every worker process so the handler is registered into
    # ``OUTBOX_HANDLERS`` before ``process_outbox_batch`` claims a row;
    # otherwise the default handler raises ``NotImplementedError`` and
    # the FR-045 warning email is never delivered.
    "echoroo.workers.trusted_expiry_dispatcher",
    # Dormancy detection (Phase 12 / T701 / FR-060). Runs daily; the
    # bound task does the SELECT + UPDATE + outbox enqueue in a single
    # AsyncSession so a half-flipped state cannot leak into the audit
    # chain.
    "echoroo.workers.dormancy_check",
    # GDPR PII null-out daily sweeps (Phase 14 / T902 / T903). Both
    # workers issue a single ``UPDATE ... RETURNING id`` so they are
    # idempotent and stateless across runs (FR-106 / FR-108).
    "echoroo.workers.invitation_email_null",
    "echoroo.workers.trusted_email_null",
    # Phase 17 backlog A-11 — dispatch poller for the admin 2FA reset
    # state machine. Picks up rows where ``dispatch_at <= now()`` every
    # 5 minutes and either clears the user's 2FA state or marks the
    # request ``cancelled`` / ``failed``.
    "echoroo.workers.two_factor_tasks",
    # Phase 17 backlog A-2 — daily PII hash dual-write backfill. Fills
    # ``email_hash_v2`` on invitation rows that pre-date a rotation
    # window (audit rows are not back-fillable; they fall back to the
    # v1 search path inside ``verify_pii_hash``).
    "echoroo.workers.pii_hash_backfill",
    # Phase 17 backlog A-4 — daily API key age sweep. Strips write
    # scopes at 180d and revokes at 270d (FR-083). Coordinated with
    # the verifier-side safety net in
    # :mod:`echoroo.services.api_key_verification`.
    "echoroo.workers.api_key_age_check",
    # spec/011 US7 (T625 / FR-011-309) — daily GC of
    # ``user_banner_dismissals`` rows older than the banner age cap
    # (``DEFAULT_BANNER_MAX_AGE_DAYS``). Single ``DELETE ... RETURNING``
    # so the sweep is idempotent and stateless across runs.
    "echoroo.workers.banner_gc",
]

# Periodic tasks (beat schedule)
app.conf.beat_schedule = {
    "cleanup-orphan-uploads": {
        "task": "echoroo.workers.upload_tasks.cleanup_orphan_uploads",
        "schedule": crontab(minute=0),  # Every hour at :00
    },
    "cleanup-orphan-search-reference": {
        "task": "echoroo.workers.search_tasks.cleanup_orphan_search_reference",
        "schedule": crontab(minute=30),  # Every hour at :30 (offset from uploads)
    },
    "fetch-japanese-vernacular-names-weekly": {
        "task": "echoroo.workers.taxon_tasks.fetch_japanese_vernacular_names",
        "schedule": crontab(hour=2, minute=0, day_of_week=0),  # Every Sunday at 02:00 UTC
        "kwargs": {"batch_size": 100},
    },
    # Drain the transactional outbox at 1Hz-ish (every 30s — the
    # spec's SLO is p95 ≤ 10s end-to-end which is set by the worker
    # poll cadence, not the beat trigger). Each beat tick fans the
    # work out across ``-c 4`` worker-cpu processes; the actual
    # ``SELECT ... FOR UPDATE SKIP LOCKED`` claim happens inside the
    # task body. Beat-driven invocation is the canonical wiring per
    # research.md §6.
    "drain-outbox-events": {
        "task": "echoroo.workers.outbox_processor.process_outbox_batch",
        "schedule": 30.0,  # seconds — see docstring above.
    },
    # FR-044 — flip Trusted overlay rows to ``status='expired'`` once
    # ``expires_at`` is in the past. Hourly cadence at minute=5 keeps the
    # job out of the on-the-hour upload janitor's window so a slow
    # PostgreSQL UPDATE on one job never starves the other. The gate
    # already enforces expiry at request time; this worker is the
    # defence-in-depth bookkeeping pass that lets the management UI
    # filter on ``status='active'`` directly.
    "trusted-auto-expire-hourly": {
        "task": "echoroo.workers.trusted_auto_expire.auto_expire_trusted_users",
        "schedule": crontab(minute=5),
    },
    # FR-045 — pre-emptively notify Trusted users + Owners 7 days before
    # an overlay's ``expires_at`` so they have a window to renew. Daily
    # at 03:00 UTC mirrors the GBIF vernacular sync's off-peak slot;
    # idempotency is guaranteed by the per-day key in
    # :func:`echoroo.workers.trusted_expiry_notifier._idempotency_key`.
    "trusted-expiry-notifier-daily": {
        "task": (
            "echoroo.workers.trusted_expiry_notifier.notify_expiring_trusted_users"
        ),
        "schedule": crontab(hour=3, minute=0),
    },
    # FR-060 — dormancy detection daily at 00:00 UTC. The single-worker
    # invariant is enforced inside the task via
    # ``pg_try_advisory_xact_lock`` (see ``dormancy_check._try_acquire_lock``)
    # so a beat collision with a manual dispatch is safe.
    "dormancy-check-daily": {
        "task": "echoroo.workers.dormancy_check.run_daily_dormancy_check",
        "schedule": crontab(hour=0, minute=0),
    },
    # FR-106 — NULL ``project_invitations.email`` 30 days after the row
    # reached a terminal status. Daily at 02:30 UTC, sandwiched between
    # the GBIF vernacular sync (02:00) and the trusted-email null-out
    # (02:45) so the three sequential daily sweeps never overlap.
    "invitation-email-null-daily": {
        "task": "echoroo.workers.invitation_email_null.sweep_invitation_emails",
        "schedule": crontab(hour=2, minute=30),
    },
    # FR-108 — NULL ``project_trusted_users.email_at_invitation`` 90
    # days after revoke / lapse. Daily at 02:45 UTC, after the
    # invitation sweep and before the trusted-expiry-notifier so the
    # three GDPR / trusted lifecycle jobs run sequentially.
    "trusted-email-null-daily": {
        "task": "echoroo.workers.trusted_email_null.sweep_trusted_emails",
        "schedule": crontab(hour=2, minute=45),
    },
    # Phase 17 backlog A-11 — admin 2FA reset dispatch poller. 5 min
    # cadence keeps the worst-case dispatch latency comparable to the
    # 24h delay we already promise (FR-072). The task body uses
    # ``SELECT ... FOR UPDATE SKIP LOCKED`` so multi-worker contention
    # is wait-free.
    "two-factor-reset-dispatch-5min": {
        "task": "echoroo.workers.two_factor_tasks.dispatch_due_two_factor_resets",
        "schedule": 300.0,
    },
    # Phase 17 backlog A-2 — daily PII hash dual-write backfill (FR-091b).
    # Fires at 01:00 UTC, ahead of the GBIF (02:00) and GDPR null-out
    # (02:30 / 02:45) sweeps so plaintext rows are still available for
    # rehashing under the v2 CMK. Single-key deployments (no v2 alias)
    # short-circuit the task body to a no-op fast path.
    "pii-hash-backfill-daily": {
        "task": (
            "echoroo.workers.pii_hash_backfill.pii_hash_backfill_invitations"
        ),
        "schedule": crontab(hour=1, minute=0),
    },
    # Phase 17 backlog A-4 — daily API key age sweep (FR-083). Fires
    # at 01:15 UTC, offset from the PII hash backfill at 01:00 so the
    # two daily sweeps never contend on the same connections. The
    # task body itself uses ``UPDATE ... RETURNING`` for revoke and
    # ``SELECT FOR UPDATE SKIP LOCKED`` for degrade so multi-worker
    # contention is wait-free.
    "api-key-age-check-daily": {
        "task": "echoroo.workers.api_key_age_check.api_key_age_check",
        "schedule": crontab(hour=1, minute=15),
    },
    # spec/011 US7 (T625 / FR-011-309) — daily GC of stale banner
    # dismissals. Fires at 03:30 UTC, after the 03:00 trusted-expiry
    # notifier so the sequential daily jobs never overlap (occupied
    # slots: 00:00 / 01:00 / 01:15 / 02:00 / 02:30 / 02:45 / 03:00).
    # The task name MUST exactly match the ``@app.task(name=...)`` in
    # :mod:`echoroo.workers.banner_gc` or beat silently fails to wire.
    "banner-dismissal-gc-daily": {
        "task": "echoroo.workers.banner_gc.gc_user_banner_dismissals",
        "schedule": crontab(hour=3, minute=30),
    },
}
