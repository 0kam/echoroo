"""Early ML device / thread environment configuration.

TensorFlow (used by BirdNET and Perch) reads ``CUDA_VISIBLE_DEVICES`` and its
thread-pool knobs once at import time. On hosts whose GPU is enumerated but
unusable by TF (e.g. NVIDIA Blackwell / RTX 50-series / sm_120) TF lists the
device and then crashes at kernel launch, so runtime auto-detection is too
late and too unreliable. :func:`apply_ml_device_env` must therefore run at the
very top of the Celery worker entrypoint, BEFORE anything imports TensorFlow,
to pin the process to CPU (and cap its thread pools) when ``ML_USE_GPU`` is
false.

This module lives in :mod:`echoroo.workers` (whose ``__init__`` is empty) and
NOT in :mod:`echoroo.ml` on purpose: importing it must not trigger
``echoroo/ml/__init__.py`` (which imports BirdNET/Perch and therefore numpy +
TensorFlow). If numpy/BLAS initialise before the thread caps are set the caps
are silently ignored — which is the core OOM safety. The module imports only
the standard library plus the (numpy/TF-free) pydantic ``Settings``.

The function is intentionally import-light (no TensorFlow / numpy import) and
idempotent: it only ever *adds* environment variables, and uses
``os.environ.setdefault`` for the thread caps so an operator who exports an
explicit value still wins.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

__all__ = ["apply_ml_device_env"]

# Thread-pool env vars capped in CPU mode. Each is set only if unset so an
# explicit operator override survives.
_CPU_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "TF_NUM_INTRAOP_THREADS",
    "TF_NUM_INTEROP_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def apply_ml_device_env() -> None:
    """Configure CUDA / TF thread env vars from :class:`Settings`.

    * CPU mode (``ML_USE_GPU`` false): force ``CUDA_VISIBLE_DEVICES=-1`` so TF
      never touches the (unusable) GPU, and cap every TF / OpenMP / BLAS
      thread pool to ``ML_CPU_NUM_THREADS`` to keep RAM bounded.
    * GPU mode with ``ML_GPU_ALLOW_GROWTH`` true: ``setdefault``
      ``TF_FORCE_GPU_ALLOW_GROWTH=true`` so TF grows device memory on demand.

    Safe to call before TensorFlow is imported and idempotent.
    """
    from echoroo.core.settings import get_settings

    settings = get_settings()

    if not settings.ML_USE_GPU:
        # Force CPU: hide the GPU from TensorFlow entirely. This is the
        # decisive knob for Blackwell/sm_120 boxes where TF enumerates the
        # device then crashes at kernel launch.
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        thread_cap = str(settings.ML_CPU_NUM_THREADS)
        for var in _CPU_THREAD_ENV_VARS:
            os.environ.setdefault(var, thread_cap)
        cpu_msg = (
            "ML device env: CPU mode (CUDA_VISIBLE_DEVICES=-1, "
            f"thread cap={thread_cap})"
        )
        # This runs at the very top of the Celery worker entrypoint, BEFORE
        # Celery configures logging, so logger.info() output is dropped. Write
        # the device-selection line to stderr directly so it is always visible
        # in container logs; keep the logger.info() for post-setup consumers.
        print(cpu_msg, file=sys.stderr)
        logger.info(cpu_msg)
        return

    # GPU mode: leave CUDA_VISIBLE_DEVICES untouched (the default GPU
    # behaviour) but optionally enable on-demand memory growth.
    if settings.ML_GPU_ALLOW_GROWTH:
        os.environ.setdefault("TF_FORCE_GPU_ALLOW_GROWTH", "true")
    gpu_msg = f"ML device env: GPU mode (allow_growth={settings.ML_GPU_ALLOW_GROWTH})"
    # Same as the CPU branch: this runs pre-logging-setup, so the logger.info()
    # is dropped. Mirror the message to stderr so it always lands in the logs.
    print(gpu_msg, file=sys.stderr)
    logger.info(gpu_msg)
