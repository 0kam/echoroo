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
