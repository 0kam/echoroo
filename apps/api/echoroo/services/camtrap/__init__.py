"""Neutral CamtrapDP export primitives (single source of truth).

This package owns the cross-export CamtrapDP contract so no individual export
service owns the shared shape:

* :mod:`echoroo.services.camtrap.identifiers` — canonical identifier functions
  (:func:`deployment_id` / :func:`media_id` / :func:`observation_id` /
  :func:`event_id`) applied across ALL export surfaces (approved 2026-06-09).
* :mod:`echoroo.services.camtrap.columns` — the CamtrapDP observation column
  list (:data:`CAMTRAPDP_OBSERVATION_COLUMNS`) and the recording-relative
  event-datetime formatter (:func:`format_event_datetime`).

Every export surface imports from here so the join keys, column shape, and
timestamp rendering stay byte-identical.
"""

from __future__ import annotations

from echoroo.services.camtrap.columns import (
    CAMTRAPDP_OBSERVATION_COLUMNS,
    format_event_datetime,
)
from echoroo.services.camtrap.identifiers import (
    deployment_id,
    event_id,
    media_id,
    observation_id,
)

__all__ = [
    "CAMTRAPDP_OBSERVATION_COLUMNS",
    "deployment_id",
    "event_id",
    "format_event_datetime",
    "media_id",
    "observation_id",
]
