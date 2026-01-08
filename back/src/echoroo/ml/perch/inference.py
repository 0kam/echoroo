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
from pathlib import Path
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

    def _normalize_embedding_batch(
        self, embeddings: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        """Normalize embeddings into (n_segments, embedding_dim).

        Perch returns embeddings with shape (1, n_segments, embedding_dim) or
        (n_segments, embedding_dim). This method normalizes to (n_segments, embedding_dim).
        """
        if embeddings.ndim == 3:
            return embeddings[0]
        if embeddings.ndim == 2:
            return embeddings
        return embeddings.reshape(1, -1)

    def _collect_predictions_by_segment(
        self, predictions_result: Any
    ) -> list[list[tuple[str, float]]]:
        """Extract predictions for each segment from birdnet/perch output.

        Returns a list where each element contains predictions for one segment.
        """
        if not hasattr(predictions_result, "species_probs"):
            return []

        species_probs = predictions_result.species_probs
        species_ids = predictions_result.species_ids
        species_masked = getattr(predictions_result, "species_masked", None)
        if species_probs is None or species_probs.size == 0:
            return []

        # Handle different output shapes
        if species_probs.ndim == 3:
            probs = species_probs[0]  # (n_segments, n_species)
            ids = species_ids[0]
        elif species_probs.ndim == 2:
            probs = species_probs
            ids = species_ids
        else:
            probs = species_probs.reshape(1, -1)
            ids = species_ids.reshape(1, -1)

        if species_masked is not None:
            if species_masked.ndim == 3:
                mask = species_masked[0].all(axis=1)
            elif species_masked.ndim == 2:
                mask = species_masked.all(axis=1)
            else:
                mask = species_masked.reshape(1, -1).all(axis=1)
            if mask.any():
                keep = ~mask
                probs = probs[keep]
                ids = ids[keep]

        species_list = self._model.species_list

        result = []
        for seg_idx in range(probs.shape[0]):
            seg_logits = probs[seg_idx].astype(np.float32)
            seg_ids = ids[seg_idx]

            # Convert logits to probabilities
            seg_probs = self._logits_to_probs(seg_logits)

            predictions = self._filter_predictions(seg_probs, seg_ids, species_list)
            predictions.sort(key=lambda x: x[1], reverse=True)
            result.append(predictions)

        return result

    def _filter_predictions(
        self,
        probs: NDArray[np.float32],
        species_ids: NDArray[np.int_],
        species_list: list[str],
    ) -> list[tuple[str, float]]:
        """Filter predictions by top_k and confidence threshold.

        Note: This method includes a safety check for logit values.
        If scores are > 1.0 (indicating they're logits not probabilities),
        sigmoid is applied to convert them to probabilities.
        """
        if probs.size == 0:
            return []
        top_k = probs.size if self._top_k is None else min(self._top_k, probs.size)
        top_indices = np.argsort(probs)[-top_k:][::-1]
        predictions: list[tuple[str, float]] = []
        for idx in top_indices:
            conf = float(probs[idx])

            # Safety check: if conf > 1.0, it's likely a logit value
            # Apply sigmoid to convert to probability
            if conf > 1.0:
                conf = 1.0 / (1.0 + np.exp(-conf))

            if conf >= self._confidence_threshold:
                actual_idx = int(species_ids[idx])
                predictions.append((species_list[actual_idx], conf))
        return predictions

    def _logits_to_probs(self, logits: NDArray[np.float32]) -> NDArray[np.float32]:
        """Convert logits to probabilities using sigmoid.

        Perch V2 is a multi-label classifier - multiple species can be detected
        in the same audio segment. We use sigmoid (not softmax) so each class
        has an independent probability, allowing overlapping detections.
        """
        # Sigmoid: 1 / (1 + exp(-x))
        # Clip to avoid overflow
        logits_clipped = np.clip(logits, -500, 500)
        return 1.0 / (1.0 + np.exp(-logits_clipped))

    def _extract_predictions_from_result(
        self, predictions_result: Any
    ) -> list[tuple[str, float]]:
        """Extract predictions from birdnet result.

        Note: Perch V2 returns logits (not probabilities) in species_probs,
        so we apply softmax to convert them to proper probabilities.
        """
        predictions: list[tuple[str, float]] = []
        species_list = self._model.species_list

        if hasattr(predictions_result, "species_probs"):
            species_logits = predictions_result.species_probs
            species_ids = predictions_result.species_ids

            if species_logits is not None and species_logits.size > 0:
                if species_logits.ndim == 3:
                    logits = species_logits[0, 0, :]
                    ids = species_ids[0, 0, :]
                elif species_logits.ndim == 2:
                    logits = species_logits[0, :]
                    ids = species_ids[0, :]
                else:
                    logits = species_logits.flatten()
                    ids = species_ids.flatten()

                # Convert logits to probabilities
                probs = self._logits_to_probs(logits.astype(np.float32))
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
        if hasattr(embeddings_result, "embeddings_masked"):
            masked = embeddings_result.embeddings_masked
            if masked.ndim == 2:
                masked = masked[0]
            keep = ~masked
            embeddings = embeddings[0][keep] if embeddings.ndim == 3 else embeddings[keep]
        return self._normalize_embedding(embeddings)

    def _run_on_file(
        self, file_path: str
    ) -> tuple[NDArray[np.float32], list[list[tuple[str, float]]]]:
        """Run encode/predict on a file and return all segment results at once.

        This method processes the entire file in a single pass, calling encode()
        and predict() only once each. This is much more efficient than processing
        each segment individually, which would require N*2 calls for N segments.

        Parameters
        ----------
        file_path : str
            Path to audio file.

        Returns
        -------
        tuple[NDArray[np.float32], list[list[tuple[str, float]]]]
            - embeddings_by_segment: Array of shape (n_segments, embedding_dim)
            - predictions_by_segment: List of predictions for each segment
        """
        infer_kwargs = self._build_infer_kwargs()
        # Single encode call for all segments
        embeddings_result = self._model.encode(file_path, **infer_kwargs)

        # Single predict call for all segments
        predictions_result = self._model.predict(
            file_path,
            top_k=self._top_k,
            default_confidence_threshold=self._confidence_threshold,
            **infer_kwargs,
        )

        # Process embeddings into (n_segments, embedding_dim)
        embeddings = self._extract_embeddings(embeddings_result)
        if hasattr(embeddings_result, "embeddings_masked"):
            masked = embeddings_result.embeddings_masked
            if masked.ndim == 2:
                masked = masked[0]
            keep = ~masked
            embeddings = embeddings[0][keep] if embeddings.ndim == 3 else embeddings[keep]
        embeddings_by_segment = self._normalize_embedding_batch(embeddings)

        # Process predictions into list of segment predictions
        predictions_by_segment = self._collect_predictions_by_segment(predictions_result)

        return embeddings_by_segment, predictions_by_segment

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

    def predict_file(
        self,
        path: Path,
        overlap: float = 0.0,
    ) -> list[InferenceResult]:
        """Run inference on an entire audio file efficiently.

        This method overrides the base class implementation to use file-based
        inference, which is significantly faster than segment-by-segment processing.

        Instead of:
        - Creating N temporary files
        - Calling encode() N times
        - Calling predict() N times

        This method:
        - Calls encode() once for the entire file
        - Calls predict() once for the entire file
        - Splits results by segment

        For a file with 61 segments, this reduces I/O from 183 operations to 2.

        Parameters
        ----------
        path : Path
            Path to the audio file. Supports wav, flac, mp3, etc.
        overlap : float, optional
            Overlap between segments in seconds. Default is 0.0.

        Returns
        -------
        list[InferenceResult]
            List of inference results, one per segment.

        Raises
        ------
        FileNotFoundError
            If the audio file does not exist.

        Examples
        --------
        >>> results = inference.predict_file(Path("recording.wav"))
        >>> for r in results:
        ...     if r.predictions:
        ...         print(f"{r.start_time:.1f}s: {r.predictions[0]}")
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        # Run encode + predict once for the entire file
        embeddings_by_segment, predictions_by_segment = self._run_on_file(str(path))

        n_segments = embeddings_by_segment.shape[0]
        results: list[InferenceResult] = []

        # Calculate time step between segments
        hop_duration = SEGMENT_DURATION - overlap

        for seg_idx in range(n_segments):
            start_time = seg_idx * hop_duration
            end_time = start_time + SEGMENT_DURATION

            embedding = embeddings_by_segment[seg_idx]
            segment_predictions = (
                predictions_by_segment[seg_idx]
                if seg_idx < len(predictions_by_segment)
                else []
            )

            result = InferenceResult(
                start_time=start_time,
                end_time=end_time,
                embedding=embedding.astype(np.float32),
                predictions=segment_predictions,
            )
            results.append(result)

        return results

    def predict_batch(
        self,
        segments: list[NDArray[np.float32]],
        start_times: list[float],
    ) -> list[InferenceResult]:
        """Run batch inference on multiple segments efficiently.

        Implements the abstract method from InferenceEngine.

        This optimized implementation concatenates all segments into a single
        temporary audio file and processes them in one encode() + predict() call,
        then splits the results back into individual segment results.

        For N segments, this reduces:
        - Temporary file operations: N -> 1
        - encode() calls: N -> 1
        - predict() calls: N -> 1

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

        # Concatenate all segments into one audio array
        # Each segment is exactly SEGMENT_SAMPLES long (5 seconds @ 32kHz)
        concatenated_audio = np.concatenate(validated_segments, axis=0)

        # Write single temporary file with all segments
        with self._temp_audio_file(concatenated_audio) as tmp_path:
            embeddings_by_segment, predictions_by_segment = self._run_on_file(tmp_path)

        # Build results
        results = []
        for seg_idx, start_time in enumerate(start_times):
            if seg_idx < embeddings_by_segment.shape[0]:
                embedding = embeddings_by_segment[seg_idx]
            else:
                embedding = np.zeros(EMBEDDING_DIM, dtype=np.float32)

            segment_predictions = (
                predictions_by_segment[seg_idx]
                if seg_idx < len(predictions_by_segment)
                else []
            )

            result = InferenceResult(
                start_time=start_time,
                end_time=start_time + SEGMENT_DURATION,
                embedding=embedding.astype(np.float32),
                predictions=segment_predictions,
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

        This optimized implementation concatenates all segments into a single
        temporary audio file and processes them in one encode() call.

        For N segments, this reduces:
        - Temporary file operations: N -> 1
        - encode() calls: N -> 1

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

        # Concatenate all segments into one audio array
        concatenated_audio = np.concatenate(validated_segments, axis=0)

        # Write single temporary file with all segments
        with self._temp_audio_file(concatenated_audio) as tmp_path:
            infer_kwargs = self._build_infer_kwargs()
            embeddings_result = self._model.encode(tmp_path, **infer_kwargs)
            embeddings = self._extract_embeddings(embeddings_result)
            embeddings_by_segment = self._normalize_embedding_batch(embeddings)

        return embeddings_by_segment.astype(np.float32)
