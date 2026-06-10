"""Model pre-loading for GPU workers.

Loads Perch and BirdNET models at worker startup so they are ready
for immediate inference without per-task loading overhead.
"""

from __future__ import annotations

import logging
from typing import Any

from celery.signals import worker_ready

logger = logging.getLogger(__name__)

# Global model store - populated at worker startup.
# Keys are model names; values are (loader, engine) pairs ready for inference.
_gpu_model_store: dict[str, tuple[Any, Any]] = {}

# Direct TF inference engine for Perch (used by search tasks for fast reference
# audio embedding, bypassing birdnet's multiprocess pipeline).
_direct_perch: Any | None = None


def preload_models() -> None:
    """Load all inference models and warm them up.

    Device + batch/feeders/workers are driven by Settings
    (``ML_USE_GPU`` / ``ML_GPU_BATCH_SIZE`` / ``ML_FEEDERS`` / ``ML_WORKERS``)
    so a host whose GPU is unusable by TensorFlow can run CPU inference by
    setting ``ECHOROO_ML_USE_GPU=false``. Defaults preserve GPU behaviour.
    """
    import echoroo.ml.birdnet  # noqa: F401
    import echoroo.ml.perch  # noqa: F401
    from echoroo.core.settings import get_settings
    from echoroo.ml.registry import ModelRegistry

    settings = get_settings()
    device = "GPU" if settings.ML_USE_GPU else "CPU"

    for model_name in ["perch", "birdnet"]:
        logger.info("Pre-loading model: %s (device=%s)", model_name, device)
        loader_cls = ModelRegistry.get_loader_class(model_name)
        engine_cls = ModelRegistry.get_engine_class(model_name)
        # The registry erases concrete types to the ModelLoader /
        # InferenceEngine base classes, whose __init__ does not declare these
        # kwargs. Every *registered* model (BirdNETLoader/Inference,
        # PerchLoader/Inference) accepts device + batch/feeders/workers, so the
        # call is safe at runtime — hence the targeted call-arg ignores.
        loader = loader_cls(device=device)  # type: ignore[call-arg]
        loader.load()
        engine = engine_cls(
            loader,
            batch_size=settings.ML_GPU_BATCH_SIZE,
            feeders=settings.ML_FEEDERS,
            workers=settings.ML_WORKERS,
            device=device,
        )  # type: ignore[call-arg]
        _gpu_model_store[model_name] = (loader, engine)
        logger.info("Model %s pre-loaded and ready", model_name)

    # Load direct TF inference engine for search reference audio.
    # This is a separate lightweight path that bypasses birdnet's multiprocess
    # pipeline, providing sub-second latency for small batches.
    _preload_direct_perch()


def _preload_direct_perch() -> None:
    """Load and warm up the direct TF inference engine for Perch.

    Called from ``preload_models()`` after the main birdnet models are loaded.
    Errors are caught and logged so a failure here does not abort worker startup.
    """
    global _direct_perch

    try:
        from echoroo.core.settings import get_settings
        from echoroo.ml.perch.direct_inference import PerchDirectInference

        settings = get_settings()
        device = "GPU" if settings.ML_USE_GPU else "CPU"

        # GPU mode keeps the historical multi-size warmup. CPU mode uses the
        # configured (smaller) list to avoid OOM; an empty list skips warmup.
        if settings.ML_USE_GPU:
            warmup_batches = [1, 6, 10, 16]
        else:
            warmup_batches = settings.ml_cpu_warmup_batch_sizes()

        logger.info(
            "Pre-loading Perch direct TF inference engine (device=%s)", device
        )
        direct = PerchDirectInference(device=device)
        direct.load()
        if warmup_batches:
            direct.warmup(warmup_batches)
        else:
            logger.info(
                "Perch direct TF warmup skipped (empty warmup batch list)"
            )
        _direct_perch = direct
        logger.info("Perch direct TF inference pre-loaded and warmed up")
    except Exception:
        logger.exception(
            "Failed to pre-load Perch direct TF inference engine (non-fatal)"
        )


def get_direct_perch() -> Any | None:
    """Return the pre-loaded direct TF inference engine, or None if unavailable.

    Returns
    -------
    PerchDirectInference | None
        The pre-loaded engine, or ``None`` if it was not loaded (e.g. no GPU,
        import error, or worker started before pre-loading).
    """
    return _direct_perch


def get_model(model_name: str) -> tuple[Any, Any]:
    """Return a (loader, engine) pair for the given model name.

    If the model was pre-loaded at worker startup it is returned immediately.
    Otherwise it is loaded on demand and cached for future calls.

    Args:
        model_name: Registered model name, e.g. "birdnet" or "perch".

    Returns:
        Tuple of (loader, engine) ready for inference.
    """
    if model_name in _gpu_model_store:
        return _gpu_model_store[model_name]

    # Fallback: load on demand (for non-GPU workers or first call before preload).
    # This MUST resolve device + batch/feeders/workers from Settings exactly as
    # ``preload_models()`` does. Otherwise the loader defaults to GPU, and
    # BirdNET's ``_configure_device`` DELETES ``CUDA_VISIBLE_DEVICES=-1`` set by
    # ``apply_ml_device_env`` — re-enabling the (unusable on Blackwell/sm_120)
    # GPU and defeating ``ECHOROO_ML_USE_GPU=false``.
    logger.warning("Model %s not pre-loaded, loading on demand", model_name)
    import echoroo.ml.birdnet  # noqa: F401
    import echoroo.ml.perch  # noqa: F401
    from echoroo.core.settings import get_settings
    from echoroo.ml.registry import ModelRegistry

    settings = get_settings()
    device = "GPU" if settings.ML_USE_GPU else "CPU"

    loader_cls = ModelRegistry.get_loader_class(model_name)
    engine_cls = ModelRegistry.get_engine_class(model_name)
    # The registry erases concrete types to the ModelLoader / InferenceEngine
    # base classes, whose __init__ does not declare these kwargs. Every
    # *registered* model (BirdNETLoader/Inference, PerchLoader/Inference)
    # accepts device + batch/feeders/workers, so the call is safe at runtime —
    # hence the targeted call-arg ignores.
    loader = loader_cls(device=device)  # type: ignore[call-arg]
    loader.load()
    engine = engine_cls(
        loader,
        batch_size=settings.ML_GPU_BATCH_SIZE,
        feeders=settings.ML_FEEDERS,
        workers=settings.ML_WORKERS,
        device=device,
    )  # type: ignore[call-arg]
    _gpu_model_store[model_name] = (loader, engine)
    return _gpu_model_store[model_name]


@worker_ready.connect  # type: ignore[untyped-decorator]
def on_worker_ready(sender: Any, **_kwargs: Any) -> None:
    """Pre-load GPU models when the worker process is ready to accept tasks.

    Only runs pre-loading when this worker handles the 'gpu' queue, or when
    no specific queue restriction is configured (default worker).
    """
    queues: list[str] = []
    if hasattr(sender, "task_consumer") and sender.task_consumer is not None:
        queues = [q.name for q in sender.task_consumer.queues]

    if "gpu" in queues or not queues:
        try:
            preload_models()
        except Exception:
            logger.exception("Failed to pre-load models at worker startup")
