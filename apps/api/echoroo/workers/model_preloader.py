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
    """Load all GPU models and warm them up."""
    import echoroo.ml.birdnet  # noqa: F401
    import echoroo.ml.perch  # noqa: F401
    from echoroo.ml.registry import ModelRegistry

    for model_name in ["perch", "birdnet"]:
        logger.info("Pre-loading model: %s", model_name)
        loader_cls = ModelRegistry.get_loader_class(model_name)
        engine_cls = ModelRegistry.get_engine_class(model_name)
        loader = loader_cls()
        loader.load()
        engine = engine_cls(loader)
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
        from echoroo.ml.perch.direct_inference import PerchDirectInference

        logger.info("Pre-loading Perch direct TF inference engine")
        direct = PerchDirectInference(device="GPU")
        direct.load()
        direct.warmup([1, 6, 10, 16])
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

    # Fallback: load on demand (for non-GPU workers or first call before preload)
    logger.warning("Model %s not pre-loaded, loading on demand", model_name)
    import echoroo.ml.birdnet  # noqa: F401
    import echoroo.ml.perch  # noqa: F401
    from echoroo.ml.registry import ModelRegistry

    loader_cls = ModelRegistry.get_loader_class(model_name)
    engine_cls = ModelRegistry.get_engine_class(model_name)
    loader = loader_cls()
    loader.load()
    engine = engine_cls(loader)
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
