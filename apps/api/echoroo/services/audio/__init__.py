"""Audio processing service package.

Re-exports AudioService and AudioMetadata for backward compatibility.
The implementation is split into sub-modules:

- service.py   : AudioService class (main entry point)
- _spectrogram.py : spectrogram computation helpers (PCEN, dB, colormap, STFT)
- _window.py   : window function builder (13 window types)
- _wav.py      : WAV header generation and streaming constants
"""

from echoroo.services.audio._spectrogram import (
    _apply_colormap,
    _apply_pcen,
    _compute_spectrogram_tensor,
    _get_colormap_lut,
    _to_db,
)
from echoroo.services.audio._wav import (
    CHUNK_SIZE,
    HEADER_FORMAT,
    HEADER_SIZE,
    generate_wav_header,
)
from echoroo.services.audio._window import _build_window
from echoroo.services.audio.service import AudioMetadata, AudioService

__all__ = [
    "AudioService",
    "AudioMetadata",
    "CHUNK_SIZE",
    "HEADER_FORMAT",
    "HEADER_SIZE",
    "generate_wav_header",
    "_apply_colormap",
    "_apply_pcen",
    "_compute_spectrogram_tensor",
    "_get_colormap_lut",
    "_to_db",
    "_build_window",
]
