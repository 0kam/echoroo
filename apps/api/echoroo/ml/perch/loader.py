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

    def _configure_device(self) -> None:
        """Configure TensorFlow to use the specified device."""
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

        return model
