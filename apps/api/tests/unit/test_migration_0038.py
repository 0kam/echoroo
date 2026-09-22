"""Focused tests for Alembic revision 0038."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0038_upload_resumable_columns.py"
)
MIGRATION_REVISION = "0038"
PREVIOUS_REVISION = "0037"


def _resolve_migration_path() -> Path:
    this_file = Path(__file__).resolve()
    candidates = [parent / _MIGRATION_RELATIVE_PATH for parent in this_file.parents]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


MIGRATION_PATH = _resolve_migration_path()


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"migration_{MIGRATION_REVISION}", MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingOp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def _record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return _record


def _record(direction: str, monkeypatch: pytest.MonkeyPatch) -> _RecordingOp:
    module = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)
    getattr(module, direction)()
    return recorder


def test_revision_identifiers() -> None:
    module = _load_migration()

    assert module.revision == MIGRATION_REVISION
    assert module.down_revision == PREVIOUS_REVISION


def test_upgrade_records_operations_in_required_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("upgrade", monkeypatch)

    operation_names = [name for name, _, _ in recorder.calls]
    assert operation_names == [
        "add_column",
        "add_column",
        "execute",
        "alter_column",
        "add_column",
        "create_check_constraint",
        "create_check_constraint",
        "create_check_constraint",
        "execute",
        "create_index",
    ]

    received = recorder.calls[0][1][1]
    declared = recorder.calls[1][1][1]
    chunk = recorder.calls[4][1][1]
    assert received.name == "received_bytes"
    assert declared.name == "declared_size"
    assert chunk.name == "chunk_digests"
    assert recorder.calls[3][1][1] == "declared_size"
    assert recorder.calls[3][2]["nullable"] is False

    checks = [
        args[0]
        for name, args, _ in recorder.calls
        if name == "create_check_constraint"
    ]
    assert checks == [
        "ck_upload_files_received_bytes_nonnegative",
        "ck_upload_files_received_within_declared",
        "ck_upload_files_chunk_digests_array",
    ]

    execute_sql = [
        str(args[0]) for name, args, _ in recorder.calls if name == "execute"
    ]
    assert "UPDATE upload_files SET declared_size = file_size" in execute_sql[0]
    assert "row_number()" in execute_sql[1]
    assert "'failed'" in execute_sql[1]

    index_args, index_kwargs = recorder.calls[-1][1:]
    assert index_args[0] == "ux_upload_sessions_active_dataset"
    assert index_kwargs["unique"] is True
    where = str(index_kwargs["postgresql_where"])
    for status in ("issued", "uploaded", "validating", "validated", "importing"):
        assert status in where


def test_downgrade_drops_index_constraints_and_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("downgrade", monkeypatch)

    assert [name for name, _, _ in recorder.calls] == [
        "drop_index",
        "drop_constraint",
        "drop_constraint",
        "drop_constraint",
        "drop_column",
        "drop_column",
        "drop_column",
    ]
    assert recorder.calls[0][1][0] == "ux_upload_sessions_active_dataset"
    assert [args[0] for name, args, _ in recorder.calls if name == "drop_constraint"] == [
        "ck_upload_files_chunk_digests_array",
        "ck_upload_files_received_within_declared",
        "ck_upload_files_received_bytes_nonnegative",
    ]
    assert [args[1] for name, args, _ in recorder.calls if name == "drop_column"] == [
        "chunk_digests",
        "declared_size",
        "received_bytes",
    ]


def test_migration_does_not_import_application_models() -> None:
    source = MIGRATION_PATH.read_text()

    assert "from echoroo" not in source
    assert "import echoroo" not in source
