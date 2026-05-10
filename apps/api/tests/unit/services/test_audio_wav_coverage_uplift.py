"""Coverage uplift unit tests for ``echoroo.services.audio._wav``.

Phase 17 §C heavy-gap batch: targets the ``generate_wav_header`` byte-rate
and block-align computation (lines 31-32, 34) so the module clears the
85% threshold without touching production code.

The module is a thin pure function around :mod:`struct.pack`. The test
verifies the canonical 44-byte WAV header layout for a known sample-rate
/ channel / data-size triple by re-parsing the produced header.
"""

from __future__ import annotations

import struct

from echoroo.services.audio import _wav
from echoroo.services.audio._wav import HEADER_FORMAT, generate_wav_header


def test_generate_wav_header_returns_exact_44_byte_layout() -> None:
    """44-byte WAV PCM header round-trips through struct.unpack (lines 31-32, 34)."""
    samplerate = 48_000
    channels = 1
    data_size = 1024
    bit_depth = 16

    header = generate_wav_header(
        samplerate=samplerate,
        channels=channels,
        data_size=data_size,
        bit_depth=bit_depth,
    )

    assert isinstance(header, bytes)
    assert len(header) == 44

    # Round-trip: unpack the produced header and verify each field.
    fields = struct.unpack(HEADER_FORMAT, header)
    (
        riff,
        chunk_size,
        wave,
        fmt_chunk_id,
        fmt_chunk_size,
        audio_format,
        n_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        data_chunk_id,
        data_chunk_size,
    ) = fields
    assert riff == b"RIFF"
    assert wave == b"WAVE"
    assert fmt_chunk_id == b"fmt "
    assert fmt_chunk_size == 16
    assert audio_format == 1  # PCM
    assert n_channels == channels
    assert sample_rate == samplerate
    assert bits_per_sample == bit_depth
    # byte_rate = samplerate * channels * bit_depth // 8 (line 31).
    assert byte_rate == samplerate * channels * bit_depth // 8
    # block_align = channels * bit_depth // 8 (line 32).
    assert block_align == channels * bit_depth // 8
    assert data_chunk_id == b"data"
    assert data_chunk_size == data_size
    # chunk_size = data_size + 36 (RIFF total minus 8 leading bytes).
    assert chunk_size == data_size + 36


def test_generate_wav_header_24bit_stereo_byte_rate() -> None:
    """24-bit stereo at 96 kHz produces the expected byte-rate constants."""
    header = generate_wav_header(
        samplerate=96_000,
        channels=2,
        data_size=2048,
        bit_depth=24,
    )
    assert len(header) == _wav.HEADER_SIZE
    fields = struct.unpack(HEADER_FORMAT, header)
    (_, _, _, _, _, _, n_channels, sample_rate, byte_rate, block_align, bits_per_sample, _, _) = fields
    assert n_channels == 2
    assert sample_rate == 96_000
    assert bits_per_sample == 24
    assert byte_rate == 96_000 * 2 * 24 // 8
    assert block_align == 2 * 24 // 8
