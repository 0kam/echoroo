#!/usr/bin/env python3
"""Check mutmut mutation scores per module and enforce a configurable threshold.

Usage:
    cd apps/api && uv run python ../../scripts/check_mutation_score.py \\
        [--threshold N] [--warn-only]

Exit codes:
    0  All modules at or above threshold (or --warn-only).
    1  One or more modules below threshold (hard-fail mode).

This script is called by the CI ``mutation-testing`` job in
``.github/workflows/ci.yml`` after ``uv run python scripts/run_mutmut.py run``
completes.  It re-invokes ``mutmut results --all`` to get *every* mutant
(including killed ones — without ``--all`` the upstream CLI omits them) and
aggregates the per-mutant lines into per-module scores.

Per-mutant output format (mutmut 3.5)
-------------------------------------
The CLI emits one indented line per mutant::

    echoroo.workers.dormancy_check.x__emit_followup_stages__mutmut_8: survived
    echoroo.core.permissions.x_register_action__mutmut_1: not checked
    echoroo.services.api_key_verification.xǁDbApiKeyVerifierǁverify__mutmut_25: survived

Module name is everything up to (but not including) the trailing
``.x_<func>__mutmut_N`` or ``.xǁ<class>ǁ<method>__mutmut_N`` suffix.

Status taxonomy (from mutmut source, ``status_by_exit_code``):

- ``killed`` — mutant detected by the suite (counts toward kill rate)
- ``survived`` — mutant not detected (counts toward kill rate)
- ``suspicious`` — flaky / non-deterministic (counts toward kill rate)
- ``timeout`` — excluded from denominator (mutant created infinite loop)
- ``no tests`` — excluded from denominator (no test exercises mutant)
- ``not checked`` — excluded from denominator (mutmut never ran the mutant)
- ``skipped`` / ``caught by type check`` / ``segfault`` /
  ``check was interrupted by user`` — excluded from denominator

Score = ``killed / (killed + survived + suspicious) * 100`` (per module).

Threshold behaviour
-------------------
- Default threshold: ``80`` (%).
- ``--threshold N``: override the threshold (integer 0-100).
- ``--warn-only``: always exit 0 but print WARN lines for below-threshold
  modules.  Used during the Phase 17 §D-0/D-1 transition while the per-module
  test additions are pending (tracked in ``PHASE17_BACKLOG.md`` §D-1).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict

_THRESHOLD_DEFAULT = 80

# Pattern for a per-mutant result line (mutmut 3.5 output of ``mutmut results``):
#
#   "    echoroo.core.permissions.x_resolve_role__mutmut_69: timeout"
#
# Some mutants use the class-method form ``xǁClassǁmethod__mutmut_N`` (the
# ``ǁ`` separator is U+01C1, used by mutmut to mangle class-qualified names).
# ANSI colour escapes may appear when run from an interactive terminal; we
# strip them before matching.
_ANSI_ESC = re.compile(r"\x1b\[[0-9;]*m")
_MUTANT_LINE = re.compile(
    r"^(?P<module>echoroo(?:\.[A-Za-z_][A-Za-z0-9_]*)+)"
    r"\.x[_ǁ].*?__mutmut_\d+"
    r":\s+(?P<status>.+)$"
)

# Statuses that count toward the kill-rate denominator are inlined in
# ``_compute_score`` (killed / survived / suspicious).  Everything else
# (timeout / no tests / not checked / skipped / caught by type check /
# segfault / check was interrupted by user) is excluded so the score reflects
# only mutants the suite actually had a chance to detect.


def _strip_ansi(text: str) -> str:
    return _ANSI_ESC.sub("", text)


def _run_mutmut_results() -> list[str]:
    """Run ``mutmut results --all`` and return stdout/stderr lines.

    ``--all`` is required because the default ``mutmut results`` only prints
    non-killed mutants, which would prevent us from computing a kill rate.
    Working directory must be ``apps/api`` (caller's responsibility).
    """
    result = subprocess.run(
        [sys.executable, "-m", "mutmut", "results", "--all"],
        capture_output=True,
        text=True,
        check=False,
    )
    # mutmut may exit non-zero when survivors exist — that is expected here.
    if result.returncode not in (0, 1):
        print(
            f"[check_mutation_score] mutmut results exit {result.returncode}",
            file=sys.stderr,
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    return (result.stdout + result.stderr).splitlines()


def _parse_results(lines: list[str]) -> dict[str, dict[str, int]]:
    """Parse mutmut result lines into ``{module: {status: count}}``.

    Module is the dotted prefix before ``.x_<func>__mutmut_N`` or
    ``.xǁ<class>ǁ<method>__mutmut_N``.
    """
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for raw_line in lines:
        line = _strip_ansi(raw_line).strip()
        m = _MUTANT_LINE.match(line)
        if not m:
            continue
        module = m.group("module")
        status = m.group("status").strip().lower()
        counts[module][status] += 1
    return {k: dict(v) for k, v in counts.items()}


def _compute_score(counts: dict[str, int]) -> tuple[float, int, int]:
    """Return ``(score_pct, killed, total_in_denominator)`` for one module."""
    killed = counts.get("killed", 0)
    survived = counts.get("survived", 0)
    suspicious = counts.get("suspicious", 0)
    total = killed + survived + suspicious
    if total == 0:
        return 0.0, 0, 0
    return round(killed / total * 100, 1), killed, total


def _format_excluded(counts: dict[str, int]) -> str:
    """Render the excluded-status counts compactly (timeout / no tests / ...)."""
    parts: list[str] = []
    for status in (
        "timeout",
        "no tests",
        "not checked",
        "skipped",
        "caught by type check",
        "segfault",
    ):
        n = counts.get(status, 0)
        if n:
            parts.append(f"{status}={n}")
    return ", ".join(parts) if parts else "-"


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
        help="Print warnings but always exit 0 (use during Phase 17 §D-1 ramp).",
    )
    args = parser.parse_args(argv)
    threshold = args.threshold

    lines = _run_mutmut_results()
    if not lines:
        print(
            "[check_mutation_score] No mutmut results found — was mutmut run completed?"
        )
        return 0 if args.warn_only else 1

    counts_by_module = _parse_results(lines)

    if not counts_by_module:
        print("[check_mutation_score] No parseable result lines from mutmut output.")
        print("[check_mutation_score] Raw output (first 20 lines):")
        for line in lines[:20]:
            print("  ", line)
        return 0 if args.warn_only else 1

    failures: list[tuple[str, float, int, int]] = []

    print(
        f"\n{'Module':<55} {'Score':>7}  {'Killed':>7} / {'Scorable':<8}  "
        f"{'Excluded':<40} Status"
    )
    print("-" * 130)

    for module in sorted(counts_by_module):
        module_counts = counts_by_module[module]
        score, killed, total = _compute_score(module_counts)
        excluded = _format_excluded(module_counts)
        status_str = (
            "PASS" if score >= threshold else ("WARN" if args.warn_only else "FAIL")
        )
        print(
            f"{module:<55} {score:>6.1f}%  {killed:>7} / {total:<8}  "
            f"{excluded:<40} {status_str}"
        )
        if score < threshold:
            failures.append((module, score, killed, total))

    print()

    if failures:
        print(
            f"[check_mutation_score] {len(failures)} module(s) below "
            f"{threshold}% threshold:"
        )
        for module, score, killed, total in failures:
            print(f"  {module}: {score:.1f}% ({killed}/{total})")
        if args.warn_only:
            print(
                "[check_mutation_score] warn-only mode — exiting 0 "
                "(Phase 17 §D-1 ramp pending)."
            )
            return 0
        print(
            "[check_mutation_score] FAIL — raise test coverage or prove "
            "surviving mutants equivalent to reach the threshold."
        )
        return 1

    print(
        f"[check_mutation_score] All {len(counts_by_module)} module(s) at or "
        f"above {threshold}% threshold. PASS."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
