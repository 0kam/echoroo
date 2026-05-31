#!/usr/bin/env python3
"""Lint: hardcoded license ``short_name`` literals are forbidden in app code.

Enforces spec/012 SC-006 (T055): after the License Master Unification, the
canonical source of truth for the four content-license short names lives in
the ``licenses`` master table (seeded once by migration
``0023_license_master_unification``). User-facing surfaces — the backend API
package, the SvelteKit frontend, and the i18n message catalogues — must NOT
hardcode the literals ``CC0`` / ``CC-BY`` / ``CC-BY-NC`` / ``CC-BY-SA`` any
more; they must fetch the master list at runtime (``useLicenses()`` on the
frontend, the ``Licenses`` repository on the backend). A reintroduced literal
is a regression that silently desynchronises the UI from the master table.

Detection strategy:

    * Walk the configured scan roots:
        - ``apps/api/echoroo/**/*.py``         (backend API package)
        - ``apps/web/src/**/*.{ts,js,svelte}`` (frontend source)
        - ``apps/web/messages/*.json``         (i18n catalogues)
    * For each file, scan line by line for QUOTE-DELIMITED EXACT tokens
      using the regex ``["'](CC0|CC-BY|CC-BY-NC|CC-BY-SA)["']``. The
      surrounding quotes make the match exact: ``"CC-BY-NC"`` matches the
      ``CC-BY-NC`` token only (it is not double-counted as ``CC-BY``), and a
      bare substring inside a sentence (``"This is the CC-BY license"``) does
      NOT match because ``CC-BY`` there is bounded by spaces, not quotes.
    * Suppress individual matches listed in
      ``scripts/allowlists/hardcoded_licenses_allowlist.txt`` at the
      LINE-LEVEL fingerprint level
      (``<file>:<line>:<token>:hardcoded-license-short-name``). The line
      number is part of the fingerprint on purpose: with only four possible
      tokens a file-level fingerprint would fail OPEN (one entry would mask
      every occurrence of that token in the file, including a future leak).
      The line-level fingerprint fails CLOSED — editing the allowlisted
      region shifts the line, invalidates the entry, and re-surfaces the
      violation for re-justification.

Excluded from the scan (legitimate uses):

    * ``tests/`` — fixtures legitimately use the literals as id / short_name
      seed values.
    * ``specs/`` — spec documents legitimately cite the literals.
    * This lint script + its allowlist (they enumerate the tokens as data).

Scan scope NOTE: the seed migration
``apps/api/alembic/versions/0023_license_master_unification.py`` legitimately
contains the literals (its ``_LICENSE_ID_FOR_ENUM`` seed/map bootstraps the
master table; the migration is forward-only and never re-runs, so the literals
there are the canonical seed, not a hardcode). It needs no skip entry because
``alembic/`` is a SIBLING of the default scan root ``apps/api/echoroo`` and is
never enumerated. If the scan root is ever broadened to ``apps/api``, add that
path back to ``ALWAYS_SKIP_PATHS``.

NOTE: ``apps/api/echoroo/models/enums.py`` previously declared the now-deleted
``ProjectLicense`` enum literals. It is deliberately NOT on the skip list so a
future re-introduction of the enum would be caught by this gate.

Exit codes:

    0 — no violations (or violations present but ``--fail-on-violation`` unset)
    1 — at least one hardcoded literal found, with ``--fail-on-violation``
    2 — unexpected internal error

CI wiring (see .github/workflows/ci.yml): warn mode in the
``permissions-lint-warn`` job (no ``--fail-on-violation``) and blocking mode in
the ``permissions-strict-gate`` job (with ``--fail-on-violation``).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Forbidden license short_name tokens (spec/012 SC-006).
FORBIDDEN_TOKENS: tuple[str, ...] = ("CC0", "CC-BY", "CC-BY-NC", "CC-BY-SA")

# Quote-delimited exact-token regex. The alternation is ordered longest-first
# so the regex engine prefers ``CC-BY-NC`` / ``CC-BY-SA`` over the ``CC-BY``
# prefix; combined with the trailing closing quote this guarantees a single
# unambiguous match per quoted literal (no double-counting).
_TOKEN_RE = re.compile(
    r"""["'](CC-BY-NC|CC-BY-SA|CC-BY|CC0)["']"""
)

# File-level always-skip suffixes (POSIX, checkout-location independent).
# Currently empty: the only candidate, the forward-only seed migration
# ``apps/api/alembic/versions/0023_license_master_unification.py``, lives in
# ``alembic/`` which is a SIBLING of the default scan root ``apps/api/echoroo``
# and is therefore never enumerated by ``_iter_scan_files`` (the entry would be
# dead code). Re-add it here only if the scan root is broadened to ``apps/api``.
ALWAYS_SKIP_PATHS: tuple[str, ...] = ()

# Directory-segment exclusions (any path containing one of these segments is
# skipped). ``tests`` covers both ``apps/api/.../tests/`` and any frontend test
# directory; ``specs`` covers the repo-level spec docs.
EXCLUDED_DIR_SEGMENTS: frozenset[str] = frozenset({"tests", "specs"})

# Default scan roots and the file globs to scan within each.
DEFAULT_API_ROOT = Path("apps/api/echoroo")
DEFAULT_WEB_SRC_ROOT = Path("apps/web/src")
DEFAULT_WEB_MESSAGES_ROOT = Path("apps/web/messages")

_WEB_SRC_SUFFIXES: frozenset[str] = frozenset({".ts", ".js", ".svelte"})

DEFAULT_ALLOWLIST = Path("scripts/allowlists/hardcoded_licenses_allowlist.txt")

# This script and its allowlist must never flag themselves (they enumerate the
# tokens as data). Matched by POSIX suffix.
_SELF_PATHS: tuple[str, ...] = (
    "scripts/lint_hardcoded_licenses.py",
    "scripts/allowlists/hardcoded_licenses_allowlist.txt",
)


# ---------------------------------------------------------------------------
# Allowlist loading
# ---------------------------------------------------------------------------


def _load_allowlist(path: Path) -> frozenset[str]:
    """Load a line-level fingerprint allowlist.

    Format: ``<file>:<line>:<token>:hardcoded-license-short-name``. Inline
    comments use ``  #`` (two spaces + hash); lines beginning with ``#`` are
    full-line comments. See scripts/allowlists/README.md.
    """
    if not path.exists():
        return frozenset()
    entries: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.split("  #", 1)[0].strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(stripped)
    return frozenset(entries)


def _violation_fingerprint(rel_str: str, line_no: int, token: str) -> str:
    """Stable LINE-LEVEL fingerprint for one hardcoded-license violation.

    The source line number is part of the fingerprint on purpose: with only
    four possible tokens, a file-level ``<file>:<token>:...`` fingerprint would
    suppress EVERY occurrence of that token in the file — including any future
    genuinely-hardcoded leak — i.e. it would fail OPEN. By pinning the line
    number the allowlist fails CLOSED: editing the allowlisted region shifts
    the line number, invalidates the fingerprint, and forces the violation to
    be re-justified (mirroring the discriminator every sibling lint embeds).
    """
    return f"{rel_str}:{line_no}:{token}:hardcoded-license-short-name"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _detect_repo_root(start: Path) -> Path:
    candidate = start.resolve()
    for _ in range(8):
        if (candidate / ".git").exists():
            return candidate
        if candidate.parent == candidate:
            return candidate
        candidate = candidate.parent
    return candidate


def _relative_posix(path: Path, repo_root: Path) -> str:
    abs_path = path.resolve()
    try:
        rel = abs_path.relative_to(repo_root.resolve())
    except ValueError:
        rel = path
    return str(rel).replace("\\", "/")


def _is_always_skipped(posix: str) -> bool:
    if any(posix.endswith(suffix) for suffix in ALWAYS_SKIP_PATHS):
        return True
    if any(posix.endswith(suffix) for suffix in _SELF_PATHS):
        return True
    return False


def _is_excluded_dir(posix: str) -> bool:
    """True when any path segment is an excluded directory (tests / specs)."""
    return any(segment in EXCLUDED_DIR_SEGMENTS for segment in posix.split("/"))


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _scan_text(
    rel_str: str, source: str, allowlist: frozenset[str]
) -> list[str]:
    """Return violation strings for a single source file.

    Each quote-delimited forbidden token produces one violation line. The
    regex anchors on the surrounding quotes so substrings inside a sentence
    do not match and longer tokens are not double-counted.
    """
    violations: list[str] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        for match in _TOKEN_RE.finditer(line):
            token = match.group(1)
            fp = _violation_fingerprint(rel_str, line_no, token)
            if fp in allowlist:
                continue
            violations.append(
                f"{rel_str}:{line_no}  hardcoded license short_name "
                f"'{token}' (fetch the master list at runtime instead)  "
                f"[fingerprint: {fp}]"
            )
    return violations


def _iter_scan_files(
    api_root: Path,
    web_src_root: Path,
    web_messages_root: Path,
) -> list[Path]:
    """Collect the set of files to scan across all configured roots."""
    files: list[Path] = []

    if api_root.exists():
        files.extend(sorted(api_root.rglob("*.py")))

    if web_src_root.exists():
        for path in sorted(web_src_root.rglob("*")):
            if path.is_file() and path.suffix in _WEB_SRC_SUFFIXES:
                files.append(path)

    if web_messages_root.exists():
        files.extend(sorted(web_messages_root.glob("*.json")))

    return files


def find_violations(
    api_root: Path,
    web_src_root: Path,
    web_messages_root: Path,
    allowlist: frozenset[str],
    repo_root: Path | None = None,
) -> list[str]:
    """Scan all roots and return human-readable violation lines."""
    if repo_root is None:
        repo_root = _detect_repo_root(api_root)

    violations: list[str] = []
    for path in _iter_scan_files(api_root, web_src_root, web_messages_root):
        rel_str = _relative_posix(path, repo_root)
        if _is_always_skipped(rel_str) or _is_excluded_dir(rel_str):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(f"{rel_str}: failed to read ({exc})")
            continue
        violations.extend(_scan_text(rel_str, source, allowlist))
    return violations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-path",
        type=Path,
        default=DEFAULT_API_ROOT,
        help=f"Backend Python root to scan (default: {DEFAULT_API_ROOT}).",
    )
    parser.add_argument(
        "--web-src-path",
        type=Path,
        default=DEFAULT_WEB_SRC_ROOT,
        help=f"Frontend source root to scan (default: {DEFAULT_WEB_SRC_ROOT}).",
    )
    parser.add_argument(
        "--web-messages-path",
        type=Path,
        default=DEFAULT_WEB_MESSAGES_ROOT,
        help=(
            "Frontend i18n message catalogue root to scan "
            f"(default: {DEFAULT_WEB_MESSAGES_ROOT})."
        ),
    )
    parser.add_argument(
        "--allowlist-file",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=(
            f"Fingerprint allowlist (default: {DEFAULT_ALLOWLIST}). Each "
            "non-comment line is a stable LINE-LEVEL fingerprint of the form "
            "<file>:<line>:<token>:hardcoded-license-short-name."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root for path normalisation (default: auto-detect).",
    )
    parser.add_argument(
        "--fail-on-violation",
        action="store_true",
        help="Exit with status 1 if any violations are found.",
    )
    args = parser.parse_args()

    try:
        allowlist = _load_allowlist(args.allowlist_file)
        violations = find_violations(
            args.api_path,
            args.web_src_path,
            args.web_messages_path,
            allowlist,
            repo_root=args.repo_root,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"[lint_hardcoded_licenses] unexpected error: {exc}",
            file=sys.stderr,
        )
        return 2

    for line in violations:
        print(line, file=sys.stderr)
    print(
        f"[lint_hardcoded_licenses] scanned api={args.api_path} "
        f"web-src={args.web_src_path} messages={args.web_messages_path}: "
        f"{len(violations)} violation(s) found",
        file=sys.stderr,
    )
    if violations and args.fail_on_violation:
        print(
            f"[lint_hardcoded_licenses] {len(violations)} violation(s); "
            "fetch license short_names from the master table at runtime "
            "(spec/012 SC-006)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
