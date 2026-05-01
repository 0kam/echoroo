#!/usr/bin/env python3
"""Assert the public OpenAPI document leaks no raw coordinate names.

Enforces FR-028f / FR-091b / SC-019 against the rendered contract: every
``Recording`` / ``Site`` / ``Detection`` schema and parameter MUST expose
``h3_index_member`` only (Phase 13 P4 / T807 full rename) — never raw
``lat``, ``lng``, ``latitude``, ``longitude``, ``coordinates``,
``geo_point``, or ``gps_*`` keys.

Detection strategy:

    * Recursively walk the JSON document.
    * Flag every dict KEY whose name matches the denylist.
    * Flag every string VALUE that exactly matches the denylist (covers
      schema ``required`` lists, ``properties`` mentions in examples,
      and parameter ``name`` fields).
    * Skip strings that are URLs / refs (``$ref``) — those are matched
      structurally by the key check anyway.

Usage:

    uv run python scripts/assert_openapi_no_coords.py openapi.json

Exit codes:

    0 — clean
    1 — at least one denylist hit
    2 — could not load the input file
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_ALLOWLIST = Path("scripts/allowlists/openapi_coords_allowlist.txt")

FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "lat",
        "lng",
        "latitude",
        "longitude",
        "coordinates",
        "geo_point",
    }
)
FORBIDDEN_PREFIXES: tuple[str, ...] = ("gps_",)


def _is_forbidden_token(token: str) -> bool:
    if not token:
        return False
    if token in FORBIDDEN_NAMES:
        return True
    return any(token.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)


def _walk(node: Any, path: str, hits: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and _is_forbidden_token(key):
                hits.append(f"{path}.{key} (forbidden key)")
            _walk(value, f"{path}.{key}", hits)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _walk(item, f"{path}[{idx}]", hits)
    elif isinstance(node, str):
        # Only flag strings that are EXACT denylist tokens — matches
        # ``required: [latitude]`` and ``parameters[].name = "lat"``
        # without false-positive on prose like "the latitude column".
        if _is_forbidden_token(node):
            hits.append(f"{path} = {node!r} (forbidden value)")


def find_hits(document: Any) -> list[str]:
    hits: list[str] = []
    _walk(document, "$", hits)
    return hits


def _load_allowlist(path: Path) -> frozenset[str]:
    """Load an allowlist of JSONPath prefixes from ``path``.

    Each non-empty / non-comment line is a JSONPath prefix; any hit whose
    path starts with the prefix is dropped from the violation list. The
    Phase 2.10 #7 baseline allowlists exact ``$.components.schemas.X.properties.lat``
    style prefixes so the strict gate can run on every push while Phase 3
    rewrites the schemas to ``h3_index_member`` only (Phase 13 P4 / T807
    completes the Site canonical rename).
    """
    if not path.exists():
        return frozenset()
    entries: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return frozenset(entries)


def _filter_hits(hits: list[str], allowlist: frozenset[str]) -> list[str]:
    if not allowlist:
        return hits
    remaining: list[str] = []
    for hit in hits:
        # Hit format: "<jsonpath> ..." — strip the trailing annotation
        # before comparing to the allowlist prefix.
        path_only = hit.split(" ", 1)[0]
        if any(path_only.startswith(prefix) for prefix in allowlist):
            continue
        remaining.append(hit)
    return remaining


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "openapi_json",
        type=Path,
        help="Path to the OpenAPI JSON document.",
    )
    parser.add_argument(
        "--allowlist-file",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=(
            f"Allowlist file (default: {DEFAULT_ALLOWLIST}). Each non-empty / "
            "non-comment line is a JSONPath prefix to drop from the hit list."
        ),
    )
    args = parser.parse_args()

    try:
        document = json.loads(args.openapi_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[assert_openapi_no_coords] could not load {args.openapi_json}: {exc}",
            file=sys.stderr,
        )
        return 2

    allowlist = _load_allowlist(args.allowlist_file)
    raw_hits = find_hits(document)
    hits = _filter_hits(raw_hits, allowlist)
    for hit in hits:
        print(hit, file=sys.stderr)

    if hits:
        print(
            f"[assert_openapi_no_coords] {len(hits)} forbidden coordinate "
            f"reference(s) in {args.openapi_json} "
            f"(after {len(raw_hits) - len(hits)} allowlisted)",
            file=sys.stderr,
        )
        return 1
    suppressed = len(raw_hits)
    print(
        f"[assert_openapi_no_coords] {args.openapi_json}: clean "
        f"(no unallowed raw lat/lng/coordinates leakage; "
        f"{suppressed} legacy reference(s) allowlisted)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
