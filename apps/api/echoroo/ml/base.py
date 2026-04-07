"""Core abstract base classes for ML models.

This module provides the foundational abstractions for integrating ML models
into Echoroo. It defines interfaces for model loading, inference,
and result formatting that can be implemented by different models
(BirdNET, Perch, etc.).

The design follows these principles:
- Thread-safe lazy loading to avoid loading models at import time
- Separation of concerns: ModelLoader handles loading, InferenceEngine handles inference
- Consistent result format across different models
- File-based inference via the birdnet library (no custom AudioPreprocessor dependency)
- Type safety with comprehensive type hints
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


@dataclass
class ModelSpecification:
    """Metadata describing a machine learning model.

    Attributes
    ----------
    name : str
        Model name (e.g., "birdnet", "perch").
    version : str
        Model version string (e.g., "2.4", "2.0").
    sample_rate : int
        Required sample rate in Hz (e.g., 48000 for BirdNET, 32000 for Perch).
    segment_duration : float
        Duration of each inference segment in seconds (e.g., 3.0 for BirdNET).
    embedding_dim : int
        Dimensionality of embedding vectors (e.g., 1024 for BirdNET).
    supports_classification : bool
        Whether the model outputs classification predictions. Default is True.
    species_list : list[str] | None
        List of species/class labels the model can predict.
        None if the model only produces embeddings. Default is None.
    """

    name: str
    version: str
    sample_rate: int
    segment_duration: float
    embedding_dim: int
    supports_classification: bool = True
    species_list: list[str] | None = None

    def __post_init__(self) -> None:
        """Validate model specification parameters."""
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {self.sample_rate}")

        if self.segment_duration <= 0:
            raise ValueError(
                f"segment_duration must be positive, got {self.segment_duration}"
            )

        if self.embedding_dim <= 0:
            raise ValueError(
                f"embedding_dim must be positive, got {self.embedding_dim}"
            )

        if self.supports_classification and not self.species_list:
            logger.warning(
                "Model %s supports classification but has no species_list", self.name
            )

    @property
    def segment_samples(self) -> int:
        """Get the number of samples per segment.

        Returns
        -------
        int
            Number of samples = sample_rate * segment_duration
        """
        return int(self.sample_rate * self.segment_duration)

    @property
    def n_species(self) -> int:
        """Get the number of species in the model vocabulary.

        Returns
        -------
        int
            Number of species, or 0 if species_list is None.
        """
        return len(self.species_list) if self.species_list else 0


@dataclass
class InferenceResult:
    """Generic container for inference results from a single audio segment.

    Attributes
    ----------
    start_time : float
        Start time of the segment in seconds (relative to recording).
    end_time : float
        End time of the segment in seconds (relative to recording).
    embedding : NDArray[np.float32]
        Embedding vector extracted from the audio segment. Shape: (embedding_dim,)
    predictions : list[tuple[str, float]]
        List of (species_label, confidence) tuples, sorted by confidence descending.
        Empty list if no predictions above threshold. Default is empty list.
    metadata : dict[str, Any]
        Additional model-specific metadata. Default is empty dict.
    """

    start_time: float
    end_time: float
    embedding: NDArray[np.float32]
    predictions: list[tuple[str, float]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate inference result."""
        if self.start_time < 0:
            raise ValueError(f"start_time must be non-negative, got {self.start_time}")

        if self.end_time <= self.start_time:
            raise ValueError(
                f"end_time ({self.end_time}) must be greater than "
                f"start_time ({self.start_time})"
            )

        if self.embedding.ndim != 1:
            raise ValueError(
                f"embedding must be 1D array, got shape {self.embedding.shape}"
            )

        # Ensure float32 dtype
        if self.embedding.dtype != np.float32:
            self.embedding = self.embedding.astype(np.float32)

        # Validate predictions format
        for pred in self.predictions:
            if not isinstance(pred, tuple) or len(pred) != 2:
                raise ValueError(
                    f"Each prediction must be a (label, confidence) tuple, got {pred}"
                )
            label, confidence = pred
            if not isinstance(label, str):
                raise ValueError(f"Prediction label must be str, got {type(label)}")
            if not isinstance(confidence, (int, float)):
                raise ValueError(
                    f"Prediction confidence must be numeric, got {type(confidence)}"
                )
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(
                    f"Prediction confidence must be in [0, 1], got {confidence}"
                )

    @property
    def duration(self) -> float:
        """Get the duration of the segment.

        Returns
        -------
        float
            Duration in seconds.
        """
        return self.end_time - self.start_time

    @property
    def top_prediction(self) -> tuple[str, float] | None:
        """Get the top prediction if any exist.

        Returns
        -------
        tuple[str, float] | None
            (label, confidence) tuple of the highest confidence prediction,
            or None if no predictions.
        """
        return self.predictions[0] if self.predictions else None

    @property
    def has_detection(self) -> bool:
        """Check if any species was detected above threshold.

        Returns
        -------
        bool
            True if predictions list is non-empty, False otherwise.
        """
        return len(self.predictions) > 0

    @property
    def embedding_dim(self) -> int:
        """Get the dimensionality of the embedding.

        Returns
        -------
        int
            Embedding dimension.
        """
        return len(self.embedding)


class ModelLoader(ABC):
    """Abstract base class for loading ML models.

    This class provides a thread-safe mechanism for lazy loading ML models
    into memory. Models are loaded on first use and cached for subsequent
    calls. Subclasses must implement the `specification` property and
    `_load_model` method.

    Parameters
    ----------
    model_dir : Path | None, optional
        Directory containing model files. If None, uses default location
        or downloads from internet. Default is None.
    """

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = model_dir
        self._lock = Lock()
        self._loaded = False
        self._model: Any = None

    @property
    @abstractmethod
    def specification(self) -> ModelSpecification:
        """Get the model specification.

        Returns
        -------
        ModelSpecification
            Model metadata including name, version, sample rate, etc.
        """
        raise NotImplementedError

    @property
    def is_loaded(self) -> bool:
        """Check if the model has been loaded.

        Returns
        -------
        bool
            True if the model is loaded in memory, False otherwise.
        """
        return self._loaded

    @property
    def device(self) -> str | None:
        """Get the device being used for inference.

        Override this property in subclasses that support device selection.

        Returns
        -------
        str | None
            Device identifier ("GPU", "CPU") or None if not applicable.
        """
        return getattr(self, "_device", None)

    def _configure_device(self) -> None:  # noqa: B027
        """Configure the device before loading.

        Override this method to implement GPU/CPU selection logic.
        Default implementation does nothing.
        """

    @abstractmethod
    def _load_model(self) -> Any:
        """Load the model into memory.

        This method must be implemented by subclasses to perform the
        actual model loading. It is called by `load()` within a thread lock.

        Returns
        -------
        Any
            The loaded model object.
        """
        raise NotImplementedError

    def load(self) -> None:
        """Load the model into memory (thread-safe, idempotent).

        Uses double-checked locking: checks the loaded flag before and after
        acquiring the lock so only the first caller performs loading.
        """
        if self._loaded:
            logger.debug("%s model already loaded", self.specification.name)
            return

        with self._lock:
            if self._loaded:
                return

            logger.info(
                "Loading %s model (v%s)",
                self.specification.name,
                self.specification.version,
            )

            self._model = self._load_model()
            self._loaded = True

            logger.info(
                "%s model loaded successfully (sample_rate=%dHz, embedding_dim=%d)",
                self.specification.name,
                self.specification.sample_rate,
                self.specification.embedding_dim,
            )

    def get_model(self) -> Any:
        """Get the loaded model.

        Returns
        -------
        Any
            The loaded model object.

        Raises
        ------
        RuntimeError
            If the model has not been loaded yet. Call `load()` first.
        """
        if not self._loaded or self._model is None:
            raise RuntimeError(
                f"{self.specification.name} model not loaded. "
                "Call load() before get_model()."
            )
        return self._model

    def unload(self) -> None:
        """Unload the model and free memory.

        The model can be reloaded by calling `load()` again.
        """
        with self._lock:
            self._model = None
            self._loaded = False
            logger.info("%s model unloaded", self.specification.name)

    def __repr__(self) -> str:
        spec = self.specification
        status = "loaded" if self._loaded else "not loaded"
        return (
            f"{self.__class__.__name__}("
            f"model={spec.name}, version={spec.version}, status={status})"
        )


class InferenceEngine(ABC):
    """Abstract base class for running ML model inference.

    This class provides a unified interface for running inference on
    audio data using different ML models. The engine depends on a
    ModelLoader for accessing the loaded model.

    Subclasses must implement `predict_segment` and `predict_batch`.
    Subclasses may also override `predict_file` when the underlying model
    library supports efficient file-based inference (e.g., birdnet's
    encode()/predict() APIs).

    Parameters
    ----------
    loader : ModelLoader
        Model loader instance. Must be loaded before creating the engine.
    """

    def __init__(self, loader: ModelLoader) -> None:
        if not loader.is_loaded:
            raise RuntimeError(
                f"{loader.specification.name} loader must be loaded before "
                "creating inference engine. Call loader.load() first."
            )

        self.loader = loader
        self._model = loader.get_model()

    @property
    def specification(self) -> ModelSpecification:
        """Get the model specification from the loader.

        Returns
        -------
        ModelSpecification
            Model metadata.
        """
        return self.loader.specification

    @abstractmethod
    def predict_segment(
        self,
        audio: NDArray[np.float32],
        start_time: float,
    ) -> InferenceResult:
        """Run inference on a single audio segment.

        Parameters
        ----------
        audio : NDArray[np.float32]
            Audio data at the model's required sample rate.
            Shape: (segment_samples,)
        start_time : float
            Start time of the segment in the original recording (seconds).

        Returns
        -------
        InferenceResult
            Inference result containing embedding and predictions.
        """
        raise NotImplementedError

    @abstractmethod
    def predict_batch(
        self,
        segments: list[NDArray[np.float32]],
        start_times: list[float],
    ) -> list[InferenceResult]:
        """Run batch inference on multiple audio segments.

        Parameters
        ----------
        segments : list[NDArray[np.float32]]
            List of audio segments, each with shape (segment_samples,).
        start_times : list[float]
            List of start times corresponding to each segment.

        Returns
        -------
        list[InferenceResult]
            List of inference results, one per segment.
        """
        raise NotImplementedError

    def predict_file(
        self,
        path: Path,
        overlap: float = 0.0,
        custom_species_list: list[str] | None = None,
    ) -> list[InferenceResult]:
        """Run inference on an entire audio file.

        Default implementation raises NotImplementedError; subclasses should
        override this method with model-specific file-based inference using
        the birdnet library's encode()/predict() APIs for efficiency.

        Parameters
        ----------
        path : Path
            Path to the audio file.
        overlap : float, optional
            Overlap between consecutive segments in seconds. Default is 0.0.
        custom_species_list : list[str] | None, optional
            Restrict predictions to this set of species labels. When provided,
            only species in this list are considered during classification.
            None means no restriction (all species). Default is None.

        Returns
        -------
        list[InferenceResult]
            List of inference results for each segment.

        Raises
        ------
        NotImplementedError
            If subclass does not override this method.
        """
        # Acknowledge parameters to satisfy static analysis; subclasses use them.
        _ = path, overlap, custom_species_list
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement predict_file(). "
            "Override this method to add file-based inference support."
        )

    def __repr__(self) -> str:
        spec = self.specification
        return (
            f"{self.__class__.__name__}("
            f"model={spec.name}, "
            f"version={spec.version}, "
            f"sample_rate={spec.sample_rate}Hz, "
            f"embedding_dim={spec.embedding_dim})"
        )
