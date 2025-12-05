"""Core abstract base classes for ML models.

This module provides the foundational abstractions for integrating ML models
into Echoroo. It defines interfaces for model loading, inference,
and result formatting that can be implemented by different models
(BirdNET, Perch, etc.).

The design follows these principles:
- Thread-safe lazy loading to avoid loading models at import time
- Separation of concerns: ModelLoader handles loading, InferenceEngine handles inference
- Consistent result format across different models
- Type safety with comprehensive type hints
- Integration with AudioPreprocessor for file processing

Example
-------
Implementing a new model:

>>> from echoroo.ml.base import ModelLoader, InferenceEngine, ModelSpecification, InferenceResult
>>>
>>> class MyModelLoader(ModelLoader):
...     @property
...     def specification(self) -> ModelSpecification:
...         return ModelSpecification(
...             name="my_model",
...             version="1.0",
...             sample_rate=48000,
...             segment_duration=3.0,
...             embedding_dim=512,
...             supports_classification=True,
...             species_list=["species_a", "species_b"],
...         )
...
...     def _load_model(self):
...         # Load model here
...         return my_model_instance
>>>
>>> class MyInferenceEngine(InferenceEngine):
...     def predict_segment(self, audio, start_time):
...         # Run inference on audio segment
...         embedding = self._get_embedding(audio)
...         predictions = self._get_predictions(audio)
...         return InferenceResult(
...             start_time=start_time,
...             end_time=start_time + self.specification.segment_duration,
...             embedding=embedding,
...             predictions=predictions,
...         )
...
...     def predict_batch(self, segments, start_times):
...         # Batch inference implementation
...         return [self.predict_segment(seg, t) for seg, t in zip(segments, start_times)]
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

from echoroo.ml.audio import AudioPreprocessor

logger = logging.getLogger(__name__)


@dataclass
class ModelSpecification:
    """Metadata describing a machine learning model.

    This class encapsulates the key characteristics of an ML model,
    providing a standardized way to query model capabilities and
    requirements.

    Attributes
    ----------
    name : str
        Model name (e.g., "birdnet", "perch").
    version : str
        Model version string (e.g., "2.4", "v1.0").
    sample_rate : int
        Required sample rate in Hz (e.g., 48000 for BirdNET, 32000 for Perch).
    segment_duration : float
        Duration of each inference segment in seconds (e.g., 3.0 for BirdNET).
    embedding_dim : int
        Dimensionality of embedding vectors (e.g., 1024 for BirdNET).
    supports_classification : bool
        Whether the model outputs classification predictions.
        Default is True.
    species_list : list[str] | None
        List of species/class labels the model can predict.
        None if the model only produces embeddings.
        Default is None.

    Examples
    --------
    >>> spec = ModelSpecification(
    ...     name="birdnet",
    ...     version="2.4",
    ...     sample_rate=48000,
    ...     segment_duration=3.0,
    ...     embedding_dim=1024,
    ...     supports_classification=True,
    ...     species_list=["species_a", "species_b"],
    ... )
    >>> print(f"{spec.name} v{spec.version} requires {spec.sample_rate}Hz audio")
    birdnet v2.4 requires 48000Hz audio
    """

    name: str
    version: str
    sample_rate: int
    segment_duration: float
    embedding_dim: int
    supports_classification: bool = True
    species_list: list[str] | None = None

    def __post_init__(self):
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
                f"Model {self.name} supports classification but has no species_list"
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
        """Get the number of species in the model's vocabulary.

        Returns
        -------
        int
            Number of species, or 0 if species_list is None.
        """
        return len(self.species_list) if self.species_list else 0


@dataclass
class InferenceResult:
    """Generic container for inference results from a single audio segment.

    This class provides a unified format for storing inference outputs
    across different models, including embeddings, predictions, and
    associated metadata.

    Attributes
    ----------
    start_time : float
        Start time of the segment in seconds (relative to recording).
    end_time : float
        End time of the segment in seconds (relative to recording).
    embedding : NDArray[np.float32]
        Embedding vector extracted from the audio segment.
        Shape: (embedding_dim,)
    predictions : list[tuple[str, float]]
        List of (species_label, confidence) tuples, sorted by confidence
        descending. Empty list if no predictions above threshold.
        Default is empty list.
    metadata : dict[str, Any]
        Additional model-specific metadata.
        Default is empty dict.

    Examples
    --------
    >>> embedding = np.random.randn(1024).astype(np.float32)
    >>> result = InferenceResult(
    ...     start_time=0.0,
    ...     end_time=3.0,
    ...     embedding=embedding,
    ...     predictions=[("species_a", 0.95), ("species_b", 0.82)],
    ...     metadata={"model": "birdnet"},
    ... )
    >>> print(f"Top prediction: {result.top_prediction}")
    Top prediction: ('species_a', 0.95)
    >>> print(f"Has detection: {result.has_detection}")
    Has detection: True
    """

    start_time: float
    end_time: float
    embedding: NDArray[np.float32]
    predictions: list[tuple[str, float]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
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

    The loader separates model loading logic from inference logic, allowing
    models to be loaded/unloaded independently of the inference engine.

    Parameters
    ----------
    model_dir : Path | None, optional
        Directory containing model files. If None, uses default location
        or downloads from internet. Default is None.

    Attributes
    ----------
    model_dir : Path | None
        Directory containing model files.

    Examples
    --------
    >>> class MyModelLoader(ModelLoader):
    ...     @property
    ...     def specification(self):
    ...         return ModelSpecification(...)
    ...
    ...     def _load_model(self):
    ...         # Load and return model
    ...         return model
    >>>
    >>> loader = MyModelLoader()
    >>> if not loader.is_loaded:
    ...     loader.load()
    >>> model = loader.get_model()
    """

    def __init__(self, model_dir: Path | None = None) -> None:
        """Initialize the model loader.

        Parameters
        ----------
        model_dir : Path | None, optional
            Directory containing model files. Default is None.
        """
        self.model_dir = model_dir
        self._lock = Lock()
        self._loaded = False
        self._model: Any = None

    @property
    @abstractmethod
    def specification(self) -> ModelSpecification:
        """Get the model specification.

        This property must be implemented by subclasses to provide
        metadata about the model.

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

    @abstractmethod
    def _load_model(self) -> Any:
        """Load the model into memory.

        This method must be implemented by subclasses to perform the
        actual model loading. It should return the loaded model object.

        This method is called by `load()` within a thread lock, so it
        does not need to be thread-safe itself.

        Returns
        -------
        Any
            The loaded model object.

        Raises
        ------
        Exception
            Any exceptions raised during model loading should be
            propagated to the caller.
        """
        raise NotImplementedError

    def load(self) -> None:
        """Load the model into memory.

        This method is thread-safe and will only load the model once,
        even if called multiple times concurrently. If the model is
        already loaded, this method returns immediately.

        Raises
        ------
        Exception
            Any exceptions raised by the _load_model implementation
            are propagated to the caller.

        Notes
        -----
        This method uses double-checked locking for thread safety:
        1. Check if loaded (without lock)
        2. Acquire lock
        3. Check again if loaded (with lock)
        4. Load if not loaded
        """
        if self._loaded:
            logger.debug(f"{self.specification.name} model already loaded")
            return

        with self._lock:
            # Double-check after acquiring lock
            if self._loaded:
                return

            logger.info(
                f"Loading {self.specification.name} model (v{self.specification.version})"
            )

            self._model = self._load_model()
            self._loaded = True

            logger.info(
                f"{self.specification.name} model loaded successfully "
                f"(sample_rate={self.specification.sample_rate}Hz, "
                f"embedding_dim={self.specification.embedding_dim})"
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

        Examples
        --------
        >>> loader = MyModelLoader()
        >>> loader.load()
        >>> model = loader.get_model()
        """
        if not self._loaded or self._model is None:
            raise RuntimeError(
                f"{self.specification.name} model not loaded. "
                "Call load() before get_model()."
            )
        return self._model

    def unload(self) -> None:
        """Unload the model and free memory.

        This method removes the model from memory. The model can be
        reloaded by calling `load()` again.

        This is useful for managing memory in systems that need to
        switch between different models or free resources when the
        model is not needed.
        """
        with self._lock:
            self._model = None
            self._loaded = False
            logger.info(f"{self.specification.name} model unloaded")

    def __repr__(self) -> str:
        """Return string representation of the loader.

        Returns
        -------
        str
            String representation including model name and load status.
        """
        spec = self.specification
        status = "loaded" if self._loaded else "not loaded"
        return f"{self.__class__.__name__}(model={spec.name}, version={spec.version}, status={status})"


class InferenceEngine(ABC):
    """Abstract base class for running ML model inference.

    This class provides a unified interface for running inference on
    audio data using different ML models. It handles single segments,
    batches, and entire audio files.

    The engine depends on a ModelLoader for accessing the loaded model
    and uses AudioPreprocessor for processing audio files.

    Parameters
    ----------
    loader : ModelLoader
        Model loader instance. Must be loaded before creating the engine.

    Attributes
    ----------
    loader : ModelLoader
        The model loader used by this engine.

    Examples
    --------
    >>> loader = MyModelLoader()
    >>> loader.load()
    >>> engine = MyInferenceEngine(loader)
    >>> results = engine.predict_file(Path("audio.wav"))
    >>> for result in results:
    ...     print(f"{result.start_time}s: {result.top_prediction}")
    """

    def __init__(self, loader: ModelLoader) -> None:
        """Initialize the inference engine.

        Parameters
        ----------
        loader : ModelLoader
            Model loader instance. Must be loaded before creating the engine.

        Raises
        ------
        RuntimeError
            If the loader has not been loaded yet.
        """
        if not loader.is_loaded:
            raise RuntimeError(
                f"{loader.specification.name} loader must be loaded before "
                "creating inference engine. Call loader.load() first."
            )

        self.loader = loader
        self._model = loader.get_model()

    @property
    def specification(self) -> ModelSpecification:
        """Get the model specification.

        Returns
        -------
        ModelSpecification
            Model metadata from the loader.
        """
        return self.loader.specification

    @abstractmethod
    def predict_segment(
        self,
        audio: NDArray[np.float32],
        start_time: float,
    ) -> InferenceResult:
        """Run inference on a single audio segment.

        This method must be implemented by subclasses to perform
        inference on a single audio segment and return the result.

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

        Raises
        ------
        ValueError
            If audio shape or dtype is invalid.

        Examples
        --------
        >>> audio = np.random.randn(144000).astype(np.float32)
        >>> result = engine.predict_segment(audio, start_time=0.0)
        >>> print(result.embedding.shape)
        (1024,)
        """
        raise NotImplementedError

    @abstractmethod
    def predict_batch(
        self,
        segments: list[NDArray[np.float32]],
        start_times: list[float],
    ) -> list[InferenceResult]:
        """Run batch inference on multiple audio segments.

        This method must be implemented by subclasses to perform
        batch inference, which may be more efficient than processing
        segments individually.

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

        Raises
        ------
        ValueError
            If segments and start_times have different lengths,
            or if any segment has invalid shape.

        Examples
        --------
        >>> segments = [np.random.randn(144000).astype(np.float32) for _ in range(5)]
        >>> start_times = [0.0, 3.0, 6.0, 9.0, 12.0]
        >>> results = engine.predict_batch(segments, start_times)
        >>> print(f"Processed {len(results)} segments")
        Processed 5 segments
        """
        raise NotImplementedError

    def predict_file(
        self,
        path: Path,
        overlap: float = 0.0,
    ) -> list[InferenceResult]:
        """Run inference on an entire audio file.

        This method provides a convenient interface for processing
        entire audio files. It uses AudioPreprocessor to load, resample,
        and segment the audio, then runs batch inference.

        Parameters
        ----------
        path : Path
            Path to the audio file.
        overlap : float, optional
            Overlap between consecutive segments in seconds.
            Must be less than segment_duration.
            Default is 0.0 (no overlap).

        Returns
        -------
        list[InferenceResult]
            List of inference results for each segment.

        Raises
        ------
        FileNotFoundError
            If the audio file does not exist.
        ValueError
            If overlap is invalid (>= segment_duration or < 0).
        RuntimeError
            If audio processing or inference fails.

        Examples
        --------
        >>> results = engine.predict_file(Path("recording.wav"))
        >>> for result in results:
        ...     if result.has_detection:
        ...         print(f"{result.start_time}s: {result.top_prediction}")

        >>> # With overlap
        >>> results = engine.predict_file(Path("recording.wav"), overlap=1.5)
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        spec = self.specification

        if overlap < 0:
            raise ValueError(f"overlap must be non-negative, got {overlap}")

        if overlap >= spec.segment_duration:
            raise ValueError(
                f"overlap ({overlap}s) must be less than "
                f"segment_duration ({spec.segment_duration}s)"
            )

        # Create preprocessor for this model
        preprocessor = AudioPreprocessor(
            target_sr=spec.sample_rate,
            segment_duration=spec.segment_duration,
            overlap=overlap,
            normalize=True,
        )

        logger.debug(
            f"Processing {path.name}: "
            f"target_sr={spec.sample_rate}Hz, "
            f"segment_duration={spec.segment_duration}s, "
            f"overlap={overlap}s"
        )

        # Process file with timestamps
        try:
            segments_with_times = preprocessor.process_recording(path)
        except Exception as e:
            raise RuntimeError(f"Failed to process audio file {path}: {e}") from e

        if not segments_with_times:
            logger.warning(f"No segments extracted from {path}")
            return []

        # Extract segments and start times
        segments = [seg for seg, _, _ in segments_with_times]
        start_times = [start for _, start, _ in segments_with_times]

        logger.debug(f"Extracted {len(segments)} segments, running batch inference")

        # Run batch inference
        try:
            results = self.predict_batch(segments, start_times)
        except Exception as e:
            raise RuntimeError(f"Inference failed for {path}: {e}") from e

        logger.debug(
            f"Inference complete: {len(results)} results, "
            f"{sum(1 for r in results if r.has_detection)} with detections"
        )

        return results

    def __repr__(self) -> str:
        """Return string representation of the engine.

        Returns
        -------
        str
            String representation including model name and version.
        """
        spec = self.specification
        return (
            f"{self.__class__.__name__}("
            f"model={spec.name}, "
            f"version={spec.version}, "
            f"sample_rate={spec.sample_rate}Hz, "
            f"embedding_dim={spec.embedding_dim})"
        )
