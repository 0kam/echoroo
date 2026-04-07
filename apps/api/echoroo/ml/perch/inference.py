"""Perch V2 inference engine using the birdnet library.

This module runs the Perch V2 model on audio segments for extracting
high-dimensional embeddings and species classification predictions.

Uses the birdnet library's Perch V2 APIs:
- model.encode() for embeddings
- model.predict() for classification

Perch V2 specifications:
- Input: 5 seconds @ 32kHz = 160,000 samples
- Output: 1536-dimensional embedding vector
- Classification: multi-label (uses sigmoid, not softmax)

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
    """Run Perch V2 inference using the birdnet library.

    Extracts 1536-dimensional embedding vectors and species classification
    predictions from audio segments using the Perch V2 model.

    The birdnet Perch V2 API provides:
    - encode() for embeddings
    - predict() for classification with confidence scores

    Parameters
    ----------
    loader : PerchLoader
        PerchLoader instance (must be loaded).
    batch_size : int, optional
        Batch size for GPU inference. Default is 16.
    confidence_threshold : float, optional
        Minimum confidence threshold for predictions (0.0 to 1.0). Default is 0.1.
    top_k : int | None, optional
        Maximum number of top predictions to return per segment.
        If None, all predictions above threshold are returned. Default is None.
    feeders : int, optional
        Number of file reading processes. Default is 1.
    workers : int, optional
        Number of GPU inference workers. Default is 1.
    device : str | None, optional
        Device for inference. If None, uses loader's device. Default is None.

    Examples
    --------
    >>> from echoroo.ml.perch.loader import PerchLoader
    >>> from echoroo.ml.perch.inference import PerchInference
    >>> loader = PerchLoader()
    >>> loader.load()
    >>> inference = PerchInference(loader, confidence_threshold=0.3)
    >>> results = inference.predict_file(Path("recording.wav"))
    >>> for result in results:
    ...     print(f"{result.start_time}s: {result.embedding.shape}")
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
    ) -> None:
        super().__init__(loader)

        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(f"confidence_threshold must be in [0, 1], got {confidence_threshold}")
        if top_k is not None and top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")

        self._batch_size = batch_size
        self._confidence_threshold = confidence_threshold
        self._top_k = top_k
        self._feeders = feeders
        self._workers = workers
        self._device = device if device is not None else loader.device

    @property
    def batch_size(self) -> int:
        """Get the current batch size."""
        return self._batch_size

    @batch_size.setter
    def batch_size(self, value: int) -> None:
        """Set the batch size (must be >= 1)."""
        if value < 1:
            raise ValueError(f"batch_size must be >= 1, got {value}")
        self._batch_size = value

    @property
    def confidence_threshold(self) -> float:
        """Get the current confidence threshold."""
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        """Set the confidence threshold (must be in [0, 1])."""
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence_threshold must be in [0, 1], got {value}")
        self._confidence_threshold = value

    @property
    def top_k(self) -> int | None:
        """Get the current top-k setting."""
        return self._top_k

    @top_k.setter
    def top_k(self, value: int | None) -> None:
        """Set the top-k value (must be positive or None)."""
        if value is not None and value <= 0:
            raise ValueError(f"top_k must be positive, got {value}")
        self._top_k = value

    def _build_infer_kwargs(self) -> dict[str, Any]:
        """Build kwargs for birdnet Perch V2 encode/predict calls.

        Perch V2 uses ``n_producers`` (not ``n_feeders``) for file reading
        processes.

        Notes
        -----
        Multiprocessing params (``n_producers``, ``n_workers``) are only
        passed when running on GPU (protobuf backend).  The TFLite backend
        used for CPU does not support these parameters.
        """
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

    def _normalize_single_embedding(self, embeddings: NDArray[np.float32]) -> NDArray[np.float32]:
        """Normalize embeddings into a single (EMBEDDING_DIM,) vector."""
        emb: NDArray[np.float32]
        if embeddings.ndim == 3:
            emb = embeddings[0, 0, :]
        elif embeddings.ndim == 2:
            emb = embeddings[0, :]
        else:
            emb = embeddings.flatten()

        if emb.shape[0] != EMBEDDING_DIM:
            num_frames = emb.shape[0] // EMBEDDING_DIM
            if num_frames > 0 and emb.shape[0] == num_frames * EMBEDDING_DIM:
                emb = emb.reshape(num_frames, EMBEDDING_DIM).mean(axis=0).astype(np.float32)
            elif emb.shape[0] > EMBEDDING_DIM:
                emb = emb[:EMBEDDING_DIM]
            else:
                padded: NDArray[np.float32] = np.zeros(EMBEDDING_DIM, dtype=np.float32)
                padded[: emb.shape[0]] = emb
                emb = padded

        return emb.astype(np.float32)

    def _normalize_embedding_batch(self, embeddings: NDArray[np.float32]) -> NDArray[np.float32]:
        """Normalize embeddings into shape (n_segments, EMBEDDING_DIM).

        Perch returns embeddings with shape (1, n_segments, embedding_dim) or
        (n_segments, embedding_dim). This method normalizes to (n_segments, embedding_dim).
        """
        result: NDArray[np.float32]
        if embeddings.ndim == 3:
            result = embeddings[0]
        elif embeddings.ndim == 2:
            result = embeddings
        else:
            result = embeddings.reshape(1, -1)
        return result

    def _logits_to_probs(self, logits: NDArray[np.float32]) -> NDArray[np.float32]:
        """Convert logits to probabilities using sigmoid.

        Perch V2 is a multi-label classifier; sigmoid is used so each class
        has an independent probability, allowing overlapping detections.
        """
        logits_clipped = np.clip(logits, -500, 500)
        return np.asarray(1.0 / (1.0 + np.exp(-logits_clipped)), dtype=np.float32)

    def _filter_predictions(
        self,
        probs: NDArray[np.float32],
        species_ids: NDArray[np.intp],
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
            # Safety check: if conf > 1.0, it's likely a logit value
            if conf > 1.0:
                conf = float(1.0 / (1.0 + np.exp(-conf)))
            if conf >= self._confidence_threshold:
                actual_idx = int(species_ids[idx])
                predictions.append((species_list[actual_idx], conf))
        return predictions

    def _collect_predictions_by_segment(
        self, predictions_result: Any
    ) -> list[list[tuple[str, float]]]:
        """Extract predictions for each segment from birdnet/Perch output."""
        if not hasattr(predictions_result, "species_probs"):
            return []

        species_probs = predictions_result.species_probs
        species_ids = predictions_result.species_ids
        species_masked = getattr(predictions_result, "species_masked", None)
        if species_probs is None or species_probs.size == 0:
            return []

        # Normalize shape to (n_segments, n_species)
        if species_probs.ndim == 3:
            probs = species_probs[0]
            ids = species_ids[0]
        elif species_probs.ndim == 2:
            probs = species_probs
            ids = species_ids
        else:
            probs = species_probs.reshape(1, -1)
            ids = species_ids.reshape(1, -1)

        # Apply masking if available
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
        if not species_list:
            # No species vocabulary available; cannot produce classification predictions.
            logger.debug("Perch model has no species_list; skipping classification predictions")
            return [[] for _ in range(probs.shape[0])]

        result = []
        for seg_idx in range(probs.shape[0]):
            seg_logits = probs[seg_idx].astype(np.float32)
            seg_ids = ids[seg_idx]

            # Convert logits to probabilities using sigmoid
            seg_probs = self._logits_to_probs(seg_logits)

            predictions = self._filter_predictions(seg_probs, seg_ids, species_list)
            predictions.sort(key=lambda x: x[1], reverse=True)
            result.append(predictions)

        return result

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

    def _run_on_file(
        self, file_path: str
    ) -> tuple[NDArray[np.float32], list[list[tuple[str, float]]]]:
        """Run encode/predict on a file and return all segment results.

        Processes the entire file in a single pass, calling encode() and
        predict() only once each for efficiency.

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

        embeddings_result = self._model.encode(file_path, **infer_kwargs)
        predictions_result = self._model.predict(
            file_path,
            top_k=self._top_k,
            default_confidence_threshold=self._confidence_threshold,
            **infer_kwargs,
        )

        # Process embeddings
        embeddings = self._extract_embeddings(embeddings_result)
        if hasattr(embeddings_result, "embeddings_masked"):
            masked = embeddings_result.embeddings_masked
            # embeddings_masked shape is (1, n_segments, embedding_dim) — per-element mask.
            # Reduce to per-segment boolean: a segment is masked if ALL elements are True.
            if masked.ndim == 3:
                seg_masked = masked[0].all(axis=1)  # (n_segments,)
            elif masked.ndim == 2:
                seg_masked = masked.all(axis=1)
            else:
                seg_masked = masked.flatten()
            keep = ~seg_masked
            # Select non-masked segments from embeddings
            embeddings = embeddings[0][keep] if embeddings.ndim == 3 else embeddings[keep]
        embeddings_by_segment = self._normalize_embedding_batch(embeddings)

        # Process predictions
        predictions_by_segment = self._collect_predictions_by_segment(predictions_result)

        return embeddings_by_segment, predictions_by_segment

    def predict_segment(
        self,
        audio: NDArray[np.float32],
        start_time: float = 0.0,
    ) -> InferenceResult:
        """Run inference on a single 5-second audio segment.

        Parameters
        ----------
        audio : NDArray[np.float32]
            Audio data at 32kHz, shape (160000,).
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
                f"Perch V2 expects audio of shape ({SEGMENT_SAMPLES},) at {SAMPLE_RATE}Hz, "
                f"got shape {audio.shape}"
            )

        with self._temp_audio_file(audio) as tmp_path:
            infer_kwargs = self._build_infer_kwargs()
            embeddings_result = self._model.encode(tmp_path, **infer_kwargs)
            embeddings = self._extract_embeddings(embeddings_result)
            if hasattr(embeddings_result, "embeddings_masked"):
                masked = embeddings_result.embeddings_masked
                # Per-element mask (1, n_segments, dim) — reduce to per-segment
                if masked.ndim == 3:
                    seg_masked = masked[0].all(axis=1)
                elif masked.ndim == 2:
                    seg_masked = masked.all(axis=1)
                else:
                    seg_masked = masked.flatten()
                keep = ~seg_masked
                embeddings = embeddings[0][keep] if embeddings.ndim == 3 else embeddings[keep]
            embedding = self._normalize_single_embedding(embeddings)

            predictions: list[tuple[str, float]] = []
            if self.specification.supports_classification:
                try:
                    pred_result = self._model.predict(
                        tmp_path,
                        default_confidence_threshold=self._confidence_threshold,
                        top_k=self._top_k,
                        **infer_kwargs,
                    )
                    segs = self._collect_predictions_by_segment(pred_result)
                    predictions = segs[0] if segs else []
                except Exception as e:
                    logger.debug("Could not extract predictions: %s", e)

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
        custom_species_list: list[str] | None = None,  # noqa: ARG002
    ) -> list[InferenceResult]:
        """Run inference on an entire audio file efficiently.

        Calls encode() and predict() once each for the entire file,
        then splits results by segment. This is significantly faster than
        processing each segment individually.

        Parameters
        ----------
        path : Path
            Path to the audio file.
        overlap : float, optional
            Overlap between segments in seconds. Default is 0.0.
        custom_species_list : list[str] | None, optional
            Restrict predictions to this set of species labels. None means no
            restriction (all species considered). Default is None.
            Note: Perch does not support geo filtering; this parameter is
            accepted for interface compatibility but currently ignored.

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

        embeddings_by_segment, predictions_by_segment = self._run_on_file(str(path))

        n_segments = embeddings_by_segment.shape[0]
        results: list[InferenceResult] = []

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

    def predict_batch(
        self,
        segments: list[NDArray[np.float32]],
        start_times: list[float],
    ) -> list[InferenceResult]:
        """Run batch inference on multiple segments.

        Concatenates all segments into a single temporary audio file and
        processes them in one encode() + predict() call for efficiency.

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
        """
        if len(segments) != len(start_times):
            raise ValueError(
                f"segments and start_times must have same length, "
                f"got {len(segments)} and {len(start_times)}"
            )

        if not segments:
            return []

        # Validate all segments
        validated: list[NDArray[np.float32]] = []
        for seg in segments:
            seg = seg.astype(np.float32)
            if seg.ndim != 1 or seg.shape[0] != SEGMENT_SAMPLES:
                raise ValueError(
                    f"Perch V2 expects audio of shape ({SEGMENT_SAMPLES},) at {SAMPLE_RATE}Hz, "
                    f"got shape {seg.shape}"
                )
            validated.append(seg)

        # Concatenate all segments into one audio array for a single file call
        concatenated_audio = np.concatenate(validated, axis=0)

        with self._temp_audio_file(concatenated_audio) as tmp_path:
            embeddings_by_segment, predictions_by_segment = self._run_on_file(tmp_path)

        results = []
        for seg_idx, start_time in enumerate(start_times):
            if seg_idx < embeddings_by_segment.shape[0]:
                embedding = embeddings_by_segment[seg_idx]
            else:
                embedding = np.zeros(EMBEDDING_DIM, dtype=np.float32)

            segment_predictions = (
                predictions_by_segment[seg_idx] if seg_idx < len(predictions_by_segment) else []
            )

            result = InferenceResult(
                start_time=start_time,
                end_time=start_time + SEGMENT_DURATION,
                embedding=embedding.astype(np.float32),
                predictions=segment_predictions,
            )
            results.append(result)

        return results

    def encode_batch(self, file_paths: list[str]) -> Any:
        """Encode multiple files in a single batch call.

        Calls model.encode() once with all file paths, allowing the Perch model
        to batch across files internally for significant performance gains.

        Parameters
        ----------
        file_paths : list[str]
            List of absolute paths to audio files. Must be sorted by the caller
            to match BirdNET's internal alphabetical sorting of files.

        Returns
        -------
        Any
            Raw result object from model.encode() with .embeddings and
            optionally .embeddings_masked attributes.
        """
        kwargs = self._build_infer_kwargs()
        return self._model.encode(file_paths, **kwargs)

    def predict_files_batch(self, file_paths: list[str]) -> tuple[Any, Any]:
        """Run encode + predict on multiple files in a single batch call.

        Calls model.encode() and model.predict() once each with all file paths,
        allowing the Perch model to batch across files internally for significant
        performance gains over per-file inference.

        Parameters
        ----------
        file_paths : list[str]
            List of absolute paths to audio files. Must be sorted by the caller
            to match BirdNET's internal alphabetical sorting of files.

        Returns
        -------
        tuple[Any, Any]
            (embeddings_result, predictions_result) from the model, where each
            result contains data for all files in the batch.
        """
        kwargs = self._build_infer_kwargs()
        embeddings_result = self._model.encode(file_paths, **kwargs)
        predictions_result = self._model.predict(
            file_paths,
            top_k=self._top_k,
            default_confidence_threshold=self._confidence_threshold,
            **kwargs,
        )
        return embeddings_result, predictions_result

    def get_embeddings_only(
        self,
        segments: list[NDArray[np.float32]],
    ) -> NDArray[np.float32]:
        """Extract embeddings without creating full results.

        Concatenates all segments into a single file and calls encode() once.

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

        validated: list[NDArray[np.float32]] = []
        for seg in segments:
            seg = seg.astype(np.float32)
            if seg.ndim != 1 or seg.shape[0] != SEGMENT_SAMPLES:
                raise ValueError(
                    f"Perch V2 expects audio of shape ({SEGMENT_SAMPLES},) at {SAMPLE_RATE}Hz, "
                    f"got shape {seg.shape}"
                )
            validated.append(seg)

        concatenated_audio = np.concatenate(validated, axis=0)

        with self._temp_audio_file(concatenated_audio) as tmp_path:
            infer_kwargs = self._build_infer_kwargs()
            embeddings_result = self._model.encode(tmp_path, **infer_kwargs)
            embeddings = self._extract_embeddings(embeddings_result)
            embeddings_by_segment = self._normalize_embedding_batch(embeddings)

        return embeddings_by_segment.astype(np.float32)
