"""BirdNET inference engine.

This module runs the BirdNET model on audio files using the official
birdnet Python package, extracting embeddings and species predictions.

Inherits from the base InferenceEngine class to provide consistent interface
with other ML models in Echoroo.

This implementation uses the file-based APIs from birdnet to minimize
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
DEFAULT_BATCH_SIZE = 16

# Default number of file reading processes
DEFAULT_FEEDERS = 1

# Default number of GPU inference workers
DEFAULT_WORKERS = 1


class BirdNETInference(InferenceEngine):
    """Run BirdNET inference on audio files using the birdnet package.

    Extracts both embeddings (1024-dim feature vectors) and species predictions
    from audio files. Uses the birdnet package's encode() and predict() APIs
    for efficient file-level processing.

    Parameters
    ----------
    loader : BirdNETLoader
        A loaded BirdNET model loader instance.
    confidence_threshold : float, optional
        Minimum confidence score for predictions. Default is 0.1.
    top_k : int, optional
        Maximum number of top predictions to return per segment. Default is 10.
    device : str, optional
        Device to use for inference: "GPU" or "CPU". Default is "GPU".
    batch_size : int, optional
        Batch size for GPU processing. Default is 16.
    feeders : int, optional
        Number of file reading processes for parallel I/O. Default is 1.
    workers : int, optional
        Number of GPU inference workers. Default is 1.

    Examples
    --------
    >>> from echoroo.ml.birdnet.loader import BirdNETLoader
    >>> from echoroo.ml.birdnet.inference import BirdNETInference
    >>> loader = BirdNETLoader()
    >>> loader.load()
    >>> inference = BirdNETInference(loader, confidence_threshold=0.25)
    >>> results = inference.predict_file(Path("recording.wav"))
    >>> for r in results:
    ...     print(f"{r.start_time:.1f}s: {r.predictions}")
    """

    def __init__(
        self,
        loader: BirdNETLoader,
        confidence_threshold: float = 0.1,
        top_k: int = 10,
        device: str | None = None,
        batch_size: int | None = None,
        feeders: int | None = None,
        workers: int | None = None,
    ) -> None:
        super().__init__(loader)
        # ``None`` defaults resolve from Settings so the worker honours
        # ECHOROO_ML_* env vars (device / batch / feeders / workers) while
        # explicit call-site overrides keep working. Defaults preserve the
        # historical GPU + batch-16 behaviour.
        from echoroo.core.settings import get_settings

        settings = get_settings()
        self._confidence_threshold = confidence_threshold
        self._top_k = top_k
        if device is not None:
            self._device = device
        else:
            self._device = "GPU" if settings.ML_USE_GPU else "CPU"
        self._batch_size = (
            batch_size if batch_size is not None else settings.ML_GPU_BATCH_SIZE
        )
        self._feeders = feeders if feeders is not None else settings.ML_FEEDERS
        self._workers = workers if workers is not None else settings.ML_WORKERS

    @property
    def confidence_threshold(self) -> float:
        """Get the current confidence threshold."""
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        """Set the confidence threshold (must be in [0, 1])."""
        if not 0 <= value <= 1:
            raise ValueError(f"confidence_threshold must be in [0, 1], got {value}")
        self._confidence_threshold = value

    @property
    def top_k(self) -> int:
        """Get the current top-k setting."""
        return self._top_k

    @top_k.setter
    def top_k(self, value: int) -> None:
        """Set the top-k value (must be >= 1)."""
        if value < 1:
            raise ValueError(f"top_k must be >= 1, got {value}")
        self._top_k = value

    @property
    def device(self) -> str:
        """Get the device being used for inference."""
        return self._device

    @property
    def batch_size(self) -> int:
        """Get the batch size for GPU processing."""
        return self._batch_size

    @batch_size.setter
    def batch_size(self, value: int) -> None:
        """Set the batch size (must be >= 1)."""
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
        # Only pass multiprocessing params for GPU mode (protobuf backend).
        # TFLite backend (CPU mode) does not support these params.
        if self._device != "CPU":
            if self._feeders > 0:
                kwargs["n_producers"] = self._feeders
            if self._workers > 0:
                kwargs["n_workers"] = self._workers
        return kwargs

    def _extract_embeddings(self, embeddings_result: Any) -> NDArray[np.float32]:
        """Normalize embeddings result into a float32 numpy array."""
        raw: Any = (
            embeddings_result.embeddings
            if hasattr(embeddings_result, "embeddings")
            else embeddings_result
        )
        if hasattr(raw, "numpy"):
            raw = raw.numpy()
        return np.asarray(raw, dtype=np.float32)

    def _normalize_embedding_batch(self, embeddings: NDArray[np.float32]) -> NDArray[np.float32]:
        """Normalize embeddings into shape (n_segments, embedding_dim)."""
        result: NDArray[np.float32]
        if embeddings.ndim == 3:
            result = embeddings[0]
        elif embeddings.ndim == 2:
            result = embeddings
        else:
            result = embeddings.reshape(1, -1)
        return result

    def _filter_predictions(
        self,
        probs: NDArray[np.float32],
        species_ids: NDArray[np.intp],
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
            for seg_probs, seg_ids in zip(probs, ids, strict=False)
        ]

    def _run_on_file(
        self,
        file_path: str,
        custom_species_list: list[str] | None = None,
    ) -> tuple[NDArray[np.float32], list[list[tuple[str, float]]]]:
        """Run encode/predict on a file and return embeddings and predictions.

        Parameters
        ----------
        file_path : str
            Path to the audio file.
        custom_species_list : list[str] | None, optional
            Restrict predictions to this set of species labels. None means no
            restriction. Default is None.
        """
        infer_kwargs = self._build_infer_kwargs()
        embeddings_result = self._model.encode(file_path, **infer_kwargs)

        predict_kwargs: dict[str, Any] = {
            "top_k": self._top_k,
            "default_confidence_threshold": self._confidence_threshold,
            **infer_kwargs,
        }
        if custom_species_list is not None:
            predict_kwargs["custom_species_list"] = custom_species_list

        predictions_result = self._model.predict(file_path, **predict_kwargs)
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
        custom_species_list: list[str] | None = None,
    ) -> list[InferenceResult]:
        """Run inference on an entire audio file.

        Uses birdnet's encode() and predict() for efficient file-level processing.

        Parameters
        ----------
        path : Path
            Path to the audio file. Supports wav, flac, mp3, etc.
        overlap : float, optional
            Overlap between segments in seconds. Default is 0.0.
        custom_species_list : list[str] | None, optional
            Restrict predictions to this set of species labels. None means no
            restriction (all species considered). Default is None.

        Returns
        -------
        list[InferenceResult]
            List of inference results, one per segment.

        Raises
        ------
        FileNotFoundError
            If the audio file does not exist.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        embeddings_by_segment, predictions_by_segment = self._run_on_file(
            str(path), custom_species_list=custom_species_list
        )
        n_segments = embeddings_by_segment.shape[0]
        results: list[InferenceResult] = []

        # Calculate time step between segments
        hop_duration = SEGMENT_DURATION - overlap

        for seg_idx in range(n_segments):
            start_time = seg_idx * hop_duration
            end_time = start_time + SEGMENT_DURATION

            embedding = embeddings_by_segment[seg_idx]
            segment_predictions = (
                predictions_by_segment[seg_idx] if seg_idx < len(predictions_by_segment) else []
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
        """Run inference on a single 3-second audio segment.

        Parameters
        ----------
        audio : NDArray[np.float32]
            Audio data at 48kHz, shape (144000,).
        start_time : float, optional
            Start time of the segment in the original recording. Default is 0.0.

        Returns
        -------
        InferenceResult
            Inference result with embedding and predictions.

        Raises
        ------
        ValueError
            If audio shape is invalid.
        """
        audio = audio.astype(np.float32)
        if audio.ndim != 1 or audio.shape[0] != SEGMENT_SAMPLES:
            raise ValueError(
                f"BirdNET expects audio of shape ({SEGMENT_SAMPLES},) at {SAMPLE_RATE}Hz, "
                f"got shape {audio.shape}"
            )

        with self._temp_audio_file(audio) as tmp_path:
            embeddings_by_segment, predictions_by_segment = self._run_on_file(tmp_path)

        if embeddings_by_segment.size == 0:
            embedding: NDArray[np.float32] = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        else:
            embedding = embeddings_by_segment[0]

        segment_predictions = predictions_by_segment[0] if predictions_by_segment else []

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

        Processes each segment individually (birdnet does not support true
        batch array processing; use predict_file() for multi-segment efficiency).

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
        """
        if len(segments) != len(start_times):
            raise ValueError(
                f"segments and start_times must have same length, "
                f"got {len(segments)} and {len(start_times)}"
            )

        if not segments:
            return []

        results = []
        for segment, start_time in zip(segments, start_times, strict=False):
            result = self.predict_segment(segment, start_time)
            results.append(result)

        return results

    def get_embeddings_only(
        self,
        segments: list[NDArray[np.float32]],
    ) -> NDArray[np.float32]:
        """Extract embeddings without predictions.

        Useful for clustering or similarity searches.

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

    def encode_batch(self, file_paths: list[str]) -> Any:
        """Encode multiple files in a single batch call.

        Calls model.encode() once with all file paths, allowing the BirdNET model
        to batch across files internally for significant performance gains.

        Parameters
        ----------
        file_paths : list[str]
            List of absolute paths to audio files. Must be sorted by the caller
            to match BirdNET's internal alphabetical sorting of files.

        Returns
        -------
        Any
            Raw result object from model.encode() with .embeddings attribute.
        """
        kwargs = self._build_infer_kwargs()
        return self._model.encode(file_paths, **kwargs)

    def predict_files_batch(
        self,
        file_paths: list[str],
        custom_species_list: list[str] | None = None,
    ) -> tuple[Any, Any]:
        """Run encode + predict on multiple files in a single batch call.

        Calls model.encode() and model.predict() once each with all file paths,
        allowing the BirdNET model to batch across files internally for significant
        performance gains over per-file inference.

        Parameters
        ----------
        file_paths : list[str]
            List of absolute paths to audio files. Must be sorted by the caller
            to match BirdNET's internal alphabetical sorting of files.
        custom_species_list : list[str] | None, optional
            Restrict predictions to this set of species labels (geo filter).
            None means no restriction (all species considered). Default is None.

        Returns
        -------
        tuple[Any, Any]
            (embeddings_result, predictions_result) from the model, where each
            result contains data for all files in the batch.
        """
        kwargs = self._build_infer_kwargs()
        embeddings_result = self._model.encode(file_paths, **kwargs)
        predict_kwargs: dict[str, Any] = {
            "top_k": self._top_k,
            "default_confidence_threshold": self._confidence_threshold,
            **kwargs,
        }
        if custom_species_list is not None:
            predict_kwargs["custom_species_list"] = custom_species_list
        predictions_result = self._model.predict(file_paths, **predict_kwargs)
        return embeddings_result, predictions_result

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
