"""Direct TensorFlow inference for Perch V2.

Bypasses birdnet's multiprocess pipeline for low-latency inference
on small numbers of audio files (e.g., search reference audio).
Uses the pre-loaded TF SavedModel directly with numpy arrays.

The TF SavedModel signature is::

    inputs:  {'inputs': Tensor[batch, 160000, float32]}
    outputs: {'embedding': Tensor[batch, 1536, float32], ...}

XLA compilation is triggered once during warmup so that the first real
inference call is fast.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from echoroo.ml.perch.constants import EMBEDDING_DIM, SAMPLE_RATE, SEGMENT_SAMPLES

if TYPE_CHECKING:
    pass  # tensorflow imported lazily inside methods

logger = logging.getLogger(__name__)

__all__ = ["PerchDirectInference"]


class PerchDirectInference:
    """Direct TF inference engine for Perch V2 embeddings.

    Loads the Perch V2 SavedModel from birdnet's local cache and calls it
    directly via ``model.signatures["serving_default"]``, skipping birdnet's
    multiprocess pipeline entirely.

    This is optimized for the search reference audio use case where only a
    small number of short clips need to be embedded on demand.

    Parameters
    ----------
    device : str, optional
        TensorFlow device string.  Only ``"GPU"`` and ``"CPU"`` are accepted
        by ``AcousticPBDownloaderPerchV2``.  Default is ``"GPU"``.
    """

    def __init__(self, device: str = "GPU") -> None:
        self._device = device
        self._model: Any = None
        self._encode_fn: Any = None
        self._warmed_up: bool = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load the TF SavedModel directly from birdnet's model cache.

        Raises
        ------
        ImportError
            If tensorflow or birdnet is not installed.
        RuntimeError
            If the model path cannot be resolved (e.g. not yet downloaded).
        """
        import tensorflow as tf  # type: ignore[import-untyped]
        from birdnet.acoustic.models.perch_v2.pb import (
            AcousticPBDownloaderPerchV2,
        )

        # Resolve effective device — AcousticPBDownloaderPerchV2 only accepts
        # "CPU" or "GPU", so normalise anything else to "CPU".
        effective_device: str
        if self._device in ("CPU", "GPU"):
            effective_device = self._device
        else:
            logger.warning(
                "PerchDirectInference: unsupported device '%s', falling back to GPU",
                self._device,
            )
            effective_device = "GPU"

        # Fall back to CPU when no GPU is visible to TensorFlow.
        if effective_device == "GPU":
            gpus = tf.config.list_physical_devices("GPU")
            if not gpus:
                logger.warning(
                    "PerchDirectInference: GPU requested but no GPU found, using CPU"
                )
                effective_device = "CPU"

        self._device = effective_device

        logger.info(
            "PerchDirectInference: loading SavedModel (device=%s)", self._device
        )

        model_path, _ = AcousticPBDownloaderPerchV2.get_model_path_and_labels(
            self._device  # type: ignore[arg-type]
        )

        if not model_path.exists():
            raise RuntimeError(
                f"Perch V2 SavedModel not found at {model_path}. "
                "Ensure the model has been downloaded by birdnet before calling load()."
            )

        self._model = tf.saved_model.load(str(model_path.absolute()))
        self._encode_fn = self._model.signatures["serving_default"]

        logger.info("PerchDirectInference: SavedModel loaded from %s", model_path)

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    def warmup(self, batch_sizes: list[int] | None = None) -> None:
        """Trigger XLA compilation for common batch sizes.

        Runs a silent dummy batch through the model for each requested size so
        that XLA traces are compiled ahead of time.  After this call the first
        real inference at any of these batch sizes will be fast.

        Parameters
        ----------
        batch_sizes : list[int] | None, optional
            Batch sizes to compile.  Defaults to ``[1, 6, 10, 16]``.
        """
        import tensorflow as tf

        if self._encode_fn is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        if batch_sizes is None:
            batch_sizes = [1, 6, 10, 16]

        logger.info(
            "PerchDirectInference: warming up for batch sizes %s", batch_sizes
        )

        for bs in batch_sizes:
            dummy = np.zeros((bs, SEGMENT_SAMPLES), dtype=np.float32)
            self._encode_fn(inputs=tf.constant(dummy))
            logger.debug("PerchDirectInference: XLA compiled for batch_size=%d", bs)

        self._warmed_up = True
        logger.info("PerchDirectInference: warmup complete")

    # ------------------------------------------------------------------
    # Inference helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_and_resample(file_path: str) -> NDArray[np.float32]:
        """Load audio from *file_path*, convert to mono, resample to 32 kHz.

        Parameters
        ----------
        file_path : str
            Path to any audio file supported by soundfile.

        Returns
        -------
        NDArray[np.float32]
            1-D float32 array of audio samples at 32 kHz.
        """
        import soundfile as sf

        audio: NDArray[np.float32]
        audio, sr = sf.read(file_path, dtype="float32")

        # Convert to mono by averaging channels
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        # Resample to Perch's required sample rate if needed
        if sr != SAMPLE_RATE:
            from math import gcd

            from scipy.signal import resample_poly

            g = gcd(SAMPLE_RATE, sr)
            audio = np.asarray(
                resample_poly(audio, SAMPLE_RATE // g, sr // g),
                dtype=np.float32,
            )

        return audio.astype(np.float32)

    @staticmethod
    def _chunk_into_segments(
        audio: NDArray[np.float32],
    ) -> NDArray[np.float32]:
        """Chunk a 1-D audio array into 5-second segments.

        If the audio is shorter than one segment it is zero-padded.  Any
        trailing samples that do not fill a complete segment are discarded.

        Parameters
        ----------
        audio : NDArray[np.float32]
            1-D float32 audio array at 32 kHz.

        Returns
        -------
        NDArray[np.float32]
            Shape ``(n_segments, SEGMENT_SAMPLES)`` float32 array.
        """
        n_segments = len(audio) // SEGMENT_SAMPLES

        if n_segments == 0:
            # Pad short audio to exactly one 5-second segment
            padded = np.zeros(SEGMENT_SAMPLES, dtype=np.float32)
            padded[: len(audio)] = audio
            return padded[np.newaxis, :]

        return np.stack(
            [
                audio[i * SEGMENT_SAMPLES : (i + 1) * SEGMENT_SAMPLES]
                for i in range(n_segments)
            ],
            axis=0,
        ).astype(np.float32)

    def encode_audio_file(self, file_path: str) -> NDArray[np.float32]:
        """Load an audio file and return per-segment Perch embeddings.

        The file is loaded, converted to mono, resampled to 32 kHz, chunked
        into 5-second segments, and fed through the model in a single batch
        call.

        Parameters
        ----------
        file_path : str
            Path to an audio file (any format that soundfile supports).

        Returns
        -------
        NDArray[np.float32]
            Shape ``(n_segments, EMBEDDING_DIM)`` float32 array.

        Raises
        ------
        RuntimeError
            If the model has not been loaded yet.
        """
        import tensorflow as tf

        if self._encode_fn is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        audio = self._load_and_resample(file_path)
        segments = self._chunk_into_segments(audio)

        result = self._encode_fn(inputs=tf.constant(segments))
        embeddings: NDArray[np.float32] = result["embedding"].numpy()

        logger.debug(
            "PerchDirectInference: encoded '%s' -> %d segment(s), shape=%s",
            file_path,
            embeddings.shape[0],
            embeddings.shape,
        )

        return embeddings.astype(np.float32)

    def encode_audio_files(
        self, file_paths: list[str]
    ) -> list[NDArray[np.float32]]:
        """Encode multiple audio files, returning per-file embeddings.

        Each file is processed independently (different files may have
        different durations and therefore different numbers of segments).

        Parameters
        ----------
        file_paths : list[str]
            List of paths to audio files.

        Returns
        -------
        list[NDArray[np.float32]]
            One ``(n_segments, EMBEDDING_DIM)`` array per file.
        """
        return [self.encode_audio_file(fp) for fp in file_paths]

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        """Return True if the model has been loaded."""
        return self._encode_fn is not None

    @property
    def is_warmed_up(self) -> bool:
        """Return True if warmup has completed."""
        return self._warmed_up

    @property
    def device(self) -> str:
        """Effective device string (``"CPU"`` or ``"GPU"``)."""
        return self._device

    # Constants exposed for callers that need them without importing constants.
    SAMPLE_RATE: int = SAMPLE_RATE
    SEGMENT_SAMPLES: int = SEGMENT_SAMPLES
    EMBEDDING_DIM: int = EMBEDDING_DIM
