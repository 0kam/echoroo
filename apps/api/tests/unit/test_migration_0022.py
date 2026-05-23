"""Focused tests for Alembic revision 0022 (spec/011 step 11).

These tests exercise the destructive zero-email migration without
requiring a live PostgreSQL connection. The migration module is loaded
via ``importlib`` and its ``upgrade`` invocation is observed through a
fake ``op`` that records every call. We then assert each expected DDL
operation (two ``drop_table`` calls and one ``drop_column`` call) was
issued.

The ``downgrade`` half of the migration is forward-only per spec/011
NFR-011-002, so we assert it raises ``NotImplementedError``.

The companion integration test
``tests/integration/migrations/test_0022_email_subsystem_removal.py``
exercises the same migration against a real PostgreSQL container so the
DDL is also proven valid SQL. This unit test gives a fast, container-
free signal that the migration's *intent* matches FR-011-002/003.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0022_email_subsystem_removal.py"
)


def _resolve_migration_path() -> Path:
    """Walk parents to find the migration file regardless of cwd."""
    this_file = Path(__file__).resolve()
    candidates = [parent / _MIGRATION_RELATIVE_PATH for parent in this_file.parents]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


MIGRATION_PATH = _resolve_migration_path()


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0022", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingOp:
    """Fake alembic ``op`` that captures every DDL call."""

    def __init__(self) -> None:
        self.drop_table_calls: list[str] = []
        self.drop_column_calls: list[tuple[str, str]] = []
        self.other_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def drop_table(self, table_name: str, **kwargs: Any) -> None:
        self.drop_table_calls.append(table_name)

    def drop_column(self, table_name: str, column_name: str, **kwargs: Any) -> None:
        self.drop_column_calls.append((table_name, column_name))

    def __getattr__(self, name: str) -> Any:
        # Catch unexpected op.* calls so the test fails loudly if the
        # migration grows new operations without a matching assertion.
        def _record(*args: Any, **kwargs: Any) -> None:
            self.other_calls.append((name, args, kwargs))

        return _record


def _run_upgrade(monkeypatch: pytest.MonkeyPatch) -> _RecordingOp:
    module = _load_migration()
    fake_op = _RecordingOp()
    monkeypatch.setattr(module, "op", fake_op)
    module.upgrade()
    return fake_op


def test_revision_identifiers_chain_from_0021() -> None:
    module = _load_migration()
    assert module.revision == "0022"
    assert module.down_revision == "0021"


def test_upgrade_drops_email_verification_tokens_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_op = _run_upgrade(monkeypatch)
    assert "email_verification_tokens" in fake_op.drop_table_calls


def test_upgrade_drops_password_reset_tokens_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_op = _run_upgrade(monkeypatch)
    assert "password_reset_tokens" in fake_op.drop_table_calls


def test_upgrade_drops_email_verified_at_column_on_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_op = _run_upgrade(monkeypatch)
    assert ("users", "email_verified_at") in fake_op.drop_column_calls


def test_upgrade_does_not_touch_trusted_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HANDOFF.md line 73 scopes the destructive surface to the email
    tokens + ``email_verified_at``. ``trusted_devices`` (added in
    ``0019_*`` alongside ``email_verified_at``) remains operational
    post-zero-email and MUST NOT be dropped here."""
    fake_op = _run_upgrade(monkeypatch)
    assert "trusted_devices" not in fake_op.drop_table_calls
    assert not any(
        table == "trusted_devices" for table, _ in fake_op.drop_column_calls
    )


def test_upgrade_issues_exactly_three_destructive_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two ``drop_table`` calls + one ``drop_column`` call — nothing
    else. This guards against accidental scope creep (e.g. dropping
    extra indexes or constraints) since ``DROP TABLE`` already cascades
    to dependent indexes in PostgreSQL."""
    fake_op = _run_upgrade(monkeypatch)
    assert len(fake_op.drop_table_calls) == 2
    assert len(fake_op.drop_column_calls) == 1
    # No other op.* calls were issued (e.g. drop_index / drop_constraint).
    assert fake_op.other_calls == []


def test_downgrade_raises_not_implemented_per_forward_only_policy() -> None:
    module = _load_migration()
    with pytest.raises(NotImplementedError, match="NFR-011-002"):
        module.downgrade()
