#!/usr/bin/env python3
"""Emit the FastAPI application's OpenAPI 3 document as JSON.

Used by CI (T100e) — after generation, ``scripts/assert_openapi_no_coords.py``
inspects the document for raw coordinate leakage (FR-028f / SC-019).

Why a dedicated script instead of ``curl /openapi.json``? The CI lint job
runs without the full Docker stack, so we need to import the FastAPI app
in-process. The script keeps imports lazy so a missing optional dep does
not crash the whole pipeline — failures are surfaced with a non-zero
exit code and a one-line error message.

Usage:

    uv run python scripts/dump_openapi.py --out openapi.json

Exit codes:

    0 — JSON written successfully
    1 — could not import the app or generate the schema
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Destination path for the OpenAPI JSON document.",
    )
    parser.add_argument(
        "--app",
        default="echoroo.main:app",
        help=(
            "Module path to the FastAPI app instance, in "
            "'package.module:attribute' form (default: echoroo.main:app)."
        ),
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent (default: 2). Use 0 for compact output.",
    )
    args = parser.parse_args()

    module_path, _, attr = args.app.partition(":")
    if not module_path or not attr:
        print(
            f"[dump_openapi] invalid --app value: {args.app!r} "
            "(expected 'module:attribute')",
            file=sys.stderr,
        )
        return 1

    try:
        import importlib

        module = importlib.import_module(module_path)
        app = getattr(module, attr)
    except Exception as exc:  # noqa: BLE001 — defensive top-level catch
        print(
            f"[dump_openapi] failed to import {args.app}: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        schema = app.openapi()
    except Exception as exc:  # noqa: BLE001 — defensive top-level catch
        print(
            f"[dump_openapi] failed to render OpenAPI schema: {exc}",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    indent: int | None = args.indent if args.indent > 0 else None
    args.out.write_text(
        json.dumps(schema, indent=indent, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(
        f"[dump_openapi] wrote OpenAPI schema to {args.out} "
        f"({len(schema.get('paths', {}))} path(s))",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
