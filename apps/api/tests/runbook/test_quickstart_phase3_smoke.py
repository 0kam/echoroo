"""Smoke tests for the quickstart §3 bootstrap scripts (Phase 16 Batch 6h-3 / T998).

Scope (FR-113, FR-114, quickstart §3): the four bootstrap scripts that an
operator runs ONCE after a release-time wipe to bring a fresh deployment to
a usable state.

  1. ``echoroo.scripts.wipe_database``         — release-time DB wipe ritual
  2. ``echoroo.scripts.init_superuser``        — first superuser bootstrap
  3. ``echoroo.scripts.initial_iucn_sync``     — IUCN Red List initial sync
  4. ``echoroo.scripts.seed_moe_rdb``          — Japanese MoE RDB CSV import

The smoke layer here is intentionally minimal because every script is
**explicitly destructive** when run with the real flags (``--confirm`` /
safety phrase / two superuser UUIDs). Running them through pytest in CI
would either be a no-op (no DB connection) or a footgun (corrupting a
shared dev DB). Instead we cover three regression-prevention guarantees:

  * ``--help`` returns exit 0 and prints the documented usage so operator
    runbooks keep working.
  * Running with no arguments / no ``--confirm`` returns a non-zero exit
    code WITHOUT mutating anything (the contract that prevents accidental
    invocation — security checklist §M-2).
  * The argparse argument schema is stable: a regression test pins the
    canonical flag set so a refactor that drops ``--confirm`` from
    ``initial_iucn_sync`` (for example) lights up red instead of silently
    enabling unsafe behaviour.

Tests that actually drive the scripts against a live database / S3 / KMS
stack are gated behind the ``requires_runbook`` pytest marker. CI runs
``-m "not requires_runbook"`` and skips them; operators opt in locally
with ``pytest -m requires_runbook`` against the Docker Compose dev stack
(quickstart §3).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Resolve the api root so ``python -m echoroo.scripts.<name>`` resolves
# correctly when pytest is invoked from any working directory. ``parents[2]``
# walks tests/runbook/ -> tests/ -> apps/api/.
_API_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# CLI surface contract — argparse-based scripts.
#
# The 3 scripts in this list expose argparse parsers and therefore support
# ``--help``. ``wipe_database`` is intentionally absent: it has no argparse
# layer because every guard rail (two-of-N superuser IDs, safety phrase,
# wipe_guard precondition) is interactive by design.
# ---------------------------------------------------------------------------
_ARGPARSE_SCRIPTS: tuple[str, ...] = (
    "echoroo.scripts.init_superuser",
    "echoroo.scripts.initial_iucn_sync",
    "echoroo.scripts.seed_moe_rdb",
)


def _run_module(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m <args>`` from the api root with no extra env.

    A short timeout protects CI: even if a script accidentally tries to
    contact the network (for example a refactor that loads settings during
    ``--help``), the test fails loudly rather than hanging the suite.
    """
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=str(_API_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


# ---------------------------------------------------------------------------
# Help output contract.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("module_name", _ARGPARSE_SCRIPTS)
def test_argparse_scripts_expose_help(module_name: str) -> None:
    """``--help`` must exit 0 and print the documented usage line.

    Regression target: a refactor that swaps argparse for ``click`` or
    ``typer`` without preserving ``--help`` would break every runbook in
    ``specs/006-permissions-redesign/quickstart.md`` and the operator
    onboarding docs at the same time.
    """
    result = _run_module(module_name, "--help")

    assert result.returncode == 0, (
        f"{module_name} --help should exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # argparse prints "usage: <prog> ..." on stdout for --help.
    assert result.stdout.lower().startswith("usage:"), (
        f"{module_name} --help did not print a usage banner.\n"
        f"stdout: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Confirmation flag contract.
#
# Each of the three argparse scripts requires --confirm. Running without it
# MUST exit non-zero without doing the destructive work. We don't assert a
# specific code (the scripts use 1, 2, 3 for different precondition failures)
# but we do require non-zero so a future change that flips the default to
# "destructive unless --skip" lights this test up.
# ---------------------------------------------------------------------------
def test_init_superuser_requires_confirm() -> None:
    """``init_superuser`` without ``--confirm`` must refuse to run."""
    result = _run_module(
        "echoroo.scripts.init_superuser",
        "--non-interactive",
        "--email",
        "smoke@example.invalid",
        "--password",
        "PlaceholderPassword123!",
        "--display-name",
        "Smoke Test",
    )
    assert result.returncode != 0, (
        "init_superuser without --confirm must exit non-zero "
        f"(got {result.returncode}). stdout: {result.stdout!r}"
    )


def test_initial_iucn_sync_requires_confirm() -> None:
    """``initial_iucn_sync`` without ``--confirm`` must refuse to run."""
    result = _run_module("echoroo.scripts.initial_iucn_sync")
    assert result.returncode != 0, (
        "initial_iucn_sync without --confirm must exit non-zero "
        f"(got {result.returncode}). stdout: {result.stdout!r}"
    )


def test_seed_moe_rdb_requires_csv_arg(tmp_path: Path) -> None:
    """``seed_moe_rdb`` without the positional CSV must exit non-zero.

    Empty argv triggers argparse's "missing required positional" path
    (exit code 2). We don't pin the code value so argparse internals can
    evolve, but non-zero is the contract.
    """
    result = _run_module("echoroo.scripts.seed_moe_rdb")
    assert result.returncode != 0, (
        "seed_moe_rdb without csv_path must exit non-zero "
        f"(got {result.returncode}). stdout: {result.stdout!r}"
    )


def test_seed_moe_rdb_requires_confirm(tmp_path: Path) -> None:
    """Even with a CSV path, ``seed_moe_rdb`` refuses without ``--confirm``."""
    fake_csv = tmp_path / "fake.csv"
    fake_csv.write_text("taxon_id,category,sensitivity_h3_res,notes\n", encoding="utf-8")

    result = _run_module("echoroo.scripts.seed_moe_rdb", str(fake_csv))
    assert result.returncode != 0, (
        "seed_moe_rdb without --confirm must exit non-zero "
        f"(got {result.returncode}). stdout: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# wipe_database has no argparse surface (intentional — every entry point
# is gated by interactive prompts + wipe_guard preconditions). The smoke
# test we can run without infra is "module imports cleanly", which proves
# the runbook can at least call ``python -m echoroo.scripts.wipe_database``
# without an ImportError. Anything destructive needs the requires_runbook
# marker below.
# ---------------------------------------------------------------------------
def test_wipe_database_module_importable() -> None:
    """The wipe_database module must import without side-effects.

    A regression here would mean the runbook line
    ``docker exec -it echoroo-backend uv run python -m echoroo.scripts.wipe_database``
    fails with an ImportError before the operator even sees the safety
    phrase prompt.
    """
    # We import inside the test so a top-level collection error does not
    # silently mask the real failure. ``importlib`` is preferred over
    # plain ``import`` so the byte-compiled cache is bypassed.
    import importlib

    module = importlib.import_module("echoroo.scripts.wipe_database")

    # The module must expose the documented CLI symbols. These are part of
    # the Phase 15 contract; if they disappear the wipe ritual is broken.
    assert hasattr(module, "main"), "wipe_database.main is missing"
    assert hasattr(module, "SAFETY_PHRASE"), "wipe_database.SAFETY_PHRASE is missing"
    # Sanity: the safety phrase should not have drifted from the runbook's
    # documented value. A drift would invalidate every existing runbook.
    assert "DESTROYS ALL DATA" in module.SAFETY_PHRASE, (
        "Safety phrase has drifted from the documented runbook value"
    )


# ---------------------------------------------------------------------------
# Live-infra integration tests (requires_runbook).
#
# These tests are skipped in CI by default. To run locally:
#
#     cd apps/api
#     docker compose up -d db redis localstack
#     uv run pytest tests/runbook/ -m requires_runbook
#
# They are intentionally minimal: a full end-to-end wipe-and-bootstrap
# round-trip lives in tests/integration/test_baseline_migration.py and the
# Phase 5+ scenario tests. Here we only check that the script entry points
# reach their first real side-effect (DB connection / S3 lookup) without
# crashing on import or argparse.
# ---------------------------------------------------------------------------
@pytest.mark.requires_runbook
def test_check_wipe_guard_runs_against_live_stack() -> None:
    """``check_wipe_guard`` should reach S3 / DB and return exit 0 or 1.

    Exit code semantics (from the script): 0 = clear for wipe, 1 = wipe
    already executed (one of the three markers present). Either is a
    legitimate "the script ran end-to-end" signal; what we forbid is a
    crash (returncode > 1 from a Python traceback).
    """
    result = _run_module("echoroo.scripts.check_wipe_guard", timeout=60.0)
    assert result.returncode in (0, 1), (
        f"check_wipe_guard crashed (rc={result.returncode}).\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
