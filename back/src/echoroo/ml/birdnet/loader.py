"""BirdNET model loader module.

This module provides a simplified loader using the official birdnet Python
package (v0.2.x) with the new API, inheriting from the base ModelLoader class.

Example
-------
>>> from echoroo.ml.birdnet import BirdNETLoader
>>> loader = BirdNETLoader()
>>> loader.load()
>>> model = loader.get_model()
>>> print(loader.specification)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from echoroo.ml.base import ModelLoader, ModelSpecification
from echoroo.ml.birdnet.constants import (
    BIRDNET_VERSION,
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
)

logger = logging.getLogger(__name__)


class BirdNETNotLoadedError(Exception):
    """Raised when attempting to use BirdNET before loading.

    Note
    ----
    This exception is kept for backward compatibility. New code should
    catch RuntimeError instead, which is raised by the base class.
    """

    pass


class BirdNETLoader(ModelLoader):
    """Loader for BirdNET model using the official birdnet package.

    This class provides a thread-safe mechanism to initialize the BirdNET
    model. The model is loaded on first use (lazy loading) and cached in
    memory for subsequent calls.

    Inherits from ModelLoader to provide consistent interface with other
    ML models in Echoroo.

    Parameters
    ----------
    model_dir : Path | None, optional
        Directory containing model files. Not used for BirdNET as it
        downloads models automatically. Kept for API consistency.
        Default is None.

    Examples
    --------
    Basic usage with lazy loading:

    >>> loader = BirdNETLoader()
    >>> if not loader.is_loaded:
    ...     loader.load()
    >>> model = loader.get_model()
    >>> print(f"Model: {loader.specification.name} v{loader.specification.version}")
    Model: birdnet v2.4
    """

    def __init__(self, model_dir: Path | None = None) -> None:
        """Initialize the BirdNET loader.

        Parameters
        ----------
        model_dir : Path | None, optional
            Directory containing model files. Not used for BirdNET.
            Default is None.
        """
        super().__init__(model_dir)
        self._species_list: list[str] | None = None

    @property
    def specification(self) -> ModelSpecification:
        """Get the BirdNET model specification.

        Returns
        -------
        ModelSpecification
            Model metadata including name, version, sample rate, etc.

        Notes
        -----
        Species list is populated after the model is loaded. Before loading,
        the species_list will be None.
        """
        return ModelSpecification(
            name="birdnet",
            version=BIRDNET_VERSION,
            sample_rate=SAMPLE_RATE,
            segment_duration=SEGMENT_DURATION,
            embedding_dim=EMBEDDING_DIM,
            supports_classification=True,
            species_list=self._species_list,
        )

    def _load_model(self) -> Any:
        """Load the BirdNET model into memory.

        This method is called by the base class `load()` method within
        a thread lock, so it does not need to be thread-safe itself.

        Returns
        -------
        Any
            The loaded birdnet acoustic model instance.

        Raises
        ------
        ImportError
            If the birdnet package is not installed.
        RuntimeError
            If model loading fails for any other reason.
        """
        # Import and load birdnet model
        try:
            import birdnet
        except ImportError as e:
            raise ImportError(
                "birdnet package is required for BirdNET model loading. "
                "Install it with: pip install birdnet"
            ) from e

        try:
            # Load acoustic model v2.4 with TensorFlow backend
            model = birdnet.load("acoustic", BIRDNET_VERSION, "tf")

            # Cache the species list for the specification
            self._species_list = list(model.species_list)

            logger.debug(
                f"BirdNET model initialized with "
                f"sample_rate={model.get_sample_rate()}Hz, "
                f"embedding_dim={model.get_embeddings_dim()}, "
                f"n_species={model.n_species}"
            )

            return model

        except Exception as e:
            raise RuntimeError(f"Failed to load BirdNET model: {e}") from e

    def get_model(self) -> Any:
        """Get the loaded BirdNET model.

        Returns
        -------
        Any
            The loaded birdnet acoustic model.

        Raises
        ------
        RuntimeError
            If the model has not been loaded yet.
        BirdNETNotLoadedError
            Legacy exception for backward compatibility.

        Notes
        -----
        This method overrides the base class to provide backward
        compatibility with the BirdNETNotLoadedError exception.
        """
        try:
            return super().get_model()
        except RuntimeError as e:
            # Raise legacy exception for backward compatibility
            raise BirdNETNotLoadedError(str(e)) from e
