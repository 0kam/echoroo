"""Perch V2 inference engine using birdnet library.

This module runs the Perch V2 model on audio segments for extracting
high-dimensional embeddings and species classification predictions.

Uses the birdnet library's Perch V2 loader, which provides:
- model.encode() for embeddings
- model.predict() for classification
- model.species_list for species labels

Perch V2 specifications:
- Input: 5 seconds @ 32kHz = 160,000 samples
- Output: 1536-dimensional embedding vector
- Classification: ~15,000 bird species classes

Inherits from the base InferenceEngine class to provide consistent interface
with other ML models in Echoroo.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from echoroo.ml.audio import validate_audio_segment
from echoroo.ml.base import InferenceEngine, InferenceResult
from echoroo.ml.perch.constants import (
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    SEGMENT_SAMPLES,
)

if TYPE_CHECKING:
    from echoroo.ml.perch.loader import PerchLoader

logger = logging.getLogger(__name__)

__all__ = [
    "PerchInference",
]


class PerchInference(InferenceEngine):
    """Run Perch V2 inference using birdnet library.

    This class handles running the Perch V2 model (loaded via birdnet)
    on preprocessed audio segments to extract 1536-dimensional embedding
    vectors and species classification predictions.

    The birdnet Perch V2 API provides:
    - encode() for embeddings
    - predict() for classification with confidence scores

    Inherits from InferenceEngine to provide consistent interface with
    other ML models in Echoroo.

    Parameters
    ----------
    loader : PerchLoader
        PerchLoader instance (must be loaded).
    batch_size : int, optional
        Batch size for GPU inference. Default is 16.
    confidence_threshold : float, optional
        Minimum confidence threshold for predictions (0.0 to 1.0).
        Predictions below this threshold are filtered out. Default is 0.1.
    top_k : int | None, optional
        Maximum number of top predictions to return per segment.
        If None, all predictions above threshold are returned. Default is None.
    feeders : int, optional
        Number of file reading processes. Default is 1.
    workers : int, optional
        Number of GPU inference workers. Default is 1.

    Attributes
    ----------
    batch_size : int
        Current batch size.
    confidence_threshold : float
        Current confidence threshold.
    top_k : int | None
        Current top-k setting.

    Examples
    --------
    >>> from echoroo.ml.perch import PerchLoader, PerchInference
    >>> loader = PerchLoader()
    >>> loader.load()
    >>> inference = PerchInference(loader, confidence_threshold=0.3)
    >>> results = inference.predict_file(Path("recording.wav"))
    >>> for result in results:
    ...     print(f"{result.start_time}s: {result.embedding.shape}")
    ...     if result.has_detection:
    ...         print(f"  Top prediction: {result.top_prediction}")
    """

    def __init__(
        self,
        loader: PerchLoader,
        batch_size: int = 16,
        confidence_threshold: float = 0.1,
        top_k: int | None = None,
        feeders: int = 1,
        workers: int = 1,
        device: str | None = None,
    ):
        """Initialize the Perch V2 inference engine.

        Parameters
        ----------
        loader : PerchLoader
            PerchLoader instance (must be loaded).
        batch_size : int, optional
            Batch size for GPU inference. Default is 16.
        confidence_threshold : float, optional
            Minimum confidence threshold. Default is 0.1.
        top_k : int | None, optional
            Maximum predictions per segment. Default is None.
    feeders : int, optional
        Number of file reading processes. Default is 1.
        workers : int, optional
            Number of GPU inference workers. Default is 1.
        device : str | None, optional
            Device for inference. If None, uses loader's device. Default is None.

        Raises
        ------
        ValueError
            If parameters are invalid.
        RuntimeError
            If loader is not loaded.
        """
        # Initialize base class (validates loader is loaded)
        super().__init__(loader)

        self._batch_size = batch_size
        self._confidence_threshold = confidence_threshold
        self._top_k = top_k
        self._feeders = feeders
        self._workers = workers
        self._device = device if device is not None else loader.device

        # Validate parameters
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                f"confidence_threshold must be in [0, 1], got {confidence_threshold}"
            )
        if top_k is not None and top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")

    @property
    def batch_size(self) -> int:
        """Get the current batch size."""
        return self._batch_size

    @batch_size.setter
    def batch_size(self, value: int) -> None:
        """Set the batch size."""
        if value < 1:
            raise ValueError(f"batch_size must be >= 1, got {value}")
        self._batch_size = value

    @property
    def confidence_threshold(self) -> float:
        """Get the current confidence threshold."""
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        """Set the confidence threshold."""
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence_threshold must be in [0, 1], got {value}")
        self._confidence_threshold = value

    @property
    def top_k(self) -> int | None:
        """Get the current top-k setting."""
        return self._top_k

    @top_k.setter
    def top_k(self, value: int | None) -> None:
        """Set the top-k value."""
        if value is not None and value <= 0:
            raise ValueError(f"top_k must be positive, got {value}")
        self._top_k = value

    def _build_infer_kwargs(self) -> dict[str, Any]:
        """Build kwargs for birdnet encode/predict calls."""
        kwargs: dict[str, Any] = {"device": self._device}
        if self._batch_size > 0:
            kwargs["batch_size"] = self._batch_size
        if self._feeders > 0:
            kwargs["n_feeders"] = self._feeders
        if self._workers > 0:
            kwargs["n_workers"] = self._workers
        return kwargs

    def _extract_embeddings(self, embeddings_result: Any) -> NDArray[np.float32]:
        """Normalize embeddings result into a float32 numpy array."""
        embeddings = (
            embeddings_result.embeddings
            if hasattr(embeddings_result, "embeddings")
            else embeddings_result
        )
        if hasattr(embeddings, "numpy"):
            embeddings = embeddings.numpy()
        return np.asarray(embeddings, dtype=np.float32)

    def _normalize_embedding(self, embeddings: NDArray[np.float32]) -> NDArray[np.float32]:
        """Normalize embeddings into a single (1536,) vector."""
        if embeddings.ndim == 3:
            embedding = embeddings[0, 0, :]
        elif embeddings.ndim == 2:
            embedding = embeddings[0, :]
        else:
            embedding = embeddings.flatten()

        if embedding.shape[0] != EMBEDDING_DIM:
            num_frames = embedding.shape[0] // EMBEDDING_DIM
            if num_frames > 0 and embedding.shape[0] == num_frames * EMBEDDING_DIM:
                embedding = embedding.reshape(num_frames, EMBEDDING_DIM).mean(axis=0)
            elif embedding.shape[0] > EMBEDDING_DIM:
                embedding = embedding[:EMBEDDING_DIM]
            else:
                padded = np.zeros(EMBEDDING_DIM, dtype=np.float32)
                padded[: embedding.shape[0]] = embedding
                embedding = padded

        return embedding.astype(np.float32)

    def _filter_predictions(
        self,
        probs: NDArray[np.float32],
        species_ids: NDArray[np.int_],
        species_list: list[str],
    ) -> list[tuple[str, float]]:
        """Filter predictions by top_k and confidence threshold."""
        if probs.size == 0:
            return []
        top_k = probs.size if self._top_k is None else min(self._top_k, probs.size)
        top_indices = np.argsort(probs)[-top_k:][::-1]
        predictions: list[tuple[str, float]] = []
        for idx in top_indices:
            conf = float(probs[idx])
            if conf >= self._confidence_threshold:
                actual_idx = int(species_ids[idx])
                predictions.append((species_list[actual_idx], conf))
        return predictions

    def _extract_predictions_from_result(
        self, predictions_result: Any
    ) -> list[tuple[str, float]]:
        """Extract predictions from birdnet result."""
        predictions: list[tuple[str, float]] = []
        species_list = self._model.species_list

        if hasattr(predictions_result, "species_probs"):
            species_probs = predictions_result.species_probs
            species_ids = predictions_result.species_ids

            if species_probs is not None and species_probs.size > 0:
                if species_probs.ndim == 3:
                    probs = species_probs[0, 0, :]
                    ids = species_ids[0, 0, :]
                elif species_probs.ndim == 2:
                    probs = species_probs[0, :]
                    ids = species_ids[0, :]
                else:
                    probs = species_probs.flatten()
                    ids = species_ids.flatten()

                predictions = self._filter_predictions(probs, ids, species_list)

        predictions.sort(key=lambda x: x[1], reverse=True)
        return predictions

    @contextmanager
    def _temp_audio_file(self, audio: NDArray[np.float32]) -> Iterator[str]:
        """Write audio to a temporary WAV file and yield its path."""
        import soundfile as sf

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE)
            tmp_path = tmp.name

        try:
            yield tmp_path
        finally:
            os.unlink(tmp_path)

    def _extract_predictions_from_file(
        self, file_path: str
    ) -> list[tuple[str, float]]:
        """Extract species predictions using model.predict().

        Parameters
        ----------
        file_path : str
            Path to audio file.

        Returns
        -------
        list[tuple[str, float]]
            List of (species_label, confidence) tuples, sorted by confidence
            descending. Returns empty list if classification is not available.

        Notes
        -----
        Uses birdnet's model.predict() API which returns predictions
        directly without needing to convert logits to probabilities.
        """
        if not self.specification.supports_classification:
            return []

        try:
            infer_kwargs = self._build_infer_kwargs()
            predictions_result = self._model.predict(
                file_path,
                default_confidence_threshold=self._confidence_threshold,
                top_k=self._top_k,
                **infer_kwargs,
            )
            return self._extract_predictions_from_result(predictions_result)
        except Exception as e:
            logger.debug(f"Could not extract predictions: {e}")
            return []

    def _get_embedding_from_file(self, file_path: str) -> NDArray[np.float32]:
        """Extract embedding from audio file using model.encode().

        Parameters
        ----------
        file_path : str
            Path to audio file.

        Returns
        -------
        NDArray[np.float32]
            Embedding vector, shape (1536,).

        Notes
        -----
        Uses birdnet's model.encode() API to extract embeddings.
        The API may return different shapes depending on implementation,
        so we normalize to ensure (1536,) output.
        """
        infer_kwargs = self._build_infer_kwargs()
        embeddings_result = self._model.encode(file_path, **infer_kwargs)
        embeddings = self._extract_embeddings(embeddings_result)
        return self._normalize_embedding(embeddings)

    def predict_segment(
        self,
        audio: NDArray[np.float32],
        start_time: float = 0.0,
    ) -> InferenceResult:
        """Run inference on a single 5-second segment.

        Implements the abstract method from InferenceEngine.

        Parameters
        ----------
        audio : NDArray[np.float32]
            Audio data, shape (160000,) at 32kHz sample rate.
            Must be exactly 5 seconds of audio.
        start_time : float, optional
            Start time of the segment in the original recording.
            Default is 0.0.

        Returns
        -------
        InferenceResult
            Inference result with embedding and predictions.

        Raises
        ------
        ValueError
            If audio shape is invalid.

        Examples
        --------
        >>> audio = np.random.randn(160000).astype(np.float32)
        >>> result = inference.predict_segment(audio, start_time=0.0)
        >>> print(f"Embedding shape: {result.embedding.shape}")
        Embedding shape: (1536,)
        """
        # Validate input using shared function
        audio = validate_audio_segment(
            audio,
            expected_samples=SEGMENT_SAMPLES,
            sample_rate=SAMPLE_RATE,
            model_name="Perch V2",
        )

        with self._temp_audio_file(audio) as tmp_path:
            embedding = self._get_embedding_from_file(tmp_path)
            predictions = self._extract_predictions_from_file(tmp_path)

        return InferenceResult(
            start_time=start_time,
            end_time=start_time + SEGMENT_DURATION,
            embedding=embedding,
            predictions=predictions,
        )

    def predict_batch(
        self,
        segments: list[NDArray[np.float32]],
        start_times: list[float],
    ) -> list[InferenceResult]:
        """Run batch inference on multiple segments.

        Implements the abstract method from InferenceEngine.

        Parameters
        ----------
        segments : list[NDArray[np.float32]]
            List of audio segments, each shape (160000,).
        start_times : list[float]
            List of start times corresponding to each segment.

        Returns
        -------
        list[InferenceResult]
            List of inference results with embeddings and predictions.

        Raises
        ------
        ValueError
            If segments and start_times have different lengths.

        Examples
        --------
        >>> segments = [np.random.randn(160000).astype(np.float32) for _ in range(5)]
        >>> start_times = [0.0, 5.0, 10.0, 15.0, 20.0]
        >>> results = inference.predict_batch(segments, start_times)
        >>> print(f"Processed {len(results)} segments")
        Processed 5 segments
        """
        if len(segments) != len(start_times):
            raise ValueError(
                f"segments and start_times must have same length, "
                f"got {len(segments)} and {len(start_times)}"
            )

        if not segments:
            return []

        # Validate all segments
        validated_segments = [
            validate_audio_segment(
                seg,
                expected_samples=SEGMENT_SAMPLES,
                sample_rate=SAMPLE_RATE,
                model_name="Perch V2",
            )
            for seg in segments
        ]

        # Process each segment
        results = []
        for audio, start_time in zip(validated_segments, start_times):
            with self._temp_audio_file(audio) as tmp_path:
                embedding = self._get_embedding_from_file(tmp_path)
                predictions = self._extract_predictions_from_file(tmp_path)

            result = InferenceResult(
                start_time=start_time,
                end_time=start_time + SEGMENT_DURATION,
                embedding=embedding,
                predictions=predictions,
            )
            results.append(result)

        return results

    def get_embeddings_only(
        self,
        segments: list[NDArray[np.float32]],
    ) -> NDArray[np.float32]:
        """Extract embeddings without creating full results.

        Useful for batch processing where only the raw embedding
        vectors are needed.

        Parameters
        ----------
        segments : list[NDArray[np.float32]]
            List of audio segments, each shape (160000,).

        Returns
        -------
        NDArray[np.float32]
            Embeddings array, shape (num_segments, 1536).
        """
        if not segments:
            return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

        validated_segments = [
            validate_audio_segment(
                seg,
                expected_samples=SEGMENT_SAMPLES,
                sample_rate=SAMPLE_RATE,
                model_name="Perch V2",
            )
            for seg in segments
        ]

        embeddings = []
        for audio in validated_segments:
            with self._temp_audio_file(audio) as tmp_path:
                embedding = self._get_embedding_from_file(tmp_path)
                embeddings.append(embedding)

        return np.stack(embeddings)
