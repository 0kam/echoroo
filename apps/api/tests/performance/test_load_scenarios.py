"""T990 — k6 load scenario file existence + syntax smoke tests.

This module asserts that the k6 placeholder scripts in
``tests/performance/scenarios/`` exist and (when k6 is installed) pass
``k6 validate``. Actual load execution is performed out-of-band by the CI
infrastructure team; these tests only gate *accidental deletion* of the
scenario files.

k6 validate
-----------
``k6 validate <script.js>`` performs a static parse of the k6 script
without running it, so it completes in milliseconds and requires no
network access or target server. If k6 is not installed the test is
*skipped* (not failed) so local developer environments without k6 are
unaffected.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Locate scenario files relative to this test module.
# ---------------------------------------------------------------------------

_SCENARIOS_DIR = Path(__file__).parent / "scenarios"

_EXPECTED_SCRIPTS = [
    "recording_list_100.js",      # T991 — recording list p95
    "auth_permission_check.js",   # T992 — auth + permission gate p95
    "audit_log_concurrent.js",    # T993 — audit log concurrent chain
    "webauthn_challenge.js",      # T992c — WebAuthn challenge latency
    "api_key_verify_hot.js",      # T992d — API key verify hot path
]


# ---------------------------------------------------------------------------
# Existence assertions (always run)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script_name", _EXPECTED_SCRIPTS)
def test_scenario_file_exists(script_name: str) -> None:
    """Each expected k6 scenario file must be present in the scenarios/ dir."""
    script_path = _SCENARIOS_DIR / script_name
    assert script_path.exists(), (
        f"k6 scenario file missing: {script_path}. "
        "If this was deleted intentionally, update _EXPECTED_SCRIPTS in "
        "tests/performance/test_load_scenarios.py."
    )
    assert script_path.is_file(), f"{script_path} exists but is not a regular file"
    assert script_path.stat().st_size > 0, f"{script_path} is an empty file"


def test_scenarios_directory_exists() -> None:
    """The scenarios/ directory itself must exist."""
    assert _SCENARIOS_DIR.exists(), (
        f"k6 scenarios directory missing: {_SCENARIOS_DIR}"
    )
    assert _SCENARIOS_DIR.is_dir()


def test_no_unexpected_files_in_scenarios() -> None:
    """scenarios/ must contain only the declared k6 .js files (+ __init__ if present).

    This catches accidental commits of large binary artefacts or secrets
    into the load test directory.
    """
    allowed_suffixes = {".js"}
    for path in _SCENARIOS_DIR.iterdir():
        if path.name.startswith("__"):
            continue  # allow __init__.py, __pycache__, etc.
        assert path.suffix in allowed_suffixes, (
            f"Unexpected file type in scenarios/: {path.name} "
            f"(only .js k6 scripts are allowed)"
        )


# ---------------------------------------------------------------------------
# k6 validate smoke (skipped when k6 not installed)
# ---------------------------------------------------------------------------


_K6_AVAILABLE = shutil.which("k6") is not None
_K6_SKIP_REASON = "k6 not installed — install k6 to run syntax validation"


@pytest.mark.skipif(not _K6_AVAILABLE, reason=_K6_SKIP_REASON)
@pytest.mark.parametrize("script_name", _EXPECTED_SCRIPTS)
def test_k6_validate_scenario(script_name: str) -> None:
    """``k6 validate`` must exit 0 for each scenario script."""
    script_path = _SCENARIOS_DIR / script_name
    result = subprocess.run(
        ["k6", "validate", str(script_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"k6 validate failed for {script_name}:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


@pytest.mark.skipif(not _K6_AVAILABLE, reason=_K6_SKIP_REASON)
def test_k6_version_is_available() -> None:
    """Sanity check that the installed k6 is executable."""
    result = subprocess.run(
        ["k6", "version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"k6 version failed: {result.stderr}"
    assert "k6" in result.stdout.lower(), f"Unexpected k6 version output: {result.stdout}"
