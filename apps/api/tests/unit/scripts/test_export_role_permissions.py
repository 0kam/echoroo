"""Unit tests for ``scripts/export_role_permissions_to_json.py``.

These exercise the fixture builder and the ``--check`` drift gate so the
CI workflow ``permissions-fixture-drift.yml`` has a stable contract.

The script lives outside the ``apps/api`` package, so the tests import it
via ``importlib.util`` from a path computed relative to the repo root
(``__file__`` → tests/unit/scripts/ → up 4 → repo root). This avoids the
need to install the script as a real module while still letting mypy /
ruff lint it as standard Python.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Path to the script under test
# ---------------------------------------------------------------------------

# tests/unit/scripts/test_export_role_permissions.py
#   parents[0] = tests/unit/scripts
#   parents[1] = tests/unit
#   parents[2] = tests
#   parents[3] = apps/api
#   parents[4] = repo root  (on the host; inside the dev container the tests
#                            are baked into ``/app/tests`` so parents[4] = "/"
#                            and the script must be located via the
#                            ``ECHOROO_EXPORT_SCRIPT_PATH`` env var or by a
#                            common-location fallback).
def _resolve_script_path() -> Path:
    override = os.environ.get("ECHOROO_EXPORT_SCRIPT_PATH")
    if override:
        return Path(override)
    candidates = [
        Path(__file__).resolve().parents[4] / "scripts" / "export_role_permissions_to_json.py",
        # Common dev-container location after ``docker cp``.
        Path("/tmp/export_role_permissions_to_json.py"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # Fall back to the first candidate so the FileNotFoundError surfaces a
    # canonical path in the test failure.
    return candidates[0]


_SCRIPT_PATH = _resolve_script_path()


def _load_script(tmp_repo_root: Path) -> ModuleType:
    """Load the script as an importable module with a private repo root.

    Setting ``ECHOROO_REPO_ROOT`` before import causes the module-level
    ``OUTPUT_PATH`` constant to point inside ``tmp_repo_root`` so each
    test has an isolated filesystem state.
    """
    os.environ["ECHOROO_REPO_ROOT"] = str(tmp_repo_root)
    # Ensure a fresh import — the module caches ``OUTPUT_PATH`` at import time.
    sys.modules.pop("_export_role_permissions_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "_export_role_permissions_under_test",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# build_fixture()
# ---------------------------------------------------------------------------

def test_build_fixture_has_all_expected_top_level_keys(tmp_path: Path) -> None:
    module = _load_script(tmp_path)
    fixture = module.build_fixture()
    assert set(fixture.keys()) == {
        "generated_at_utc",
        "generated_from_commit",
        "permissions",
        "categories",
        "role_permissions",
        "frontend_project_permissions",
        "visibility_overlays",
    }


def test_build_fixture_permissions_are_sorted_and_complete(tmp_path: Path) -> None:
    module = _load_script(tmp_path)
    fixture = module.build_fixture()
    perms = fixture["permissions"]
    assert perms == sorted(perms), "permissions must be sorted for stable output"
    # 29 = 27 project-scope + 2 user-scope (MANAGE_API_KEY / MANAGE_2FA).
    assert len(perms) == 29


def test_build_fixture_categories_partition_full_enum(tmp_path: Path) -> None:
    module = _load_script(tmp_path)
    fixture = module.build_fixture()
    cats = fixture["categories"]
    expected_category_keys = {
        "endpoint_backed",
        "computed_only",
        "user_scope",
        "superuser_only",
        "frontend_project",
    }
    assert set(cats.keys()) == expected_category_keys

    # The first four are the partition (frontend_project is a separate view).
    partition_union = (
        set(cats["endpoint_backed"])
        | set(cats["computed_only"])
        | set(cats["user_scope"])
        | set(cats["superuser_only"])
    )
    assert partition_union == set(fixture["permissions"]), (
        "endpoint_backed + computed_only + user_scope + superuser_only must "
        "cover every Permission member exactly once"
    )


def test_build_fixture_role_permissions_has_four_roles(tmp_path: Path) -> None:
    module = _load_script(tmp_path)
    fixture = module.build_fixture()
    assert set(fixture["role_permissions"].keys()) == {
        "viewer",
        "member",
        "admin",
        "owner",
    }
    # Sanity: Owner is a superset of Admin, Admin is a superset of Member, etc.
    viewer = set(fixture["role_permissions"]["viewer"])
    member = set(fixture["role_permissions"]["member"])
    admin = set(fixture["role_permissions"]["admin"])
    owner = set(fixture["role_permissions"]["owner"])
    assert viewer < member, "Viewer must be a strict subset of Member"
    assert member < admin, "Member must be a strict subset of Admin"
    assert admin < owner, "Admin must be a strict subset of Owner"


def test_build_fixture_visibility_overlays_has_expected_shape(tmp_path: Path) -> None:
    module = _load_script(tmp_path)
    fixture = module.build_fixture()
    overlays = fixture["visibility_overlays"]
    assert set(overlays.keys()) == {"public", "restricted_toggles"}
    assert set(overlays["public"].keys()) == {"guest", "authenticated_non_member"}
    assert set(overlays["restricted_toggles"].keys()) == {
        "allow_media_playback",
        "allow_detection_view",
        "allow_download",
        "allow_export",
        "allow_voting_and_comments",
        "allow_precise_location_to_viewer",
    }


def test_build_fixture_is_deterministic(tmp_path: Path) -> None:
    """Two invocations of build_fixture() differ only in ``generated_at_utc``."""
    module = _load_script(tmp_path)
    a = module.build_fixture()
    b = module.build_fixture()
    # Strip timestamp before comparing.
    a.pop("generated_at_utc")
    b.pop("generated_at_utc")
    assert a == b


# ---------------------------------------------------------------------------
# --check mode
# ---------------------------------------------------------------------------

def test_check_mode_returns_0_on_matching_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script(tmp_path)
    # First write the fixture, then re-run with --check.
    sys.argv = ["export_role_permissions_to_json.py"]
    assert module.main() == 0
    sys.argv = ["export_role_permissions_to_json.py", "--check"]
    rc = module.main()
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "OK" in captured.out


def test_check_mode_returns_1_on_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script(tmp_path)
    # Seed a stale fixture.
    out_path: Path = module.OUTPUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"permissions": ["stale"]}) + "\n")
    sys.argv = ["export_role_permissions_to_json.py", "--check"]
    rc = module.main()
    captured = capsys.readouterr()
    assert rc == 1
    assert "out of date" in captured.err


def test_check_mode_returns_1_when_fixture_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script(tmp_path)
    sys.argv = ["export_role_permissions_to_json.py", "--check"]
    rc = module.main()
    captured = capsys.readouterr()
    assert rc == 1
    assert "does not exist" in captured.err


def test_check_mode_ignores_timestamp_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``generated_at_utc`` differences must NOT trigger drift."""
    module = _load_script(tmp_path)
    sys.argv = ["export_role_permissions_to_json.py"]
    assert module.main() == 0
    # Mutate the on-disk fixture's timestamp only.
    text = module.OUTPUT_PATH.read_text()
    mutated = text.replace(
        '"generated_at_utc":', '"generated_at_utc": "1970-01-01T00:00:00+00:00", "_ignored":'
    )
    module.OUTPUT_PATH.write_text(mutated)
    sys.argv = ["export_role_permissions_to_json.py", "--check"]
    # The strip is line-based, so we additionally need the line containing
    # generated_at_utc to be the only thing that differs. Use a simpler
    # mutation: rewrite just the timestamp value on its own line.
    rebuilt = []
    for line in text.splitlines():
        if '"generated_at_utc"' in line:
            rebuilt.append('  "generated_at_utc": "1970-01-01T00:00:00+00:00",')
        else:
            rebuilt.append(line)
    module.OUTPUT_PATH.write_text("\n".join(rebuilt) + "\n")
    rc = module.main()
    captured = capsys.readouterr()
    assert rc == 0, captured.err
