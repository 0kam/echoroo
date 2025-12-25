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
from typing import TYPE_CHECKING

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
        Batch size for processing multiple segments. Default is 32.
    confidence_threshold : float, optional
        Minimum confidence threshold for predictions (0.0 to 1.0).
        Predictions below this threshold are filtered out. Default is 0.1.
    top_k : int | None, optional
        Maximum number of top predictions to return per segment.
        If None, all predictions above threshold are returned. Default is None.

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
        batch_size: int = 32,
        confidence_threshold: float = 0.1,
        top_k: int | None = None,
    ):
        """Initialize the Perch V2 inference engine.

        Parameters
        ----------
        loader : PerchLoader
            PerchLoader instance (must be loaded).
        batch_size : int, optional
            Batch size for processing. Default is 32.
        confidence_threshold : float, optional
            Minimum confidence threshold. Default is 0.1.
        top_k : int | None, optional
            Maximum predictions per segment. Default is None.

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

    def _extract_predictions(
        self, audio: NDArray[np.float32]
    ) -> list[tuple[str, float]]:
        """Extract species predictions using model.predict().

        Parameters
        ----------
        audio : NDArray[np.float32]
            Audio segment, shape (segment_samples,).

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
            # Use birdnet's predict API
            # Returns list of predictions with species and confidence
            predictions_raw = self._model.predict(audio)

            # Convert to our format and filter by threshold
            predictions: list[tuple[str, float]] = []
            for pred in predictions_raw:
                # Extract species and confidence from prediction
                if isinstance(pred, dict):
                    species = pred.get("species", pred.get("label", ""))
                    confidence = float(pred.get("confidence", pred.get("score", 0.0)))
                elif isinstance(pred, (tuple, list)) and len(pred) >= 2:
                    species, confidence = str(pred[0]), float(pred[1])
                else:
                    continue

                # Filter by threshold
                if confidence >= self._confidence_threshold:
                    predictions.append((species, confidence))

            # Sort by confidence descending
            predictions.sort(key=lambda x: x[1], reverse=True)

            # Apply top_k if specified
            if self._top_k is not None:
                predictions = predictions[: self._top_k]

            return predictions

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
        # Use birdnet's encode API for embeddings
        embeddings_result = self._model.encode(file_path)

        # Handle EmbeddingsResult object from birdnet
        if hasattr(embeddings_result, "embeddings"):
            embeddings = embeddings_result.embeddings
        else:
            embeddings = embeddings_result

        # Convert to numpy if needed
        if hasattr(embeddings, "numpy"):
            embeddings = embeddings.numpy()

        embeddings = np.asarray(embeddings, dtype=np.float32)

        # Shape: (n_inputs, n_segments, embedding_dim) -> flatten to single embedding
        if embeddings.ndim == 3:
            embedding = embeddings[0, 0, :]
        elif embeddings.ndim == 2:
            embedding = embeddings[0, :]
        else:
            embedding = embeddings.flatten()

        # Handle multi-frame embeddings by averaging
        if embedding.shape[0] != EMBEDDING_DIM:
            num_frames = embedding.shape[0] // EMBEDDING_DIM
            if num_frames > 0 and embedding.shape[0] == num_frames * EMBEDDING_DIM:
                embedding = embedding.reshape(num_frames, EMBEDDING_DIM).mean(axis=0)
            else:
                # Truncate or pad to expected dimension
                if embedding.shape[0] > EMBEDDING_DIM:
                    embedding = embedding[:EMBEDDING_DIM]
                else:
                    padded = np.zeros(EMBEDDING_DIM, dtype=np.float32)
                    padded[: embedding.shape[0]] = embedding
                    embedding = padded

        return embedding

    def _get_embedding(self, audio: NDArray[np.float32]) -> NDArray[np.float32]:
        """Extract embedding using model.encode() via temporary file.

        Parameters
        ----------
        audio : NDArray[np.float32]
            Audio segment, shape (segment_samples,).

        Returns
        -------
        NDArray[np.float32]
            Embedding vector, shape (1536,).

        Notes
        -----
        The birdnet Perch API expects file paths, so we write audio to
        a temporary file for processing.
        """
        import soundfile as sf

        # Write to temporary file for birdnet processing
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE)
            tmp_path = tmp.name

        try:
            return self._get_embedding_from_file(tmp_path)
        finally:
            # Clean up temp file
            os.unlink(tmp_path)

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

        # Extract embedding
        embedding = self._get_embedding(audio)

        # Extract predictions
        predictions = self._extract_predictions(audio)

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
            # Extract embedding
            embedding = self._get_embedding(audio)

            # Extract predictions
            predictions = self._extract_predictions(audio)

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
            embedding = self._get_embedding(audio)
            embeddings.append(embedding)

        return np.stack(embeddings)
