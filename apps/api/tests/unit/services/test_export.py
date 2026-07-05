"""Unit tests for ExportService.export_dataset_zip failure manifest (SFR-4).

A recording whose audio cannot be localised must NOT vanish from the ZIP with
no trace. The archive is still produced (the export does not abort), but an
``export_manifest.json`` entry names the skipped recording and the reason, and
each failure is logged.

External I/O is faked; no real audio files, DB, or S3 are touched.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.services.export import ExportService


def _make_recording(path: str) -> MagicMock:
    rec = MagicMock()
    rec.id = uuid4()
    rec.path = path
    return rec


async def _collect(gen: Any) -> bytes:
    buf = bytearray()
    async for chunk in gen:
        buf.extend(chunk)
    return bytes(buf)


@pytest.mark.asyncio
async def test_export_manifest_records_skipped_recording(
    tmp_path: Path,
) -> None:
    """When one recording fails to localise, the ZIP builds and names it."""
    good = _make_recording("recordings/good.wav")
    bad = _make_recording("recordings/bad.wav")

    # A real on-disk file for the good recording so zf.write succeeds.
    good_file = tmp_path / "good.wav"
    good_file.write_bytes(b"RIFFfake-wav-bytes")

    def _ensure_file_local(path: str) -> str:
        if path == "recordings/bad.wav":
            raise FileNotFoundError("object missing in S3")
        return str(good_file)

    audio_service = MagicMock()
    audio_service.ensure_file_local = MagicMock(side_effect=_ensure_file_local)

    service = ExportService(db=MagicMock(), audio_service=audio_service)

    # Stub metadata generators + repos so only the audio loop matters.
    service.dataset_repo.get_by_id = AsyncMock(return_value=MagicMock())
    service.generate_datapackage_json = AsyncMock(return_value="{}")  # type: ignore[method-assign]
    service.generate_deployments_csv = AsyncMock(return_value="deployments")  # type: ignore[method-assign]
    service.generate_media_csv = AsyncMock(return_value="media")  # type: ignore[method-assign]
    service.recording_repo.list_by_dataset = AsyncMock(
        return_value=([good, bad], 2)
    )

    zip_bytes = await _collect(
        service.export_dataset_zip(uuid4(), include_audio=True)
    )

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        # The archive was still produced with the good recording's audio.
        assert "export_manifest.json" in names
        assert "data/recordings/good.wav" in names
        assert "data/recordings/bad.wav" not in names

        manifest = json.loads(zf.read("export_manifest.json"))

    assert manifest["included_count"] == 1
    assert len(manifest["skipped"]) == 1
    skipped = manifest["skipped"][0]
    assert skipped["recording_id"] == str(bad.id)
    assert skipped["path"] == "recordings/bad.wav"
    assert "FileNotFoundError" in skipped["reason"]


@pytest.mark.asyncio
async def test_export_manifest_empty_when_all_succeed(
    tmp_path: Path,
) -> None:
    """No failures -> manifest present with an empty skipped list."""
    good = _make_recording("recordings/good.wav")
    good_file = tmp_path / "good.wav"
    good_file.write_bytes(b"RIFFfake-wav-bytes")

    audio_service = MagicMock()
    audio_service.ensure_file_local = MagicMock(return_value=str(good_file))

    service = ExportService(db=MagicMock(), audio_service=audio_service)
    service.dataset_repo.get_by_id = AsyncMock(return_value=MagicMock())
    service.generate_datapackage_json = AsyncMock(return_value="{}")  # type: ignore[method-assign]
    service.generate_deployments_csv = AsyncMock(return_value="deployments")  # type: ignore[method-assign]
    service.generate_media_csv = AsyncMock(return_value="media")  # type: ignore[method-assign]
    service.recording_repo.list_by_dataset = AsyncMock(return_value=([good], 1))

    zip_bytes = await _collect(
        service.export_dataset_zip(uuid4(), include_audio=True)
    )

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        manifest = json.loads(zf.read("export_manifest.json"))

    assert manifest["included_count"] == 1
    assert manifest["skipped"] == []
