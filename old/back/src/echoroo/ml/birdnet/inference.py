"""BirdNET inference engine.

This module runs the BirdNET model on audio files using the official
birdnet Python package (v0.2.x), extracting embeddings and species predictions.

Inherits from the base InferenceEngine class to provide consistent interface
with other ML models in Echoroo.

This implementation uses the compact file-based APIs from birdnet to minimize
overhead and avoid complex session management.
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
from echoroo.ml.birdnet.constants import (
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    SEGMENT_SAMPLES,
)

if TYPE_CHECKING:
    from echoroo.ml.birdnet.loader import BirdNETLoader

logger = logging.getLogger(__name__)

__all__ = [
    "BirdNETInference",
]

# Default batch size for GPU processing
# Adjust based on GPU memory (higher = more GPU utilization but more memory)
DEFAULT_BATCH_SIZE = 16

# Default number of file reading processes
DEFAULT_FEEDERS = 1

# Default number of GPU inference workers
DEFAULT_WORKERS = 1


class BirdNETInference(InferenceEngine):
    """Run BirdNET inference on audio files using the birdnet package.

    This class handles running the BirdNET model on audio files using
    the official birdnet Python package. It extracts both embeddings
    (1024-dim feature vectors) and species predictions.

    Inherits from InferenceEngine to provide consistent interface with
    other ML models in Echoroo.

    Parameters
    ----------
    loader : BirdNETLoader
        A loaded BirdNET model loader instance.
    confidence_threshold : float, optional
        Minimum confidence score for predictions. Default is 0.1.
    top_k : int, optional
        Maximum number of top predictions to return per segment.
        Default is 10.
    device : str, optional
        Device to use for inference: "GPU" or "CPU". Default is "GPU".
    batch_size : int, optional
        Batch size for GPU processing. Default is 16.
    feeders : int, optional
        Number of file reading processes for parallel I/O. Default is 1.
    workers : int, optional
        Number of GPU inference workers. Default is 1.

    Attributes
    ----------
    confidence_threshold : float
        Current confidence threshold.
    top_k : int
        Current top-k setting.
    device : str
        Device being used for inference.
    feeders : int
        Number of file reading processes.
    workers : int
        Number of GPU inference workers.

    Examples
    --------
    Basic usage:

    >>> from echoroo.ml.birdnet import BirdNETLoader, BirdNETInference
    >>> loader = BirdNETLoader()
    >>> loader.load()
    >>> inference = BirdNETInference(loader, confidence_threshold=0.25)
    >>>
    >>> # Process entire file
    >>> results = inference.predict_file(Path("recording.wav"))
    >>> for r in results:
    ...     print(f"{r.start_time:.1f}s: {r.predictions}")
    >>>
    >>> # Process single segment
    >>> audio = np.random.randn(144000).astype(np.float32)
    >>> result = inference.predict_segment(audio)
    >>> print(f"Embedding shape: {result.embedding.shape}")
    Embedding shape: (1024,)

    Notes
    -----
    BirdNET expects audio in the following format:
    - Sample rate: 48kHz
    - Duration: 3 seconds (144,000 samples)
    - Format: mono, float32

    The birdnet package handles resampling internally when using
    predict_file(), but predict_segment() and predict_batch() require
    properly formatted audio.
    """

    def __init__(
        self,
        loader: BirdNETLoader,
        confidence_threshold: float = 0.1,
        top_k: int = 10,
        device: str = "GPU",
        batch_size: int = DEFAULT_BATCH_SIZE,
        feeders: int = DEFAULT_FEEDERS,
        workers: int = DEFAULT_WORKERS,
    ) -> None:
        """Initialize the BirdNET inference engine.

        Parameters
        ----------
        loader : BirdNETLoader
            A loaded BirdNET model loader instance.
        confidence_threshold : float, optional
            Minimum confidence score for predictions. Default is 0.1.
        top_k : int, optional
            Maximum number of top predictions to return. Default is 10.
        device : str, optional
            Device to use for inference: "GPU" or "CPU". Default is "GPU".
        batch_size : int, optional
            Batch size for GPU processing. Higher values use more GPU memory
            but improve throughput. Default is 16.
    feeders : int, optional
        Number of file reading processes for parallel I/O. Default is 1.
        workers : int, optional
            Number of GPU inference workers. Default is 1.

        Raises
        ------
        RuntimeError
            If the loader is not yet loaded.
        """
        super().__init__(loader)
        self._confidence_threshold = confidence_threshold
        self._top_k = top_k
        self._device = device
        self._batch_size = batch_size
        self._feeders = feeders
        self._workers = workers

    @property
    def confidence_threshold(self) -> float:
        """Get the current confidence threshold."""
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        """Set the confidence threshold.

        Parameters
        ----------
        value : float
            New threshold value (0-1).

        Raises
        ------
        ValueError
            If value is not in [0, 1].
        """
        if not 0 <= value <= 1:
            raise ValueError(f"confidence_threshold must be in [0, 1], got {value}")
        self._confidence_threshold = value

    @property
    def top_k(self) -> int:
        """Get the current top-k setting."""
        return self._top_k

    @property
    def device(self) -> str:
        """Get the device being used for inference."""
        return self._device

    @top_k.setter
    def top_k(self, value: int) -> None:
        """Set the top-k value.

        Parameters
        ----------
        value : int
            New top-k value (>= 1).

        Raises
        ------
        ValueError
            If value is less than 1.
        """
        if value < 1:
            raise ValueError(f"top_k must be >= 1, got {value}")
        self._top_k = value

    @property
    def batch_size(self) -> int:
        """Get the batch size for GPU processing."""
        return self._batch_size

    @batch_size.setter
    def batch_size(self, value: int) -> None:
        """Set the batch size.

        Parameters
        ----------
        value : int
            New batch size (>= 1).

        Raises
        ------
        ValueError
            If value is less than 1.
        """
        if value < 1:
            raise ValueError(f"batch_size must be >= 1, got {value}")
        self._batch_size = value

    @property
    def feeders(self) -> int:
        """Get the number of file reading processes."""
        return self._feeders

    @property
    def workers(self) -> int:
        """Get the number of GPU inference workers."""
        return self._workers

    def _build_infer_kwargs(self) -> dict[str, Any]:
        """Build kwargs for birdnet encode/predict calls."""
        kwargs: dict[str, Any] = {"device": self._device}
        if self._batch_size > 0:
            kwargs["batch_size"] = self._batch_size
        # Only pass multiprocessing params for GPU mode (protobuf backend)
        # TFLite backend (CPU mode) doesn't use these and they cause issues
        if self._device != "CPU":
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

    def _normalize_embedding_batch(
        self, embeddings: NDArray[np.float32]
    ) -> NDArray[np.float32]:
        """Normalize embeddings into (n_segments, embedding_dim)."""
        if embeddings.ndim == 3:
            return embeddings[0]
        if embeddings.ndim == 2:
            return embeddings
        return embeddings.reshape(1, -1)

    def _filter_predictions(
        self,
        probs: NDArray[np.float32],
        species_ids: NDArray[np.int_],
        species_list: list[str],
    ) -> list[tuple[str, float]]:
        """Filter predictions by top_k and confidence threshold."""
        if probs.size == 0:
            return []
        top_k = min(self._top_k, probs.size)
        top_indices = np.argsort(probs)[-top_k:][::-1]
        predictions: list[tuple[str, float]] = []
        for idx in top_indices:
            conf = float(probs[idx])
            if conf >= self._confidence_threshold:
                actual_idx = int(species_ids[idx])
                predictions.append((species_list[actual_idx], conf))
        return predictions

    def _collect_predictions_by_segment(
        self, predictions_result: Any
    ) -> list[list[tuple[str, float]]]:
        """Extract predictions for each segment from birdnet output."""
        if not hasattr(predictions_result, "species_probs"):
            return []

        species_probs = predictions_result.species_probs
        species_ids = predictions_result.species_ids
        if species_probs is None or species_probs.size == 0:
            return []

        if species_probs.ndim == 3:
            probs = species_probs[0]
            ids = species_ids[0]
        elif species_probs.ndim == 2:
            probs = species_probs
            ids = species_ids
        else:
            probs = species_probs.reshape(1, -1)
            ids = species_ids.reshape(1, -1)

        species_list = self._model.species_list
        return [
            self._filter_predictions(seg_probs, seg_ids, species_list)
            for seg_probs, seg_ids in zip(probs, ids)
        ]

    def _run_on_file(
        self, file_path: str
    ) -> tuple[NDArray[np.float32], list[list[tuple[str, float]]]]:
        """Run encode/predict on a file and return embeddings and predictions."""
        infer_kwargs = self._build_infer_kwargs()
        embeddings_result = self._model.encode(file_path, **infer_kwargs)
        predictions_result = self._model.predict(
            file_path,
            top_k=self._top_k,
            default_confidence_threshold=self._confidence_threshold,
            **infer_kwargs,
        )
        embeddings = self._extract_embeddings(embeddings_result)
        embeddings_by_segment = self._normalize_embedding_batch(embeddings)
        predictions_by_segment = self._collect_predictions_by_segment(predictions_result)
        return embeddings_by_segment, predictions_by_segment

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


    def predict_file(
        self,
        path: Path,
        overlap: float = 0.0,
    ) -> list[InferenceResult]:
        """Run inference on an entire audio file.

        Implements the abstract method from InferenceEngine.

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

    def predict_segment(
        self,
        audio: NDArray[np.float32],
        start_time: float = 0.0,
    ) -> InferenceResult:
        """Run inference on a single 3-second segment.

        Implements the abstract method from InferenceEngine.

        Parameters
        ----------
        audio : NDArray[np.float32]
            Audio data, shape (144000,) at 48kHz sample rate.
            Must be exactly 3 seconds of audio.
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
        >>> audio = np.random.randn(144000).astype(np.float32)
        >>> result = inference.predict_segment(audio, start_time=0.0)
        >>> print(f"Embedding shape: {result.embedding.shape}")
        Embedding shape: (1024,)
        """
        # Validate audio using shared function
        audio = validate_audio_segment(
            audio,
            expected_samples=SEGMENT_SAMPLES,
            sample_rate=SAMPLE_RATE,
            model_name="BirdNET",
        )

        with self._temp_audio_file(audio) as tmp_path:
            embeddings_by_segment, predictions_by_segment = self._run_on_file(tmp_path)

        if embeddings_by_segment.size == 0:
            embedding = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        else:
            embedding = embeddings_by_segment[0]

        segment_predictions = (
            predictions_by_segment[0] if predictions_by_segment else []
        )

        return InferenceResult(
            start_time=start_time,
            end_time=start_time + SEGMENT_DURATION,
            embedding=embedding.astype(np.float32),
            predictions=segment_predictions,
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
            List of audio segments, each shape (144000,).
        start_times : list[float]
            List of start times corresponding to each segment.

        Returns
        -------
        list[InferenceResult]
            List of inference results.

        Raises
        ------
        ValueError
            If segments and start_times have different lengths.

        Examples
        --------
        >>> segments = [np.random.randn(144000).astype(np.float32) for _ in range(5)]
        >>> start_times = [0.0, 3.0, 6.0, 9.0, 12.0]
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

        # Process each segment individually
        # Note: BirdNET's Python API doesn't support true batch processing,
        # so we process segments one at a time
        results = []
        for segment, start_time in zip(segments, start_times):
            result = self.predict_segment(segment, start_time)
            results.append(result)

        return results

    def get_embeddings_only(
        self,
        segments: list[NDArray[np.float32]],
    ) -> NDArray[np.float32]:
        """Extract embeddings without predictions.

        Useful for clustering or similarity searches where species
        predictions are not needed.

        Parameters
        ----------
        segments : list[NDArray[np.float32]]
            List of audio segments, each shape (144000,).

        Returns
        -------
        NDArray[np.float32]
            Embeddings array, shape (num_segments, 1024).
        """
        if not segments:
            return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

        embeddings = []
        for segment in segments:
            result = self.predict_segment(segment)
            embeddings.append(result.embedding)

        return np.stack(embeddings)

    def get_embeddings_from_file(self, path: Path) -> NDArray[np.float32]:
        """Extract embeddings from an audio file.

        Parameters
        ----------
        path : Path
            Path to the audio file.

        Returns
        -------
        NDArray[np.float32]
            Embeddings array, shape (num_segments, 1024).

        Raises
        ------
        FileNotFoundError
            If the audio file does not exist.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        infer_kwargs = self._build_infer_kwargs()
        embeddings_result = self._model.encode(str(path), **infer_kwargs)
        embeddings = self._extract_embeddings(embeddings_result)
        return self._normalize_embedding_batch(embeddings).astype(np.float32)
