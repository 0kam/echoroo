#!/usr/bin/env python3
"""Enforce requirements traceability between spec.md and requirements-traceability.md (T999).

Phase 16 Batch 6h-4 final docs gate. Walks the spec document for the
006-permissions-redesign feature and ensures every FR / NFR / PR / SC
identifier is referenced from the traceability matrix.

Implements the recipe documented inline in
``specs/006-permissions-redesign/requirements-traceability.md`` §"CI での
未リンク検出":

    grep -oE "(FR|NFR|PR|SC)-[0-9]+[a-z]?" spec.md | sort -u > spec_ids.txt
    grep -oE "(FR|NFR|PR|SC)-[0-9]+[a-z]?" requirements-traceability.md \
        | sort -u > trace_ids.txt
    comm -23 spec_ids.txt trace_ids.txt   # MUST be empty

Usage:
    python scripts/check_traceability.py
        # default paths under specs/006-permissions-redesign/

    python scripts/check_traceability.py \
        --spec specs/006-permissions-redesign/spec.md \
        --traceability specs/006-permissions-redesign/requirements-traceability.md

Exit codes:
    0  All spec IDs are linked from the traceability matrix.
    1  One or more IDs are unlinked (printed to stderr).
    2  Input file missing or unreadable.

The pattern is intentionally identical to the inline recipe — any change
here must be mirrored to requirements-traceability.md so operators can
reproduce the gate locally.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Identical to the recipe in requirements-traceability.md §"CI での未リンク検出".
# A trailing lowercase letter (e.g. FR-091a, NFR-001a) is part of the same ID
# and must be preserved verbatim — both spec and traceability use this form.
ID_RE = re.compile(r"\b(?:FR|NFR|PR|SC)-[0-9]+[a-z]?\b")

DEFAULT_SPEC = Path("specs/006-permissions-redesign/spec.md")
DEFAULT_TRACE = Path("specs/006-permissions-redesign/requirements-traceability.md")


def extract_ids(path: Path) -> set[str]:
    """Return the set of FR/NFR/PR/SC IDs referenced in ``path``."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"[check_traceability] FATAL: file not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
        print(
            f"[check_traceability] FATAL: cannot read {path}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    return set(ID_RE.findall(text))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify every spec FR/NFR/PR/SC ID is linked from the "
            "requirements-traceability matrix (T999)."
        ),
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=DEFAULT_SPEC,
        help=f"Path to spec.md (default: {DEFAULT_SPEC})",
    )
    parser.add_argument(
        "--traceability",
        type=Path,
        default=DEFAULT_TRACE,
        help=f"Path to requirements-traceability.md (default: {DEFAULT_TRACE})",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress success summary; still print unlinked IDs on failure.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    spec_ids = extract_ids(args.spec)
    trace_ids = extract_ids(args.traceability)

    # comm -23 spec trace == in spec but NOT in trace
    unlinked = sorted(spec_ids - trace_ids)
    # Diagnostic only: traceability IDs that no longer appear in the spec.
    # This is informational, not a gate failure (e.g. resolved/historic IDs).
    orphaned = sorted(trace_ids - spec_ids)

    if unlinked:
        print(
            "[check_traceability] FAIL: the following IDs appear in spec.md but"
            " are not referenced by requirements-traceability.md:",
            file=sys.stderr,
        )
        for ident in unlinked:
            print(f"  - {ident}", file=sys.stderr)
        print(
            "\nFix: add a row for each unlinked ID under the appropriate"
            " section in requirements-traceability.md, or rename the spec ID"
            " to match an existing trace entry.",
            file=sys.stderr,
        )
        return 1

    if not args.quiet:
        print(
            f"[check_traceability] OK: {len(spec_ids)} spec IDs all linked"
            f" ({len(trace_ids)} trace IDs total, {len(orphaned)} orphan)."
        )
        if orphaned:
            # Orphans are informational; print to stdout so CI logs show the
            # drift but do not fail the build.
            print(
                "[check_traceability] note: trace IDs not present in spec"
                f" (informational): {', '.join(orphaned[:10])}"
                + (" ..." if len(orphaned) > 10 else "")
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
