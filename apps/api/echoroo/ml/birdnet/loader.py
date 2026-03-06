"""BirdNET model loader.

This module provides a loader for the BirdNET V2.4 model using the official
birdnet Python package. Inherits from the base ModelLoader class to provide
a consistent interface with other ML models in Echoroo.

Example
-------
>>> from echoroo.ml.birdnet.loader import BirdNETLoader
>>> loader = BirdNETLoader()
>>> loader.load()
>>> model = loader.get_model()
>>> print(loader.specification.name, loader.specification.version)
birdnet 2.4
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from echoroo.ml.base import ModelLoader, ModelSpecification
from echoroo.ml.birdnet.constants import (
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    VERSION,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BirdNETLoader",
]


class BirdNETLoader(ModelLoader):
    """Loader for BirdNET model using the official birdnet package.

    Provides thread-safe lazy loading of the BirdNET acoustic model.
    The model is loaded on first use and cached in memory for subsequent calls.

    Parameters
    ----------
    model_dir : Path | None, optional
        Directory containing model files. Not used for BirdNET (it downloads
        models automatically). Kept for API consistency. Default is None.
    device : str, optional
        Device to use for inference: "GPU", "CPU", "GPU:0", "GPU:1", etc.
        Default is "GPU".

    Examples
    --------
    >>> loader = BirdNETLoader()
    >>> loader.load()
    >>> model = loader.get_model()

    >>> # Force CPU usage
    >>> loader = BirdNETLoader(device="CPU")
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
        """Get the BirdNET model specification.

        Returns
        -------
        ModelSpecification
            Model metadata. Species list is populated only after loading.
        """
        return ModelSpecification(
            name="birdnet",
            version=VERSION,
            sample_rate=SAMPLE_RATE,
            segment_duration=SEGMENT_DURATION,
            embedding_dim=EMBEDDING_DIM,
            supports_classification=self._species_list is not None,
            species_list=self._species_list,
        )

    def _configure_device(self) -> None:
        """Configure TensorFlow to use the specified device.

        Sets CUDA_VISIBLE_DEVICES environment variable before birdnet
        (and TensorFlow) is imported, since TF reads the variable at import time.
        """
        if self._device == "CPU":
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
            logger.info("BirdNET configured to use CPU (GPU disabled)")
        elif self._device.startswith("GPU:"):
            gpu_index = self._device.split(":", 1)[1]
            os.environ["CUDA_VISIBLE_DEVICES"] = gpu_index
            logger.info(
                "BirdNET configured to use device: %s (CUDA_VISIBLE_DEVICES=%s)",
                self._device,
                gpu_index,
            )
        else:
            # Allow GPU usage (default behavior)
            if os.environ.get("CUDA_VISIBLE_DEVICES") == "-1":
                del os.environ["CUDA_VISIBLE_DEVICES"]
            logger.info("BirdNET configured to use device: %s", self._device)

    def _load_model(self) -> Any:
        """Load the BirdNET acoustic model.

        Called by the base class `load()` method within a thread lock.

        Returns
        -------
        Any
            Loaded birdnet acoustic model instance.

        Raises
        ------
        ImportError
            If the birdnet package is not installed.
        RuntimeError
            If model loading fails for any other reason.

        Notes
        -----
        GPU/CPU selection is controlled via the CUDA_VISIBLE_DEVICES
        environment variable. When device="CPU", TFLite backend is used
        ("tf") to avoid asyncio deadlocks in the protobuf backend ("pb").
        """
        self._configure_device()

        try:
            import birdnet
        except ImportError as e:
            raise ImportError(
                "birdnet package is required for BirdNET model loading. "
                "Install it with: pip install birdnet"
            ) from e

        try:
            # Use TFLite backend for CPU (avoids asyncio deadlocks).
            # Use protobuf backend for GPU (required for GPU acceleration).
            backend: Any = "tf" if self._device == "CPU" else "pb"
            model = birdnet.load("acoustic", VERSION, backend)  # type: ignore[call-overload]

            # Cache the species list for the specification
            self._species_list = list(model.species_list)

            logger.debug(
                "BirdNET model initialized with sample_rate=%dHz, "
                "embedding_dim=%d, n_species=%d, device=%s",
                model.get_sample_rate(),
                model.get_embeddings_dim(),
                model.n_species,
                self._device,
            )

            return model

        except Exception as e:
            raise RuntimeError(f"Failed to load BirdNET model: {e}") from e
