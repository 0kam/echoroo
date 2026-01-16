"""Audio processing service for metadata extraction and spectrogram generation."""

import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import mutagen


@dataclass
class AudioMetadata:
    """Audio file metadata."""

    filename: str
    path: str
    hash: str
    duration: float
    samplerate: int
    channels: int
    bit_depth: int | None
    format: str


class AudioService:
    """Service for audio file processing and analysis."""

    SUPPORTED_FORMATS = {".wav", ".flac", ".mp3", ".ogg"}
    SPECTROGRAM_COLORMAPS = [
        "gray", "viridis", "magma", "inferno", "plasma",
        "cividis", "cool", "cubehelix", "twilight"
    ]

    def __init__(self, audio_root: str, cache_dir: str | None = None) -> None:
        """Initialize AudioService.

        Args:
            audio_root: Root directory for audio files
            cache_dir: Directory for caching spectrograms (optional)
        """
        self.audio_root = Path(audio_root)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_absolute_path(self, relative_path: str) -> Path:
        """Get absolute path from relative path.

        Args:
            relative_path: Path relative to audio_root

        Returns:
            Absolute path to the file
        """
        return self.audio_root / relative_path

    def is_supported_format(self, filename: str) -> bool:
        """Check if file format is supported.

        Args:
            filename: Filename to check

        Returns:
            True if format is supported
        """
        return Path(filename).suffix.lower() in self.SUPPORTED_FORMATS

    def compute_file_hash(self, file_path: Path, chunk_size: int = 8192) -> str:
        """Compute MD5 hash of a file.

        Args:
            file_path: Path to the file
            chunk_size: Size of chunks to read

        Returns:
            MD5 hash as hex string
        """
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def extract_metadata(self, relative_path: str) -> AudioMetadata:
        """Extract metadata from an audio file.

        Args:
            relative_path: Path relative to audio_root

        Returns:
            AudioMetadata object with file information

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is not supported
        """
        file_path = self.get_absolute_path(relative_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        if not self.is_supported_format(file_path.name):
            raise ValueError(f"Unsupported audio format: {file_path.suffix}")

        # Get audio info using soundfile
        info = sf.info(str(file_path))

        # Try to get bit depth from mutagen
        bit_depth = None
        try:
            mutagen_file = mutagen.File(str(file_path))  # type: ignore[attr-defined]
            if mutagen_file is not None and hasattr(mutagen_file.info, "bits_per_sample"):
                bit_depth = mutagen_file.info.bits_per_sample
        except Exception:
            pass

        # Compute file hash
        file_hash = self.compute_file_hash(file_path)

        return AudioMetadata(
            filename=file_path.name,
            path=relative_path,
            hash=file_hash,
            duration=info.duration,
            samplerate=info.samplerate,
            channels=info.channels,
            bit_depth=bit_depth,
            format=file_path.suffix.lower().lstrip("."),
        )

    def apply_filter(
        self,
        data: np.ndarray,
        samplerate: int,
        highpass: int | None = None,
        lowpass: int | None = None,
    ) -> np.ndarray:
        """Apply frequency filters to audio data.

        Args:
            data: Audio data
            samplerate: Sample rate
            highpass: Highpass filter cutoff in Hz
            lowpass: Lowpass filter cutoff in Hz

        Returns:
            Filtered audio data
        """
        from scipy.signal import butter, sosfilt

        if highpass and lowpass:
            # Band-pass filter
            if highpass >= lowpass:
                return data  # Invalid range, return unchanged
            sos = butter(4, [highpass, lowpass], btype="band", fs=samplerate, output="sos")
        elif highpass:
            # High-pass filter
            if highpass >= samplerate / 2:
                return data  # Invalid cutoff, return unchanged
            sos = butter(4, highpass, btype="high", fs=samplerate, output="sos")
        elif lowpass:
            # Low-pass filter
            if lowpass >= samplerate / 2:
                return data  # Invalid cutoff, return unchanged
            sos = butter(4, lowpass, btype="low", fs=samplerate, output="sos")
        else:
            return data

        result: np.ndarray = sosfilt(sos, data, axis=0)
        return result

    def read_audio(
        self,
        relative_path: str,
        start: float = 0,
        end: float | None = None,
        channel: int | None = None,
    ) -> tuple[np.ndarray, int]:
        """Read audio data from a file.

        Args:
            relative_path: Path relative to audio_root
            start: Start time in seconds
            end: End time in seconds (None for end of file)
            channel: Channel to extract (None for all channels)

        Returns:
            Tuple of (audio data as numpy array, sample rate)
        """
        file_path = self.get_absolute_path(relative_path)

        info = sf.info(str(file_path))
        start_frame = int(start * info.samplerate)
        end_frame = int(end * info.samplerate) if end else None

        frames = end_frame - start_frame if end_frame else -1

        data, samplerate = sf.read(
            str(file_path),
            start=start_frame,
            frames=frames if frames > 0 else -1,
            dtype="float32",
        )

        # Handle channel selection
        if channel is not None and len(data.shape) > 1:
            if channel < data.shape[1]:
                data = data[:, channel]
            else:
                data = data[:, 0]

        return data, samplerate

    def resample_for_playback(
        self,
        relative_path: str,
        target_samplerate: int = 48000,
        speed: float = 1.0,
        start: float | None = None,
        end: float | None = None,
    ) -> tuple[np.ndarray, int]:
        """Resample audio for browser playback.

        Args:
            relative_path: Path relative to audio_root
            target_samplerate: Target sample rate (default 48kHz for browsers)
            speed: Playback speed multiplier
            start: Start time in seconds
            end: End time in seconds

        Returns:
            Tuple of (resampled audio data, target sample rate)
        """
        data, original_sr = self.read_audio(relative_path, start or 0, end)

        # Apply speed adjustment
        if speed != 1.0:
            # Adjust effective sample rate for speed change
            effective_sr = int(original_sr / speed)
        else:
            effective_sr = original_sr

        # Resample if needed
        if effective_sr != target_samplerate:
            # Simple resampling using numpy interpolation
            original_length = len(data)
            target_length = int(original_length * target_samplerate / effective_sr)

            if len(data.shape) == 1:
                # Mono
                indices = np.linspace(0, original_length - 1, target_length)
                data = np.interp(indices, np.arange(original_length), data)
            else:
                # Stereo/multi-channel
                resampled = np.zeros((target_length, data.shape[1]), dtype=np.float32)
                indices = np.linspace(0, original_length - 1, target_length)
                for ch in range(data.shape[1]):
                    resampled[:, ch] = np.interp(indices, np.arange(original_length), data[:, ch])
                data = resampled

        return data.astype(np.float32), target_samplerate

    def generate_spectrogram(
        self,
        relative_path: str,
        start: float = 0,
        end: float | None = None,
        n_fft: int = 2048,
        hop_length: int = 512,
        freq_min: int = 0,
        freq_max: int | None = None,
        colormap: str = "viridis",
        pcen: bool = False,
        channel: int = 0,
        width: int = 1200,
        height: int = 400,
    ) -> bytes:
        """Generate spectrogram image as PNG bytes.

        Args:
            relative_path: Path relative to audio_root
            start: Start time in seconds
            end: End time in seconds
            n_fft: FFT window size
            hop_length: Hop length between windows
            freq_min: Minimum frequency in Hz
            freq_max: Maximum frequency in Hz
            colormap: Matplotlib colormap name
            pcen: Apply PCEN normalization
            channel: Audio channel to use
            width: Output image width
            height: Output image height

        Returns:
            PNG image as bytes
        """
        # Read audio
        data, samplerate = self.read_audio(relative_path, start, end, channel)

        # Compute spectrogram using numpy
        # Simple STFT implementation
        num_frames = (len(data) - n_fft) // hop_length + 1
        if num_frames <= 0:
            num_frames = 1

        # Hann window
        window = np.hanning(n_fft)

        # Compute STFT
        spectrogram = np.zeros((n_fft // 2 + 1, num_frames), dtype=np.float32)
        for i in range(num_frames):
            start_idx = i * hop_length
            end_idx = start_idx + n_fft
            if end_idx <= len(data):
                frame = data[start_idx:end_idx] * window
                fft_result = np.fft.rfft(frame)
                spectrogram[:, i] = np.abs(fft_result)

        # Convert to dB scale
        spectrogram = np.maximum(spectrogram, 1e-10)
        spectrogram_db = 20 * np.log10(spectrogram)

        # Apply PCEN if requested
        if pcen:
            spectrogram_db = self._apply_pcen(spectrogram_db)

        # Normalize to 0-255 range
        spec_min = spectrogram_db.min()
        spec_max = spectrogram_db.max()
        if spec_max > spec_min:
            spectrogram_norm = (spectrogram_db - spec_min) / (spec_max - spec_min)
        else:
            spectrogram_norm = np.zeros_like(spectrogram_db)

        # Apply frequency limits
        nyquist = samplerate / 2
        freq_max_actual = freq_max if freq_max else nyquist
        freq_bins = np.linspace(0, nyquist, spectrogram_norm.shape[0])
        min_bin = np.searchsorted(freq_bins, freq_min)
        max_bin = np.searchsorted(freq_bins, freq_max_actual)
        spectrogram_norm = spectrogram_norm[min_bin:max_bin, :]

        # Flip for display (low freq at bottom)
        spectrogram_norm = np.flipud(spectrogram_norm)

        # Convert to image using matplotlib
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        ax.imshow(
            spectrogram_norm,
            aspect="auto",
            cmap=colormap if colormap in self.SPECTROGRAM_COLORMAPS else "viridis",
            interpolation="nearest",
        )
        ax.axis("off")
        plt.tight_layout(pad=0)

        # Save to bytes
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
        plt.close(fig)
        buf.seek(0)

        return buf.getvalue()

    def _apply_pcen(self, spectrogram_db: np.ndarray) -> np.ndarray:
        """Apply Per-Channel Energy Normalization (PCEN).

        Args:
            spectrogram_db: Spectrogram in dB scale

        Returns:
            PCEN-normalized spectrogram
        """
        # Simple PCEN implementation
        # s = 0.025, alpha = 0.98, delta = 2, r = 0.5
        s = 0.025
        alpha = 0.98
        delta = 2.0
        r = 0.5

        # Convert back from dB
        spec_linear = 10 ** (spectrogram_db / 20)

        # Smooth along time axis
        smoothed = np.zeros_like(spec_linear)
        smoothed[:, 0] = spec_linear[:, 0]
        for t in range(1, spec_linear.shape[1]):
            smoothed[:, t] = s * spec_linear[:, t] + (1 - s) * smoothed[:, t - 1]

        # PCEN formula
        pcen = (spec_linear / (smoothed ** alpha + delta) ** r) - delta ** (-r)

        # Convert back to dB-like scale
        pcen = np.maximum(pcen, 1e-10)
        result: np.ndarray = 20 * np.log10(pcen + 1)
        return result

    def audio_to_wav_bytes(self, data: np.ndarray, samplerate: int) -> bytes:
        """Convert audio data to WAV bytes.

        Args:
            data: Audio data as numpy array
            samplerate: Sample rate

        Returns:
            WAV file as bytes
        """
        buf = io.BytesIO()
        sf.write(buf, data, samplerate, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return buf.getvalue()

    def scan_directory(self, relative_dir: str) -> list[str]:
        """Scan directory for audio files.

        Args:
            relative_dir: Directory path relative to audio_root

        Returns:
            List of relative paths to audio files
        """
        dir_path = self.get_absolute_path(relative_dir)
        audio_files: list[str] = []

        if not dir_path.exists() or not dir_path.is_dir():
            return audio_files

        for root, _, files in os.walk(dir_path):
            for filename in files:
                if self.is_supported_format(filename):
                    abs_path = Path(root) / filename
                    rel_path = abs_path.relative_to(self.audio_root)
                    audio_files.append(str(rel_path))

        return sorted(audio_files)

    def list_directories(self, relative_path: str = "") -> list[dict[str, str | int | list[str]]]:
        """List subdirectories with audio file info.

        Args:
            relative_path: Path relative to audio_root

        Returns:
            List of directory info dicts
        """
        dir_path = self.audio_root / relative_path if relative_path else self.audio_root
        directories: list[dict[str, str | int | list[str]]] = []

        if not dir_path.exists() or not dir_path.is_dir():
            return directories

        for item in sorted(dir_path.iterdir()):
            if item.is_dir():
                # Count audio files and collect formats
                audio_count = 0
                formats: set[str] = set()
                for _, _, files in os.walk(item):
                    for f in files:
                        ext = Path(f).suffix.lower()
                        if ext in self.SUPPORTED_FORMATS:
                            audio_count += 1
                            formats.add(ext.lstrip("."))

                rel_path = item.relative_to(self.audio_root)
                directories.append({
                    "name": item.name,
                    "path": str(rel_path),
                    "audio_file_count": audio_count,
                    "formats": sorted(formats),
                })

        return directories
