"""CamtrapDP observation column list + event-datetime formatter.

Neutral single source of truth for the CamtrapDP ``observations.csv`` column
order and the recording-relative event-datetime formatter, shared by every
export surface so the column shape and timestamp rendering stay byte-identical.

The column list and formatter were previously owned by
``echoroo.services.detection_export``; they were moved here (approved
2026-06-09) so neither the detection export nor the annotation-set export owns
the shared CamtrapDP shape. The contents and ordering are preserved exactly.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# CamtrapDP observations.csv columns in standard order. Extended with four
# Phase 6 / FR-086 trailing columns appended **after** the CamtrapDP block —
# CamtrapDP-compliant readers ignore unknown trailing columns, so the
# extension is non-breaking. NOTE: raw lat/lng / latitude / longitude
# columns are intentionally absent (FR-028 / SC-016).
CAMTRAPDP_OBSERVATION_COLUMNS = [
    "observationID",
    "deploymentID",
    "mediaID",
    "eventID",
    "eventStart",
    "eventEnd",
    "observationLevel",
    "observationType",
    "deviceSetupType",
    "scientificName",
    "count",
    "lifeStage",
    "sex",
    "behavior",
    "individualID",
    "individualPositionRadius",
    "individualPositionAngle",
    "individualSpeed",
    "bboxX",
    "bboxY",
    "bboxWidth",
    "bboxHeight",
    "frequencyLow",
    "frequencyHigh",
    "classificationMethod",
    "classifiedBy",
    "classificationTimestamp",
    "classificationProbability",
    "classificationConfirmation",
    "observationTags",
    "observationComments",
    # FR-086 trailing extensions (non-CamtrapDP):
    "license",
    "license_history_url",
    "location_generalization",
    "withheld_reason",
]


def format_event_datetime(
    recording_datetime: datetime | None,
    offset_seconds: float,
) -> str:
    """Format an absolute ISO 8601 datetime from recording start + offset.

    Sub-second precision is preserved: the offset is added as a float (no int
    truncation) and the output carries a millisecond fraction, uniformly — a
    whole-second value renders as ``.000``. Audio detections / annotations often
    have fractional-second boundaries (many are shorter than one second), so
    truncating to whole seconds would drop their real duration. The trailing
    ``Z`` (UTC) suffix style is preserved from the previous implementation.

    Args:
        recording_datetime: Base datetime of the recording (timezone-aware or naive).
        offset_seconds: Offset in seconds from the recording start (float;
            fractional part preserved).

    Returns:
        ISO 8601 string with millisecond fraction and ``Z`` suffix
        (e.g. ``2026-06-04T05:23:25.450Z``), or empty string if datetime is None.
    """
    if recording_datetime is None:
        return ""
    result = recording_datetime + timedelta(seconds=float(offset_seconds))
    # Emit millisecond (3 fractional-digit) precision while keeping the existing
    # ``Z`` UTC suffix; recording datetimes are stored UTC.
    return result.strftime("%Y-%m-%dT%H:%M:%S.") + f"{result.microsecond // 1000:03d}Z"
