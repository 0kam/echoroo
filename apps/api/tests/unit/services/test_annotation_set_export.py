"""Unit tests for ``echoroo.services.annotation_set_export``.

Verifies the CamtrapDP + ToriTore CSV export shape without requiring a live
database: the export service's SQL is stubbed to return in-memory model
instances with relationships pre-wired, and the streamed bytes are decoded and
parsed back through :mod:`csv` to assert:

* the header row equals the detection export's CamtrapDP/FR-086 columns plus
  the three trailing ToriTore proficiency columns, in order; and
* there is exactly one data row per ``TimeRangeAnnotation`` with the
  ToriTore ``annotator_total_score`` populated for a gated annotation, plus a
  resolved ``scientificName`` and ``classifiedBy``.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.services.annotation_set_export import (
    _ANNOTATION_SET_COLUMNS,
    _TORITORE_COLUMNS,
    AnnotationSetExportService,
)
from echoroo.services.detection_export import _CAMTRAPDP_COLUMNS


def _make_annotation(
    *,
    dataset_name: str,
    scientific_name: str,
    annotator_name: str,
    total_score: float | None,
    species_score: float | None,
    test_reference: str | None,
    start_offset: float,
    end_offset: float,
) -> SimpleNamespace:
    """Build an in-memory TimeRangeAnnotation-like object with relationships."""
    recording = SimpleNamespace(
        id=uuid4(),
        datetime=datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC),
        dataset=SimpleNamespace(name=dataset_name),
    )
    segment = SimpleNamespace(
        recording_id=recording.id,
        start_time_sec=10.0,
        recording=recording,
    )
    return SimpleNamespace(
        id=uuid4(),
        segment=segment,
        start_time_sec=start_offset,
        end_time_sec=end_offset,
        confidence=0.75,
        created_at=datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC),
        taxon=SimpleNamespace(scientific_name=scientific_name),
        created_by=SimpleNamespace(display_name=annotator_name, email="x@y.z"),
        annotator_species_score=species_score,
        annotator_total_score=total_score,
        annotator_test_reference=test_reference,
    )


async def _collect(service: AnnotationSetExportService, **kwargs: object) -> str:
    chunks: list[bytes] = []
    async for chunk in service.export_csv_stream(**kwargs):  # type: ignore[arg-type]
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


@pytest.mark.asyncio
async def test_export_columns_and_one_row_per_annotation() -> None:
    """Header = CamtrapDP + ToriTore cols; one row per annotation; score set."""
    set_id = uuid4()
    project_id = uuid4()

    annotations = [
        _make_annotation(
            dataset_name="Forest A",
            scientific_name="Turdus merula",
            annotator_name="Alice",
            total_score=0.91,
            species_score=0.8,
            test_reference="test#1@20260604142325+9:00",
            start_offset=1.0,
            end_offset=3.5,
        ),
        _make_annotation(
            dataset_name="Forest A",
            scientific_name="Parus major",
            annotator_name="Bob",
            total_score=0.42,
            species_score=None,
            test_reference=None,
            start_offset=4.0,
            end_offset=6.0,
        ),
    ]

    anno_set = SimpleNamespace(id=set_id, project_id=project_id)
    project = SimpleNamespace(license="CC-BY-4.0")

    db = MagicMock()

    # ``_require_set`` query → set row.
    set_result = MagicMock()
    set_result.scalar_one_or_none.return_value = anno_set
    # ``_fetch_annotations`` query → annotation rows.
    ann_result = MagicMock()
    ann_result.scalars.return_value.all.return_value = annotations
    # ``_build_recording_h3_resolution_map`` query → no sites (default res).
    h3_result = MagicMock()
    h3_result.all.return_value = []

    db.execute = AsyncMock(side_effect=[set_result, ann_result, h3_result])

    service = AnnotationSetExportService(db)
    # ``_load_project`` is reused from DetectionExportService; stub it so we do
    # not need a fourth DB round-trip wired into the side_effect list.
    service._detection._load_project = AsyncMock(return_value=project)  # type: ignore[method-assign]

    body = await _collect(service, project_id=project_id, set_id=set_id)

    reader = csv.DictReader(io.StringIO(body))
    assert reader.fieldnames is not None
    assert reader.fieldnames == _ANNOTATION_SET_COLUMNS
    # Sanity: detection CamtrapDP cols precede the ToriTore cols.
    assert list(reader.fieldnames[: len(_CAMTRAPDP_COLUMNS)]) == _CAMTRAPDP_COLUMNS
    assert list(reader.fieldnames[-len(_TORITORE_COLUMNS) :]) == _TORITORE_COLUMNS

    rows = list(reader)
    assert len(rows) == len(annotations)

    first = rows[0]
    assert first["scientificName"] == "Turdus merula"
    assert first["classifiedBy"] == "Alice"
    assert first["classificationMethod"] == "human"
    assert first["deploymentID"] == "Forest A"
    assert first["count"] == "1"
    assert first["license"] == "CC-BY-4.0"
    # ToriTore proficiency snapshot populated for the gated annotation.
    assert first["annotator_total_score"] == "0.9100"
    assert first["annotator_species_score"] == "0.8000"
    assert first["annotator_test_reference"] == "test#1@20260604142325+9:00"
    # Event datetime = recording start + segment offset (10s) + annotation
    # offset (1s) = 00:00:11 on 2026-06-01. Sub-second precision is preserved
    # (millisecond fraction), so a whole-second offset renders ``.000``.
    assert first["eventStart"] == "2026-06-01T00:00:11.000Z"

    second = rows[1]
    assert second["annotator_total_score"] == "0.4200"
    # Null ToriTore species/test reference render as blank.
    assert second["annotator_species_score"] == ""
    assert second["annotator_test_reference"] == ""


@pytest.mark.asyncio
async def test_export_event_times_preserve_subsecond_precision() -> None:
    """eventStart/eventEnd keep the fractional offset (not whole-second rounded).

    Many audio annotations are shorter than one second or begin/end at
    fractional-second offsets. With segment.start_time_sec=10.0 and annotation
    offsets start=2.45 / end=2.75, the absolute times are 00:00:12.450 and
    00:00:12.750 on 2026-06-01 — the millisecond fraction must survive.
    """
    set_id = uuid4()
    project_id = uuid4()

    annotations = [
        _make_annotation(
            dataset_name="Forest A",
            scientific_name="Turdus merula",
            annotator_name="Alice",
            total_score=0.91,
            species_score=0.8,
            test_reference=None,
            start_offset=2.45,
            end_offset=2.75,
        ),
    ]

    anno_set = SimpleNamespace(id=set_id, project_id=project_id)
    project = SimpleNamespace(license="CC-BY-4.0")

    db = MagicMock()
    set_result = MagicMock()
    set_result.scalar_one_or_none.return_value = anno_set
    ann_result = MagicMock()
    ann_result.scalars.return_value.all.return_value = annotations
    h3_result = MagicMock()
    h3_result.all.return_value = []
    db.execute = AsyncMock(side_effect=[set_result, ann_result, h3_result])

    service = AnnotationSetExportService(db)
    service._detection._load_project = AsyncMock(return_value=project)  # type: ignore[method-assign]

    body = await _collect(service, project_id=project_id, set_id=set_id)

    reader = csv.DictReader(io.StringIO(body))
    # Header shape (incl. ToriTore cols) must remain intact.
    assert reader.fieldnames == _ANNOTATION_SET_COLUMNS
    rows = list(reader)
    assert len(rows) == 1

    event_start = rows[0]["eventStart"]
    event_end = rows[0]["eventEnd"]
    # The sub-second fraction must be present (NOT truncated to whole seconds).
    assert event_start == "2026-06-01T00:00:12.450Z"
    assert event_end == "2026-06-01T00:00:12.750Z"
    # Defensive: a whole-second-only renderer would have produced these.
    assert event_start != "2026-06-01T00:00:12Z"
    assert event_end != "2026-06-01T00:00:12Z"


@pytest.mark.asyncio
async def test_export_missing_set_raises_before_streaming() -> None:
    """A missing set raises ValueError before the first chunk is yielded."""
    db = MagicMock()
    missing = MagicMock()
    missing.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=missing)

    service = AnnotationSetExportService(db)
    gen = service.export_csv_stream(project_id=uuid4(), set_id=uuid4())
    with pytest.raises(ValueError, match="Annotation set not found"):
        await gen.__anext__()
