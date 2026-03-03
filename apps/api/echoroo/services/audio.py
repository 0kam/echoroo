"""Audio processing service for metadata extraction and spectrogram generation.

Spectrogram computation uses PyTorch and torchaudio for scientific-quality
acoustic analysis, including:
- torchaudio.functional.spectrogram for FFT (sinc-accurate STFT)
- 13 window functions via torch native and scipy.signal fallback
- PSD normalization: divide by (samplerate * window_energy)
- One-sided spectrum correction (double non-DC/Nyquist bins)
- PCEN: IIR smoothing in linear domain (soundevent-compatible parameters)
- dB conversion: 10*log10 with configurable floor/ceiling (power spectrum)
- PIL-based image rendering (no matplotlib figure overhead)

Audio resampling uses:
- torchaudio.functional.resample (windowed sinc / Kaiser filter)

Audio filtering uses:
- torchaudio.functional.highpass_biquad / lowpass_biquad (Q=0.707)
"""

from __future__ import annotations

import hashlib
import io
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path

import mutagen
import numpy as np
import soundfile as sf
import torch
from torchaudio import functional as taF

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Window builder (supports 13 named windows)
# ---------------------------------------------------------------------------


def _build_window(
    window_type: str,
    length: int,
    device: torch.device,
) -> torch.Tensor:
    """Create a window tensor for use with torchaudio spectrogram.

    Supports hann, hamming, bartlett, blackman natively via torch.
    All other named windows (boxcar, triang, flattop, parzen, bohman,
    blackmanharris, nuttall, barthann, kaiser) are delegated to
    scipy.signal.get_window.

    Args:
        window_type: Name of the window function (case-insensitive).
        length: Number of samples in the window.
        device: Torch device to place the tensor on.

    Returns:
        1-D float32 tensor of the specified window.
    """
    if length <= 0:
        return torch.ones(1, device=device)

    wtype = window_type.lower()

    if wtype == "hann":
        return torch.hann_window(length, periodic=True, device=device)
    if wtype == "hamming":
        return torch.hamming_window(length, periodic=True, device=device)
    if wtype == "bartlett":
        return torch.bartlett_window(length, periodic=True, device=device)
    if wtype == "blackman":
        return torch.blackman_window(length, periodic=True, device=device)
    if wtype == "boxcar":
        return torch.ones(length, dtype=torch.float32, device=device)

    # scipy.signal fallback for remaining window types
    try:
        from scipy.signal import get_window

        win_np: np.ndarray = get_window(wtype, length, fftbins=True)
        win_tensor: torch.Tensor = torch.from_numpy(win_np.astype(np.float32)).to(device)
        return win_tensor
    except Exception:
        # Final fallback: hann
        return torch.hann_window(length, periodic=True, device=device)


# ---------------------------------------------------------------------------
# PCEN (Per-Channel Energy Normalization)
# ---------------------------------------------------------------------------


def _apply_pcen(spec: torch.Tensor) -> torch.Tensor:
    """Apply PCEN normalization in the linear power domain.

    Implements the IIR smoothing variant used by soundevent / librosa:
        M[t] = s * X[t] + (1 - s) * M[t-1]
        PCEN = (bias^power) * expm1(power * log1p(X * smooth_factor / bias))

    Parameters are fixed to the reference values:
        smooth=0.025, gain=0.98, bias=2.0, power=0.5, eps=1e-6

    Args:
        spec: Power spectrogram tensor with time on the last axis.

    Returns:
        PCEN-normalized tensor with the same shape.
    """
    if spec.numel() == 0:
        return spec

    smooth: float = 0.025
    gain: float = 0.98
    bias: float = 2.0
    power: float = 0.5
    eps: float = 1e-6

    device = spec.device
    dtype = spec.dtype

    smoothing = torch.zeros_like(spec)
    smoothing[..., 0] = spec[..., 0]

    s_t = torch.tensor(smooth, device=device, dtype=dtype)
    one_minus_s = 1.0 - s_t

    for idx in range(1, spec.shape[-1]):
        smoothing[..., idx] = (
            s_t * spec[..., idx] + one_minus_s * smoothing[..., idx - 1]
        )

    eps_t = torch.tensor(eps, device=device, dtype=dtype)
    smooth_factor = torch.exp(
        -gain * (torch.log(eps_t) + torch.log1p(smoothing / eps_t))
    )
    bias_power = torch.tensor(bias**power, device=device, dtype=dtype)
    pcen: torch.Tensor = bias_power * torch.expm1(
        power * torch.log1p(spec * smooth_factor / bias)
    )
    return pcen


# ---------------------------------------------------------------------------
# dB conversion
# ---------------------------------------------------------------------------


def _to_db(
    spec: torch.Tensor,
    min_db: float = -100.0,
    max_db: float = 0.0,
) -> torch.Tensor:
    """Convert a power spectrogram to decibels with clamping.

    Uses 10*log10 (power convention) which is equivalent to 20*log10 of amplitude.

    Args:
        spec: Power spectrogram tensor (values >= 0).
        min_db: Floor value in dB (default -100 dB).
        max_db: Ceiling value in dB (default 0 dB).

    Returns:
        Spectrogram in dB scale clamped to [min_db, max_db].
    """
    log_spec = 10.0 * torch.log10(spec.clamp(min=1e-10))
    return log_spec.clamp(min=min_db, max=max_db)


# ---------------------------------------------------------------------------
# Colormap lookup table (PIL-based rendering)
# ---------------------------------------------------------------------------


def _get_colormap_lut(name: str) -> np.ndarray:
    """Return a 256x3 uint8 RGB lookup table for the given colormap name.

    For gray we build the LUT directly. For other colormaps we sample
    matplotlib's registry (only 256 evaluations, no figure rendering).

    Args:
        name: Colormap name string.

    Returns:
        Array of shape (256, 3) with uint8 RGB values.
    """
    if name == "gray":
        ramp = np.arange(256, dtype=np.uint8)
        return np.stack([ramp, ramp, ramp], axis=-1)

    try:
        import matplotlib.cm as cm

        cmap = cm.get_cmap(name, 256)
        lut_f: np.ndarray = np.array(cmap(np.linspace(0.0, 1.0, 256)))[:, :3]
        lut: np.ndarray = (lut_f * 255).clip(0, 255).astype(np.uint8)
        return lut
    except Exception:
        ramp = np.arange(256, dtype=np.uint8)
        return np.stack([ramp, ramp, ramp], axis=-1)


def _apply_colormap(data_uint8: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Map a 2-D uint8 array through a 256x3 LUT to produce an RGB image.

    Args:
        data_uint8: 2-D uint8 array used as indices into the LUT.
        lut: (256, 3) uint8 RGB lookup table.

    Returns:
        (H, W, 3) uint8 RGB array.
    """
    rgb: np.ndarray = lut[data_uint8]
    return rgb


# ---------------------------------------------------------------------------
# Core spectrogram computation
# ---------------------------------------------------------------------------


def _compute_spectrogram_tensor(
    waveform: torch.Tensor,
    samplerate: int,
    window_size: float,
    overlap: float,
    window_type: str,
) -> tuple[torch.Tensor, int, int, int]:
    """Compute a PSD-normalized power spectrogram using torchaudio.

    PSD normalization:  spec = |STFT|^2 / (fs * sum(window^2))
    One-sided correction: double all bins except DC and Nyquist.

    Args:
        waveform: Audio tensor of shape (1, samples) - single channel.
        samplerate: Sample rate in Hz.
        window_size: FFT window duration in seconds.
        overlap: Window overlap as fraction of window_size (0 < overlap < 1).
        window_type: Window function name.

    Returns:
        Tuple of (spec, win_length, hop_length, n_fft) where spec has shape
        (freq_bins, time_frames).
    """
    hop_size = max((1.0 - overlap) * window_size, 1.0 / samplerate)
    win_length = max(1, int(round(window_size * samplerate)))
    hop_length = max(1, int(round(hop_size * samplerate)))
    n_fft = max(2, win_length)

    device = waveform.device
    window_tensor = _build_window(window_type, win_length, device)

    spec = taF.spectrogram(
        waveform,
        pad=0,
        window=window_tensor,
        n_fft=n_fft,
        hop_length=hop_length,
        win_length=win_length,
        power=2.0,
        normalized=False,
        center=True,
        pad_mode="constant",
        onesided=True,
    )
    # spec: (1, freq_bins, time_frames) -> squeeze channel dim
    spec = spec.squeeze(0)  # (freq_bins, time_frames)

    # PSD normalization
    window_energy = window_tensor.pow(2).sum()
    if samplerate > 0 and window_energy > 0:
        spec = spec / (samplerate * window_energy)

    # One-sided correction: double all bins except DC (index 0) and Nyquist
    if n_fft % 2 == 0 and spec.shape[0] > 2:
        spec[1:-1] *= 2.0
    elif spec.shape[0] > 1:
        spec[1:] *= 2.0

    return spec, win_length, hop_length, n_fft


# ---------------------------------------------------------------------------
# WAV header generation and streaming constants
# ---------------------------------------------------------------------------

CHUNK_SIZE = 512 * 1024
HEADER_FORMAT = "<4si4s4sihhiihh4si"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def generate_wav_header(
    samplerate: int,
    channels: int,
    data_size: int,
    bit_depth: int = 16,
) -> bytes:
    """Generate a standard WAV PCM header.

    See http://soundfile.sapp.org/doc/WaveFormat/ for the format specification.

    Args:
        samplerate: Sample rate in Hz.
        channels: Number of audio channels.
        data_size: Size of the PCM data chunk in bytes.
        bit_depth: Bits per sample (default 16).

    Returns:
        44-byte WAV header as bytes.
    """
    byte_rate = samplerate * channels * bit_depth // 8
    block_align = channels * bit_depth // 8

    return struct.pack(
        HEADER_FORMAT,
        b"RIFF",
        data_size + 36,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        samplerate,
        byte_rate,
        block_align,
        bit_depth,
        b"data",
        data_size,
    )


# ---------------------------------------------------------------------------
# Main AudioService class
# ---------------------------------------------------------------------------


class AudioService:
    """Service for audio file processing and spectrogram generation.

    Spectrogram computation is backed by PyTorch + torchaudio for
    scientific-quality output (PSD normalization, PCEN, 13 window types).
    Audio resampling uses torchaudio sinc interpolation. Filtering uses
    torchaudio biquad (Q=0.707).
    """

    SUPPORTED_FORMATS = {".wav", ".flac", ".mp3", ".ogg"}
    SPECTROGRAM_COLORMAPS = [
        "gray",
        "viridis",
        "magma",
        "inferno",
        "plasma",
        "cividis",
        "cool",
        "cubehelix",
        "twilight",
    ]

    def __init__(self, audio_root: str, cache_dir: str | None = None) -> None:
        """Initialize AudioService.

        Args:
            audio_root: Root directory for audio files.
            cache_dir: Optional directory for caching spectrograms.
        """
        self.audio_root = Path(audio_root)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def get_absolute_path(self, relative_path: str) -> Path:
        """Get absolute path from relative path.

        Args:
            relative_path: Path relative to audio_root.

        Returns:
            Absolute path to the file.
        """
        return self.audio_root / relative_path

    def is_supported_format(self, filename: str) -> bool:
        """Check if file format is supported.

        Args:
            filename: Filename to check.

        Returns:
            True if the format is in SUPPORTED_FORMATS.
        """
        return Path(filename).suffix.lower() in self.SUPPORTED_FORMATS

    # ------------------------------------------------------------------
    # Metadata / hash
    # ------------------------------------------------------------------

    def compute_file_hash(self, file_path: Path, chunk_size: int = 8192) -> str:
        """Compute MD5 hash of a file.

        Args:
            file_path: Path to the file.
            chunk_size: Read chunk size in bytes.

        Returns:
            MD5 hex digest string.
        """
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def extract_metadata(self, relative_path: str) -> AudioMetadata:
        """Extract metadata from an audio file.

        Args:
            relative_path: Path relative to audio_root.

        Returns:
            AudioMetadata with file information.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file format is not supported.
        """
        file_path = self.get_absolute_path(relative_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")
        if not self.is_supported_format(file_path.name):
            raise ValueError(f"Unsupported audio format: {file_path.suffix}")

        info = sf.info(str(file_path))

        bit_depth: int | None = None
        try:
            mutagen_file = mutagen.File(str(file_path))  # type: ignore[attr-defined]
            if mutagen_file is not None and hasattr(mutagen_file.info, "bits_per_sample"):
                bit_depth = mutagen_file.info.bits_per_sample
        except Exception:
            pass

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

    # ------------------------------------------------------------------
    # Audio I/O
    # ------------------------------------------------------------------

    def read_audio(
        self,
        relative_path: str,
        start: float = 0,
        end: float | None = None,
        channel: int | None = None,
    ) -> tuple[np.ndarray, int]:
        """Read audio data from a file.

        Args:
            relative_path: Path relative to audio_root.
            start: Start time in seconds.
            end: End time in seconds (None = end of file).
            channel: Channel index to extract (None = all channels).

        Returns:
            Tuple of (audio data as float32 numpy array, sample rate).
        """
        file_path = self.get_absolute_path(relative_path)
        info = sf.info(str(file_path))
        start_frame = int(start * info.samplerate)
        end_frame = int(end * info.samplerate) if end is not None else None
        frames = (end_frame - start_frame) if end_frame is not None else -1

        data, samplerate = sf.read(
            str(file_path),
            start=start_frame,
            frames=frames if frames > 0 else -1,
            dtype="float32",
        )

        if channel is not None and len(data.shape) > 1:
            data = data[:, channel] if channel < data.shape[1] else data[:, 0]

        return data, samplerate

    def _load_waveform_tensor(
        self,
        relative_path: str,
        start: float = 0,
        end: float | None = None,
        channel: int | None = None,
    ) -> tuple[torch.Tensor, int]:
        """Load audio as a torch tensor of shape (1, samples).

        Args:
            relative_path: Path relative to audio_root.
            start: Start time in seconds.
            end: End time in seconds (None = end of file).
            channel: Channel index to select (None = channel 0).

        Returns:
            Tuple of (waveform tensor, samplerate).
        """
        data, samplerate = self.read_audio(relative_path, start, end)

        if data.ndim == 1:
            data = data[:, np.newaxis]  # (samples, 1)

        ch = channel if channel is not None else 0
        ch = min(ch, data.shape[1] - 1)
        selected: np.ndarray = data[:, ch]  # (samples,)

        waveform = torch.from_numpy(selected.copy()).unsqueeze(0)  # (1, samples)
        return waveform, samplerate

    # ------------------------------------------------------------------
    # Filtering (legacy scipy interface - retained for backward compat)
    # ------------------------------------------------------------------

    def apply_filter(
        self,
        data: np.ndarray,
        samplerate: int,
        highpass: int | None = None,
        lowpass: int | None = None,
    ) -> np.ndarray:
        """Apply frequency filters using scipy (legacy interface).

        New internal code should use torchaudio biquad helpers instead.

        Args:
            data: Audio data array.
            samplerate: Sample rate in Hz.
            highpass: Highpass cutoff in Hz (None = skip).
            lowpass: Lowpass cutoff in Hz (None = skip).

        Returns:
            Filtered audio data.
        """
        from scipy.signal import butter, sosfilt

        if highpass and lowpass:
            if highpass >= lowpass:
                return data
            sos = butter(4, [highpass, lowpass], btype="band", fs=samplerate, output="sos")
        elif highpass:
            if highpass >= samplerate / 2:
                return data
            sos = butter(4, highpass, btype="high", fs=samplerate, output="sos")
        elif lowpass:
            if lowpass >= samplerate / 2:
                return data
            sos = butter(4, lowpass, btype="low", fs=samplerate, output="sos")
        else:
            return data

        result: np.ndarray = np.asarray(sosfilt(sos, data, axis=0))
        return result

    # ------------------------------------------------------------------
    # Playback resampling (torchaudio sinc interpolation)
    # ------------------------------------------------------------------

    def resample_for_playback(
        self,
        relative_path: str,
        target_samplerate: int = 48000,
        speed: float = 1.0,
        start: float | None = None,
        end: float | None = None,
    ) -> tuple[np.ndarray, int]:
        """Resample audio for browser playback using torchaudio sinc interpolation.

        Replaces the previous numpy.interp-based approach. torchaudio's
        resample uses a windowed sinc (Kaiser) filter that is significantly
        more accurate for arbitrary rational rate ratios.

        Args:
            relative_path: Path relative to audio_root.
            target_samplerate: Desired output sample rate (default 48 kHz).
            speed: Playback speed multiplier (applied as source rate scaling).
            start: Start time in seconds.
            end: End time in seconds.

        Returns:
            Tuple of (resampled float32 numpy array, target_samplerate).
        """
        data, original_sr = self.read_audio(relative_path, start or 0, end)

        effective_sr = int(round(original_sr / speed)) if speed != 1.0 else original_sr

        if data.ndim == 1:
            data = data[:, np.newaxis]  # (samples, 1)

        # (channels, samples) for torchaudio
        waveform = torch.from_numpy(data.T.copy())  # (channels, samples)

        if effective_sr != target_samplerate and waveform.shape[1] > 0:
            waveform = taF.resample(waveform, effective_sr, target_samplerate)

        # Back to (samples, channels) numpy
        result: np.ndarray = waveform.T.cpu().numpy().astype(np.float32)

        # Squeeze to 1-D for mono (backward compat with WAV writer)
        if result.shape[1] == 1:
            result = result[:, 0]

        return result, target_samplerate

    # ------------------------------------------------------------------
    # Spectrogram generation (PyTorch / torchaudio / PIL)
    # ------------------------------------------------------------------

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
        """Generate a spectrogram image as PNG bytes.

        Uses torchaudio.functional.spectrogram (STFT) with PSD normalization,
        optional PCEN normalization, dB conversion, and PIL rendering.

        The n_fft / hop_length parameters are accepted for API backward
        compatibility and are translated to window_size / overlap based on
        the recording's actual sample rate.

        Args:
            relative_path: Path relative to audio_root.
            start: Start time in seconds.
            end: End time in seconds (None = end of file).
            n_fft: FFT window size in samples (used to derive window_size_sec).
            hop_length: Hop size in samples (used to derive overlap fraction).
            freq_min: Minimum display frequency in Hz.
            freq_max: Maximum display frequency in Hz (None = Nyquist).
            colormap: Colormap name for rendering.
            pcen: Apply PCEN normalization before dB conversion.
            channel: Audio channel to visualize.
            width: Output image width in pixels.
            height: Output image height in pixels.

        Returns:
            PNG image as bytes.
        """
        from PIL import Image

        # Load waveform as torch tensor (1, samples)
        waveform, samplerate = self._load_waveform_tensor(
            relative_path, start, end, channel
        )

        # Translate sample-count parameters to time-based parameters
        window_size_sec = n_fft / samplerate
        overlap = 1.0 - (hop_length / n_fft)
        overlap = max(0.0, min(overlap, 0.999))

        # PSD-normalized power spectrogram via torchaudio STFT
        spec, _, _, _ = _compute_spectrogram_tensor(
            waveform,
            samplerate,
            window_size=window_size_sec,
            overlap=overlap,
            window_type="hann",
        )
        # spec: (freq_bins, time_frames) in linear power domain

        # Optional PCEN normalization (must happen before dB conversion)
        if pcen:
            spec = _apply_pcen(spec)

        # Convert to dB scale
        spec_db = _to_db(spec, min_db=-100.0, max_db=0.0)

        # Move to numpy for image operations
        spec_np: np.ndarray = spec_db.cpu().numpy()  # (freq_bins, time_frames)

        # Frequency-axis crop
        nyquist = samplerate / 2.0
        freq_bins = spec_np.shape[0]
        freq_values = np.linspace(0.0, nyquist, freq_bins)
        freq_max_actual = float(freq_max) if freq_max is not None else nyquist
        min_bin = max(0, int(np.searchsorted(freq_values, float(freq_min))))
        max_bin = min(freq_bins, int(np.searchsorted(freq_values, freq_max_actual)))
        if max_bin <= min_bin:
            max_bin = freq_bins

        spec_crop = spec_np[min_bin:max_bin, :]

        # Normalize to [0, 1] then uint8
        s_min = spec_crop.min()
        s_max = spec_crop.max()
        if s_max > s_min:
            spec_norm = (spec_crop - s_min) / (s_max - s_min)
        else:
            spec_norm = np.zeros_like(spec_crop)

        # Flip so low frequencies appear at the bottom of the image
        spec_norm = np.flipud(spec_norm)
        spec_uint8 = (spec_norm * 255).clip(0, 255).astype(np.uint8)

        # Apply colormap via 256x3 LUT - no matplotlib figure overhead
        lut = _get_colormap_lut(colormap)
        rgb = _apply_colormap(spec_uint8, lut)  # (H, W, 3) uint8

        # Render with PIL and resize to requested dimensions
        img = Image.fromarray(rgb, mode="RGB")
        if img.width != width or img.height != height:
            img = img.resize((width, height), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False, compress_level=1)
        buf.seek(0)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # WAV bytes helper
    # ------------------------------------------------------------------

    def audio_to_wav_bytes(self, data: np.ndarray, samplerate: int) -> bytes:
        """Convert audio data to WAV bytes.

        Args:
            data: Audio data (samples,) or (samples, channels).
            samplerate: Sample rate in Hz.

        Returns:
            WAV file as bytes.
        """
        buf = io.BytesIO()
        sf.write(buf, data, samplerate, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # HTTP Range streaming helper
    # ------------------------------------------------------------------

    def load_clip_bytes(
        self,
        relative_path: str,
        byte_start: int = 0,
        speed: float = 1.0,
        time_expansion: float = 1.0,
        start_time: float | None = None,
        end_time: float | None = None,
        target_samplerate: int | None = None,
        chunk_frames: int = CHUNK_SIZE // 2,
    ) -> tuple[bytes, int, int, int]:
        """Load a chunk of audio bytes for HTTP Range streaming.

        Supports two modes:
        - Passthrough mode: When speed=1, time_expansion=1, no clip trimming,
          no resampling — stream raw file bytes directly without decoding.
        - Processing mode: Decode, trim, resample, convert to 16-bit PCM bytes.
          Speed/time_expansion applied via WAV header samplerate manipulation
          (no actual pitch shift).

        Args:
            relative_path: Path relative to audio_root.
            byte_start: Start byte position for range requests. Use 0 for the
                beginning of the stream.
            speed: Playback speed multiplier applied via WAV header. Default 1.
            time_expansion: Time expansion factor of the original recording.
            start_time: Clip start time in seconds (original recording domain).
            end_time: Clip end time in seconds (original recording domain).
            target_samplerate: Resample to this rate. If None, use file rate.
            chunk_frames: Target number of output frames to read per chunk.

        Returns:
            Tuple of (audio_bytes, actual_start_byte, actual_end_byte,
            total_filesize_bytes).
        """
        import logging

        logger = logging.getLogger(__name__)

        file_path = self.get_absolute_path(relative_path)

        with sf.SoundFile(str(file_path)) as sf_file:
            file_samplerate: int = sf_file.samplerate
            channels: int = sf_file.channels

            # Processing mode always outputs 16-bit PCM. Passthrough mode
            # streams raw bytes and uses file_path.stat().st_size directly.
            bytes_per_frame = channels * 16 // 8

            output_samplerate = (
                target_samplerate if target_samplerate is not None else file_samplerate
            )

            passthrough = (
                speed == 1.0
                and time_expansion == 1.0
                and start_time is None
                and end_time is None
                and (target_samplerate is None or target_samplerate == file_samplerate)
            )

            if passthrough:
                bytes_to_read = chunk_frames * bytes_per_frame
                if byte_start == 0:
                    bytes_to_read += HEADER_SIZE
                if bytes_to_read <= 0:
                    bytes_to_read = -1

                with file_path.open("rb") as raw_file:
                    raw_file.seek(byte_start)
                    chunk = raw_file.read(bytes_to_read)

                actual_end = byte_start + len(chunk)
                return chunk, byte_start, actual_end, file_path.stat().st_size

            # Calculate time boundaries (original recording domain -> file domain)
            clip_start: float = start_time if start_time is not None else 0.0
            clip_end: float = (
                end_time
                if end_time is not None
                else (sf_file.frames / file_samplerate) / time_expansion
            )

            file_start_time = clip_start * time_expansion
            file_end_time = clip_end * time_expansion

            start_frame = max(0, min(int(round(file_start_time * file_samplerate)), sf_file.frames))
            end_frame = max(start_frame, min(int(round(file_end_time * file_samplerate)), sf_file.frames))

            total_frames_in_file = end_frame - start_frame
            total_frames_in_output = int(total_frames_in_file * output_samplerate / file_samplerate)
            filesize = total_frames_in_output * bytes_per_frame

            # Determine read offset
            offset = start_frame
            if byte_start > HEADER_SIZE:
                byte_offset = byte_start - HEADER_SIZE
                frame_offset_in_output = byte_offset // bytes_per_frame
                frame_offset_in_file = int(
                    frame_offset_in_output * file_samplerate / output_samplerate
                )
                offset = start_frame + frame_offset_in_file

            frames_to_read = int(math.ceil(chunk_frames * file_samplerate / output_samplerate))
            frames_to_read = max(0, min(frames_to_read, end_frame - offset))

            logger.debug(
                "load_clip_bytes: byte_start=%d, speed=%.2f, time_expansion=%.2f, "
                "original_time=[%.3f, %.3f], file_sr=%d, output_sr=%d, offset=%d, "
                "frames_to_read=%d",
                byte_start,
                speed,
                time_expansion,
                clip_start,
                clip_end,
                file_samplerate,
                output_samplerate,
                offset,
                frames_to_read,
            )

            sf_file.seek(offset)
            audio_data: np.ndarray = sf_file.read(
                frames_to_read, fill_value=0, always_2d=True
            )

        # Resample if needed (torchaudio sinc interpolation)
        if (
            target_samplerate is not None
            and target_samplerate > 0
            and target_samplerate != file_samplerate
        ):
            try:
                wf = torch.from_numpy(audio_data.T).to(torch.float32)
                if wf.shape[1] > 0:
                    wf = taF.resample(wf, file_samplerate, target_samplerate)
                audio_data = wf.T.cpu().numpy()
            except Exception as exc:
                logger.error(
                    "Resampling failed from %dHz to %dHz: %s. Using original rate.",
                    file_samplerate,
                    target_samplerate,
                    exc,
                )
                output_samplerate = file_samplerate
                total_frames_in_output = total_frames_in_file
                filesize = total_frames_in_output * bytes_per_frame

        # Convert numpy array to WAV PCM bytes (without header)
        pcm_buf = io.BytesIO()
        sf.write(pcm_buf, audio_data, output_samplerate, format="RAW", subtype="PCM_16")
        pcm_buf.seek(0)
        audio_bytes = pcm_buf.read()

        total_filesize = filesize + HEADER_SIZE

        # Prepend WAV header at the start of the stream
        if byte_start == 0:
            header_samplerate = int(round(output_samplerate * speed * time_expansion))
            header = generate_wav_header(
                samplerate=header_samplerate,
                channels=channels,
                data_size=filesize,
                bit_depth=16,
            )
            audio_bytes = header + audio_bytes

        actual_start = byte_start
        actual_end = byte_start + len(audio_bytes)

        return audio_bytes, actual_start, actual_end, total_filesize

    # ------------------------------------------------------------------
    # Directory scanning
    # ------------------------------------------------------------------

    def scan_directory(self, relative_dir: str) -> list[str]:
        """Scan a directory recursively for supported audio files.

        Args:
            relative_dir: Directory path relative to audio_root.

        Returns:
            Sorted list of relative paths to audio files.
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

    def list_directories(
        self, relative_path: str = ""
    ) -> list[dict[str, str | int | list[str]]]:
        """List subdirectories with audio file count and format info.

        Args:
            relative_path: Path relative to audio_root (empty = root).

        Returns:
            List of directory info dicts.
        """
        dir_path = self.audio_root / relative_path if relative_path else self.audio_root
        directories: list[dict[str, str | int | list[str]]] = []

        if not dir_path.exists() or not dir_path.is_dir():
            return directories

        for item in sorted(dir_path.iterdir()):
            if item.is_dir():
                audio_count = 0
                formats: set[str] = set()
                for _, _, files in os.walk(item):
                    for f in files:
                        ext = Path(f).suffix.lower()
                        if ext in self.SUPPORTED_FORMATS:
                            audio_count += 1
                            formats.add(ext.lstrip("."))

                rel_path = item.relative_to(self.audio_root)
                directories.append(
                    {
                        "name": item.name,
                        "path": str(rel_path),
                        "audio_file_count": audio_count,
                        "formats": sorted(formats),
                    }
                )

        return directories

