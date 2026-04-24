#!/usr/bin/env python3
"""Lint: raw latitude / longitude / gps_* keys must not leak from the API.

Enforces FR-028f (coordinate privacy): raw `lat`, `lng`, `latitude`,
`longitude`, and `gps_*` fields must never appear in:
    * API response models (`apps/api/echoroo/schemas/**/*.py`)
    * FastAPI path-operation return annotations / response_model keywords
    * OpenAPI contract YAML files
    * Celery task payload schemas

Target pattern (regex-based):
    * Scan `apps/api/echoroo/**/*.py`,
      `apps/api/echoroo/**/*.yaml`, and
      `specs/006-permissions-redesign/contracts/*.yaml`.
    * Match the forbidden token set: `latitude`, `longitude`, `\blat\b`,
      `\blng\b`, and any identifier starting with `gps_`.
    * Skip whole files listed in the allowlist (default:
      `scripts/allowlists/raw_coordinates_allowlist.txt`).
    * Skip comment-only matches that reference `h3_index` or Markdown
      documentation (handled in Phase 2).

See specs/006-permissions-redesign/research.md §18-E/F.

Full implementation: T044 (Phase 2).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Forbidden token pattern. Phase 2 will refine the regex (e.g. word
# boundaries, ignoring `h3_index`, honouring inline suppression pragmas).
FORBIDDEN_PATTERN = re.compile(
    r"\b(latitude|longitude|lat|lng)\b|\bgps_[A-Za-z0-9_]+",
)

DEFAULT_SCAN_TARGETS: tuple[Path, ...] = (
    Path("apps/api/echoroo"),
    Path("specs/006-permissions-redesign/contracts"),
)


def load_allowlist(allowlist_file: Path) -> set[str]:
    """Load the allowlist file. Missing file == empty allowlist."""
    if not allowlist_file.exists():
        return set()
    entries: set[str] = set()
    for raw_line in allowlist_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line)
    return entries


def find_violations(
    root: Path,
    allowlist: set[str],
) -> list[str]:
    """Return a list of human-readable violation descriptions.

    TODO(T044): implement in Phase 2. The skeleton exercises the file
    discovery pipeline without yet emitting findings.
    """
    if not root.exists():
        return []
    suffixes = (".py", ".yaml", ".yml")
    for candidate in root.rglob("*"):
        if not candidate.is_file() or candidate.suffix not in suffixes:
            continue
        rel = str(candidate)
        if rel in allowlist:
            continue
        # Read the file to prove the pipeline works; Phase 2 will scan.
        try:
            candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    # TODO(T044): accumulate and return violations using FORBIDDEN_PATTERN.
    print(
        "[lint_no_raw_coordinates] skeleton scan complete "
        "(TODO: implement in T044)",
        file=sys.stderr,
    )
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_SCAN_TARGETS[0],
        help=(
            "Root directory to scan (default: apps/api/echoroo). "
            "Phase 2 will additionally scan contracts/*.yaml."
        ),
    )
    parser.add_argument(
        "--allowlist-file",
        type=Path,
        default=Path("scripts/allowlists/raw_coordinates_allowlist.txt"),
        help="Path to the allowlist file (one entry per line).",
    )
    parser.add_argument(
        "--fail-on-violation",
        action="store_true",
        help="Exit with status 1 if any violations are found.",
    )
    args = parser.parse_args()

    try:
        allowlist = load_allowlist(args.allowlist_file)
        violations = find_violations(args.path, allowlist)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[lint_no_raw_coordinates] unexpected error: {exc}", file=sys.stderr)
        return 2

    for v in violations:
        print(v, file=sys.stderr)
    if violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
