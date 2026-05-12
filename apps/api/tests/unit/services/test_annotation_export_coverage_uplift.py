"""Coverage uplift unit tests for ``echoroo.services.annotation_export``.

Phase 17 §C Batch 9a (35-50pp gap range): covers AnnotationExportService
so the module clears the 85% threshold.

Missing lines: 58-62,83,85-86,103,106-110,112-113,148,206-225,227-232,235,
              238,240,255,275,277,288,290-291
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.services.annotation_export import AnnotationExportService


def _make_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    return db


def _build_export_data(
    with_annotations: bool = False,
    with_bounding_box: bool = False,
    with_time_interval: bool = False,
) -> dict[str, Any]:
    """Build minimal export data for format tests."""
    clip_id = str(uuid4())
    clip_annotation_id = str(uuid4())
    task_id = str(uuid4())
    sea_id = str(uuid4())

    sound_events: list[dict[str, Any]] = []
    if with_bounding_box:
        sound_events.append({
            "id": sea_id,
            "geometry": {
                "type": "BoundingBox",
                "coordinates": [0.5, 2000.0, 1.5, 8000.0],
            },
            "source": "human",
            "confidence": 0.9,
            "tags": [{"name": "SYLATR", "category": "species"}],
            "created_at": "2026-01-01T00:00:00+00:00",
        })
    if with_time_interval:
        sound_events.append({
            "id": sea_id,
            "geometry": {
                "type": "TimeInterval",
                "coordinates": [0.2, 0.8],
            },
            "source": "human",
            "confidence": None,
            "tags": [],
            "created_at": None,
        })

    annotations: list[dict[str, Any]] = []
    if with_annotations:
        annotations.append({
            "clip_annotation_id": clip_annotation_id,
            "task_id": task_id,
            "clip": {
                "id": clip_id,
                "start_time": 0.0,
                "end_time": 3.0,
            },
            "review_status": "unreviewed",
            "tags": [],
            "sound_events": sound_events,
            "created_at": None,
        })

    return {
        "annotation_project": {
            "id": str(uuid4()),
            "name": "Test AP",
            "description": "desc",
            "instructions": None,
            "visibility": "private",
            "created_at": None,
        },
        "annotations": annotations,
    }


@pytest.mark.asyncio
async def test_export_annotations_raises_422_for_invalid_format() -> None:
    """export_annotations raises 422 for unsupported format (lines 58-62)."""
    db = _make_db()
    service = AnnotationExportService(db)

    with pytest.raises(HTTPException) as exc_info:
        await service.export_annotations(uuid4(), format="xlsx")

    assert exc_info.value.status_code == 422
    assert "Unsupported export format" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_export_annotations_raises_404_when_project_not_found() -> None:
    """export_annotations raises 404 when annotation project not found (lines 83,85-86)."""
    db = _make_db()

    no_ap_result = MagicMock()
    no_ap_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=no_ap_result)

    service = AnnotationExportService(db)

    with pytest.raises(HTTPException) as exc_info:
        await service.export_annotations(uuid4(), format="json")

    assert exc_info.value.status_code == 404


def test_format_json_returns_data_unchanged() -> None:
    """_format_json returns data dict as-is (lines 148)."""
    service = AnnotationExportService(MagicMock())
    data = _build_export_data()
    result = service._format_json(data)
    assert result is data


def test_format_csv_empty_no_sound_events() -> None:
    """_format_csv returns header-only CSV when no sound events (lines 206-240)."""
    service = AnnotationExportService(MagicMock())
    data = _build_export_data(with_annotations=True, with_bounding_box=False)
    # annotation has no sound events
    data["annotations"][0]["sound_events"] = []

    result = service._format_csv(data)

    assert isinstance(result, str)
    # Should have at least the header row
    assert "Selection" in result


def test_format_csv_with_bounding_box_geometry() -> None:
    """_format_csv writes BoundingBox geometry columns (lines 217-225)."""
    service = AnnotationExportService(MagicMock())
    data = _build_export_data(with_annotations=True, with_bounding_box=True)

    result = service._format_csv(data)

    assert isinstance(result, str)
    lines = result.strip().split("\n")
    assert len(lines) == 2  # header + 1 sound event row
    assert "SYLATR" in result


def test_format_csv_with_time_interval_geometry() -> None:
    """_format_csv handles TimeInterval geometry (lines 227-229)."""
    service = AnnotationExportService(MagicMock())
    data = _build_export_data(with_annotations=True, with_time_interval=True)

    result = service._format_csv(data)

    assert isinstance(result, str)
    lines = result.strip().split("\n")
    assert len(lines) == 2  # header + 1 sound event row


def test_format_csv_with_unknown_geometry() -> None:
    """_format_csv handles unknown geometry type with fallback (lines 230-232)."""
    service = AnnotationExportService(MagicMock())
    data = _build_export_data(with_annotations=True)
    # Add a sound event with unknown geometry
    data["annotations"][0]["sound_events"] = [{
        "id": str(uuid4()),
        "geometry": {"type": "Polygon", "coordinates": []},
        "source": "human",
        "confidence": None,
        "tags": [],
        "created_at": None,
    }]

    result = service._format_csv(data)

    assert isinstance(result, str)


def test_format_aoef_returns_structured_output() -> None:
    """_format_aoef returns AOEF-structured dict (lines 255-291)."""
    service = AnnotationExportService(MagicMock())
    data = _build_export_data(with_annotations=True, with_bounding_box=True)

    result = service._format_aoef(data)

    assert "info" in result
    assert result["info"]["format"] == "aoef"
    assert "clip_annotations" in result
    assert "sound_event_annotations" in result
    assert len(result["clip_annotations"]) == 1
    assert len(result["sound_event_annotations"]) == 1


def test_format_aoef_empty_annotations() -> None:
    """_format_aoef handles empty annotations list (lines 255-260)."""
    service = AnnotationExportService(MagicMock())
    data = _build_export_data(with_annotations=False)

    result = service._format_aoef(data)

    assert result["clip_annotations"] == []
    assert result["sound_event_annotations"] == []


@pytest.mark.asyncio
async def test_export_annotations_json_format() -> None:
    """export_annotations returns JSON dict for json format (lines 103,106-107)."""
    ap = MagicMock()
    ap.id = uuid4()
    ap.name = "AP"
    ap.description = ""
    ap.instructions = None
    ap.visibility = MagicMock(value="private")
    ap.created_at = None

    ap_result = MagicMock()
    ap_result.scalar_one_or_none.return_value = ap

    tasks_result = MagicMock()
    tasks_result.scalars.return_value.all.return_value = []

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[ap_result, tasks_result])

    service = AnnotationExportService(db)

    result = await service.export_annotations(uuid4(), format="json")

    assert isinstance(result, dict)
    assert "annotation_project" in result


@pytest.mark.asyncio
async def test_export_annotations_csv_format() -> None:
    """export_annotations returns CSV string for csv format (lines 108-109)."""
    ap = MagicMock()
    ap.id = uuid4()
    ap.name = "AP"
    ap.description = ""
    ap.instructions = None
    ap.visibility = MagicMock(value="private")
    ap.created_at = None

    ap_result = MagicMock()
    ap_result.scalar_one_or_none.return_value = ap

    tasks_result = MagicMock()
    tasks_result.scalars.return_value.all.return_value = []

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[ap_result, tasks_result])

    service = AnnotationExportService(db)

    result = await service.export_annotations(uuid4(), format="csv")

    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_export_annotations_aoef_format() -> None:
    """export_annotations returns AOEF dict for aoef format (lines 112-113)."""
    ap = MagicMock()
    ap.id = uuid4()
    ap.name = "AP"
    ap.description = ""
    ap.instructions = None
    ap.visibility = MagicMock(value="private")
    ap.created_at = None

    ap_result = MagicMock()
    ap_result.scalar_one_or_none.return_value = ap

    tasks_result = MagicMock()
    tasks_result.scalars.return_value.all.return_value = []

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[ap_result, tasks_result])

    service = AnnotationExportService(db)

    result = await service.export_annotations(uuid4(), format="aoef")

    assert isinstance(result, dict)
    assert "info" in result
