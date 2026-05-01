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


@pytest.mark.xfail(
    reason=(
        "EXIF strip integration deferred to upload pipeline rewrite "
        "(FR-028a). T128 covers S3 metadata strip only; this scaffold "
        "ensures the test contract exists when the upload sanitizer lands."
    ),
    strict=False,
)
def test_wav_upload_strips_gps_chunk_before_persistence() -> None:
    """The upload pipeline must remove GPS-bearing chunks pre-persistence."""
    raw = _build_wav_with_fake_gps_chunk()
    assert b"GPS " in raw, "fixture must seed a GPS chunk for the strip test"

    # The upload pipeline EXIF stripper is delivered by a separate Phase 3
    # task. Once available, the call below should be replaced with the
    # production import; for now we deliberately fail the xfail by importing
    # an attribute that does not exist yet.
    from echoroo.services import upload as upload_service  # noqa: F401

    strip_fn = getattr(upload_service, "strip_audio_gps_metadata", None)
    assert strip_fn is not None, (
        "strip_audio_gps_metadata not yet implemented "
        "(FR-028a Phase 3 follow-up)"
    )

    cleaned = strip_fn(io.BytesIO(raw)).read()
    assert b"GPS " not in cleaned, "GPS chunk must be stripped before save"
