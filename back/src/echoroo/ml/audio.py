"""Audio preprocessing module for ML inference.

This module provides utilities for loading, resampling, segmenting,
and normalizing audio files for machine learning model inference.

Supported target sample rates:
- 48000 Hz: BirdNET models
- 32000 Hz: Perch models
"""

import logging
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# Type alias for audio array
AudioArray = NDArray[np.float32]


def load_audio(
    path: Path,
    target_sr: int = 48000,
    start_time: float | None = None,
    end_time: float | None = None,
) -> tuple[AudioArray, int]:
    """Load and resample audio file.

    Loads an audio file from disk, optionally extracting a specific
    time range, and resamples to the target sample rate if necessary.

    Parameters
    ----------
    path : Path
        Path to the audio file. Supports wav, flac, and other formats
        readable by soundfile.
    target_sr : int, optional
        Target sample rate in Hz. Default is 48000 (for BirdNET).
        Use 32000 for Perch models.
    start_time : float, optional
        Start time in seconds for partial loading. If None, starts from
        the beginning.
    end_time : float, optional
        End time in seconds for partial loading. If None, loads until
        the end.

    Returns
    -------
    tuple[AudioArray, int]
        Tuple of (audio_data, sample_rate) where audio_data is a 1D
        numpy array of float32 values and sample_rate is the actual
        sample rate of the returned audio.

    Raises
    ------
    FileNotFoundError
        If the audio file does not exist.
    RuntimeError
        If the audio file cannot be read.

    Examples
    --------
    >>> audio, sr = load_audio(Path("recording.wav"))
    >>> audio, sr = load_audio(Path("recording.flac"), target_sr=32000)
    >>> audio, sr = load_audio(Path("long.wav"), start_time=10.0, end_time=20.0)
    """
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    # Get file info first
    try:
        info = sf.info(path)
    except Exception as e:
        raise RuntimeError(f"Cannot read audio file: {path}") from e

    original_sr = info.samplerate

    # Calculate frame positions for partial loading
    start_frame = 0
    frames_to_read = -1  # -1 means read all

    if start_time is not None:
        start_frame = int(start_time * original_sr)
        start_frame = max(0, min(start_frame, info.frames))

    if end_time is not None:
        end_frame = int(end_time * original_sr)
        end_frame = max(start_frame, min(end_frame, info.frames))
        frames_to_read = end_frame - start_frame

    # Load audio
    try:
        audio, file_sr = sf.read(
            path,
            start=start_frame,
            frames=frames_to_read,
            dtype="float32",
            always_2d=False,
        )
    except Exception as e:
        raise RuntimeError(f"Error reading audio file: {path}") from e

    # Convert stereo to mono if necessary
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    # Ensure float32
    audio = audio.astype(np.float32)

    # Resample if necessary
    if file_sr != target_sr:
        audio = _resample(audio, file_sr, target_sr)

    return audio, target_sr


def _resample(
    audio: AudioArray,
    orig_sr: int,
    target_sr: int,
) -> AudioArray:
    """Resample audio using linear interpolation.

    This is a simple resampling method suitable for inference.
    For more sophisticated resampling, consider using scipy or
    librosa.

    Parameters
    ----------
    audio : AudioArray
        Input audio array.
    orig_sr : int
        Original sample rate.
    target_sr : int
        Target sample rate.

    Returns
    -------
    AudioArray
        Resampled audio array.
    """
    if orig_sr == target_sr:
        return audio

    # Calculate new length
    duration = len(audio) / orig_sr
    new_length = int(duration * target_sr)

    if new_length == 0:
        return np.array([], dtype=np.float32)

    # Use numpy interpolation for resampling
    old_indices = np.arange(len(audio))
    new_indices = np.linspace(0, len(audio) - 1, new_length)

    resampled = np.interp(new_indices, old_indices, audio)
    return resampled.astype(np.float32)


def segment_audio(
    audio: AudioArray,
    sr: int,
    segment_duration: float = 3.0,
    overlap: float = 0.0,
) -> list[AudioArray]:
    """Split audio into fixed-length segments.

    Divides an audio array into segments of a specified duration,
    with optional overlap between consecutive segments.

    Parameters
    ----------
    audio : AudioArray
        Input audio array (1D numpy array).
    sr : int
        Sample rate of the audio.
    segment_duration : float, optional
        Duration of each segment in seconds. Default is 3.0 seconds.
    overlap : float, optional
        Overlap between consecutive segments in seconds. Default is 0.0.
        Must be less than segment_duration.

    Returns
    -------
    list[AudioArray]
        List of audio segments. Each segment is a 1D numpy array of
        float32 values. The last segment may be zero-padded if the
        audio length is not evenly divisible.

    Raises
    ------
    ValueError
        If overlap is greater than or equal to segment_duration.

    Examples
    --------
    >>> segments = segment_audio(audio, sr=48000, segment_duration=3.0)
    >>> segments = segment_audio(audio, sr=48000, segment_duration=3.0, overlap=1.5)
    """
    if overlap >= segment_duration:
        raise ValueError(
            f"Overlap ({overlap}s) must be less than "
            f"segment_duration ({segment_duration}s)"
        )

    segment_samples = int(segment_duration * sr)
    hop_samples = int((segment_duration - overlap) * sr)

    if hop_samples <= 0:
        hop_samples = 1

    segments: list[AudioArray] = []
    start = 0

    while start < len(audio):
        end = start + segment_samples
        segment = audio[start:end]

        # Pad with zeros if segment is shorter than expected
        if len(segment) < segment_samples:
            padding = np.zeros(segment_samples - len(segment), dtype=np.float32)
            segment = np.concatenate([segment, padding])

        segments.append(segment)
        start += hop_samples

    return segments


def normalize_audio(audio: AudioArray) -> AudioArray:
    """Normalize audio to [-1, 1] range.

    Normalizes the audio by dividing by the maximum absolute value.
    If the audio is silent (all zeros), returns the original array.

    Parameters
    ----------
    audio : AudioArray
        Input audio array.

    Returns
    -------
    AudioArray
        Normalized audio array with values in [-1, 1] range.

    Examples
    --------
    >>> normalized = normalize_audio(audio)
    """
    max_val = np.max(np.abs(audio))

    if max_val > 0:
        return (audio / max_val).astype(np.float32)

    return audio.astype(np.float32)


class AudioPreprocessor:
    """Preprocess audio for ML inference.

    This class provides a convenient interface for loading, segmenting,
    and normalizing audio files for machine learning model inference.

    Parameters
    ----------
    target_sr : int, optional
        Target sample rate in Hz. Default is 48000 (for BirdNET).
        Use 32000 for Perch models.
    segment_duration : float, optional
        Duration of each segment in seconds. Default is 3.0 seconds.
    overlap : float, optional
        Overlap between consecutive segments in seconds. Default is 0.0.
    normalize : bool, optional
        Whether to normalize audio segments. Default is True.

    Attributes
    ----------
    target_sr : int
        Target sample rate.
    segment_duration : float
        Duration of each segment.
    overlap : float
        Overlap between segments.
    normalize : bool
        Whether normalization is enabled.

    Examples
    --------
    >>> # For BirdNET
    >>> preprocessor = AudioPreprocessor(target_sr=48000, segment_duration=3.0)
    >>> segments = preprocessor.process_file(Path("recording.wav"))

    >>> # For Perch
    >>> preprocessor = AudioPreprocessor(target_sr=32000, segment_duration=5.0)
    >>> segments_with_times = preprocessor.process_recording(
    ...     Path("recording.wav"),
    ...     start_time=10.0,
    ...     end_time=60.0,
    ... )
    """

    def __init__(
        self,
        target_sr: int = 48000,
        segment_duration: float = 3.0,
        overlap: float = 0.0,
        normalize: bool = True,
    ) -> None:
        """Initialize the audio preprocessor."""
        if overlap >= segment_duration:
            raise ValueError(
                f"Overlap ({overlap}s) must be less than "
                f"segment_duration ({segment_duration}s)"
            )

        self.target_sr = target_sr
        self.segment_duration = segment_duration
        self.overlap = overlap
        self.normalize = normalize

    def process_file(self, path: Path) -> list[AudioArray]:
        """Load and segment audio file.

        Loads an audio file, resamples to the target sample rate,
        segments into fixed-length chunks, and optionally normalizes.

        Parameters
        ----------
        path : Path
            Path to the audio file.

        Returns
        -------
        list[AudioArray]
            List of processed audio segments.

        Raises
        ------
        FileNotFoundError
            If the audio file does not exist.
        RuntimeError
            If the audio file cannot be read.
        """
        audio, sr = load_audio(path, target_sr=self.target_sr)

        if self.normalize:
            audio = normalize_audio(audio)

        segments = segment_audio(
            audio,
            sr=sr,
            segment_duration=self.segment_duration,
            overlap=self.overlap,
        )

        return segments

    def process_recording(
        self,
        path: Path,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> list[tuple[AudioArray, float, float]]:
        """Process recording, return segments with timestamps.

        Loads a specific time range from an audio file, segments it,
        and returns each segment along with its start and end timestamps
        relative to the original recording.

        Parameters
        ----------
        path : Path
            Path to the audio file.
        start_time : float, optional
            Start time in seconds. If None, starts from the beginning.
        end_time : float, optional
            End time in seconds. If None, loads until the end.

        Returns
        -------
        list[tuple[AudioArray, float, float]]
            List of tuples containing (segment, start_time, end_time)
            where start_time and end_time are in seconds relative to
            the original recording.

        Raises
        ------
        FileNotFoundError
            If the audio file does not exist.
        RuntimeError
            If the audio file cannot be read.

        Examples
        --------
        >>> preprocessor = AudioPreprocessor()
        >>> results = preprocessor.process_recording(
        ...     Path("recording.wav"),
        ...     start_time=10.0,
        ...     end_time=60.0,
        ... )
        >>> for segment, seg_start, seg_end in results:
        ...     print(f"Segment from {seg_start:.2f}s to {seg_end:.2f}s")
        """
        audio, sr = load_audio(
            path,
            target_sr=self.target_sr,
            start_time=start_time,
            end_time=end_time,
        )

        if self.normalize:
            audio = normalize_audio(audio)

        # Calculate base offset (start of the loaded region)
        base_offset = start_time if start_time is not None else 0.0

        segments = segment_audio(
            audio,
            sr=sr,
            segment_duration=self.segment_duration,
            overlap=self.overlap,
        )

        # Calculate hop duration for timestamp computation
        hop_duration = self.segment_duration - self.overlap

        results: list[tuple[AudioArray, float, float]] = []
        for i, segment in enumerate(segments):
            seg_start = base_offset + i * hop_duration
            seg_end = seg_start + self.segment_duration
            results.append((segment, seg_start, seg_end))

        return results

    def get_segment_count(self, duration: float) -> int:
        """Calculate number of segments for a given audio duration.

        Parameters
        ----------
        duration : float
            Total audio duration in seconds.

        Returns
        -------
        int
            Number of segments that will be produced.
        """
        if duration <= 0:
            return 0

        hop_duration = self.segment_duration - self.overlap
        if hop_duration <= 0:
            return 1

        # Number of complete hops plus one for the initial segment
        num_segments = int(np.ceil((duration - self.overlap) / hop_duration))
        return max(1, num_segments)


def validate_audio_segment(
    audio: AudioArray,
    expected_samples: int,
    sample_rate: int,
    model_name: str = "model",
) -> AudioArray:
    """Validate and prepare audio segment for ML inference.

    This function ensures the audio segment has the correct format and
    length for inference. It handles common issues like stereo input,
    wrong dimensions, and incorrect length.

    Parameters
    ----------
    audio : AudioArray
        Input audio data. Can be 1D (mono) or 2D (stereo or batched).
    expected_samples : int
        Expected number of samples in the segment.
    sample_rate : int
        Expected sample rate (used for error messages).
    model_name : str, optional
        Name of the model (used for error messages). Default is "model".

    Returns
    -------
    AudioArray
        Validated audio as 1D float32 array with expected_samples length.

    Raises
    ------
    ValueError
        If audio shape is invalid or length doesn't match expected_samples.

    Examples
    --------
    >>> # BirdNET expects 144000 samples (3s @ 48kHz)
    >>> audio = validate_audio_segment(raw_audio, 144000, 48000, "BirdNET")
    >>>
    >>> # Perch expects 160000 samples (5s @ 32000Hz)
    >>> audio = validate_audio_segment(raw_audio, 160000, 32000, "Perch")

    Notes
    -----
    This function is used by both BirdNET and Perch inference engines
    to ensure consistent audio validation across models.
    """
    # Ensure float32
    audio = audio.astype(np.float32)

    # Handle 2D input (stereo or batched)
    if audio.ndim == 2:
        if audio.shape[0] == 1:
            # Shape is (1, samples) - squeeze first dimension
            audio = audio.squeeze(0)
        elif audio.shape[1] == 1:
            # Shape is (samples, 1) - squeeze second dimension
            audio = audio.squeeze(1)
        else:
            # True stereo or multi-channel - take first channel
            if audio.shape[0] < audio.shape[1]:
                # Shape is (channels, samples)
                audio = audio[0]
                logger.debug(
                    "Converting multi-channel audio to mono (took first channel)"
                )
            else:
                # Shape is (samples, channels)
                audio = audio[:, 0]
                logger.debug(
                    "Converting multi-channel audio to mono (took first channel)"
                )

    # Validate final shape
    if audio.ndim != 1:
        raise ValueError(
            f"{model_name} audio segment must be 1D, got shape {audio.shape}"
        )

    # Validate length
    if len(audio) != expected_samples:
        duration = expected_samples / sample_rate
        raise ValueError(
            f"{model_name} audio segment must have {expected_samples} samples "
            f"({duration}s at {sample_rate}Hz), got {len(audio)} samples"
        )

    return audio


def pad_or_trim_segment(
    audio: AudioArray,
    target_samples: int,
    pad_value: float = 0.0,
) -> AudioArray:
    """Pad or trim audio segment to target length.

    If the audio is shorter than target_samples, it is padded with
    pad_value at the end. If longer, it is trimmed.

    Parameters
    ----------
    audio : AudioArray
        Input audio array (1D).
    target_samples : int
        Target number of samples.
    pad_value : float, optional
        Value to use for padding. Default is 0.0.

    Returns
    -------
    AudioArray
        Audio array with exactly target_samples length.

    Examples
    --------
    >>> # Pad short segment
    >>> audio = np.zeros(100000, dtype=np.float32)
    >>> padded = pad_or_trim_segment(audio, 144000)
    >>> assert len(padded) == 144000
    >>>
    >>> # Trim long segment
    >>> audio = np.zeros(200000, dtype=np.float32)
    >>> trimmed = pad_or_trim_segment(audio, 144000)
    >>> assert len(trimmed) == 144000
    """
    current_length = len(audio)

    if current_length == target_samples:
        return audio
    elif current_length < target_samples:
        # Pad with zeros (or pad_value)
        padding = np.full(
            target_samples - current_length,
            pad_value,
            dtype=np.float32,
        )
        return np.concatenate([audio, padding])
    else:
        # Trim to target length
        return audio[:target_samples]
