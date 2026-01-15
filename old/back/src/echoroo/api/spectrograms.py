"""API functions to generate spectrograms."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import xarray as xr
from soundevent import arrays
from torchaudio import functional as taF

import echoroo.api.audio as audio_api
from echoroo import schemas
from echoroo.core.spectrograms import normalize_spectrogram

__all__ = [
    "compute_spectrogram",
    "compute_spectrogram_from_bytes",
]


def _build_window(
    window_type: str,
    length: int,
    device: torch.device,
) -> torch.Tensor:
    """Create a window tensor compatible with torchaudio."""
    if length <= 0:
        return torch.ones(1, device=device)

    window_type = window_type.lower()
    if window_type == "hann":
        return torch.hann_window(length, periodic=True, device=device)
    if window_type == "hamming":
        return torch.hamming_window(length, periodic=True, device=device)
    if window_type == "bartlett":
        return torch.bartlett_window(length, periodic=True, device=device)
    if window_type == "blackman":
        return torch.blackman_window(length, periodic=True, device=device)

    # Fallback to numpy window generation.
    window = None
    if hasattr(np, window_type):
        candidate = getattr(np, window_type)
        try:
            window = candidate(length)
        except TypeError:
            window = None
    if window is None and hasattr(np, f"{window_type}_window"):
        candidate = getattr(np, f"{window_type}_window")
        try:
            window = candidate(length)
        except TypeError:
            window = None
    if window is None:
        window = np.hanning(length)
    return torch.from_numpy(np.asarray(window, dtype=np.float32)).to(device)


def _apply_pcen(spec: torch.Tensor) -> torch.Tensor:
    """Apply PCEN in torch following the original SciPy implementation."""
    if spec.numel() == 0:
        return spec

    smooth = 0.025
    gain = 0.98
    bias = 2.0
    power = 0.5
    eps = 1e-6

    device = spec.device
    dtype = spec.dtype

    smoothing = torch.zeros_like(spec)
    smoothing[..., 0] = spec[..., 0]

    smoothing_coef = torch.tensor(smooth, device=device, dtype=dtype)
    one_minus = 1 - smoothing_coef

    for idx in range(1, spec.shape[-1]):
        smoothing[..., idx] = (
            smoothing_coef * spec[..., idx] + one_minus * smoothing[..., idx - 1]
        )

    eps_t = torch.tensor(eps, device=device, dtype=dtype)
    smooth_term = torch.exp(
        -gain * (torch.log(eps_t) + torch.log1p(smoothing / eps_t))
    )
    pcen = (bias**power) * torch.expm1(
        power * torch.log1p(spec * smooth_term / bias)
    )
    return pcen


def compute_spectrogram(
    recording: schemas.Recording,
    start_time: float,
    end_time: float,
    audio_parameters: schemas.AudioParameters,
    spectrogram_parameters: schemas.SpectrogramParameters,
    audio_dir: Path | None = None,
) -> np.ndarray:
    """Compute a spectrogram for a recording."""
    if audio_dir is None:
        audio_dir = Path.cwd()

    wav = audio_api.load_audio(
        recording,
        start_time,
        end_time,
        audio_parameters=audio_parameters,
        audio_dir=audio_dir,
    )

    # Select channel. Do this early to avoid unnecessary computation.
    wav = wav[dict(channel=[spectrogram_parameters.channel])]

    time_step = wav.time.attrs.get("step")
    if time_step is None or time_step <= 0:
        raise ValueError(
            "Audio data must include a positive time step attribute."
        )
    samplerate = int(round(1 / time_step))

    window_size = spectrogram_parameters.window_size
    hop_size = (1 - spectrogram_parameters.overlap) * window_size
    hop_size = max(hop_size, 1 / samplerate)

    win_length = max(1, int(round(window_size * samplerate)))
    hop_length = max(1, int(round(hop_size * samplerate)))
    n_fft = max(2, win_length)

    waveform_np = np.asarray(wav.data, dtype=np.float32)
    if waveform_np.ndim == 1:
        waveform_np = waveform_np[:, np.newaxis]
    waveform = torch.from_numpy(waveform_np.T.copy())

    device = waveform.device
    window_tensor = _build_window(
        spectrogram_parameters.window,
        win_length,
        device=device,
    )

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

    window_energy = torch.sum(window_tensor.pow(2))
    if samplerate > 0 and window_energy > 0:
        spec = spec / (samplerate * window_energy)

    if n_fft % 2 == 0 and spec.shape[1] > 2:
        spec[:, 1:-1] *= 2
    elif spec.shape[1] > 1:
        spec[:, 1:] *= 2

    if spectrogram_parameters.pcen:
        spec = _apply_pcen(spec)

    freq_values = torch.fft.rfftfreq(n_fft, d=1 / samplerate).cpu().numpy()
    hop_seconds = hop_length / samplerate
    time_offset = float(wav.time.data[0]) + hop_seconds / 2
    time_values = (
        time_offset
        + np.arange(spec.shape[-1], dtype=np.float64) * hop_seconds
    )

    spectrogram = xr.DataArray(
        data=spec.permute(1, 2, 0).cpu().numpy(),
        dims=("frequency", "time", "channel"),
        coords={
            "frequency": arrays.create_frequency_dim_from_array(
                freq_values,
                step=samplerate / n_fft,
            ),
            "time": arrays.create_time_dim_from_array(
                time_values,
                step=hop_seconds,
            ),
            "channel": wav.channel,
        },
        attrs={
            **wav.attrs,
            "window_size": window_size,
            "hop_size": hop_size,
            "window_type": spectrogram_parameters.window,
            arrays.ArrayAttrs.units.value: "V**2/Hz",
            arrays.ArrayAttrs.standard_name.value: "spectrogram",
            arrays.ArrayAttrs.long_name.value: "Power Spectral Density",
        },
    )

    spectrogram = arrays.to_db(
        spectrogram,
        min_db=spectrogram_parameters.min_dB,
        max_db=spectrogram_parameters.max_dB,
    )

    spectrogram = normalize_spectrogram(
        spectrogram,
        relative=spectrogram_parameters.normalize,
    )

    return spectrogram.data.squeeze()


def compute_spectrogram_from_bytes(
    audio_bytes: bytes,
    start_time: float,
    end_time: float,
    audio_parameters: schemas.AudioParameters,
    spectrogram_parameters: schemas.SpectrogramParameters,
) -> np.ndarray:
    """Compute a spectrogram from raw audio bytes.

    This function is used for generating spectrograms from Xeno-Canto recordings
    or other external audio sources where we have bytes instead of a file path.

    Parameters
    ----------
    audio_bytes : bytes
        Raw audio data in any format supported by soundfile.
    start_time : float
        Start time in seconds to extract from the audio.
    end_time : float
        End time in seconds to extract from the audio.
    audio_parameters : schemas.AudioParameters
        Audio processing parameters (resampling, filtering).
    spectrogram_parameters : schemas.SpectrogramParameters
        Spectrogram generation parameters.

    Returns
    -------
    np.ndarray
        Spectrogram data as a 2D numpy array (frequency x time).
    """
    import io
    import soundfile as sf

    # Load audio from bytes
    with io.BytesIO(audio_bytes) as audio_buffer:
        data, samplerate = sf.read(audio_buffer, always_2d=True)

    # Convert to numpy array and transpose to (channels, samples)
    if data.ndim == 1:
        data = data[:, np.newaxis]
    data = data.T

    # Calculate sample indices for time slicing
    start_sample = int(start_time * samplerate)
    end_sample = int(end_time * samplerate)

    # Clamp to valid range
    start_sample = max(0, start_sample)
    end_sample = min(data.shape[1], end_sample)

    # Extract time segment
    if start_sample < end_sample:
        data = data[:, start_sample:end_sample]
    else:
        # If invalid range, return empty spectrogram
        data = np.zeros((data.shape[0], 1), dtype=np.float32)

    # Convert to torch tensor for processing
    waveform = torch.from_numpy(data.astype(np.float32))

    # Import torchaudio functional (needed for spectrogram computation)
    from torchaudio import functional as taF

    # Apply resampling if requested
    if audio_parameters.resample and audio_parameters.samplerate != samplerate:
        waveform = taF.resample(
            waveform,
            orig_freq=samplerate,
            new_freq=audio_parameters.samplerate,
        )
        samplerate = audio_parameters.samplerate

    # Apply filtering if requested
    if audio_parameters.low_freq is not None or audio_parameters.high_freq is not None:
        from echoroo.api.audio import _apply_filters
        waveform = _apply_filters(
            waveform,
            samplerate,
            audio_parameters.low_freq,
            audio_parameters.high_freq,
            audio_parameters.filter_order,
        )

    # Select channel
    if waveform.shape[0] > spectrogram_parameters.channel:
        waveform = waveform[spectrogram_parameters.channel:spectrogram_parameters.channel+1]
    else:
        waveform = waveform[0:1]

    # Compute spectrogram parameters
    window_size = spectrogram_parameters.window_size
    hop_size = (1 - spectrogram_parameters.overlap) * window_size
    hop_size = max(hop_size, 1 / samplerate)

    win_length = max(1, int(round(window_size * samplerate)))
    hop_length = max(1, int(round(hop_size * samplerate)))
    n_fft = max(2, win_length)

    device = waveform.device
    window_tensor = _build_window(
        spectrogram_parameters.window,
        win_length,
        device=device,
    )

    # Compute spectrogram
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

    # Normalize by window energy
    window_energy = torch.sum(window_tensor.pow(2))
    if samplerate > 0 and window_energy > 0:
        spec = spec / (samplerate * window_energy)

    # Apply one-sided correction
    if n_fft % 2 == 0 and spec.shape[1] > 2:
        spec[:, 1:-1] *= 2
    elif spec.shape[1] > 1:
        spec[:, 1:] *= 2

    # Apply PCEN if requested
    if spectrogram_parameters.pcen:
        spec = _apply_pcen(spec)

    # Convert to numpy and create xarray for dB conversion
    spec_np = spec.squeeze().cpu().numpy()

    # Convert to dB scale
    from soundevent import arrays

    freq_values = torch.fft.rfftfreq(n_fft, d=1 / samplerate).cpu().numpy()
    hop_seconds = hop_length / samplerate
    time_offset = start_time + hop_seconds / 2
    time_values = (
        time_offset
        + np.arange(spec_np.shape[1] if spec_np.ndim > 1 else 1, dtype=np.float64) * hop_seconds
    )

    # Ensure spec_np is 2D
    if spec_np.ndim == 1:
        spec_np = spec_np[:, np.newaxis]

    spectrogram = xr.DataArray(
        data=spec_np,
        dims=("frequency", "time"),
        coords={
            "frequency": arrays.create_frequency_dim_from_array(
                freq_values,
                step=samplerate / n_fft,
            ),
            "time": arrays.create_time_dim_from_array(
                time_values,
                step=hop_seconds,
            ),
        },
        attrs={
            "window_size": window_size,
            "hop_size": hop_size,
            "window_type": spectrogram_parameters.window,
            arrays.ArrayAttrs.units.value: "V**2/Hz",
            arrays.ArrayAttrs.standard_name.value: "spectrogram",
            arrays.ArrayAttrs.long_name.value: "Power Spectral Density",
        },
    )

    spectrogram = arrays.to_db(
        spectrogram,
        min_db=spectrogram_parameters.min_dB,
        max_db=spectrogram_parameters.max_dB,
    )

    spectrogram = normalize_spectrogram(
        spectrogram,
        relative=spectrogram_parameters.normalize,
    )

    return spectrogram.data.squeeze()
