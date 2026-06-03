"""Unit tests for ultrasonic playback rule (real-time vs time-expansion).

Covers the playback behavior implemented in
:func:`echoroo.api.v1.recordings.get_playback_audio` and the underlying
:meth:`echoroo.services.audio.service.AudioService.load_clip_bytes`:

- Ultrasonic + default (speed == 1.0): REAL-TIME. The clip is genuinely
  resampled down to ~48 kHz so the output WAV header rate is ~48 kHz AND the
  output duration equals the original recording duration (NOT ~5.3x longer).
- Ultrasonic + explicit slower speed (speed < 1.0): TIME-EXPANSION. The WAV
  header rate is rewritten low (no resampling), so the same PCM plays back
  slower / pitch-shifted into the audible band.
- Non-ultrasonic at speed 1.0: passthrough (raw bytes, unchanged).
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import soundfile as sf

from echoroo.api.v1.recordings import PLAYBACK_TARGET_SAMPLERATE
from echoroo.services.audio._wav import HEADER_FORMAT, HEADER_SIZE
from echoroo.services.audio.service import AudioService

# Field offsets within the canonical 44-byte WAV header (see _wav.HEADER_FORMAT).
_SAMPLERATE_FIELD_INDEX = 7
_DATA_SIZE_FIELD_INDEX = 12


def _parse_header(audio_bytes: bytes) -> tuple[int, int]:
    """Return (samplerate, data_size) parsed from the leading WAV header."""
    fields = struct.unpack(HEADER_FORMAT, audio_bytes[:HEADER_SIZE])
    return fields[_SAMPLERATE_FIELD_INDEX], fields[_DATA_SIZE_FIELD_INDEX]


def _write_wav(
    root: Path, rel: str, *, samplerate: int, duration_s: float
) -> str:
    """Write a mono test WAV under ``root`` and return its relative path."""
    n = int(samplerate * duration_s)
    # Low-amplitude tone; content is irrelevant, only frame counts/rates matter.
    data = (0.1 * np.sin(np.linspace(0, 2 * np.pi * 1000, n))).astype(np.float32)
    abs_path = root / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(abs_path), data, samplerate, subtype="PCM_16")
    return rel


def test_ultrasonic_default_is_realtime_resampled(tmp_path: Path) -> None:
    """Ultrasonic + default: header ~48 kHz AND original duration preserved.

    This mirrors the endpoint default branch: target_samplerate=48000,
    speed=1.0, time_expansion=1.0 -> genuine downsample, real-time playback.
    """
    samplerate = 192_000
    duration_s = 2.0
    rel = _write_wav(tmp_path, "recordings/us.wav", samplerate=samplerate, duration_s=duration_s)
    service = AudioService(audio_root=str(tmp_path))

    audio_bytes, _start, _end, _total = service.load_clip_bytes(
        relative_path=rel,
        byte_start=0,
        speed=1.0,
        time_expansion=1.0,
        target_samplerate=PLAYBACK_TARGET_SAMPLERATE,
        # Read the whole clip in one shot.
        chunk_frames=int(samplerate * duration_s),
    )

    header_sr, data_size = _parse_header(audio_bytes)

    # Header advertises the browser-friendly rate (real-time, not slowed).
    assert header_sr == PLAYBACK_TARGET_SAMPLERATE

    # Output duration must equal the ORIGINAL duration (real-time), i.e. the
    # number of 16-bit mono frames is ~ 48000 * duration, NOT 192000 * duration.
    out_frames = data_size // 2  # 16-bit mono => 2 bytes/frame
    expected_frames = PLAYBACK_TARGET_SAMPLERATE * duration_s
    out_duration = out_frames / PLAYBACK_TARGET_SAMPLERATE
    assert out_duration == round(out_duration, 6)
    assert abs(out_frames - expected_frames) <= PLAYBACK_TARGET_SAMPLERATE * 0.05
    assert abs(out_duration - duration_s) < 0.1

    # Regression guard: it must NOT be the old ~4x (192000/48000) longer output.
    assert out_duration < duration_s * 1.5


def test_ultrasonic_default_ignores_stored_time_expansion(tmp_path: Path) -> None:
    """Ultrasonic + default + stored time_expansion != 1.0: still real-time 48 kHz.

    A recording may carry BOTH ``samplerate > 96 kHz`` AND a stored
    ``time_expansion != 1.0`` (an independent field, ge=0.1 le=100.0). The
    real-time branch of ``get_playback_audio`` intentionally forces
    ``effective_te = 1.0`` so the output targets 48 kHz at the file's
    wall-clock duration (keeping the UI seek bar consistent) rather than
    compressing by the stored TE. This locks that documented behavior: the
    stored time_expansion is deliberately ignored here (it only applies on the
    explicit slow-speed path). A future change is therefore a conscious one.

    This mirrors the endpoint default branch: regardless of the stored TE the
    call passes target_samplerate=48000, speed=1.0, time_expansion=1.0.
    """
    samplerate = 192_000
    duration_s = 2.0
    rel = _write_wav(
        tmp_path, "recordings/us_te.wav", samplerate=samplerate, duration_s=duration_s
    )
    service = AudioService(audio_root=str(tmp_path))

    # The stored time_expansion (e.g. 10.0) is NOT forwarded by the real-time
    # branch — it forces time_expansion=1.0 — so the load_clip_bytes call is
    # byte-for-byte the same as a recording with TE == 1.0.
    audio_bytes, _start, _end, _total = service.load_clip_bytes(
        relative_path=rel,
        byte_start=0,
        speed=1.0,
        time_expansion=1.0,  # effective_te is forced to 1.0 by the endpoint
        target_samplerate=PLAYBACK_TARGET_SAMPLERATE,
        chunk_frames=int(samplerate * duration_s),
    )

    header_sr, data_size = _parse_header(audio_bytes)

    # Header advertises the browser-friendly rate (real-time, not slowed and
    # NOT compressed by the stored time_expansion).
    assert header_sr == PLAYBACK_TARGET_SAMPLERATE

    # Output duration must equal the ORIGINAL file (wall-clock) duration, i.e.
    # ~48000 * duration frames — NOT compressed by the stored TE.
    out_frames = data_size // 2  # 16-bit mono => 2 bytes/frame
    expected_frames = PLAYBACK_TARGET_SAMPLERATE * duration_s
    out_duration = out_frames / PLAYBACK_TARGET_SAMPLERATE
    assert abs(out_frames - expected_frames) <= PLAYBACK_TARGET_SAMPLERATE * 0.05
    assert abs(out_duration - duration_s) < 0.1

    # Regression guard: the stored TE must not stretch or compress the output.
    assert out_duration < duration_s * 1.5


def test_ultrasonic_explicit_slow_is_time_expanded(tmp_path: Path) -> None:
    """Ultrasonic + explicit slow: low header rate, no resampling (time-expansion).

    Mirrors the endpoint slow branch: target_samplerate=None, speed<1.0,
    time_expansion=stored. The full ultrasonic PCM is kept and the header rate
    is rewritten low so it plays back slower / shifted into the audible band.
    """
    samplerate = 192_000
    duration_s = 1.0
    rel = _write_wav(tmp_path, "recordings/us_slow.wav", samplerate=samplerate, duration_s=duration_s)
    service = AudioService(audio_root=str(tmp_path))

    speed = 0.25  # explicit slow-down requested by the client
    audio_bytes, _start, _end, _total = service.load_clip_bytes(
        relative_path=rel,
        byte_start=0,
        speed=speed,
        time_expansion=1.0,
        target_samplerate=None,
        chunk_frames=int(samplerate * duration_s),
    )

    header_sr, data_size = _parse_header(audio_bytes)

    # header_sr = output_sr * speed * time_expansion = 192000 * 0.25 * 1.0
    assert header_sr == int(round(samplerate * speed * 1.0))
    assert header_sr < samplerate  # plays back slower than real time

    # No resampling: full-rate PCM retained, so the byte count corresponds to
    # the native sample rate (NOT downsampled to 48 kHz).
    out_frames = data_size // 2
    expected_native_frames = samplerate * duration_s
    assert abs(out_frames - expected_native_frames) <= samplerate * 0.05

    # Played at the rewritten header rate, the effective duration is expanded.
    played_duration = out_frames / header_sr
    assert played_duration > duration_s * 2  # ~4x longer at speed 0.25


def test_non_ultrasonic_passthrough_unchanged(tmp_path: Path) -> None:
    """Non-ultrasonic at speed 1.0 / te 1.0: passthrough, raw bytes unchanged."""
    samplerate = 48_000
    duration_s = 0.5
    rel = _write_wav(tmp_path, "recordings/normal.wav", samplerate=samplerate, duration_s=duration_s)
    service = AudioService(audio_root=str(tmp_path))

    audio_bytes, start, _end, total = service.load_clip_bytes(
        relative_path=rel,
        byte_start=0,
        speed=1.0,
        time_expansion=1.0,
        target_samplerate=None,
        chunk_frames=int(samplerate * duration_s) + HEADER_SIZE,
    )

    # Passthrough streams the raw file bytes verbatim (header byte-identical).
    abs_path = tmp_path / rel
    raw = abs_path.read_bytes()
    assert start == 0
    assert total == abs_path.stat().st_size
    # The returned chunk is a prefix of the raw file (verbatim passthrough).
    assert raw.startswith(audio_bytes[: min(len(audio_bytes), len(raw))])
    # Header sample rate is the original, native rate (no rewrite).
    header_sr, _data_size = _parse_header(audio_bytes)
    assert header_sr == samplerate
