#!/usr/bin/env python3
"""Check mutmut mutation scores and enforce an 80% threshold (T995, PR-004, SC-012).

Usage:
    cd apps/api && uv run python ../../scripts/check_mutation_score.py [--threshold N] [--warn-only]

Exit codes:
    0  All modules at or above threshold (or --warn-only).
    1  One or more modules below threshold (hard-fail mode).

This script is called by the CI `mutation-testing` job in
`.github/workflows/ci.yml` after `uv run mutmut run` completes.
It parses `uv run mutmut results` output and computes per-module scores.

Threshold behaviour:
    Default threshold: 80 (%).
    --warn-only: always exit 0 but print WARN lines for below-threshold modules.
    --threshold N: override the threshold (integer 0-100).

mutmut results output format (mutmut >=3.2):
    Killed (N)    <path>
    Survived (N)  <path>
    Suspicious (N) <path>

Score = killed / (killed + survived + suspicious) * 100.
Timeout / no-coverage mutants are excluded from the denominator (standard
mutation score convention).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict

_THRESHOLD_DEFAULT = 80

# Pattern for a mutmut result line:
#   "Killed (42)   echoroo/core/permissions.py"
# The status word may be preceded by ANSI colour codes in interactive terminals;
# we strip those before matching.
_ANSI_ESC = re.compile(r"\x1b\[[0-9;]*m")
_RESULT_LINE = re.compile(
    r"^(?P<status>Killed|Survived|Suspicious|Timeout|No coverage)"
    r"\s+\((?P<count>\d+)\)\s+(?P<path>\S+)",
    re.IGNORECASE,
)


def _strip_ansi(text: str) -> str:
    return _ANSI_ESC.sub("", text)


def _run_mutmut_results() -> list[str]:
    """Run `mutmut results` and return stdout lines (CWD = apps/api)."""
    result = subprocess.run(
        [sys.executable, "-m", "mutmut", "results"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):  # mutmut exits 1 when survivors exist
        print(f"[check_mutation_score] mutmut results exit {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    return (result.stdout + result.stderr).splitlines()


def _parse_results(lines: list[str]) -> dict[str, dict[str, int]]:
    """Parse mutmut results into {path: {status: count}}."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for raw_line in lines:
        line = _strip_ansi(raw_line).strip()
        m = _RESULT_LINE.match(line)
        if m:
            status = m.group("status").capitalize()
            count = int(m.group("count"))
            path = m.group("path")
            counts[path][status] += count
    return {k: dict(v) for k, v in counts.items()}


def _compute_score(counts: dict[str, int]) -> tuple[float, int, int]:
    """Return (score_pct, killed, total) for a single module."""
    killed = counts.get("Killed", 0)
    survived = counts.get("Survived", 0)
    suspicious = counts.get("Suspicious", 0)
    # Timeout + No coverage are excluded from denominator per convention.
    total = killed + survived + suspicious
    if total == 0:
        return 0.0, 0, 0
    return round(killed / total * 100, 1), killed, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check mutmut mutation scores.")
    parser.add_argument(
        "--threshold",
        type=int,
        default=_THRESHOLD_DEFAULT,
        metavar="N",
        help=f"Minimum mutation score %% (default: {_THRESHOLD_DEFAULT})",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        default=False,
        help="Print warnings but always exit 0 (use for modules pending Phase 17).",
    )
    args = parser.parse_args(argv)
    threshold = args.threshold

    lines = _run_mutmut_results()
    if not lines:
        print("[check_mutation_score] No mutmut results found — was mutmut run completed?")
        if args.warn_only:
            return 0
        return 1

    counts_by_path = _parse_results(lines)

    if not counts_by_path:
        print("[check_mutation_score] No parseable result lines from mutmut output.")
        print("[check_mutation_score] Raw output (first 20 lines):")
        for line in lines[:20]:
            print("  ", line)
        if args.warn_only:
            return 0
        return 1

    failures: list[tuple[str, float, int, int]] = []

    print(f"\n{'Module':<50} {'Score':>7}  {'Killed':>7} / {'Total':<7}  Status")
    print("-" * 90)

    for path in sorted(counts_by_path):
        score, killed, total = _compute_score(counts_by_path[path])
        status_str = "PASS" if score >= threshold else ("WARN" if args.warn_only else "FAIL")
        print(f"{path:<50} {score:>6.1f}%  {killed:>7} / {total:<7}  {status_str}")
        if score < threshold:
            failures.append((path, score, killed, total))

    print()

    if failures:
        print(f"[check_mutation_score] {len(failures)} module(s) below {threshold}% threshold:")
        for path, score, killed, total in failures:
            print(f"  {path}: {score:.1f}% ({killed}/{total})")
        if args.warn_only:
            print("[check_mutation_score] warn-only mode — exiting 0 (Phase 17 items pending).")
            return 0
        print("[check_mutation_score] FAIL — raise test coverage to reach 80% threshold.")
        return 1

    print(f"[check_mutation_score] All modules at or above {threshold}% threshold. PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
