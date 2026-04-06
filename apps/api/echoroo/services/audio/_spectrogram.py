"""Core spectrogram computation functions.

Includes PCEN normalization, dB conversion, colormap rendering,
and PSD-normalized power spectrogram computation via torchaudio.
"""

from __future__ import annotations

import numpy as np
import torch
from torchaudio import functional as taF

from echoroo.services.audio._window import _build_window

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
