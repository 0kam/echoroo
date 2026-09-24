"""GPS metadata strip tests for uploaded file content."""
from __future__ import annotations

import io
import struct

import pytest

# ---------------------------------------------------------------------------
# WAV/FLAC/MP3 file-content GPS strip tests
# ---------------------------------------------------------------------------


def _build_wav_with_fake_gps_chunk() -> bytes:
    """Build a minimal RIFF WAV byte stream containing a fake "GPS " chunk.

    The bytes are not a playable audio file; they only need to satisfy the
    structural contract: the resulting blob contains the 4-byte ASCII chunk
    id ``GPS `` so the eventual EXIF-strip integration can be validated by
    asserting its absence post-strip.
    """
    chunk_id = b"GPS "
    chunk_payload = b"\x00\x00\x00\x00LAT=35.6;LON=139.7"
    chunk_size = struct.pack("<I", len(chunk_payload))
    gps_chunk = chunk_id + chunk_size + chunk_payload

    fmt_chunk = b"fmt " + struct.pack("<I", 16) + b"\x01\x00" + b"\x01\x00"
    fmt_chunk += struct.pack("<I", 44100) + struct.pack("<I", 88200)
    fmt_chunk += b"\x02\x00" + b"\x10\x00"

    data_chunk = b"data" + struct.pack("<I", 0)

    body = b"WAVE" + fmt_chunk + gps_chunk + data_chunk
    riff_header = b"RIFF" + struct.pack("<I", len(body)) + b""
    return riff_header + body


def test_wav_upload_strips_gps_chunk_before_persistence() -> None:
    """The upload pipeline must remove GPS-bearing chunks pre-persistence."""
    raw = _build_wav_with_fake_gps_chunk()
    assert b"GPS " in raw, "fixture must seed a GPS chunk for the strip test"

    from echoroo.services.upload import strip_audio_gps_metadata

    cleaned = strip_audio_gps_metadata(io.BytesIO(raw)).read()
    assert b"GPS " not in cleaned, "GPS chunk must be stripped before save"
    # Sanity: the fmt chunk must still be present so the file remains valid.
    assert b"fmt " in cleaned
    # RIFF header must be rewritten with the new (smaller) size.
    assert cleaned[:4] == b"RIFF"
    assert cleaned[8:12] == b"WAVE"


def test_wav_without_gps_chunk_is_unchanged() -> None:
    """A WAV with no GPS chunk must pass through unchanged."""
    fmt_chunk = b"fmt " + struct.pack("<I", 16) + b"\x01\x00" + b"\x01\x00"
    fmt_chunk += struct.pack("<I", 44100) + struct.pack("<I", 88200)
    fmt_chunk += b"\x02\x00" + b"\x10\x00"
    data_chunk = b"data" + struct.pack("<I", 0)
    body = b"WAVE" + fmt_chunk + data_chunk
    payload = b"RIFF" + struct.pack("<I", len(body)) + body

    from echoroo.services.upload import strip_audio_gps_metadata

    out = strip_audio_gps_metadata(io.BytesIO(payload)).read()
    assert out == payload

def test_wav_strips_case_insensitive_gps_chunk() -> None:
    """RIFF GPS chunks with case-variant ids must also be stripped."""
    chunk_id = b"gps "  # lowercase
    chunk_payload = b"\x00\x00\x00\x00LAT=35.6"
    chunk_size = struct.pack("<I", len(chunk_payload))
    gps_chunk = chunk_id + chunk_size + chunk_payload

    fmt_chunk = b"fmt " + struct.pack("<I", 16) + b"\x01\x00" + b"\x01\x00"
    fmt_chunk += struct.pack("<I", 44100) + struct.pack("<I", 88200)
    fmt_chunk += b"\x02\x00" + b"\x10\x00"
    data_chunk = b"data" + struct.pack("<I", 0)
    body = b"WAVE" + fmt_chunk + gps_chunk + data_chunk
    payload = b"RIFF" + struct.pack("<I", len(body)) + body

    from echoroo.services.upload import strip_audio_gps_metadata

    out = strip_audio_gps_metadata(io.BytesIO(payload)).read()
    assert b"gps " not in out
    assert b"LAT=35.6" not in out


def _build_flac_with_gps_tags() -> bytes:
    """Build a minimal valid FLAC with GPS Vorbis comments for tests."""
    import tempfile

    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    from mutagen.flac import FLAC

    buf = io.BytesIO()
    sf.write(buf, np.zeros(4410, dtype="int16"), 44100, format="FLAC")
    seed = buf.getvalue()
    with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as tmp:
        tmp.write(seed)
        tmp_path = tmp.name
    try:
        flac = FLAC(tmp_path)
        flac["LATITUDE"] = "35.6"
        flac["LONGITUDE"] = "139.7"
        flac["GPS-RAW"] = "1,2,3"
        flac["LOCATION-CITY"] = "Tokyo"
        flac["GEO-POINT"] = "x,y"
        flac["COORD-PT"] = "x,y"
        flac["ARTIST"] = "Alice"
        flac["TITLE"] = "Recording"
        flac.save()
        with open(tmp_path, "rb") as fp:
            return fp.read()
    finally:
        import os as _os

        _os.unlink(tmp_path)


def test_flac_upload_strips_gps_vorbis_comments() -> None:
    """FLAC GPS / coordinate tags must be removed; non-GPS tags preserved."""
    raw = _build_flac_with_gps_tags()
    assert b"LATITUDE" in raw

    from echoroo.services.upload import strip_audio_gps_metadata

    cleaned = strip_audio_gps_metadata(io.BytesIO(raw)).read()
    # mutagen may rewrite tag block, so we also check via re-parse.
    import tempfile

    from mutagen.flac import FLAC

    with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as tmp:
        tmp.write(cleaned)
        tmp_path = tmp.name
    try:
        flac = FLAC(tmp_path)
        keys_lower = {k.lower() for k in list((flac.tags or {}).keys())}
        assert "latitude" not in keys_lower
        assert "longitude" not in keys_lower
        assert "gps-raw" not in keys_lower
        assert "location-city" not in keys_lower
        assert "geo-point" not in keys_lower
        assert "coord-pt" not in keys_lower
        # Non-GPS tags survive.
        assert "artist" in keys_lower
        assert "title" in keys_lower
    finally:
        import os as _os

        _os.unlink(tmp_path)


def _build_ogg_vorbis_with_gps_tags() -> bytes:
    """Build a minimal valid OGG Vorbis with GPS Vorbis comments."""
    import tempfile

    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    from mutagen.oggvorbis import OggVorbis

    buf = io.BytesIO()
    sf.write(buf, np.zeros(4410, dtype="int16"), 44100, format="OGG", subtype="VORBIS")
    seed = buf.getvalue()
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp.write(seed)
        tmp_path = tmp.name
    try:
        ogg = OggVorbis(tmp_path)
        ogg["LATITUDE"] = "35.6"
        ogg["LONGITUDE"] = "139.7"
        ogg["GPS_RAW"] = "1,2,3"
        ogg["LOCATION_CITY"] = "Tokyo"
        ogg["ARTIST"] = "Alice"
        ogg.save()
        with open(tmp_path, "rb") as fp:
            return fp.read()
    finally:
        import os as _os

        _os.unlink(tmp_path)


def test_ogg_vorbis_upload_strips_gps_comments() -> None:
    """OGG Vorbis GPS tags must be removed; non-GPS tags preserved."""
    raw = _build_ogg_vorbis_with_gps_tags()

    from echoroo.services.upload import strip_audio_gps_metadata

    cleaned = strip_audio_gps_metadata(io.BytesIO(raw)).read()
    import tempfile

    from mutagen.oggvorbis import OggVorbis

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp.write(cleaned)
        tmp_path = tmp.name
    try:
        ogg = OggVorbis(tmp_path)
        keys_lower = {k.lower() for k in list((ogg.tags or {}).keys())}
        assert "latitude" not in keys_lower
        assert "longitude" not in keys_lower
        assert "gps_raw" not in keys_lower
        assert "location_city" not in keys_lower
        assert "artist" in keys_lower
    finally:
        import os as _os

        _os.unlink(tmp_path)


def _build_mp3_with_gps_id3() -> bytes:
    """Build a minimal valid MP3 with GPS-bearing ID3 frames via ffmpeg."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available; cannot synthesize MP3 fixture")
    from mutagen.id3 import TIT2, TXXX
    from mutagen.mp3 import MP3

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        res = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-t",
                "0.1",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "32k",
                tmp_path,
            ],
            capture_output=True,
            timeout=20,
        )
        if res.returncode != 0:
            pytest.skip("ffmpeg failed to synthesize MP3 fixture")
        mp3 = MP3(tmp_path)
        if mp3.tags is None:
            mp3.add_tags()
        mp3.tags.add(TXXX(encoding=3, desc="GPS Latitude", text="35.6"))
        mp3.tags.add(TXXX(encoding=3, desc="GPS Longitude", text="139.7"))
        mp3.tags.add(TXXX(encoding=3, desc="Location City", text="Tokyo"))
        mp3.tags.add(TIT2(encoding=3, text="Test Title"))
        mp3.save()
        with open(tmp_path, "rb") as fp:
            return fp.read()
    finally:
        import os as _os

        with __import__("contextlib").suppress(OSError):
            _os.unlink(tmp_path)


def test_mp3_upload_strips_gps_id3_frames() -> None:
    """MP3 ID3v2 GPS-bearing TXXX frames must be removed; TIT2 preserved."""
    raw = _build_mp3_with_gps_id3()

    from echoroo.services.upload import strip_audio_gps_metadata

    cleaned = strip_audio_gps_metadata(io.BytesIO(raw)).read()
    import tempfile

    from mutagen.mp3 import MP3

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(cleaned)
        tmp_path = tmp.name
    try:
        mp3 = MP3(tmp_path)
        tag_keys = list((mp3.tags or {}).keys())
        # No TXXX frame whose desc starts with GPS/Location should remain.
        assert not any(
            k.lower().startswith("txxx:gps")
            or k.lower().startswith("txxx:location")
            for k in tag_keys
        )
        # Non-GPS frame survives.
        assert any(k == "TIT2" for k in tag_keys)
    finally:
        import os as _os

        _os.unlink(tmp_path)


def test_unknown_format_passthrough() -> None:
    """Unknown audio container bytes must pass through unchanged."""
    from echoroo.services.upload import strip_audio_gps_metadata

    payload = b"\x00\x01\x02\x03not-an-audio-format-payload"
    out = strip_audio_gps_metadata(io.BytesIO(payload)).read()
    assert out == payload


# ---------------------------------------------------------------------------
# Fail-closed behavior for supported audio formats.
# ---------------------------------------------------------------------------


def test_strip_audio_gps_metadata_fail_closed_on_supported_format() -> None:
    """A supported-format payload that mutagen cannot parse must raise.

    This covers High-1 from the Codex Round 1 review: a corrupt MP3
    header that still satisfies the magic-byte test (``ID3``) but trips
    mutagen on load must surface as :class:`AudioGpsStripError` so the
    worker marks the file INVALID rather than persisting a payload whose
    GPS state we cannot prove is clean.
    """
    from echoroo.services.upload import (
        AudioGpsStripError,
        strip_audio_gps_metadata,
    )

    # ID3v2 magic + total nonsense afterwards. mutagen.MP3 will choke.
    payload = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
    with pytest.raises(AudioGpsStripError):
        strip_audio_gps_metadata(io.BytesIO(payload))


def test_strip_audio_gps_metadata_unsupported_format_still_passthrough() -> None:
    """Unsupported / unknown formats must continue to pass through clean.

    Round 2 only tightens the *supported*-format failure path. Bytes
    whose magic does not match any known container are still returned
    unchanged because the upload pipeline rejects them at the
    ``_detect_audio_format`` magic-byte stage upstream.
    """
    from echoroo.services.upload import strip_audio_gps_metadata

    payload = b"\x00\x01\x02\x03not-an-audio-format-payload"
    out = strip_audio_gps_metadata(io.BytesIO(payload)).read()
    assert out == payload
