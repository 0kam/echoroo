"""Celery task payload base model with raw-coordinate denylist (FR-028b).

The permissions redesign forbids any code path from carrying raw
latitude / longitude through Celery task payloads — the only acceptable
spatial reference is an opaque ``h3_index_member`` string. Producers MUST
inherit from :class:`CeleryTaskPayload` so that a structural validator
rejects any field literally named ``lat``, ``lng``, ``latitude``,
``longitude``, ``coordinates``, ``geo_point`` (case-insensitive,
recursive through dicts and lists). The check runs at task enqueue time,
*before* the message hits the broker.

The denylist intentionally uses *exact field name* matching plus a small
substring set rather than a full PII regex (that job belongs to
:class:`echoroo.core.audit.AuditLogSanitizer`). The goal here is the
narrow, well-bounded "no raw coordinates ever ride a Celery task" rule
from FR-028b — additional PII concerns are handled by the audit
sanitizer when the payload is logged, not when it is dispatched.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, model_validator

# Exact field names that are always rejected, case-insensitive. These are
# the literal coordinate keys defined by FR-028b/c plus a few obvious
# aliases so a typo or rename in a downstream codebase does not slip raw
# coordinates through the gate.
_DENYLIST_EXACT: Final[frozenset[str]] = frozenset(
    {
        "lat",
        "lng",
        "lon",
        "latitude",
        "longitude",
        "coords",
        "coordinates",
        "geo_point",
        "geopoint",
        "gps",
        "gps_lat",
        "gps_lng",
        "gps_lon",
        "gps_latitude",
        "gps_longitude",
    }
)


# Substrings that, when *exactly equal* (after lowercasing), are NOT a
# violation but, when found as the start of a compound key, are. Example:
# ``gps_altitude`` is allowed (altitude is not a horizontal coordinate)
# but ``gps_lat_min`` is rejected. To keep the validator simple, we treat
# any key starting with one of these prefixes AND containing 'lat'/'lng'
# /'lon'/'longitude'/'latitude' as a violation.
_PREFIX_PATTERNS: Final[tuple[str, ...]] = ("gps_",)
_PREFIX_TRIGGERS: Final[tuple[str, ...]] = ("lat", "lng", "lon")


class CoordinateInPayloadError(ValueError):
    """Raised when a Celery task payload contains a forbidden coordinate field.

    Inherits from :class:`ValueError` so Pydantic's ``model_validator``
    converts the raise into a standard validation error suitable for
    surfacing through FastAPI / Celery's serialiser.
    """


def _is_forbidden_key(key: str) -> bool:
    """Return ``True`` if a field name is a raw-coordinate field.

    Matching is **case-insensitive** and uses a denylist of exact names
    plus a small heuristic for prefixed coordinate fields so that
    deliberately-renamed fields (``gps_lat_average``, ``location_lng``)
    are still caught.
    """
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    if lowered in _DENYLIST_EXACT:
        return True
    # Prefix pattern: e.g. "gps_lat_min" — the prefix triggers the heuristic
    # only when the rest of the key contains a coordinate substring.
    for prefix in _PREFIX_PATTERNS:
        if lowered.startswith(prefix):
            tail = lowered[len(prefix) :]
            if any(trigger in tail for trigger in _PREFIX_TRIGGERS):
                return True
    return False


def _scan_for_forbidden(value: Any, *, path: str) -> str | None:
    """Recursively walk ``value`` and return the first violating path.

    Returns the dotted JSON path of a forbidden field, or ``None`` if the
    payload is clean. The traversal is bounded by Python's recursion
    limit; outbox payloads are kicked through this validator, so very
    deep nesting is itself a smell that the writer should be encouraged
    to flatten.
    """
    if isinstance(value, dict):
        for k, v in value.items():
            if _is_forbidden_key(str(k)):
                return f"{path}.{k}" if path else str(k)
            nested = _scan_for_forbidden(v, path=f"{path}.{k}" if path else str(k))
            if nested is not None:
                return nested
        return None
    if isinstance(value, list):
        for i, item in enumerate(value):
            nested = _scan_for_forbidden(item, path=f"{path}[{i}]")
            if nested is not None:
                return nested
        return None
    # Primitive value — nothing to do.
    return None


class CeleryTaskPayload(BaseModel):
    """Base Pydantic model for Celery task payloads.

    Subclasses gain a structural ``model_validator`` that rejects any
    field whose name (or any nested-dict / list key) matches the raw
    coordinate denylist. The validator runs in ``mode='after'`` so that
    Pydantic has already coerced the data into the subclass shape; the
    nested scan is therefore over the same dict the producer would
    serialise to JSON.

    Attribute naming on the subclass itself is also enforced — a field
    literally called ``lat`` will fail validation even before the nested
    scan runs.

    Example
    -------
    >>> from pydantic import Field
    >>> class MyPayload(CeleryTaskPayload):
    ...     project_id: str
    ...     h3_index_member: str
    >>> MyPayload(project_id="p1", h3_index_member="89283082837ffff")
    MyPayload(project_id='p1', h3_index_member='89283082837ffff')
    """

    model_config = ConfigDict(
        # Forbid extra fields by default — producers must declare every
        # field they pass, which makes the denylist scan fully reliable.
        extra="forbid",
        # Strip whitespace from string fields to match Celery's JSON
        # serialiser behaviour.
        str_strip_whitespace=True,
    )

    @model_validator(mode="after")
    def _reject_raw_coordinates(self) -> CeleryTaskPayload:
        """Reject any forbidden coordinate field on the model or in nested data."""
        # 1) Scan the model's own field names.
        for field_name in type(self).model_fields:
            if _is_forbidden_key(field_name):
                raise CoordinateInPayloadError(
                    f"forbidden raw-coordinate field on Celery payload: {field_name!r}"
                )

        # 2) Scan nested dict / list values (a payload may legally hold a
        # JSONB blob — but every key in it is still subject to FR-028b).
        for field_name in type(self).model_fields:
            value = getattr(self, field_name, None)
            offending = _scan_for_forbidden(value, path=field_name)
            if offending is not None:
                raise CoordinateInPayloadError(
                    f"forbidden raw-coordinate field on Celery payload: {offending!r}"
                )

        return self


__all__ = [
    "CeleryTaskPayload",
    "CoordinateInPayloadError",
]
