"""WAV header generation and streaming constants."""

from __future__ import annotations

import struct

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
