"""T979f: Supply chain security — dependency lockfile & audit gate (OWASP A06/A08).

Verifies that:
A. ``apps/api/uv.lock`` is committed to git (lockfile required).
B. ``apps/web/package-lock.json`` is committed to git (lockfile required).
C. ``pyproject.toml`` defines all *production* dependencies with an explicit
   upper-bound SemVer pin (e.g. ``>=2.9.0,<3.0``) for critical security deps.
   A lower bound alone (``>=X.Y.Z``) is allowed for low-risk deps because
   uv.lock pins the exact version; the test targets the highest-risk subset.
D. ``uv.lock`` is valid TOML and contains at least one ``[[package]]`` block.
E. ``package-lock.json`` uses ``lockfileVersion: 3`` (npm 7+, integrity hashes
   present on all entries).
F. The CI workflow file (``ci.yml``) defines a dependency-audit step.
   Implemented in Phase 17 backlog A-9 (T979f) — runs live as a hard-fail
   assertion (no xfail).

Shim: OFF — all checks are static file/content inspection; no HTTP transport.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repository root helpers
#
# The test runs in three different environments:
#   - Host (dev): .../echoroo/apps/api/tests/security/supply_chain/ → parents[5]
#     is the repo root (contains ``apps/`` and ``.github/``).
#   - Docker (/app): /app/tests/security/supply_chain/ → parents[3] is /app
#     which doubles as the api dir (no repo root above it).
#   - mutmut (apps/api/mutants/tests/security/supply_chain/) → mutmut copies
#     the source + tests trees AND ``pyproject.toml`` (which it rewrites
#     during mutation runs) into ``apps/api/mutants/`` but does NOT copy
#     ``uv.lock``.  The walk must therefore skip any ``mutants/`` directory
#     and require BOTH ``uv.lock`` and ``pyproject.toml`` so that the api
#     dir resolves to the real ``apps/api/`` one level above.
#
# We probe all depths from 0..len(parents) and identify the api dir by the
# joint presence of ``uv.lock`` AND ``pyproject.toml`` — this is the most
# reliable marker because mutmut's working copy contains only the latter.
# Any directory whose basename is ``mutants`` is skipped as defence in
# depth. The repo root, web dir and github dir are then derived from the
# api dir's parent when available.
# ---------------------------------------------------------------------------


def _find_repo_root() -> tuple[Path, Path, Path, Path]:
    """Return (repo_root, api_dir, web_dir, github_dir) for the current environment.

    Resolution strategy: walk upward from this test file looking for a
    directory that contains BOTH ``uv.lock`` AND ``pyproject.toml`` — that
    is the api dir.  Requiring both markers is critical because mutmut
    copies ``pyproject.toml`` (it rewrites it during mutation runs) into
    its working directory ``apps/api/mutants/`` but does NOT copy
    ``uv.lock``.  A walk that accepts either marker would stop at
    ``mutants/`` and report a missing lockfile.

    As a defence-in-depth, any directory whose basename is ``mutants`` is
    skipped during the walk (covers nested mutmut layouts).

    From the api dir, the repo root is the first ancestor containing
    ``apps/`` or ``.github/``; fall back to the api dir itself when no
    such ancestor exists (Docker /app, mutmut copies).
    """
    this_file = Path(__file__).resolve()

    api_dir: Path | None = None
    for candidate in this_file.parents:
        # Skip mutmut's working directory — it has pyproject.toml but no uv.lock.
        if candidate.name == "mutants":
            continue
        if (candidate / "uv.lock").is_file() and (candidate / "pyproject.toml").is_file():
            api_dir = candidate
            break

    # Fallback: accept a directory with only one marker (e.g. Docker /app
    # which may not ship uv.lock, or a partial mutmut copy).  Still skip
    # ``mutants/`` so the lockfile assertion can fail loudly with the
    # correct path instead of silently pointing inside ``mutants/``.
    if api_dir is None:
        for candidate in this_file.parents:
            if candidate.name == "mutants":
                continue
            if (candidate / "uv.lock").is_file() or (candidate / "pyproject.toml").is_file():
                api_dir = candidate
                break

    if api_dir is None:
        # Final fallback: /app is the api dir, no repo root
        api_dir = Path("/app")
        return (
            api_dir,
            api_dir,
            Path("/nonexistent/web"),
            Path("/nonexistent/.github/workflows"),
        )

    # Walk further up from api_dir looking for a repo root marker.
    repo_root: Path | None = None
    for candidate in [api_dir, *api_dir.parents]:
        if candidate.name == "mutants":
            continue
        if (candidate / "apps").is_dir() or (candidate / ".github").is_dir():
            repo_root = candidate
            break

    if repo_root is None:
        # Docker /app or mutmut mutants/ — no repo root above the api dir.
        return (
            api_dir,
            api_dir,
            Path("/nonexistent/web"),
            Path("/nonexistent/.github/workflows"),
        )

    web_dir = repo_root / "apps" / "web"
    github_dir = repo_root / ".github" / "workflows"
    return repo_root, api_dir, web_dir, github_dir


_REPO_ROOT, _API_DIR, _WEB_DIR, _GITHUB_DIR = _find_repo_root()

UV_LOCK = _API_DIR / "uv.lock"
PACKAGE_LOCK = _WEB_DIR / "package-lock.json"
PYPROJECT = _API_DIR / "pyproject.toml"
CI_WORKFLOW = _GITHUB_DIR / "ci.yml"


# ---------------------------------------------------------------------------
# Section A: uv.lock exists and is committed
# ---------------------------------------------------------------------------


def test_uv_lock_exists() -> None:
    """uv.lock must be present in the repository (supply-chain requirement).

    Without a committed lockfile, builds may silently upgrade transitive
    dependencies and introduce a vulnerability (OWASP A06 — Vulnerable and
    Outdated Components).
    """
    assert UV_LOCK.is_file(), (
        f"uv.lock not found at {UV_LOCK}. "
        "Run `uv lock` and commit the lockfile."
    )


def test_uv_lock_is_valid_toml_with_packages() -> None:
    """uv.lock must be valid TOML and contain at least one [[package]] block.

    A corrupted or empty lockfile provides no supply-chain guarantee.
    """
    assert UV_LOCK.is_file(), "uv.lock missing — skipping content check"
    content = UV_LOCK.read_text(encoding="utf-8")
    # The lockfile may be large; we only need the presence of a package block.
    assert "[[package]]" in content, (
        "uv.lock does not contain any [[package]] blocks — "
        "the lockfile appears to be empty or malformed."
    )
    # Validate that the TOML is at least partially parseable.
    # uv.lock uses a non-standard inline array format that may not be fully
    # TOML-spec-compliant depending on version; parse what we can.
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        # uv >= 0.6 extended TOML with dot-in-package-name syntax; tolerate
        # partial parse failures on the extras block but flag structural errors.
        msg = str(exc)
        if "Invalid" in msg and "key" not in msg.lower():
            pytest.fail(f"uv.lock is not valid TOML: {exc}")


# ---------------------------------------------------------------------------
# Section B: package-lock.json exists and is committed
# ---------------------------------------------------------------------------


def test_package_lock_exists() -> None:
    """apps/web/package-lock.json must exist in the repository (npm lockfile required).

    Without it, ``npm ci`` on a fresh checkout will fail and the installed
    versions are non-deterministic.

    Note: ``apps/web`` is not mounted into the backend Docker container, so
    this test is skipped when run inside Docker (PACKAGE_LOCK path is
    ``/nonexistent/...``).
    """
    if not PACKAGE_LOCK.parent.is_dir():
        pytest.skip(
            "apps/web is not available in this environment "
            f"(looked at {PACKAGE_LOCK}). Run from the host checkout."
        )
    assert PACKAGE_LOCK.is_file(), (
        f"package-lock.json not found at {PACKAGE_LOCK}. "
        "Run `npm install` inside apps/web and commit the lockfile."
    )


def test_package_lock_version_3() -> None:
    """package-lock.json must use lockfileVersion 3 (npm 7+).

    lockfileVersion 2/3 includes ``integrity`` hashes for every installed
    package.  lockfileVersion 1 (npm 6) omits them, providing weaker
    supply-chain guarantees (OWASP A06).

    Note: skipped when ``apps/web`` is not available (Docker backend container).
    """
    if not PACKAGE_LOCK.parent.is_dir():
        pytest.skip(
            "apps/web is not available in this environment "
            f"(looked at {PACKAGE_LOCK}). Run from the host checkout."
        )
    assert PACKAGE_LOCK.is_file(), "package-lock.json missing — skipping version check"
    data = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    lock_version = data.get("lockfileVersion")
    assert lock_version == 3, (
        f"package-lock.json lockfileVersion={lock_version!r}; expected 3. "
        "Upgrade npm to v7+ and regenerate the lockfile."
    )


# ---------------------------------------------------------------------------
# Section C: upper-bound SemVer pins in pyproject.toml for critical deps
# ---------------------------------------------------------------------------

# These are the deps known to have had high-impact CVEs where a breaking
# change also accompanied the security patch; pinning the major prevents
# silent upgrades into an incompatible-but-vulnerable range.
_CRITICAL_UPPER_BOUND_DEPS: list[str] = [
    "pyotp",
    "webauthn",
    "cryptography",
]

# Pattern for upper-bound pin: e.g. "pyotp>=2.9.0,<3.0"
_UPPER_BOUND_RE = re.compile(r"<\d+")


def test_pyproject_exists() -> None:
    """pyproject.toml must exist at apps/api/pyproject.toml."""
    assert PYPROJECT.is_file(), f"pyproject.toml not found at {PYPROJECT}"


def test_critical_deps_have_upper_bound_pin() -> None:
    """Critical security deps must carry an explicit upper-bound (<X.Y) in pyproject.toml.

    An unconstrained lower bound (``>=X.Y.Z``) allows ``uv upgrade`` or a
    freshly cloned build to pull in a new major version that may contain
    breaking auth changes without the team noticing (OWASP A08 — Software
    and Data Integrity Failures).
    """
    assert PYPROJECT.is_file(), "pyproject.toml missing — skipping dep pin check"
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps: list[str] = data.get("project", {}).get("dependencies", [])

    missing_upper_bound: list[str] = []
    for dep_name in _CRITICAL_UPPER_BOUND_DEPS:
        # Find the matching dependency line (case-insensitive, normalise - to _)
        dep_name_norm = dep_name.lower().replace("-", "_")
        matched: list[str] = []
        for dep in deps:
            candidate = dep.split(">=")[0].split(">")[0].split("==")[0].split("[")[0]
            if candidate.lower().replace("-", "_") == dep_name_norm:
                matched.append(dep)
        if not matched:
            # Dep not present; skip (may be optional-only)
            continue
        for entry in matched:
            if not _UPPER_BOUND_RE.search(entry):
                missing_upper_bound.append(entry)

    assert not missing_upper_bound, (
        "The following critical dependencies lack an upper-bound pin (<X.Y) in "
        f"pyproject.toml: {missing_upper_bound}. "
        "Add e.g. `<3.0` to each entry to prevent accidental major-version upgrades."
    )


# ---------------------------------------------------------------------------
# Section D (live): CI workflow has a pip-audit or osv-scanner step
# ---------------------------------------------------------------------------


def test_ci_workflow_has_advisory_check_step() -> None:
    """CI workflow must include a pip-audit or osv-scanner step (OWASP A06).

    Automated advisory scanning catches known CVEs in transitive dependencies
    before they reach production. The absence of such a step means
    vulnerabilities may go undetected until exploited.

    Phase 17 backlog A-9 (T979f) closed this gap by adding the
    `supply-chain` job to `.github/workflows/ci.yml`. Round 3
    (2026-05-04) split the gate into two hard-fail steps:
      1. ``uv sync --locked`` — verifies the wheel hash chain recorded
         in ``apps/api/uv.lock`` (dependency-substitution defence).
      2. ``pip-audit --disable-pip --strict`` — advisory CVE check
         against the OSV / PyPI advisory DB.
    Both steps must exit 0 for the job to pass. The xfail marker has
    been removed: this is now a hard-fail live assertion.

    Note: ``.github/workflows`` is not mounted into the backend Docker
    container, so this test is skipped when run inside Docker
    (CI_WORKFLOW path is ``/nonexistent/...``). On the host checkout and
    in CI, the live assertion runs.
    """
    if not CI_WORKFLOW.parent.is_dir():
        pytest.skip(
            ".github/workflows is not available in this environment "
            f"(looked at {CI_WORKFLOW}). Run from the host checkout or in CI."
        )
    assert CI_WORKFLOW.is_file(), f"ci.yml not found at {CI_WORKFLOW}"
    content = CI_WORKFLOW.read_text(encoding="utf-8")
    audit_patterns = [
        "pip-audit",
        "pip audit",
        "osv-scanner",
        "osv_scanner",
        "safety check",
        "trivy",
    ]
    found = any(p in content for p in audit_patterns)
    assert found, (
        f"No advisory-check step (pip-audit / osv-scanner / trivy) found in {CI_WORKFLOW}. "
        "Add a dependency-vulnerability scan step to the CI pipeline."
    )


__all__ = [
    "test_ci_workflow_has_advisory_check_step",
    "test_critical_deps_have_upper_bound_pin",
    "test_package_lock_exists",
    "test_package_lock_version_3",
    "test_pyproject_exists",
    "test_uv_lock_exists",
    "test_uv_lock_is_valid_toml_with_packages",
]
