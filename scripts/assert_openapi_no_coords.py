#!/usr/bin/env python3
"""Assert the public OpenAPI document leaks no raw coordinate names.

Enforces FR-028f / FR-091b / SC-019 against the rendered contract: every
``Recording`` / ``Site`` / ``Detection`` schema and parameter MUST expose
``h3_index`` only — never raw ``lat``, ``lng``, ``latitude``,
``longitude``, ``coordinates``, ``geo_point``, or ``gps_*`` keys.

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "openapi_json",
        type=Path,
        help="Path to the OpenAPI JSON document.",
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

    hits = find_hits(document)
    for hit in hits:
        print(hit, file=sys.stderr)

    if hits:
        print(
            f"[assert_openapi_no_coords] {len(hits)} forbidden coordinate "
            f"reference(s) in {args.openapi_json}",
            file=sys.stderr,
        )
        return 1
    print(
        f"[assert_openapi_no_coords] {args.openapi_json}: clean "
        "(no raw lat/lng/coordinates leakage)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
