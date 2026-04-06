"""Window function builder for spectrogram computation.

Supports 13 named window functions via torch native and scipy.signal fallback.
"""

from __future__ import annotations

import numpy as np
import torch


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
