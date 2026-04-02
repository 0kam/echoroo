"""Perch model loader using the birdnet library.

This module provides a loader for the Perch V2 model via the official birdnet
Python package, which supports ProtoBuf-format Perch models.

Perch is a general-purpose audio embedding model developed by Google Research
for bioacoustic analysis. It produces 1536-dimensional embeddings that capture
acoustic features useful for downstream classification tasks.

Example
-------
>>> from echoroo.ml.perch.loader import PerchLoader
>>> loader = PerchLoader()
>>> loader.load()
>>> model = loader.get_model()
>>> print(loader.specification.name, loader.specification.version)
perch 2.0
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from echoroo.ml.base import ModelLoader, ModelSpecification
from echoroo.ml.perch.constants import (
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    SEGMENT_SAMPLES,
    VERSION,
)
from echoroo.ml.perch.exceptions import PerchModelNotFoundError

logger = logging.getLogger(__name__)

__all__ = [
    "PerchLoader",
]


class PerchLoader(ModelLoader):
    """Loader for Perch V2 model via birdnet library.

    Provides thread-safe lazy loading of the Perch V2 model using the birdnet
    library's `load_perch_v2()` function, which downloads the ProtoBuf model
    automatically on first use.

    Parameters
    ----------
    model_dir : Path | None, optional
        Directory containing model files. Not used for Perch (it downloads
        models automatically). Kept for API consistency. Default is None.
    device : str, optional
        Device to use for inference: "GPU", "CPU", "GPU:0", "GPU:1", etc.
        Default is "GPU".

    Examples
    --------
    >>> loader = PerchLoader()
    >>> loader.load()
    >>> model = loader.get_model()

    >>> # Force CPU usage
    >>> loader = PerchLoader(device="CPU")
    >>> loader.load()
    """

    def __init__(
        self,
        model_dir: Path | None = None,
        device: str = "GPU",
    ) -> None:
        super().__init__(model_dir)
        self._device = device
        self._species_list: list[str] | None = None

    @property
    def device(self) -> str:
        """Get the device being used.

        Returns
        -------
        str
            The device (e.g., "GPU", "CPU", "GPU:0").
        """
        return self._device

    @property
    def specification(self) -> ModelSpecification:
        """Get the Perch model specification.

        Returns
        -------
        ModelSpecification
            Model metadata. Species list is populated only after loading.
        """
        return ModelSpecification(
            name="perch",
            version=VERSION,
            sample_rate=SAMPLE_RATE,
            segment_duration=SEGMENT_DURATION,
            embedding_dim=EMBEDDING_DIM,
            supports_classification=self._species_list is not None,
            species_list=self._species_list,
        )

    def _detect_gpu_available(self) -> bool:
        """Check whether at least one GPU is visible to TensorFlow.

        Returns
        -------
        bool
            True if TensorFlow can see at least one GPU, False otherwise.
        """
        try:
            import tensorflow as tf  # type: ignore[import-untyped]

            return len(tf.config.list_physical_devices("GPU")) > 0
        except Exception:
            return False

    def _configure_device(self) -> None:
        """Configure TensorFlow to use the specified device.

        When device is "GPU" but no physical GPU is available, automatically
        falls back to "CPU" to avoid an AssertionError inside birdnet internals.
        """
        if self._device == "GPU" and not self._detect_gpu_available():
            logger.warning(
                "Perch requested GPU but no GPU is available; falling back to CPU"
            )
            self._device = "CPU"

        if self._device == "CPU":
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
            logger.info("Perch configured to use CPU (GPU disabled)")
        elif self._device.startswith("GPU:"):
            gpu_index = self._device.split(":", 1)[1]
            os.environ["CUDA_VISIBLE_DEVICES"] = gpu_index
            logger.info(
                "Perch configured to use device: %s (CUDA_VISIBLE_DEVICES=%s)",
                self._device,
                gpu_index,
            )
        else:
            if os.environ.get("CUDA_VISIBLE_DEVICES") == "-1":
                del os.environ["CUDA_VISIBLE_DEVICES"]
            logger.info("Perch configured to use device: %s", self._device)

    def _load_model(self) -> Any:
        """Load the Perch V2 model using birdnet library.

        Called by the base class `load()` method within a thread lock.

        Returns
        -------
        Any
            Loaded Perch V2 model object from birdnet.

        Raises
        ------
        ImportError
            If the birdnet package is not installed.
        PerchModelNotFoundError
            If the model cannot be loaded (download failure, etc.).
        """
        self._configure_device()

        try:
            import birdnet
        except ImportError as e:
            raise ImportError(
                "birdnet library is required for Perch V2 model loading. "
                "Install it with: pip install birdnet"
            ) from e

        logger.info(
            "Loading Perch V2 model via birdnet (device: %s)", self._device
        )

        try:
            load_perch_v2 = getattr(birdnet, "load_perch_v2", None)
            if load_perch_v2 is None:
                raise AttributeError(
                    "birdnet.load_perch_v2() is not available in this version. "
                    "This loader requires birdnet with Perch V2 support."
                )

            model = load_perch_v2(self._device)

            # Extract species list from model
            if hasattr(model, "species_list"):
                self._species_list = list(model.species_list)
                logger.info(
                    "Loaded Perch V2 with %d species", len(self._species_list)
                )
            else:
                logger.warning(
                    "Could not extract species list from Perch V2 model. "
                    "Classification will not be available."
                )
                self._species_list = None

        except Exception as e:
            raise PerchModelNotFoundError(
                f"Failed to load Perch V2 model via birdnet: {e}\n"
                "Make sure you have a working internet connection for "
                "automatic model download."
            ) from e

        logger.debug(
            "Perch V2 model initialized with sample_rate=%dHz, "
            "embedding_dim=%d, device=%s",
            SAMPLE_RATE,
            EMBEDDING_DIM,
            self._device,
        )

        # Warm up the model with a silent dummy clip so that XLA compilation
        # and TensorFlow session initialization happen now rather than on the
        # first real inference request.  This amortizes the cold-start overhead
        # and prevents a surprise latency spike on the first search task.
        self._warmup_model(model)

        return model

    def _warmup_model(self, model: Any) -> None:
        """Run a single silent clip through the model to trigger XLA compilation.

        Uses a 5-second silent WAV at 32 kHz — the minimum input length accepted
        by Perch V2.  Errors are caught and logged so that a warm-up failure
        never prevents the model from being returned to callers.
        """
        import os
        import tempfile

        try:
            import numpy as np
            import soundfile as sf

            silence = np.zeros(SEGMENT_SAMPLES, dtype=np.float32)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                sf.write(tmp.name, silence, SAMPLE_RATE)
                tmp_path = tmp.name

            try:
                kwargs: dict[str, Any] = {"device": self._device}
                model.encode(tmp_path, **kwargs)
                logger.info("Perch V2 warm-up inference completed (XLA compiled)")
            finally:
                os.unlink(tmp_path)

        except Exception as exc:  # noqa: BLE001
            logger.warning("Perch V2 warm-up inference failed (non-fatal): %s", exc)
