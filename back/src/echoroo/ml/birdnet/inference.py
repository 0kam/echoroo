"""BirdNET inference engine.

This module runs the BirdNET model on audio files using the official
birdnet Python package (v0.2.x), extracting embeddings and species predictions.

Inherits from the base InferenceEngine class to provide consistent interface
with other ML models in Echoroo.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

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

    Attributes
    ----------
    confidence_threshold : float
        Current confidence threshold.
    top_k : int
        Current top-k setting.

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

        Raises
        ------
        RuntimeError
            If the loader is not yet loaded.
        """
        super().__init__(loader)
        self._confidence_threshold = confidence_threshold
        self._top_k = top_k

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

        # Get embeddings using birdnet
        embeddings_result = self._model.encode(str(path))
        embeddings = embeddings_result.embeddings

        # Get predictions
        predictions_result = self._model.predict(
            str(path),
            top_k=self._top_k,
            default_confidence_threshold=self._confidence_threshold,
        )
        species_probs = predictions_result.species_probs
        species_list = self._model.species_list

        # Build results for each segment
        results: list[InferenceResult] = []

        # Calculate number of segments
        # Embeddings shape: (n_inputs, n_segments, embedding_dim)
        if embeddings.ndim == 3:
            n_segments = embeddings.shape[1]
        else:
            n_segments = 1

        # Calculate time step between segments
        hop_duration = SEGMENT_DURATION - overlap

        for seg_idx in range(n_segments):
            start_time = seg_idx * hop_duration
            end_time = start_time + SEGMENT_DURATION

            # Extract embedding
            if embeddings.ndim == 3:
                embedding = embeddings[0, seg_idx, :]
            else:
                embedding = embeddings.flatten()[:EMBEDDING_DIM]

            # Extract predictions for this segment
            segment_predictions: list[tuple[str, float]] = []
            if species_probs is not None and species_probs.size > 0:
                if species_probs.ndim == 3:
                    probs = species_probs[0, seg_idx, :]
                elif species_probs.ndim == 2:
                    probs = species_probs[seg_idx, :]
                else:
                    probs = species_probs.flatten()

                # Get top-k predictions above threshold
                top_indices = np.argsort(probs)[-self._top_k:][::-1]
                for idx in top_indices:
                    conf = float(probs[idx])
                    if conf >= self._confidence_threshold:
                        species = species_list[idx]
                        segment_predictions.append((species, conf))

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
        import soundfile as sf

        # Validate audio using shared function
        audio = validate_audio_segment(
            audio,
            expected_samples=SEGMENT_SAMPLES,
            sample_rate=SAMPLE_RATE,
            model_name="BirdNET",
        )

        # Write to temporary file for birdnet processing
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE)
            tmp_path = tmp.name

        try:
            # Get embeddings
            embeddings_result = self._model.encode(tmp_path)
            embeddings = embeddings_result.embeddings

            # Get predictions
            predictions_result = self._model.predict(
                tmp_path,
                top_k=self._top_k,
                default_confidence_threshold=self._confidence_threshold,
            )
        finally:
            # Clean up temp file
            os.unlink(tmp_path)

        # Extract embedding (shape: n_inputs, n_segments, embedding_dim)
        if embeddings.ndim == 3:
            embedding = embeddings[0, 0, :]
        else:
            embedding = embeddings.flatten()[:EMBEDDING_DIM]

        # Extract predictions
        segment_predictions: list[tuple[str, float]] = []
        species_list = self._model.species_list
        species_probs = predictions_result.species_probs

        if species_probs is not None and species_probs.size > 0:
            if species_probs.ndim == 3:
                probs = species_probs[0, 0, :]
            else:
                probs = species_probs.flatten()

            top_indices = np.argsort(probs)[-self._top_k:][::-1]
            for idx in top_indices:
                conf = float(probs[idx])
                if conf >= self._confidence_threshold:
                    species = species_list[idx]
                    segment_predictions.append((species, conf))

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

        embeddings_result = self._model.encode(str(path))
        embeddings = embeddings_result.embeddings

        # Shape: (n_inputs, n_segments, embedding_dim) -> (n_segments, embedding_dim)
        if embeddings.ndim == 3:
            return embeddings[0].astype(np.float32)
        return embeddings.astype(np.float32)
