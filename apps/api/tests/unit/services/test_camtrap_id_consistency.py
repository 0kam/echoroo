"""Cross-export CamtrapDP identifier consistency guard (anti-drift).

The canonical CamtrapDP identifier scheme (approved 2026-06-09) lives in
:mod:`echoroo.services.camtrap`:

* ``deploymentID``  == ``str(dataset.id)`` — EVERYWHERE.
* ``mediaID``       == ``str(recording.id)`` — EVERYWHERE (including the
  segment-centric annotation-set export).
* ``observationID`` == ``str(annotation.id)``.
* ``eventID``       == ``""`` (empty).

This module is the guard that keeps all four export surfaces wired to that
single source of truth. It drives the row builders directly (no DB) via
``service.__new__`` + minimal :class:`~types.SimpleNamespace` stubs, mirroring
the existing in-memory export test style, and asserts that the join keys the
``deployments.csv`` / ``media.csv`` writers would emit are byte-identical to the
keys the observation rows emit. If a future change re-routes any surface around
``echoroo.services.camtrap``, one of these assertions fails.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from echoroo.models.annotation_set import TimeRangeAnnotation
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.services import camtrap
from echoroo.services.annotation_set_export import AnnotationSetExportService
from echoroo.services.detection_export import DetectionExportService

# ---------------------------------------------------------------------------
# 1. The neutral identifier functions themselves.
# ---------------------------------------------------------------------------


def test_identifier_functions_match_canonical_scheme() -> None:
    """deployment_id / media_id / observation_id stringify the UUID; event_id == ''."""
    dataset_uuid = uuid4()
    recording_uuid = uuid4()
    annotation_uuid = uuid4()

    assert camtrap.deployment_id(dataset_uuid) == str(dataset_uuid)
    assert camtrap.media_id(recording_uuid) == str(recording_uuid)
    assert camtrap.observation_id(annotation_uuid) == str(annotation_uuid)
    assert camtrap.event_id() == ""


# ---------------------------------------------------------------------------
# 2. Detection export row builder routes through the canonical functions.
# ---------------------------------------------------------------------------


def _make_detection_annotation() -> SimpleNamespace:
    """Minimal detection-shaped annotation for ``_build_csv_row`` (no DB)."""
    dataset = SimpleNamespace(id=uuid4(), name="A Human-Readable Dataset Name")
    recording = SimpleNamespace(
        id=uuid4(),
        dataset=dataset,
        datetime=datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC),
    )
    return SimpleNamespace(
        id=uuid4(),
        recording=recording,
        recording_id=recording.id,
        start_time=1.0,
        end_time=2.0,
        source=None,  # not in machine_sources → "human" path
        detection_run=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=datetime(2026, 6, 2, 0, 0, 0, tzinfo=UTC),
        tag=SimpleNamespace(name="Turdus merula"),
        freq_low=None,
        freq_high=None,
        confidence=None,
    )


def test_detection_row_uses_canonical_ids() -> None:
    """deploymentID == dataset UUID (NOT name), mediaID == recording UUID, eventID == ''."""
    service = DetectionExportService.__new__(DetectionExportService)
    ann = _make_detection_annotation()

    row = service._build_csv_row(
        cast(RecordingAnnotation, ann),
        project=None,
        license_value="",
        license_history_url="",
        recording_h3_map={},
    )

    dataset = ann.recording.dataset
    assert row["deploymentID"] == str(dataset.id)
    # The dataset's human-readable name must NOT leak into deploymentID.
    assert row["deploymentID"] != dataset.name
    assert row["mediaID"] == str(ann.recording.id)
    assert row["observationID"] == str(ann.id)
    assert row["eventID"] == ""


# ---------------------------------------------------------------------------
# 3. Annotation-set export row builder routes through the canonical functions.
# ---------------------------------------------------------------------------


def _make_annotation_set_annotation() -> SimpleNamespace:
    """Minimal annotation-set-shaped annotation for ``_build_row`` (no DB)."""
    dataset = SimpleNamespace(id=uuid4(), name="Another Dataset Name")
    recording = SimpleNamespace(
        id=uuid4(),
        dataset=dataset,
        datetime=datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC),
    )
    segment = SimpleNamespace(
        id=uuid4(),
        recording_id=recording.id,
        start_time_sec=10.0,
        recording=recording,
    )
    return SimpleNamespace(
        id=uuid4(),
        segment=segment,
        start_time_sec=1.0,
        end_time_sec=2.0,
        confidence=None,
        created_at=datetime(2026, 6, 2, 0, 0, 0, tzinfo=UTC),
        taxon=SimpleNamespace(scientific_name="Parus major"),
        created_by=None,
    )


def test_annotation_set_row_uses_canonical_ids() -> None:
    """deploymentID == dataset UUID, mediaID == recording UUID (NOT segment id), eventID == ''."""
    service = AnnotationSetExportService.__new__(AnnotationSetExportService)
    ann = _make_annotation_set_annotation()

    row = service._build_row(
        cast(TimeRangeAnnotation, ann),
        project=None,
        license_value="",
        license_history_url="",
        recording_h3_map={},
    )

    dataset = ann.segment.recording.dataset
    assert row["deploymentID"] == str(dataset.id)
    assert row["deploymentID"] != dataset.name
    # mediaID is the RECORDING id, NOT the segment id (which would be the old,
    # drifted behaviour). The segment linkage lives in the extension columns.
    assert row["mediaID"] == str(ann.segment.recording.id)
    assert row["mediaID"] != str(ann.segment.id)
    assert row["observationID"] == str(ann.id)
    assert row["eventID"] == ""
    # The segment linkage is still present in the trailing extension columns.
    assert row["segment_id"] == str(ann.segment.id)
    assert row["recording_id"] == str(ann.segment.recording.id)


# ---------------------------------------------------------------------------
# 4. Cross-CSV join keys are identical (deployments/media <-> observations).
# ---------------------------------------------------------------------------


def test_cross_csv_join_keys_are_identical() -> None:
    """The deploymentID/mediaID an observation emits equals the deployments/media key.

    ``export.py`` builds ``deployments.csv`` / ``media.csv`` via
    ``camtrap.deployment_id(dataset.id)`` / ``camtrap.media_id(recording.id)``.
    The observation row builders must derive the SAME values from the SAME
    function for the join to hold across files. We compute both sides from the
    shared functions and the row builders and assert byte-equality.
    """
    # --- detection observation <-> deployments/media ---
    det_ann = _make_detection_annotation()
    det_service = DetectionExportService.__new__(DetectionExportService)
    det_row = det_service._build_csv_row(
        cast(RecordingAnnotation, det_ann),
        project=None,
        license_value="",
        license_history_url="",
        recording_h3_map={},
    )
    det_dataset = det_ann.recording.dataset
    # The deployments.csv / media.csv key export.py would write:
    expected_deployment_key = camtrap.deployment_id(det_dataset.id)
    expected_media_key = camtrap.media_id(det_ann.recording.id)
    assert det_row["deploymentID"] == expected_deployment_key
    assert det_row["mediaID"] == expected_media_key

    # --- annotation-set observation <-> deployments/media ---
    set_ann = _make_annotation_set_annotation()
    set_service = AnnotationSetExportService.__new__(AnnotationSetExportService)
    set_row = set_service._build_row(
        cast(TimeRangeAnnotation, set_ann),
        project=None,
        license_value="",
        license_history_url="",
        recording_h3_map={},
    )
    set_dataset = set_ann.segment.recording.dataset
    assert set_row["deploymentID"] == camtrap.deployment_id(set_dataset.id)
    assert set_row["mediaID"] == camtrap.media_id(set_ann.segment.recording.id)
