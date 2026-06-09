"""Canonical CamtrapDP identifier functions (single source of truth).

This module is the ONE place that decides how Echoroo maps its internal
entities onto the CamtrapDP identifier columns. Every export surface
(detection observations, annotation-set observations, the
``deployments.csv`` / ``media.csv`` join tables, and the dataset ZIP) MUST
route its identifier values through these functions so the join keys are
byte-identical across files.

Canonical scheme (approved 2026-06-09)
--------------------------------------
* ``deploymentID``  = ``str(dataset.id)`` (the dataset UUID) — EVERYWHERE.
  CamtrapDP treats a deployment as one camera/recorder placement; Echoroo
  models that as a ``Dataset``, so the dataset UUID is the stable join key
  shared by ``deployments.csv`` and every observation row.
* ``mediaID``       = ``str(recording.id)`` (the recording UUID) — EVERYWHERE.
  The media unit is always the source recording, even for the
  segment-centric annotation-set export. The segment linkage is preserved in
  the export's trailing extension columns (``segment_id`` / ``recording_id`` /
  the segment/recording offset columns) and in the dataset ZIP's
  ``segments.csv`` — it is NOT folded into ``mediaID``.
* ``observationID`` = ``str(annotation.id)`` (the annotation UUID).
  Each row is one observation; the annotation's own UUID identifies it.
* ``eventID``       = ``""`` (EMPTY).
  Echoroo does not group observations into CamtrapDP "events", so the field
  is intentionally blank rather than aliased to the observation/annotation
  id (which would falsely imply a one-observation-per-event grouping).

These functions are pure and dependency-free so they can be imported by any
export service (and by tests) without pulling in ORM/session machinery.
"""

from __future__ import annotations

from uuid import UUID


def deployment_id(dataset_id: UUID) -> str:
    """Return the canonical CamtrapDP ``deploymentID`` for a dataset.

    Canonical scheme (approved 2026-06-09): ``deploymentID == str(dataset.id)``
    everywhere. This is the join key shared by ``deployments.csv`` and every
    observation row, so all surfaces MUST derive it from this function.

    Args:
        dataset_id: The dataset's UUID.

    Returns:
        The dataset UUID rendered as a string.
    """
    return str(dataset_id)


def media_id(recording_id: UUID) -> str:
    """Return the canonical CamtrapDP ``mediaID`` for a recording.

    Canonical scheme (approved 2026-06-09): ``mediaID == str(recording.id)``
    everywhere, including the segment-centric annotation-set export. The
    segment linkage lives in the export's trailing extension columns and the
    dataset ZIP's ``segments.csv``; it is never folded into ``mediaID``.

    Args:
        recording_id: The source recording's UUID.

    Returns:
        The recording UUID rendered as a string.
    """
    return str(recording_id)


def observation_id(annotation_id: UUID) -> str:
    """Return the canonical CamtrapDP ``observationID`` for an annotation.

    Canonical scheme (approved 2026-06-09):
    ``observationID == str(annotation.id)``. Each export row is one
    observation, identified by the annotation's own UUID.

    Args:
        annotation_id: The annotation's UUID.

    Returns:
        The annotation UUID rendered as a string.
    """
    return str(annotation_id)


def event_id() -> str:
    """Return the canonical CamtrapDP ``eventID`` (always empty).

    Canonical scheme (approved 2026-06-09): ``eventID == ""``. Echoroo does
    not group observations into CamtrapDP events, so this field is left blank
    rather than aliased to the observation/annotation id.

    Returns:
        The empty string.
    """
    return ""
