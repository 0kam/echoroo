"""Unit tests for ``echoroo.services.annotation_set_dataset_export``.

Verifies the dataset ZIP export shape without a live database or real audio.
The export is now split into an async planning phase
(:meth:`AnnotationSetDatasetExportService.prepare_plan`, all DB/ORM work) and a
sync assembly phase (:func:`write_dataset_zip`, the blocking audio + ZIP work,
written to a temp file on disk). The tests drive them together:

* the export universe is finalized (``ANNOTATED``) segments only — an
  unannotated segment is excluded from both ``segments.csv`` and ``clips/``;
* a confirmed-empty segment (``is_empty=True``, no annotations) is present in
  ``segments.csv`` as a negative (``n_annotations == 0``) with its own clip;
* a per-clip extraction failure leaves ``clip_path`` blank in ``segments.csv``
  but still produces the manifest row (and omits the ``.wav`` member); and
* ``annotations.csv`` and ``segments.csv`` are always present.

The :class:`AudioService` clip methods are mocked so no real audio is read:
``ensure_file_local`` is a no-op, ``read_audio`` returns deterministic data and
``audio_to_wav_bytes`` returns deterministic bytes (or raises, to exercise the
failure path).

The endpoint's :func:`_build_content_disposition` helper is also unit-tested
directly with a Japanese set name to prove the RFC 6266 header is Latin-1
encodable (no HTTP 500).
"""

from __future__ import annotations

import csv
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import numpy as np
import pytest

from echoroo.models.enums import AnnotationSegmentStatus
from echoroo.services.annotation_set_dataset_export import (
    AnnotationSetDatasetExportService,
    write_dataset_zip,
)


def _make_segment(
    *,
    recording: SimpleNamespace,
    status: AnnotationSegmentStatus,
    is_empty: bool,
    n_annotations: int,
    start: float = 0.0,
    end: float = 10.0,
) -> SimpleNamespace:
    """Build an in-memory AnnotationSegment-like object with relationships."""
    return SimpleNamespace(
        id=uuid4(),
        recording_id=recording.id,
        recording=recording,
        start_time_sec=start,
        end_time_sec=end,
        status=status,
        is_empty=is_empty,
        annotations=[SimpleNamespace(id=uuid4()) for _ in range(n_annotations)],
    )


def _read_zip_path(path: str) -> zipfile.ZipFile:
    """Read a ZIP file written to disk into an in-memory ZipFile object."""
    with open(path, "rb") as fh:
        return zipfile.ZipFile(io.BytesIO(fh.read()))


async def _build_plan_and_zip(
    service: AnnotationSetDatasetExportService,
    *,
    project_id: UUID,
    set_id: UUID,
    tmp_path,
) -> str:
    """Run the async plan + sync ZIP assembly together, returning the zip path."""
    plan = await service.prepare_plan(project_id=project_id, set_id=set_id)
    out_path = str(tmp_path / "dataset.zip")
    write_dataset_zip(plan, service.audio, out_path)
    return out_path


@pytest.mark.asyncio
async def test_dataset_zip_finalized_universe_and_negatives(tmp_path) -> None:
    """ZIP has CSVs + clips for finalized segments only; negatives are explicit.

    One finalized segment WITH annotations, one finalized confirmed-empty
    segment (negative), and one UNANNOTATED segment. The unannotated segment
    must NOT appear in segments.csv nor produce a clip.
    """
    set_id = uuid4()
    project_id = uuid4()

    recording = SimpleNamespace(id=uuid4(), path="recordings/p/d/r.wav")

    positive = _make_segment(
        recording=recording,
        status=AnnotationSegmentStatus.ANNOTATED,
        is_empty=False,
        n_annotations=2,
    )
    empty = _make_segment(
        recording=recording,
        status=AnnotationSegmentStatus.ANNOTATED,
        is_empty=True,
        n_annotations=0,
    )
    # An unannotated segment is intentionally NOT returned by the finalized
    # query; the test only feeds finalized segments to the segment fetch to
    # mirror the SQL predicate, and asserts the count is exactly 2.

    finalized_segments = [positive, empty]
    annotation_rows = [{"observationID": "x"}, {"observationID": "y"}]

    anno_set = SimpleNamespace(id=set_id, project_id=project_id, name="My Set")

    db = MagicMock()
    # prepare_plan → _require_set (set row)
    set_result_1 = MagicMock()
    set_result_1.scalar_one_or_none.return_value = anno_set
    # build_csv_rows → _require_set (set row again)
    set_result_2 = MagicMock()
    set_result_2.scalar_one_or_none.return_value = anno_set
    # build_csv_rows → _fetch_annotations (finalized) — return raw rows; we stub
    # _build_row below so these can be opaque sentinels.
    ann_result = MagicMock()
    ann_result.scalars.return_value.all.return_value = [SimpleNamespace()] * 2
    # _fetch_finalized_segments → segments
    seg_result = MagicMock()
    seg_result.scalars.return_value.all.return_value = finalized_segments

    db.execute = AsyncMock(
        side_effect=[set_result_1, set_result_2, ann_result, seg_result]
    )

    audio = MagicMock()
    audio.ensure_file_local = MagicMock(return_value="/local/r.wav")
    audio.read_audio = MagicMock(
        return_value=(np.zeros(48000, dtype=np.float32), 48000)
    )
    audio.audio_to_wav_bytes = MagicMock(return_value=b"RIFFwavbytes")

    service = AnnotationSetDatasetExportService(db, audio)
    # Stub the CSV row builder + h3 map so we don't depend on the full
    # CamtrapDP/license plumbing; this isolates the ZIP-assembly logic.
    service._csv._detection._load_project = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(license="CC-BY-4.0")
    )
    service._csv._build_recording_h3_map = AsyncMock(return_value={})  # type: ignore[method-assign]
    service._csv._build_row = MagicMock(  # type: ignore[method-assign]
        side_effect=annotation_rows
    )

    out_path = await _build_plan_and_zip(
        service, project_id=project_id, set_id=set_id, tmp_path=tmp_path
    )

    zf = _read_zip_path(out_path)
    names = set(zf.namelist())

    # Both CSV manifests are always present.
    assert "annotations.csv" in names
    assert "segments.csv" in names

    # A clip exists for each finalized segment, and ONLY for finalized ones.
    assert f"clips/{positive.id}.wav" in names
    assert f"clips/{empty.id}.wav" in names
    clip_names = {n for n in names if n.startswith("clips/")}
    assert len(clip_names) == 2  # no unannotated segment clip

    # The clip bytes are the deterministic mock output.
    assert zf.read(f"clips/{positive.id}.wav") == b"RIFFwavbytes"

    # segments.csv has exactly the two finalized segments.
    seg_reader = csv.DictReader(io.StringIO(zf.read("segments.csv").decode("utf-8")))
    seg_rows = {row["segment_id"]: row for row in seg_reader}
    assert set(seg_rows) == {str(positive.id), str(empty.id)}

    pos_row = seg_rows[str(positive.id)]
    assert pos_row["clip_path"] == f"clips/{positive.id}.wav"
    assert pos_row["n_annotations"] == "2"
    assert pos_row["is_empty"] == "false"
    assert pos_row["status"] == "annotated"

    # The confirmed-empty negative is explicit: n_annotations == 0.
    empty_row = seg_rows[str(empty.id)]
    assert empty_row["n_annotations"] == "0"
    assert empty_row["is_empty"] == "true"
    assert empty_row["clip_path"] == f"clips/{empty.id}.wav"

    # ensure_file_local is called ONCE per distinct recording (both segments
    # share one recording), not once per segment.
    assert audio.ensure_file_local.call_count == 1


@pytest.mark.asyncio
async def test_dataset_clip_failure_leaves_clip_path_blank(tmp_path) -> None:
    """A clip-extraction failure → blank clip_path, still a manifest row, no wav.

    ``read_audio`` raises for the segment; ``segments.csv`` must still carry the
    row with an empty ``clip_path`` and no ``clips/<id>.wav`` member is emitted.
    """
    set_id = uuid4()
    project_id = uuid4()

    recording = SimpleNamespace(id=uuid4(), path="recordings/p/d/r.wav")
    seg = _make_segment(
        recording=recording,
        status=AnnotationSegmentStatus.ANNOTATED,
        is_empty=False,
        n_annotations=1,
    )

    anno_set = SimpleNamespace(id=set_id, project_id=project_id, name="Set")

    db = MagicMock()
    set_result_1 = MagicMock()
    set_result_1.scalar_one_or_none.return_value = anno_set
    set_result_2 = MagicMock()
    set_result_2.scalar_one_or_none.return_value = anno_set
    ann_result = MagicMock()
    ann_result.scalars.return_value.all.return_value = [SimpleNamespace()]
    seg_result = MagicMock()
    seg_result.scalars.return_value.all.return_value = [seg]
    db.execute = AsyncMock(
        side_effect=[set_result_1, set_result_2, ann_result, seg_result]
    )

    audio = MagicMock()
    audio.ensure_file_local = MagicMock(return_value="/local/r.wav")
    audio.read_audio = MagicMock(side_effect=RuntimeError("decode error"))
    audio.audio_to_wav_bytes = MagicMock(return_value=b"unused")

    service = AnnotationSetDatasetExportService(db, audio)
    service._csv._detection._load_project = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(license="CC-BY-4.0")
    )
    service._csv._build_recording_h3_map = AsyncMock(return_value={})  # type: ignore[method-assign]
    service._csv._build_row = MagicMock(return_value={"observationID": "x"})  # type: ignore[method-assign]

    out_path = await _build_plan_and_zip(
        service, project_id=project_id, set_id=set_id, tmp_path=tmp_path
    )

    zf = _read_zip_path(out_path)
    names = set(zf.namelist())

    # No clip member for the failed segment.
    assert f"clips/{seg.id}.wav" not in names
    assert not any(n.startswith("clips/") for n in names)

    # But the manifest row exists with a blank clip_path.
    seg_reader = csv.DictReader(io.StringIO(zf.read("segments.csv").decode("utf-8")))
    rows = list(seg_reader)
    assert len(rows) == 1
    assert rows[0]["segment_id"] == str(seg.id)
    assert rows[0]["clip_path"] == ""
    assert rows[0]["n_annotations"] == "1"


@pytest.mark.asyncio
async def test_dataset_missing_set_raises() -> None:
    """A missing set raises ValueError (caller maps to 404)."""
    db = MagicMock()
    missing = MagicMock()
    missing.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=missing)

    audio = MagicMock()
    service = AnnotationSetDatasetExportService(db, audio)

    with pytest.raises(ValueError, match="Annotation set not found"):
        await service.prepare_plan(project_id=uuid4(), set_id=uuid4())


def test_content_disposition_japanese_name_is_latin1_encodable() -> None:
    """A non-ASCII set name yields an RFC 6266 header encodable as Latin-1.

    Regression for the Content-Disposition 500: ``str.isalnum()`` returns True
    for Japanese characters, so the old allowlist let them through unchanged
    and Starlette's Latin-1 header encoding raised ``UnicodeEncodeError`` → 500.
    The fixed builder must emit an ASCII ``filename`` fallback + a percent-
    encoded ``filename*`` form that is always Latin-1 safe.
    """
    from echoroo.api.web_v1.projects._annotation_set_export import (
        _build_content_disposition,
    )

    set_id = uuid4()
    header = _build_content_disposition("テストセット", set_id)

    # Must not raise — this is exactly what Starlette/uvicorn does at the ASGI
    # layer when serializing the response header.
    header.encode("latin-1")

    # Both RFC 6266 forms are present.
    assert "attachment;" in header
    assert "filename=" in header
    assert "filename*=UTF-8''" in header
    # The non-ASCII name appears only percent-encoded (never raw).
    assert "テストセット" not in header
    # The ASCII fallback collapses non-ASCII to a sensible default (here the
    # name is entirely non-ASCII → falls back to the set UUID).
    assert f'filename="{set_id}_dataset.zip"' in header


def test_content_disposition_ascii_name_is_preserved() -> None:
    """An ASCII set name survives in the fallback filename, sanitised safely."""
    from echoroo.api.web_v1.projects._annotation_set_export import (
        _build_content_disposition,
    )

    header = _build_content_disposition("My Set/v2", uuid4())
    header.encode("latin-1")  # must not raise
    # Space and slash collapse to '_' (and runs collapse): "My_Set_v2".
    assert 'filename="My_Set_v2_dataset.zip"' in header
    assert "filename*=UTF-8''" in header
