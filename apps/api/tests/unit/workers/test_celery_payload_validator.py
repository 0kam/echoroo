"""Unit tests for the Celery task payload base model (T084, FR-028b).

The :class:`CeleryTaskPayload` base must reject any field — top-level or
nested inside dict / list payloads — whose name matches the raw
coordinate denylist. The denylist intentionally covers only the literal
spatial keys defined by FR-028b/c so that the validator stays narrow and
predictable; broader PII concerns are handled by the audit sanitizer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from echoroo.workers._celery_payload import (
    CeleryTaskPayload,
    CoordinateInPayloadError,
    _is_forbidden_key,
)

# ---------------------------------------------------------------------------
# Top-level field name rejection
# ---------------------------------------------------------------------------


def test_lat_field_at_top_level_is_rejected() -> None:
    """A literal ``lat`` field name on the model must trigger the validator."""

    class Bad(CeleryTaskPayload):
        lat: float

    with pytest.raises(ValidationError) as excinfo:
        Bad(lat=35.6)  # type: ignore[call-arg]
    assert "forbidden raw-coordinate field" in str(excinfo.value)


def test_longitude_field_at_top_level_is_rejected() -> None:
    """The full-name variant is also caught."""

    class Bad(CeleryTaskPayload):
        longitude: float

    with pytest.raises(ValidationError) as excinfo:
        Bad(longitude=139.7)  # type: ignore[call-arg]
    assert "forbidden raw-coordinate field" in str(excinfo.value)


def test_lng_field_at_top_level_is_rejected() -> None:
    """The ``lng`` short form (used by some libraries) is also rejected."""

    class Bad(CeleryTaskPayload):
        lng: float

    with pytest.raises(ValidationError):
        Bad(lng=139.7)  # type: ignore[call-arg]


def test_case_insensitive_match_top_level() -> None:
    """``LAT``, ``Lat``, ``lAt`` are all rejected."""

    class BadUpper(CeleryTaskPayload):
        LAT: float

    class BadMixed(CeleryTaskPayload):
        Latitude: float

    with pytest.raises(ValidationError):
        BadUpper(LAT=1.0)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        BadMixed(Latitude=1.0)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Nested dict / list rejection
# ---------------------------------------------------------------------------


def test_nested_dict_with_lat_key_is_rejected() -> None:
    """A nested dict carrying a forbidden key must fail validation."""

    class Payload(CeleryTaskPayload):
        recording: dict

    with pytest.raises(ValidationError) as excinfo:
        Payload(recording={"id": "rec-1", "lat": 35.6, "lng": 139.7})
    assert "forbidden raw-coordinate field" in str(excinfo.value)


def test_deeply_nested_coordinates_are_rejected() -> None:
    """The recursive scan must reach into multi-level nested dicts."""

    class Payload(CeleryTaskPayload):
        meta: dict

    bad = {
        "site": {
            "metadata": {
                "device": {"latitude": 1.23},
            }
        }
    }
    with pytest.raises(ValidationError):
        Payload(meta=bad)


def test_list_of_dicts_with_coordinate_keys_is_rejected() -> None:
    """Lists are walked element-by-element."""

    class Payload(CeleryTaskPayload):
        items: list

    with pytest.raises(ValidationError):
        Payload(items=[{"id": 1}, {"id": 2, "longitude": 0.0}])


def test_gps_prefix_with_coordinate_substring_is_rejected() -> None:
    """``gps_lat_min`` etc. are caught by the prefix heuristic."""

    class Payload(CeleryTaskPayload):
        meta: dict

    with pytest.raises(ValidationError):
        Payload(meta={"gps_lat_min": 0.0})


def test_geo_point_alias_is_rejected() -> None:
    """ElasticSearch-style ``geo_point`` is also banned."""

    class Payload(CeleryTaskPayload):
        meta: dict

    with pytest.raises(ValidationError):
        Payload(meta={"geo_point": "35.6,139.7"})


# ---------------------------------------------------------------------------
# Allowed payloads (no raw coordinates, only h3 indices)
# ---------------------------------------------------------------------------


def test_h3_index_member_field_is_allowed() -> None:
    """The canonical FR-028b-compliant field is accepted."""

    class GoodPayload(CeleryTaskPayload):
        project_id: str
        h3_index_member: str

    payload = GoodPayload(
        project_id="00000000-0000-0000-0000-000000000001",
        h3_index_member="89283082837ffff",
    )
    assert payload.h3_index_member == "89283082837ffff"


def test_nested_dict_without_coordinate_keys_is_allowed() -> None:
    """A clean nested payload should validate without errors."""

    class Payload(CeleryTaskPayload):
        meta: dict

    Payload(meta={"site": {"id": "s1", "h3_index_member": "89283082837ffff"}})


def test_altitude_alone_is_allowed() -> None:
    """``gps_altitude`` (vertical only, no horizontal coords) passes.

    The denylist targets horizontal coordinates explicitly; altitude is
    not a privacy-sensitive horizontal location and should be permitted.
    """

    class Payload(CeleryTaskPayload):
        meta: dict

    Payload(meta={"gps_altitude": 100})


# ---------------------------------------------------------------------------
# Helper-level coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "lat",
        "lng",
        "lon",
        "latitude",
        "longitude",
        "coords",
        "coordinates",
        "geo_point",
        "geopoint",
        "gps_lat",
        "gps_lng",
        "gps_lon",
        "gps_latitude",
        "gps_longitude",
        "GPS_LATITUDE",
        "Latitude",
        "Lng",
    ],
)
def test_is_forbidden_key_exact_denylist(key: str) -> None:
    assert _is_forbidden_key(key) is True


@pytest.mark.parametrize(
    "key",
    [
        "h3_index_member",
        "project_id",
        "site_id",
        "altitude",
        "gps_altitude",
        "elevation",
        "id",
        "created_at",
    ],
)
def test_is_forbidden_key_safe_keys(key: str) -> None:
    assert _is_forbidden_key(key) is False


def test_coordinate_in_payload_error_inherits_from_value_error() -> None:
    """ValueError ancestry lets Pydantic convert the raise to a validation error."""
    assert issubclass(CoordinateInPayloadError, ValueError)


# ---------------------------------------------------------------------------
# Extra-fields strictness
# ---------------------------------------------------------------------------


def test_extra_fields_are_forbidden_by_default() -> None:
    """``extra='forbid'`` keeps the denylist scan exhaustive — unknown
    fields cannot bypass the validator by piggy-backing on a generic
    ``Any`` field.
    """

    class Payload(CeleryTaskPayload):
        project_id: str

    with pytest.raises(ValidationError):
        Payload(project_id="p", surprise=1)  # type: ignore[call-arg]
