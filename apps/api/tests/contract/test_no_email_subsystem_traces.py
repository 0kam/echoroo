"""spec/011 NFR-011-001 — guard against email-subsystem regressions.

After the email-verification subsystem is deleted (spec/011 Step 10),
the codebase MUST NOT carry any reference to the Resend SDK, SMTP
helpers, or the deleted email-side functions / columns / settings.
This CI guard scans the listed source roots for the NFR-011-001 grep
pattern and asserts zero matches outside historical / spec / test
scaffolding.

The regex pattern is copied verbatim from ``specs/011-zero-email-
deployment/spec.md`` §NFR-011-001:

  resend|mailpit|aiosmtplib|smtplib|SMTP_HOST|SMTP_PORT|SMTP_USER|
  SMTP_PASSWORD|send_verification_email|send_password_reset_email|
  send_2fa_reset_magic_link|email_verified_at|EMAIL_VERIFICATION|
  RESEND_API_KEY|EMAIL_FROM

Step 10 R1 extension — URL-path residue
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Codex R1 review found that the spec's identifier-based regex did not
catch runtime path-string residue (``"/web-api/v1/auth/password-reset/
confirm"``) that survived T128 cleanup inside
``two_factor_enforcement.py``. We extend the guard with the three URL
fragments owned by the deleted surface:

* ``/verify-email``
* ``/password-reset``
* ``/2fa-reset/magic-link``

The spec regex itself is unchanged — this extension lives in the
guard test only and is documented as an R1 expansion. The extra
patterns sit behind the SAME ``re.IGNORECASE`` flag and the SAME
comment-stripping pipeline so existing exclusions (this file,
historical migrations, etc.) continue to apply.

Bare ``smtp`` (lowercase) is intentionally NOT in the pattern because
``email_validator``'s ``allow_smtputf8=True`` keyword (RFC 6531 charset
support) legitimately appears in user-input normalisation paths.

Exclusion rules (spec §NFR-011-001 closing paragraph):

* ``specs/010-*`` / ``specs/011-*`` / any other spec/* documents.
* The test file itself (this module).
* Any test file with ``_legacy`` in the stem (none currently exist;
  retained as a future escape hatch).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pytest

# Grep pattern — keep byte-for-byte aligned with spec §NFR-011-001.
#
# Step 10 R1 (2026-05-23): the trailing alternation block beginning
# with ``/verify-email`` is the R1 URL-path extension documented in
# the module docstring. The literal forward slash prefix is what
# distinguishes it from the spec regex's identifier alternatives.
_EMAIL_REGEX = re.compile(
    r"resend|mailpit|aiosmtplib|smtplib|SMTP_HOST|SMTP_PORT|SMTP_USER|"
    r"SMTP_PASSWORD|send_verification_email|send_password_reset_email|"
    r"send_2fa_reset_magic_link|email_verified_at|EMAIL_VERIFICATION|"
    r"RESEND_API_KEY|EMAIL_FROM|"
    # R1 extension — URL path residue (see module docstring).
    r"/verify-email|/password-reset|/2fa-reset/magic-link",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    """Locate the repository root.

    The guard test runs in two contexts:

    1. **Local / CI host** — invoked from a checkout where the test file
       lives at ``apps/api/tests/contract/test_no_email_subsystem_traces.py``.
       The repo root has both ``apps/`` and ``scripts/`` siblings.
    2. **Docker container** — invoked under ``/app`` where the API
       subtree is flattened (``/app/echoroo``, ``/app/tests``) and the
       repository root is bind-mounted at ``/repo`` (or similar). The
       harness skips with a clear message in that case.

    The detection walks parent directories of this test file looking for
    the ``apps/`` + ``scripts/`` pair. If neither layout matches, the
    test is skipped with a diagnostic so the operator can decide
    whether to invoke a host-side run instead.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "apps").is_dir() and (parent / "scripts").is_dir():
            return parent
    pytest.skip(
        "repository root not located from test file path — run this "
        "guard from the host checkout (the docker container's /app "
        "tree does not carry the top-level apps/ + scripts/ layout)."
    )


# Roots scanned. Mirrors the spec §NFR-011-001 target list.
_SCAN_ROOTS = (
    "apps",
    "scripts",
    ".github/workflows",
    "docs/runbook",
    "apps/api/alembic",
)

# Single files scanned in addition to the directory roots.
_SCAN_FILES = (
    "compose.dev.yaml",
    ".env.example",
    "apps/api/README.md",
    "README.md",
)

# Per-path exclusion predicates. A file is excluded if any predicate
# returns ``True`` against its repo-relative POSIX path.
_EXCLUSION_PREDICATES = (
    # Spec / historical documents. spec/010 + spec/011 own the historical
    # email-subsystem context; this guard intentionally never scans them
    # per NFR-011-001 closing paragraph.
    lambda rel: rel.startswith("specs/"),
    # Documentation reports archive (research / postmortem markdowns).
    lambda rel: rel.startswith("docs/reports/"),
    # The test file itself (NFR-011-001 closing paragraph).
    lambda rel: rel.endswith("apps/api/tests/contract/test_no_email_subsystem_traces.py"),
    # Future escape hatch: any test file with ``_legacy`` in the stem.
    lambda rel: "_legacy" in Path(rel).name,
    # Historical Alembic migrations that pre-date spec/011 and reference
    # the now-removed columns / tables / dispatcher event-types as the
    # very subject of their forward-only DDL. Per NFR-011-001 these are
    # "historical spec/010 documents" in code form — the
    # ``0022_email_subsystem_removal`` migration that lands in spec/011
    # Step 11 will likewise reference these names because it drops them.
    lambda rel: rel.startswith("apps/api/alembic/versions/.archive/"),
    lambda rel: re.match(
        r"^apps/api/alembic/versions/(0019_email_verification|0021_zero_email|0022_email_subsystem)",
        rel,
    )
    is not None,
    # spec/011 Step 11 migration tests (T700/T701) verify the destructive
    # ``0022_email_subsystem_removal`` migration drops the
    # ``email_verified_at`` column and the email-token tables; they
    # therefore reference the deleted-surface identifiers as the very
    # subject of their assertions. Same rationale as the migration-file
    # exclusion above — historical-by-design.
    lambda rel: rel == "apps/api/tests/unit/test_migration_0022.py",
    lambda rel: rel
    == "apps/api/tests/integration/migrations/test_0022_email_subsystem_removal.py",
    # spec/011 Step 10b handles the frontend cleanup (T140-T149). Until
    # that PR lands the SvelteKit tree still references the deleted
    # surface in legacy stores, tests, and route components. The
    # backend-half PR (Step 10a) excludes ``apps/web/`` so the
    # transient drift between backend deletion and frontend deletion
    # does not regress CI. Step 10b removes this exclusion.
    lambda rel: rel.startswith("apps/web/"),
    # Generated / vendored / build outputs.
    lambda rel: any(part in {"__pycache__", "node_modules", ".venv", "dist", "build"} for part in Path(rel).parts),
    # Compiled bytecode + minified JS.
    lambda rel: Path(rel).suffix in {".pyc", ".pyo", ".min.js", ".min.css", ".map"},
)


def _is_excluded(rel_path: str) -> bool:
    return any(predicate(rel_path) for predicate in _EXCLUSION_PREDICATES)


def _candidate_files(root: Path) -> Iterable[Path]:
    """Yield text files under ``root`` (best-effort encoding sniff)."""
    if not root.exists():
        return
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # Skip obvious binary suffixes.
        if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".whl", ".tar", ".gz", ".zip", ".woff", ".woff2", ".ttf", ".eot", ".wav", ".mp3", ".mp4", ".webm", ".so", ".dylib", ".dll"}:
            continue
        yield path


_DOCSTRING_QUOTES = ('"""', "'''")


def _strip_python_comment_and_docstring_segments(
    text: str, suffix: str
) -> Iterable[tuple[int, str]]:
    """Yield ``(lineno, scannable_part)`` per source line.

    Python comments + triple-quoted docstring bodies are stripped from
    the scannable part. Other languages return the line verbatim.
    Markdown / YAML / TOML files are scanned with no comment-stripping
    because their "comment" syntax varies and they are documentation /
    config where the patterns are normally meaningful (the few
    legitimate documentation comments are handled via case-by-case
    rewrite or the path-exclusion list).
    """
    if suffix in {".toml", ".yml", ".yaml", ".cfg", ".ini"}:
        # Shell-style ``#`` comments.
        for lineno, raw_line in enumerate(text.splitlines(), start=1):
            scratch = raw_line
            if "#" in scratch:
                scratch = scratch[: scratch.index("#")]
            yield lineno, scratch
        return
    if suffix == ".py":
        in_docstring = False
        docstring_quote: str | None = None
        for lineno, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line
            # Cheap docstring tracker: a line that opens/closes a
            # ``"""`` or ``'''`` toggles the flag for subsequent lines.
            # If a docstring opens AND closes on the same line, the
            # state stays consistent.
            scratch = line
            while True:
                if not in_docstring:
                    starts = [
                        (scratch.find(q), q) for q in _DOCSTRING_QUOTES if q in scratch
                    ]
                    starts = [s for s in starts if s[0] >= 0]
                    if not starts:
                        break
                    start_idx, quote = min(starts, key=lambda t: t[0])
                    after_open = scratch[start_idx + 3 :]
                    if quote in after_open:
                        # Single-line docstring; strip from open to close.
                        close_idx = after_open.find(quote)
                        scratch = scratch[:start_idx] + after_open[close_idx + 3 :]
                        continue
                    # Multi-line docstring opens here; strip everything
                    # from the quote onwards.
                    scratch = scratch[:start_idx]
                    in_docstring = True
                    docstring_quote = quote
                    break
                # Currently inside a docstring; look for the close.
                assert docstring_quote is not None
                if docstring_quote in scratch:
                    close_idx = scratch.find(docstring_quote)
                    scratch = scratch[close_idx + 3 :]
                    in_docstring = False
                    docstring_quote = None
                    continue
                scratch = ""
                break
            # Strip ``#`` comments outside of strings (cheap heuristic —
            # does not handle ``"# inside"`` strings, but for our purposes
            # treating ``"text containing # something"`` as code is fine).
            if "#" in scratch:
                scratch = scratch[: scratch.index("#")]
            yield lineno, scratch
        return
    # Non-Python: yield as-is.
    for lineno, line in enumerate(text.splitlines(), start=1):
        yield lineno, line


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, line)`` tuples for every NFR-011-001 match.

    Python files have ``#`` comments + triple-quoted docstrings
    stripped before matching so historical "this was the legacy
    behaviour" comments do not regress the guard. Non-Python files
    are scanned verbatim.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[tuple[int, str]] = []
    suffix = path.suffix.lower()
    for lineno, scanned in _strip_python_comment_and_docstring_segments(text, suffix):
        if _EMAIL_REGEX.search(scanned):
            hits.append((lineno, scanned.rstrip()))
    return hits


def test_no_email_subsystem_traces() -> None:
    """spec/011 NFR-011-001 — zero matches outside spec/test scaffolding."""
    root = _repo_root()
    violations: list[str] = []

    scanned_paths: set[Path] = set()
    for rel_root in _SCAN_ROOTS:
        for path in _candidate_files(root / rel_root):
            scanned_paths.add(path)
    for rel_file in _SCAN_FILES:
        file_path = root / rel_file
        if file_path.exists():
            scanned_paths.add(file_path)

    for path in sorted(scanned_paths):
        rel = path.relative_to(root).as_posix()
        if _is_excluded(rel):
            continue
        for lineno, line in _scan_file(path):
            violations.append(f"{rel}:{lineno}: {line}")

    if violations:
        joined = "\n".join(violations[:50])
        more = "" if len(violations) <= 50 else f"\n... and {len(violations) - 50} more"
        pytest.fail(
            "spec/011 NFR-011-001 violation — found email-subsystem "
            f"traces ({len(violations)} matches):\n{joined}{more}"
        )
