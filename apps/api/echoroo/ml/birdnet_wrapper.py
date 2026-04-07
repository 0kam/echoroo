"""BirdNET model wrapper using the birdnet package."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

BIRDNET_VERSION = "2.4"
EMBEDDING_DIM = 1024
SAMPLE_RATE = 48000
SEGMENT_DURATION = 3.0


def _detect_device() -> str:
    """Detect whether a TensorFlow-accessible GPU is available.

    Uses TensorFlow's device enumeration rather than PyTorch/CUDA to reflect
    the actual runtime used by BirdNET (TensorFlow backend).

    Returns:
        "GPU" if TensorFlow can access at least one GPU, "CPU" otherwise.
    """
    try:
        import tensorflow as tf  # type: ignore[import-untyped]

        gpus = tf.config.list_physical_devices("GPU")
        if gpus:
            logger.info("TensorFlow GPU detected: %s", [g.name for g in gpus])
            return "GPU"
    except Exception as exc:
        logger.debug("TensorFlow GPU detection failed: %s", exc)
    return "CPU"


@dataclass
class BirdNETDetection:
    """Single detection result from BirdNET analysis.

    Attributes:
        scientific_name: Scientific name of the detected species.
        common_name: Common name of the detected species.
        confidence: Model confidence score (0.0-1.0).
        start_time: Detection start time in seconds within the recording.
        end_time: Detection end time in seconds within the recording.
    """

    scientific_name: str
    common_name: str
    confidence: float
    start_time: float
    end_time: float


class BirdNETWrapper:
    """Wrapper around the birdnet package for bird sound detection.

    Uses a singleton pattern to reuse the loaded model across multiple
    analyze_file calls within the same worker process, avoiding repeated
    model initialization overhead.

    Supports GPU (protobuf backend) and CPU (TFLite backend).
    """

    _instance: BirdNETWrapper | None = None
    _model: Any = None
    _geo_model: Any = None

    @classmethod
    def get_instance(cls, device: str | None = None) -> BirdNETWrapper:
        """Return the shared BirdNETWrapper instance, initializing on first call.

        Args:
            device: Device to use for inference ("GPU" or "CPU").
                    Defaults to auto-detection via CUDA availability check.

        Returns:
            Shared BirdNETWrapper instance with model loaded.
        """
        if cls._instance is None:
            resolved = device if device is not None else _detect_device()
            cls._instance = cls(device=resolved)
        return cls._instance

    def __init__(self, device: str | None = None) -> None:
        """Initialize the BirdNET wrapper.

        Args:
            device: Device to use for inference ("GPU", "CPU", or "GPU:N").
                    Defaults to auto-detection via CUDA availability check.
        """
        self._device = device if device is not None else _detect_device()
        self._species_list: list[str] | None = None

    def _configure_device(self) -> None:
        """Configure TensorFlow device before import."""
        if self._device == "CPU":
            os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
            logger.info("BirdNET configured to use CPU (GPU disabled)")
        elif self._device.startswith("GPU:"):
            gpu_index = self._device.split(":", 1)[1]
            os.environ["CUDA_VISIBLE_DEVICES"] = gpu_index
            logger.info(
                "BirdNET configured to use device: %s (CUDA_VISIBLE_DEVICES=%s)",
                self._device,
                gpu_index,
            )
        else:
            # Allow GPU usage (default behavior)
            if os.environ.get("CUDA_VISIBLE_DEVICES") == "-1":
                del os.environ["CUDA_VISIBLE_DEVICES"]
            logger.info("BirdNET configured to use device: %s", self._device)

    def load(self) -> None:
        """Load the BirdNET acoustic model."""
        if self._model is not None:
            return

        self._configure_device()
        import birdnet

        # Use TFLite ("tf") backend for CPU to avoid asyncio deadlocks.
        # Use protobuf ("pb") backend for GPU: TFLite does not support GPU
        # acceleration, while the protobuf backend runs on TensorFlow and can
        # use GPU devices detected via tf.config.list_physical_devices("GPU").
        backend = "tf" if self._device == "CPU" else "pb"
        logger.info(
            "Loading BirdNET %s with backend=%s, device=%s",
            BIRDNET_VERSION,
            backend,
            self._device,
        )
        self._model = birdnet.load("acoustic", BIRDNET_VERSION, backend)  # type: ignore[call-overload]
        self._species_list = list(self._model.species_list)
        logger.info("BirdNET loaded. %d species available.", len(self._species_list))

    def load_geo_model(self) -> None:
        """Load the BirdNET geo model (lazy, called on first use).

        The geo model uses the same version and backend as the acoustic model.
        It is used to predict species occurrence probability for a given
        location and week of year.
        """
        if self._geo_model is not None:
            return

        import birdnet

        # Geo model only supports the TFLite (tf) backend
        backend = "tf"
        logger.info(
            "Loading BirdNET geo model %s with backend=%s",
            BIRDNET_VERSION,
            backend,
        )
        self._geo_model = birdnet.load("geo", BIRDNET_VERSION, backend)  # type: ignore[call-overload]
        logger.info("BirdNET geo model loaded.")

    def get_species_for_location(
        self,
        lat: float,
        lon: float,
        week: int,
        min_species_conf: float = 0.03,
    ) -> list[str]:
        """Get species list filtered by location and season using geo model.

        Args:
            lat: Latitude of the recording location.
            lon: Longitude of the recording location.
            week: Week of year (1-48) corresponding to the recording date.
            min_species_conf: Minimum confidence threshold for including a
                species in the returned list (default 0.03).

        Returns:
            List of species strings in "Scientific Name_Common Name" format,
            filtered to those with confidence >= min_species_conf.
        """
        if self._geo_model is None:
            self.load_geo_model()

        logger.info(
            "Running BirdNET geo model for lat=%.4f, lon=%.4f, week=%d",
            lat,
            lon,
            week,
        )
        result = self._geo_model.predict(
            lat,
            lon,
            week=week,
            min_confidence=min_species_conf,
        )
        # to_set() returns a set of "Scientific_Common" strings that passed
        # the min_confidence filter applied inside predict()
        species_set: set[str] = result.to_set()
        species_list = list(species_set)
        logger.info(
            "BirdNET geo model returned %d species for location (lat=%.4f, lon=%.4f, week=%d)",
            len(species_list),
            lat,
            lon,
            week,
        )
        return species_list

    def _build_infer_kwargs(self) -> dict[str, Any]:
        """Build kwargs for birdnet encode/predict calls.

        For the TFLite backend (CPU mode), pass device="CPU" as required by
        the birdnet package (asserts uppercase). For the protobuf backend (GPU mode), pass "GPU".

        n_workers=1 uses a single worker thread, which is compatible with Celery
        workers while avoiding the overhead of spawning multiple child processes.
        n_producers=1 keeps audio loading single-threaded for the same reason.
        Multiprocessing params (n_workers, n_producers) are only passed for
        the protobuf (GPU) backend; TFLite ignores them and they can cause issues.
        """
        is_cpu = self._device == "CPU"
        # birdnet package expects uppercase device strings ("CPU"/"GPU") for predict/encode
        birdnet_device = "CPU" if is_cpu else "GPU"
        kwargs: dict[str, Any] = {"device": birdnet_device}
        if not is_cpu:
            # Only pass multiprocessing params for GPU/protobuf backend
            kwargs["n_workers"] = 1
            kwargs["n_producers"] = 1
        return kwargs

    def _extract_embeddings(self, embeddings_result: Any) -> NDArray[np.float32]:
        """Normalize embeddings result into a (n_segments, EMBEDDING_DIM) float32 array."""
        raw: Any = (
            embeddings_result.embeddings
            if hasattr(embeddings_result, "embeddings")
            else embeddings_result
        )
        if hasattr(raw, "numpy"):
            raw = raw.numpy()
        arr = cast("NDArray[np.float32]", np.asarray(raw, dtype=np.float32))
        # Normalize to (n_segments, EMBEDDING_DIM)
        if arr.ndim == 3:
            return cast("NDArray[np.float32]", arr[0])
        if arr.ndim == 2:
            return arr
        return cast("NDArray[np.float32]", arr.reshape(1, -1))

    def _collect_predictions_by_segment(
        self, predictions_result: Any
    ) -> list[list[tuple[str, float]]]:
        """Extract per-segment predictions from birdnet output object."""
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
        results: list[list[tuple[str, float]]] = []
        for seg_probs, seg_ids in zip(probs, ids, strict=False):
            seg_preds: list[tuple[str, float]] = []
            for idx in range(len(seg_probs)):
                conf = float(seg_probs[idx])
                actual_idx = int(seg_ids[idx])
                seg_preds.append((species_list[actual_idx], conf))
            results.append(seg_preds)
        return results

    def analyze_file(
        self,
        file_path: str | Path,
        min_conf: float = 0.25,
        top_k: int = 10,
        custom_species_list: list[str] | None = None,
    ) -> list[BirdNETDetection]:
        """Analyze an audio file and return detections above threshold.

        Model loading errors (e.g. TensorFlow crash, missing weights) propagate
        to the caller so the task can be marked FAILED rather than silently
        returning 0 detections.  Only file-level I/O problems return [] to
        allow the per-recording error handler in the worker to skip bad files
        without aborting the entire run.

        Args:
            file_path: Path to the audio file to analyze.
            min_conf: Minimum confidence threshold (default 0.25).
            top_k: Maximum number of top predictions per segment (default 10).
            custom_species_list: Optional list of species strings in
                "Scientific Name_Common Name" format to restrict detection to.
                When provided (e.g. from get_species_for_location()), only
                species in this list are considered. When None, all species
                in the acoustic model are considered.

        Returns:
            List of BirdNETDetection results.

        Raises:
            Any exception raised by load() (model-level failure).
        """
        # Model loading is intentionally outside the file-level try/except so
        # that initialization failures propagate up and fail the whole task.
        if self._model is None:
            self.load()

        file_path = Path(file_path)
        if not file_path.exists():
            logger.error("File not found: %s", file_path)
            return []

        infer_kwargs = self._build_infer_kwargs()

        predict_kwargs: dict[str, Any] = {
            "top_k": top_k,
            "default_confidence_threshold": min_conf,
            **infer_kwargs,
        }
        if custom_species_list is not None:
            predict_kwargs["custom_species_list"] = custom_species_list

        predictions_result = self._model.predict(
            str(file_path),
            **predict_kwargs,
        )

        predictions_by_segment = self._collect_predictions_by_segment(
            predictions_result
        )

        detections: list[BirdNETDetection] = []
        for seg_idx, seg_preds in enumerate(predictions_by_segment):
            start_time = float(seg_idx) * SEGMENT_DURATION
            end_time = start_time + SEGMENT_DURATION
            for species_name, confidence in seg_preds:
                if confidence >= min_conf:
                    # Species name format: "Scientific Name_Common Name"
                    parts = species_name.split("_", 1)
                    scientific = parts[0] if parts else species_name
                    common = parts[1] if len(parts) > 1 else ""
                    detections.append(
                        BirdNETDetection(
                            scientific_name=scientific,
                            common_name=common,
                            confidence=float(confidence),
                            start_time=start_time,
                            end_time=end_time,
                        )
                    )

        logger.info(
            "BirdNET found %d detections in %s",
            len(detections),
            file_path.name,
        )
        return detections

    def get_embeddings(self, file_path: str | Path) -> NDArray[np.float32] | None:
        """Extract embeddings from an audio file.

        Args:
            file_path: Path to the audio file.

        Returns:
            Array of shape (n_segments, 1024), or None on error.
        """
        if self._model is None:
            self.load()

        file_path = Path(file_path)
        if not file_path.exists():
            return None

        try:
            infer_kwargs = self._build_infer_kwargs()
            embeddings_result = self._model.encode(str(file_path), **infer_kwargs)
            return self._extract_embeddings(embeddings_result)
        except Exception:
            logger.exception("BirdNET embedding extraction failed for %s", file_path)
            return None
