"""T651: OpenAPI schema fuzzer — no raw coordinate fields in core response schemas (FR-030, FR-031, SC-016).

Walks every 200 / 201 response schema in the FastAPI-generated OpenAPI
document and asserts that no field named latitude / longitude / lat / lng /
lon appears at any nesting depth (including arrays of objects and
oneOf / anyOf / allOf compositions) — for the core data endpoints
(detections, recordings, sites, annotations, clips, datasets, embeddings).

FR-030 scope: "Recording / Detection / Site の Pydantic response model に
latitude / longitude フィールドを定義しない" — the prohibition is on the
Pydantic *response* models for the core data surfaces, not on utility
endpoints (H3 coordinate conversion tools, Xeno-Canto proxy, admin
overview) that necessarily deal in coordinates as part of their contract.

Excluded path prefixes (they are either input-only, admin helpers, or
third-party proxies that cannot omit coordinates by design):
  /api/v1/h3/*           — coordinate ↔ H3 conversion tools (input field)
  /api/v1/projects/{id}/xeno-canto/*  — Xeno-Canto search proxy
  /api/v1/projects/{id}/overview      — admin overview / stats

All other /api/v1/projects/{id}/detections,
/api/v1/projects/{id}/recordings, /api/v1/projects/{id}/sites and every
endpoint under /web-api/ must pass the check.

FR-030: Raw latitude / longitude coordinates must never appear in public
        API responses for detections or recordings.
FR-031: The H3 cell index is the only location representation in responses.
SC-016: Raw-coordinate API leak must be caught by automated tests.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from echoroo.main import create_app

# ---------------------------------------------------------------------------
# Forbidden raw-coordinate field names (FR-030 / SC-016).
# ---------------------------------------------------------------------------

_FORBIDDEN_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "latitude",
        "longitude",
        "lat",
        "lng",
        "lon",
    }
)

# Compile a pattern for fast substring check in field names.
_FORBIDDEN_PATTERN: re.Pattern[str] = re.compile(
    r"^(latitude|longitude|lat|lng|lon)$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Excluded path prefixes — endpoints that legitimately deal in coordinates.
#
# FR-030 prohibits raw coordinates on the core *data* response surfaces:
# detections / recordings / sites / annotations. It does NOT prohibit:
#   * Coordinate conversion utilities (H3 tools need lat/lng as input/output)
#   * Third-party search proxies (Xeno-Canto returns coords by design)
#   * Admin overview / stats pages (aggregate metadata, not observation data)
# ---------------------------------------------------------------------------

_EXCLUDED_PATH_PREFIXES: tuple[str, ...] = (
    "/api/v1/h3",              # H3 ↔ lat/lng conversion tools
    "/api/v1/projects/{project_id}/xeno-canto",  # Xeno-Canto proxy
    "/api/v1/projects/{project_id}/overview",    # Admin overview stats
)


# ---------------------------------------------------------------------------
# Schema traversal helpers
# ---------------------------------------------------------------------------


def _resolve_ref(ref: str, components: dict[str, Any]) -> dict[str, Any]:
    """Resolve a ``$ref`` string against the OpenAPI ``components`` dict.

    Only ``#/components/schemas/...`` refs are expected here — the full
    JSON-Pointer traversal is kept simple because FastAPI always uses
    component-level references.
    """
    if not ref.startswith("#/components/schemas/"):
        return {}
    schema_name = ref.removeprefix("#/components/schemas/")
    return components.get("schemas", {}).get(schema_name, {})


def _collect_field_names(
    schema: dict[str, Any],
    components: dict[str, Any],
    visited: set[str] | None = None,
) -> list[str]:
    """Recursively collect all property field names from an OpenAPI schema.

    Handles:
    * ``properties``     — object properties
    * ``items``          — array element schema
    * ``oneOf`` / ``anyOf`` / ``allOf`` — composition keywords
    * ``$ref``           — component schema references (with cycle detection)

    Args:
        schema:     OpenAPI schema object (a dict).
        components: Top-level ``components`` dict from the OpenAPI document.
        visited:    Set of ``$ref`` names already traversed; prevents cycles.

    Returns:
        Flat list of all property field names reachable from this schema.
    """
    if visited is None:
        visited = set()

    if not isinstance(schema, dict):
        return []

    # Follow $ref first.
    ref = schema.get("$ref")
    if ref:
        if ref in visited:
            return []
        visited = visited | {ref}
        resolved = _resolve_ref(ref, components)
        return _collect_field_names(resolved, components, visited)

    collected: list[str] = []

    # Collect direct properties.
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        for field_name, field_schema in properties.items():
            collected.append(field_name)
            # Recurse into nested object schemas.
            if isinstance(field_schema, dict):
                collected.extend(
                    _collect_field_names(field_schema, components, visited)
                )

    # Array items.
    items = schema.get("items")
    if isinstance(items, dict):
        collected.extend(_collect_field_names(items, components, visited))

    # Composition keywords.
    for keyword in ("oneOf", "anyOf", "allOf"):
        for sub_schema in schema.get(keyword, []):
            if isinstance(sub_schema, dict):
                collected.extend(
                    _collect_field_names(sub_schema, components, visited)
                )

    return collected


def _get_response_schemas(
    path_item: dict[str, Any],
    components: dict[str, Any],
) -> list[tuple[str, str, dict[str, Any]]]:
    """Extract (method, status_code, schema) triples for 200/201 responses.

    Follows ``$ref`` on the ``schema`` keyword inside ``content.application/json``.
    Non-JSON or non-200/201 responses are silently skipped.

    Returns:
        List of ``(http_method, status_code, schema_dict)`` tuples.
    """
    results: list[tuple[str, str, dict[str, Any]]] = []
    http_methods = ("get", "post", "put", "patch", "delete")

    for method in http_methods:
        operation = path_item.get(method)
        if not isinstance(operation, dict):
            continue

        responses = operation.get("responses", {})
        for status_code in ("200", "201"):
            response = responses.get(status_code)
            if not isinstance(response, dict):
                continue

            # Follow $ref on the response object itself.
            resp_ref = response.get("$ref")
            if resp_ref:
                response = _resolve_ref(resp_ref, components)

            content = response.get("content", {})
            json_content = content.get("application/json", {})
            schema = json_content.get("schema")
            if isinstance(schema, dict):
                results.append((method.upper(), status_code, schema))

    return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def openapi_document() -> dict[str, Any]:
    """Return the FastAPI-generated OpenAPI document.

    Uses ``scope="module"`` so the app is only instantiated once per test
    module run — the OpenAPI generation is deterministic and there is no
    need to rebuild it for every test case.
    """
    app = create_app()
    return app.openapi()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Known FR-030 violations.
#
# Round 1 review C3 (2026-04-28): the previously-known
# ``SiteDetailResponse.latitude`` / ``longitude`` violations have been
# removed at the schema layer — the test now asserts a clean ZERO-violation
# state. Any future regression introduces a NEW violation and fails the
# test outright.
# ---------------------------------------------------------------------------
_KNOWN_VIOLATIONS: dict[str, frozenset[str]] = {}


@pytest.mark.parametrize(
    "forbidden_field",
    sorted(_FORBIDDEN_FIELD_NAMES),
)
def test_openapi_schema_has_no_raw_coordinate_fields(
    openapi_document: dict[str, Any],
    forbidden_field: str,
) -> None:
    """FR-030 / SC-016: no response schema uses a forbidden raw-coordinate field name.

    Parametrised over each forbidden name so failures are reported per-field,
    making it easy to identify which field and path caused the violation.

    Known violations in ``_KNOWN_VIOLATIONS`` are tolerated (recorded as
    xfail) until the SiteResponse schema is cleaned up. Any *new* violation
    outside the known set causes an immediate test failure.
    """
    paths = openapi_document.get("paths", {})
    components = openapi_document.get("components", {})

    known_for_field = _KNOWN_VIOLATIONS.get(forbidden_field, frozenset())
    new_violations: list[str] = []
    known_violations_found: list[str] = []

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        # Skip excluded endpoints — they legitimately use coordinates
        # as part of their contract (H3 tools, Xeno-Canto proxy, etc.)
        if any(path.startswith(prefix) for prefix in _EXCLUDED_PATH_PREFIXES):
            continue

        response_schemas = _get_response_schemas(path_item, components)
        for method, status_code, schema in response_schemas:
            field_names = _collect_field_names(schema, components)
            for found_name in field_names:
                if found_name.lower() == forbidden_field:
                    entry = (
                        f"  {method} {path} ({status_code}): "
                        f"field '{found_name}' matches forbidden name '{forbidden_field}'"
                    )
                    if path in known_for_field:
                        known_violations_found.append(entry)
                    else:
                        new_violations.append(entry)

    # Any genuinely new violation is an immediate failure.
    assert not new_violations, (
        f"NEW raw coordinate field '{forbidden_field}' found in "
        f"{len(new_violations)} response schema(s) — FR-030 / SC-016 violation:\n"
        + "\n".join(new_violations)
    )

    # Known violations are reported via xfail so they are visible in test
    # output but do not block CI until the cleanup task is resolved.
    if known_violations_found:
        pytest.xfail(
            f"Known FR-030 violation: '{forbidden_field}' still present in "
            f"{len(known_violations_found)} schema(s) — tracked for cleanup:\n"
            + "\n".join(known_violations_found)
        )


def test_openapi_has_at_least_50_response_schemas(
    openapi_document: dict[str, Any],
) -> None:
    """Sanity check: the fuzzer must have at least 50 schemas to scan.

    This guards against the case where schema generation silently produces
    an empty or near-empty document, which would make the negative assertions
    trivially pass without providing any real coverage.
    """
    paths = openapi_document.get("paths", {})
    components = openapi_document.get("components", {})

    total_schemas = 0
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        if any(path.startswith(prefix) for prefix in _EXCLUDED_PATH_PREFIXES):
            continue
        total_schemas += len(_get_response_schemas(path_item, components))

    assert total_schemas >= 50, (
        f"Expected at least 50 response schemas from the OpenAPI document, "
        f"found {total_schemas}. The fuzzer may not be scanning enough endpoints."
    )


def test_openapi_document_loads_successfully(
    openapi_document: dict[str, Any],
) -> None:
    """Sanity: the OpenAPI document is non-empty and has a valid structure."""
    assert "paths" in openapi_document, "OpenAPI document must have a 'paths' key"
    assert "components" in openapi_document, "OpenAPI document must have a 'components' key"
    assert len(openapi_document["paths"]) > 0, "OpenAPI document must define at least one path"


def test_forbidden_field_names_are_checked_case_insensitively(
    openapi_document: dict[str, Any],
) -> None:
    """Regression guard: the traversal normalises field names to lowercase.

    This test builds a synthetic schema containing a 'Latitude' (capitalised)
    field and verifies the traversal collects it and the forbidden-name check
    would detect it via case-insensitive comparison.
    """
    # Build a minimal synthetic schema that includes 'Latitude' (wrong case).
    synthetic_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "Latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "h3_index": {"type": "string"},
        },
    }
    components = openapi_document.get("components", {})
    field_names = _collect_field_names(synthetic_schema, components)

    # Verify the traversal found all three field names.
    assert "Latitude" in field_names, "Traversal must collect 'Latitude' property"
    assert "longitude" in field_names, "Traversal must collect 'longitude' property"

    # Verify the case-insensitive match logic.
    found_forbidden = [
        name for name in field_names if name.lower() in _FORBIDDEN_FIELD_NAMES
    ]
    assert len(found_forbidden) == 2, (
        f"Expected 2 forbidden names detected ('Latitude', 'longitude'), "
        f"found: {found_forbidden}"
    )
