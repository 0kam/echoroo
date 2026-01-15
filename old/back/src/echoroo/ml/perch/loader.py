"""Perch model loader module using birdnet library.

This module provides a loader for Perch V2 using the official birdnet Python
package, which supports ProtoBuf-format Perch models.

Perch is a general-purpose audio embedding model developed by Google Research
for bioacoustic analysis. It produces 1536-dimensional embeddings that capture
acoustic features useful for downstream classification tasks.

Example
-------
>>> from echoroo.ml.perch import PerchLoader
>>> loader = PerchLoader()
>>> loader.load()
>>> model = loader.get_model()
>>> print(loader.specification)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from echoroo.ml.base import ModelLoader, ModelSpecification
from echoroo.ml.perch.constants import (
    EMBEDDING_DIM,
    PERCH_VERSION,
    SAMPLE_RATE,
    SEGMENT_DURATION,
)
from echoroo.ml.perch.exceptions import PerchModelNotFoundError

logger = logging.getLogger(__name__)


class PerchLoader(ModelLoader):
    """Loader for Perch V2 model via birdnet library.

    This class provides a thread-safe mechanism to load and cache the Perch V2
    model using the birdnet library, which supports ProtoBuf models.

    Inherits from ModelLoader to provide consistent interface with other
    ML models in Echoroo.

    Parameters
    ----------
    model_dir : Path | None, optional
        Directory containing model files. Not used for Perch as it
        downloads models automatically. Kept for API consistency.
        Default is None.
    device : str, optional
        Device to use for inference: "GPU", "CPU", "GPU:0", "GPU:1", etc.
        Default is "GPU".

    Examples
    --------
    Basic usage with lazy loading:

    >>> loader = PerchLoader()
    >>> if not loader.is_loaded:
    ...     loader.load()
    >>> model = loader.get_model()
    >>> print(f"Model: {loader.specification.name} v{loader.specification.version}")
    Model: perch v2.0

    Using CPU device:

    >>> loader = PerchLoader(device="CPU")
    >>> loader.load()
    """

    def __init__(
        self,
        model_dir: Path | None = None,
        device: str = "GPU",
    ) -> None:
        """Initialize the Perch loader.

        Parameters
        ----------
        model_dir : Path | None, optional
            Directory containing model files. Not used for Perch.
            Default is None.
        device : str, optional
            Device to use for inference: "GPU", "CPU", "GPU:0", "GPU:1", etc.
            Default is "GPU".
        """
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

    def _configure_device(self) -> None:
        """Configure TensorFlow to use the specified device."""
        import os

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

    @property
    def specification(self) -> ModelSpecification:
        """Get the Perch model specification.

        Returns
        -------
        ModelSpecification
            Model metadata including name, version, sample rate, etc.

        Notes
        -----
        Perch V2 supports both embeddings and species classification.
        The species_list is populated after the model is loaded.
        """
        return ModelSpecification(
            name="perch",
            version=PERCH_VERSION,
            sample_rate=SAMPLE_RATE,
            segment_duration=SEGMENT_DURATION,
            embedding_dim=EMBEDDING_DIM,
            supports_classification=self._species_list is not None,
            species_list=self._species_list,
        )

    def _load_model(self) -> Any:
        """Load the Perch V2 model using birdnet library.

        This method is called by the base class `load()` method within
        a thread lock, so it does not need to be thread-safe itself.

        Returns
        -------
        Any
            Loaded Perch V2 model object from birdnet.

        Raises
        ------
        ImportError
            If birdnet is not installed.
        PerchModelNotFoundError
            If the model cannot be loaded.
        """
        # Configure device before importing TensorFlow/birdnet
        self._configure_device()

        try:
            import birdnet
        except ImportError as e:
            raise ImportError(
                "birdnet library is required for Perch V2 model loading. "
                "Install it with: pip install birdnet"
            ) from e

        logger.info(
            f"Loading Perch V2 model via birdnet (device: {self._device})"
        )

        try:
            # Load Perch V2 using birdnet library
            # This downloads the ProtoBuf model automatically
            if hasattr(birdnet, "load_perch_v2"):
                model = birdnet.load_perch_v2(self._device)  # type: ignore[attr-defined]
            else:
                raise AttributeError(
                    "birdnet.load_perch_v2() is not available in this version. "
                    "This loader requires birdnet with Perch V2 support."
                )

            # Extract species list from model
            if hasattr(model, "species_list"):
                self._species_list = list(model.species_list)
                logger.info(
                    f"Loaded Perch V2 with {len(self._species_list)} species"
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
                f"Make sure you have a working internet connection for "
                f"automatic model download."
            ) from e

        logger.debug(
            f"Perch V2 model initialized with "
            f"sample_rate={SAMPLE_RATE}Hz, "
            f"embedding_dim={EMBEDDING_DIM}, "
            f"device={self._device}"
        )

        return model
