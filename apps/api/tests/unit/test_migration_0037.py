"""Focused tests for Alembic revision 0037."""

from __future__ import annotations

import contextlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0037_upload_file_status_skipped.py"
)
MIGRATION_REVISION = "0037"
PREVIOUS_REVISION = "0036"


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


class _RecordingContext:
    def __init__(self) -> None:
        self.entered = False

    @contextlib.contextmanager
    def autocommit_block(self):
        self.entered = True
        yield


class _RecordingOp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.context = _RecordingContext()

    def get_context(self) -> _RecordingContext:
        return self.context

    def __getattr__(self, name: str) -> Any:
        def _record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return _record


def test_revision_identifiers() -> None:
    module = _load_migration()

    assert module.revision == MIGRATION_REVISION
    assert module.down_revision == PREVIOUS_REVISION


def test_upgrade_executes_enum_add_in_autocommit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()

    assert recorder.context.entered
    assert recorder.calls == [
        (
            "execute",
            ("ALTER TYPE uploadfilestatus ADD VALUE IF NOT EXISTS 'skipped'",),
            {},
        )
    ]


def test_downgrade_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.downgrade()

    assert recorder.calls == []


def test_migration_does_not_import_application_models() -> None:
    source = MIGRATION_PATH.read_text()

    assert "from echoroo" not in source
    assert "import echoroo" not in source
