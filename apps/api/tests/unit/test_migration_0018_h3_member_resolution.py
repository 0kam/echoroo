"""Focused tests for Alembic revision 0018."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0018_sites_h3_member_resolution_5_15.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0018", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downgrade_preflights_before_restoring_legacy_site_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_migration()
    captured: list[str] = []

    class _FakeOp:
        @staticmethod
        def execute(stmt: Any) -> None:
            captured.append(str(stmt))

    monkeypatch.setattr(module, "op", _FakeOp)

    module.downgrade()

    site_preflight_index = next(
        i
        for i, sql in enumerate(captured)
        if "FROM sites" in sql
        and "h3_index_member_resolution NOT IN (9, 15)" in sql
        and "RAISE EXCEPTION" in sql
    )
    project_preflight_index = next(
        i
        for i, sql in enumerate(captured)
        if "FROM projects" in sql
        and "public_location_precision_h3_res" in sql
        and "NOT IN ('2', '3', '5', '7', '9', '15')" in sql
        and "RAISE EXCEPTION" in sql
    )
    drop_index = next(
        i for i, sql in enumerate(captured) if "DROP CONSTRAINT IF EXISTS" in sql
    )
    add_index = next(
        i
        for i, sql in enumerate(captured)
        if "CHECK (h3_index_member_resolution IN (9, 15))" in sql
    )

    assert site_preflight_index < drop_index < add_index
    assert project_preflight_index < drop_index < add_index

    assert not any(
        "UPDATE sites" in sql and "h3_index_member_resolution" in sql
        for sql in captured
    )
