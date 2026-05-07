"""GPS metadata strip tests (FR-028a + FR-028e).

T128: ``sanitize_put_object_kwargs`` direct unit tests confirm that S3 object
metadata never carries raw lat/lng / GPS-prefixed keys, regardless of case.

T129: EXIF-stripping tests for the upload pipeline are scaffolded as ``xfail``
because the upload-side stream sanitizer (FR-028a) is delivered by a separate
Phase 3 task. The structural test enforces that the contract still exists once
that pipeline lands; it must not be deleted.
"""
from __future__ import annotations

import io
import logging
import struct
from datetime import UTC, datetime
from typing import Any

import pytest

from echoroo.services.s3_upload_sanitizer import sanitize_put_object_kwargs

# ---------------------------------------------------------------------------
# T128: sanitize_put_object_kwargs direct tests (FR-028e)
# ---------------------------------------------------------------------------


class TestSanitizePutObjectKwargs:
    """Direct unit tests for the S3 PutObject metadata sanitizer."""

    def test_strips_lat_lng_keeps_user_metadata(self) -> None:
        kwargs = {
            "Bucket": "echoroo-uploads",
            "Key": "recordings/foo.wav",
            "Body": b"fake-bytes",
            "Metadata": {"lat": "35.6", "lng": "139.7", "user": "alice"},
        }
        result = sanitize_put_object_kwargs(kwargs)

        assert result["Metadata"] == {"user": "alice"}
        # Non-Metadata kwargs preserved unchanged.
        assert result["Bucket"] == "echoroo-uploads"
        assert result["Key"] == "recordings/foo.wav"
        assert result["Body"] == b"fake-bytes"

    def test_strips_mixed_case_and_gps_prefixed_keys(self) -> None:
        kwargs = {
            "Bucket": "b",
            "Key": "k",
            "Metadata": {
                "GPS": "raw",
                "Gps_Lat": "35.6",
                "GPS-LON": "139.7",
                "Latitude": "35.6",
                "LONGITUDE": "139.7",
                "Lon": "139.7",
                "geo_point": "...",
                "coord": "x,y",
                "coords": "x,y",
                "location": "tokyo",
                "Location_City": "tokyo",
                "description": "field recording",
            },
        }
        result = sanitize_put_object_kwargs(kwargs)

        assert result["Metadata"] == {"description": "field recording"}

    def test_non_gps_keys_are_preserved(self) -> None:
        kwargs = {
            "Bucket": "b",
            "Key": "k",
            "Metadata": {
                "description": "field recording",
                "uploaded_by": "alice",
                "license": "CC-BY-4.0",
            },
        }
        result = sanitize_put_object_kwargs(kwargs)

        assert result["Metadata"] == {
            "description": "field recording",
            "uploaded_by": "alice",
            "license": "CC-BY-4.0",
        }

    def test_no_metadata_kwarg_is_passthrough(self) -> None:
        kwargs: dict[str, Any] = {
            "Bucket": "b",
            "Key": "k",
            "Body": b"x",
            "ContentType": "audio/wav",
        }
        result = sanitize_put_object_kwargs(kwargs)

        assert result == kwargs
        # Defensive copy: mutating the result must not bleed into the input.
        result["Bucket"] = "other"
        assert kwargs["Bucket"] == "b"

    def test_empty_metadata_dict_is_kept_empty(self) -> None:
        kwargs: dict[str, Any] = {"Bucket": "b", "Key": "k", "Metadata": {}}
        result = sanitize_put_object_kwargs(kwargs)

        assert result["Metadata"] == {}

    def test_input_metadata_is_not_mutated(self) -> None:
        original_metadata = {"lat": "35.6", "user": "alice"}
        kwargs = {"Bucket": "b", "Key": "k", "Metadata": original_metadata}

        sanitize_put_object_kwargs(kwargs)

        # Original metadata dict must remain untouched (defensive copy).
        assert original_metadata == {"lat": "35.6", "user": "alice"}

    def test_log_event_emitted_when_keys_stripped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        kwargs = {
            "Bucket": "b",
            "Key": "k",
            "Metadata": {"lat": "35.6", "lng": "139.7", "user": "alice"},
        }
        with caplog.at_level(
            logging.INFO, logger="echoroo.services.s3_upload_sanitizer"
        ):
            sanitize_put_object_kwargs(kwargs)

        matching = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "s3_metadata_gps_stripped"
        ]
        assert len(matching) == 1, (
            "Exactly one s3_metadata_gps_stripped event expected when GPS "
            f"keys are stripped, got {len(matching)}"
        )
        stripped = matching[0].keys  # type: ignore[attr-defined]
        assert set(stripped) == {"lat", "lng"}

    def test_no_log_event_when_metadata_clean(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        kwargs = {
            "Bucket": "b",
            "Key": "k",
            "Metadata": {"user": "alice", "description": "ok"},
        }
        with caplog.at_level(
            logging.INFO, logger="echoroo.services.s3_upload_sanitizer"
        ):
            sanitize_put_object_kwargs(kwargs)

        matching = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "s3_metadata_gps_stripped"
        ]
        assert matching == []

    def test_non_dict_metadata_is_left_alone(self) -> None:
        # If a caller passes a non-dict Metadata value, the sanitizer should
        # not raise; boto3 itself will reject the malformed argument.
        kwargs: dict[str, Any] = {
            "Bucket": "b",
            "Key": "k",
            "Metadata": ["lat", "lng"],  # malformed input
        }
        result = sanitize_put_object_kwargs(kwargs)
        assert result["Metadata"] == ["lat", "lng"]


# ---------------------------------------------------------------------------
# T129: WAV/FLAC/MP3 EXIF strip TDD scaffold (FR-028a)
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
# Wiring assertions: every production put_object call routes through the
# sanitizer (FR-028e defense in depth).
# ---------------------------------------------------------------------------


def test_audit_log_export_routes_put_object_through_sanitizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """audit_log_export._upload_with_object_lock must use sanitize_put_object_kwargs."""
    from echoroo.workers import audit_log_export

    captured_kwargs: dict[str, Any] = {}

    class _StubClient:
        def put_object(self, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(audit_log_export, "get_s3_client", lambda: _StubClient())

    sanitizer_called: list[dict[str, Any]] = []
    original = audit_log_export.__dict__.get("sanitize_put_object_kwargs")

    from echoroo.services import s3_upload_sanitizer as sanitizer_mod

    real_sanitizer = sanitizer_mod.sanitize_put_object_kwargs

    def _spy(kwargs: dict[str, Any]) -> dict[str, Any]:
        sanitizer_called.append(kwargs)
        return real_sanitizer(kwargs)

    monkeypatch.setattr(sanitizer_mod, "sanitize_put_object_kwargs", _spy)

    now = datetime(2026, 5, 7, tzinfo=UTC)
    audit_log_export._upload_with_object_lock(
        bucket="b", key="audit-log/x.ndjson", body=b"{}", now=now,
    )

    assert sanitizer_called, "sanitize_put_object_kwargs was not invoked"
    assert captured_kwargs["Bucket"] == "b"
    assert captured_kwargs["Key"] == "audit-log/x.ndjson"
    # Sanity: kwargs passed downstream do not carry GPS keys.
    assert "Metadata" not in captured_kwargs or all(
        not k.lower().startswith(("gps", "geo", "lat", "lon", "lng", "coord", "location"))
        for k in (captured_kwargs.get("Metadata") or {})
    )
    # Suppress unused-variable warnings for `original`.
    assert original is None or callable(original)


def test_worker_sanitize_uploaded_object_gps_invokes_head_strip_put(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker GPS sanitize helper must head_object, strip, then put_object."""
    from echoroo.workers import upload_tasks

    # Stub settings so we have a deterministic bucket name.
    class _Settings:
        S3_BUCKET = "echoroo-test"

    monkeypatch.setattr(upload_tasks, "get_settings", lambda: _Settings())

    raw_wav = _build_wav_with_fake_gps_chunk()
    local_file = tmp_path / "input.wav"
    local_file.write_bytes(raw_wav)

    head_calls: list[dict[str, Any]] = []
    put_calls: list[dict[str, Any]] = []

    class _StubS3:
        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            head_calls.append(kwargs)
            return {
                "Metadata": {"lat": "35.6", "user": "alice"},
                "ContentType": "audio/wav",
            }

        def put_object(self, **kwargs: Any) -> None:
            put_calls.append(kwargs)

    result = upload_tasks._sanitize_uploaded_object_gps(
        object_key="recordings/x/y/z.wav",
        local_path=str(local_file),
        s3_client=_StubS3(),
    )

    assert result is not None, "sanitize must rewrite when GPS chunk present"
    new_bytes, new_sha = result
    assert b"GPS " not in new_bytes
    # head_object called exactly once for this key.
    assert len(head_calls) == 1
    assert head_calls[0]["Bucket"] == "echoroo-test"
    assert head_calls[0]["Key"] == "recordings/x/y/z.wav"
    # put_object called with sanitized Metadata (no `lat` key).
    assert len(put_calls) == 1
    put_kwargs = put_calls[0]
    assert put_kwargs["Bucket"] == "echoroo-test"
    assert put_kwargs["Key"] == "recordings/x/y/z.wav"
    assert put_kwargs["Body"] == new_bytes
    assert "lat" not in put_kwargs.get("Metadata", {})
    # Non-GPS metadata preserved.
    assert put_kwargs["Metadata"].get("user") == "alice"
    # ContentType preserved.
    assert put_kwargs.get("ContentType") == "audio/wav"
    # SHA-256 matches the new bytes.
    import hashlib as _hash

    assert new_sha == _hash.sha256(new_bytes).hexdigest()


def test_worker_sanitize_returns_none_when_clean(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When neither audio bytes nor S3 metadata carry GPS, return None."""
    from echoroo.workers import upload_tasks

    class _Settings:
        S3_BUCKET = "echoroo-test"

    monkeypatch.setattr(upload_tasks, "get_settings", lambda: _Settings())

    # Clean WAV (no GPS chunk).
    fmt_chunk = b"fmt " + struct.pack("<I", 16) + b"\x01\x00" + b"\x01\x00"
    fmt_chunk += struct.pack("<I", 44100) + struct.pack("<I", 88200)
    fmt_chunk += b"\x02\x00" + b"\x10\x00"
    data_chunk = b"data" + struct.pack("<I", 0)
    body = b"WAVE" + fmt_chunk + data_chunk
    payload = b"RIFF" + struct.pack("<I", len(body)) + body
    local_file = tmp_path / "clean.wav"
    local_file.write_bytes(payload)

    put_calls: list[dict[str, Any]] = []

    class _StubS3:
        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            return {"Metadata": {"user": "alice"}, "ContentType": "audio/wav"}

        def put_object(self, **kwargs: Any) -> None:
            put_calls.append(kwargs)

    result = upload_tasks._sanitize_uploaded_object_gps(
        object_key="recordings/clean.wav",
        local_path=str(local_file),
        s3_client=_StubS3(),
    )
    assert result is None
    # Crucially, no put_object was issued (no rewrite needed).
    assert put_calls == []


def test_search_batch_routes_put_object_through_sanitizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """search/batch.py PutObject path must funnel through sanitize_put_object_kwargs.

    We exercise the import path directly by re-importing the module after
    monkey-patching the sanitizer. A real end-to-end trip would require a
    full request fixture; here we pin the call site by inspecting the
    module source for the import + call shape (regression guard).
    """
    import inspect

    from echoroo.api.v1.search import batch as batch_mod

    src = inspect.getsource(batch_mod)
    assert "sanitize_put_object_kwargs" in src, (
        "search/batch.py must import sanitize_put_object_kwargs"
    )
    # Ensure the helper is invoked before the put_object call (textually).
    helper_idx = src.find("sanitize_put_object_kwargs(")
    put_idx = src.find("s3_client.put_object(")
    assert helper_idx != -1 and put_idx != -1
    assert helper_idx < put_idx, (
        "sanitize_put_object_kwargs must be called before s3_client.put_object"
    )


# ---------------------------------------------------------------------------
# Round 2 (Codex review) — fail-closed + TOCTOU SHA-256 verification.
# ---------------------------------------------------------------------------


def test_worker_sanitize_fail_closed_on_head_object_error(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """head_object failure must raise so the caller marks the file INVALID.

    Round 1 returned ``None`` here, which let the file proceed to
    ``VALID`` without ever running the GPS strip. Round 2 fails closed.
    """
    from echoroo.workers import upload_tasks

    class _Settings:
        S3_BUCKET = "echoroo-test"

    monkeypatch.setattr(upload_tasks, "get_settings", lambda: _Settings())

    raw_wav = _build_wav_with_fake_gps_chunk()
    local_file = tmp_path / "input.wav"
    local_file.write_bytes(raw_wav)

    class _BrokenS3:
        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("S3 backend down")

        def put_object(self, **kwargs: Any) -> None:  # pragma: no cover
            raise AssertionError("put_object must not be called when head fails")

    with pytest.raises(RuntimeError, match="S3 backend down"):
        upload_tasks._sanitize_uploaded_object_gps(
            object_key="recordings/x/y/z.wav",
            local_path=str(local_file),
            s3_client=_BrokenS3(),
        )


def test_worker_sanitize_fail_closed_on_put_object_error(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """put_object failure must raise (Round 1 behaviour preserved)."""
    from echoroo.workers import upload_tasks

    class _Settings:
        S3_BUCKET = "echoroo-test"

    monkeypatch.setattr(upload_tasks, "get_settings", lambda: _Settings())

    raw_wav = _build_wav_with_fake_gps_chunk()
    local_file = tmp_path / "input.wav"
    local_file.write_bytes(raw_wav)

    class _PutBrokenS3:
        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            return {"Metadata": {"user": "alice"}, "ContentType": "audio/wav"}

        def put_object(self, **kwargs: Any) -> None:
            raise RuntimeError("S3 PUT capacity exhausted")

    with pytest.raises(RuntimeError, match="S3 PUT capacity"):
        upload_tasks._sanitize_uploaded_object_gps(
            object_key="recordings/x/y/z.wav",
            local_path=str(local_file),
            s3_client=_PutBrokenS3(),
        )


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


def test_verify_object_exists_sha256_match() -> None:
    """verify_object_exists must compare expected_sha256 against the body."""
    import hashlib as _hashlib

    from echoroo.core import s3 as s3_mod

    body = b"real-audio-bytes"
    digest = _hashlib.sha256(body).hexdigest()

    class _StubBody:
        def __init__(self, data: bytes) -> None:
            self._buf = io.BytesIO(data)

        def read(self, n: int = -1) -> bytes:
            return self._buf.read(n)

    class _StubClient:
        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            return {"ContentLength": len(body), "ETag": '"abc"'}

        def get_object(self, **kwargs: Any) -> dict[str, Any]:
            return {"Body": _StubBody(body)}

    result = s3_mod.verify_object_exists(
        "k", expected_size=len(body), client=_StubClient(),
        expected_sha256=digest,
    )
    assert result["exists"] is True
    assert result["size_match"] is True
    assert result["sha256_match"] is True
    assert result["actual_sha256"] == digest


def test_verify_object_exists_sha256_mismatch() -> None:
    """A swapped-body attack must surface as sha256_match=False."""
    import hashlib as _hashlib

    from echoroo.core import s3 as s3_mod

    persisted_digest = _hashlib.sha256(b"sanitized-bytes").hexdigest()
    swapped_body = b"unsanitized-bytes-with-gps"
    # Same length to defeat size_match: pad to len(b"sanitized-bytes").
    swapped_body = swapped_body[: len(b"sanitized-bytes")]

    class _StubBody:
        def __init__(self, data: bytes) -> None:
            self._buf = io.BytesIO(data)

        def read(self, n: int = -1) -> bytes:
            return self._buf.read(n)

    class _StubClient:
        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "ContentLength": len(swapped_body),
                "ETag": '"abc"',
            }

        def get_object(self, **kwargs: Any) -> dict[str, Any]:
            return {"Body": _StubBody(swapped_body)}

    result = s3_mod.verify_object_exists(
        "k",
        expected_size=len(swapped_body),
        client=_StubClient(),
        expected_sha256=persisted_digest,
    )
    # Size matches but body differs — exactly the TOCTOU scenario.
    assert result["exists"] is True
    assert result["size_match"] is True
    assert result["sha256_match"] is False
    assert result["actual_sha256"] is not None
    assert result["actual_sha256"] != persisted_digest


def test_verify_object_exists_no_expected_sha256_keeps_legacy_shape() -> None:
    """When no expected_sha256 is given, sha256_match stays None."""
    from echoroo.core import s3 as s3_mod

    class _StubClient:
        def head_object(self, **kwargs: Any) -> dict[str, Any]:
            return {"ContentLength": 10, "ETag": '"x"'}

    result = s3_mod.verify_object_exists(
        "k", expected_size=10, client=_StubClient(),
    )
    assert result["exists"] is True
    assert result["size_match"] is True
    assert result["sha256_match"] is None
    assert result["actual_sha256"] is None
