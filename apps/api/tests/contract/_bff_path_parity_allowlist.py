"""BFF path parity allowlist consumed by PR J's test_bff_path_parity.py.

Spec/009 (browser API → BFF migration) — each per-resource PR (A2 / B /
C / D / E / F / G / H) appends the `/web-api/v1/*` paths it adds to the
list below. PR J's test then asserts each entry is present in the live
OpenAPI surface.

This file is intentionally a Python module (not YAML) so it can be
imported directly by the test and edits track as code changes.
"""

from __future__ import annotations

# Live-form BFF paths declared by this migration. Each per-PR appends
# its paths here (e.g. "/web-api/v1/projects" GET, "/web-api/v1/projects"
# POST, "/web-api/v1/projects/{project_id}" PATCH, etc.).
#
# Entry format: a string in the live OpenAPI form (i.e. with the
# `/web-api/v1` prefix), suffixed by " " + the uppercase HTTP method
# (e.g. "/web-api/v1/projects POST"). PR J's test parses these on the
# space and looks each up in the live FastAPI OpenAPI dict.
BFF_PATHS_DECLARED_BY_SPEC_009: list[str] = [
    # appended by each per-PR; empty until PR A starts wiring
]
