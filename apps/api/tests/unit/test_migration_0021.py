"""Focused tests for Alembic revision 0021 (spec/011 step 1).

These tests exercise the additive zero-email migration without requiring
a live PostgreSQL connection. The migration module is loaded via
``importlib`` and its ``upgrade`` invocation is observed through a fake
``op`` that records every call. We then assert each expected DDL
operation (column add / table create / CHECK constraint) was issued.

Note: no secondary index is created on ``user_banner_dismissals`` —
the composite PK ``(user_id, audit_table, audit_log_id)`` already
covers the leading-column prefix scan needed for "list dismissals for
this user" (see ``data-model.md`` § ``user_banner_dismissals``).

The ``downgrade`` half of the migration is forward-only per spec/011
NFR-011-002, so we assert it raises ``NotImplementedError``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0021_zero_email_additive.py"
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
    spec = importlib.util.spec_from_file_location("migration_0021", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingOp:
    """Fake alembic ``op`` that captures every DDL call."""

    def __init__(self) -> None:
        self.add_column_calls: list[tuple[str, Any]] = []
        self.create_table_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.create_check_constraint_calls: list[tuple[str, str, str]] = []
        self.create_index_calls: list[tuple[str, str, list[str]]] = []
        self.other_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def add_column(self, table_name: str, column: Any) -> None:
        self.add_column_calls.append((table_name, column))

    def create_table(self, table_name: str, *args: Any, **kwargs: Any) -> None:
        self.create_table_calls.append((table_name, args))

    def create_check_constraint(
        self,
        constraint_name: str,
        table_name: str,
        condition: str,
        **kwargs: Any,
    ) -> None:
        self.create_check_constraint_calls.append(
            (constraint_name, table_name, condition)
        )

    def create_index(
        self,
        index_name: str,
        table_name: str,
        columns: list[str],
        **kwargs: Any,
    ) -> None:
        self.create_index_calls.append((index_name, table_name, columns))

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


def test_revision_identifiers_chain_from_0020() -> None:
    module = _load_migration()
    assert module.revision == "0021"
    assert module.down_revision == "0020"


def test_upgrade_adds_must_change_password_to_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_op = _run_upgrade(monkeypatch)
    matches = [
        col
        for table, col in fake_op.add_column_calls
        if table == "users" and col.name == "must_change_password"
    ]
    assert len(matches) == 1
    column = matches[0]
    assert column.nullable is False
    assert column.server_default is not None


def test_upgrade_adds_temp_password_expires_at_to_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_op = _run_upgrade(monkeypatch)
    matches = [
        col
        for table, col in fake_op.add_column_calls
        if table == "users" and col.name == "temp_password_expires_at"
    ]
    assert len(matches) == 1
    column = matches[0]
    assert column.nullable is True
    # TIMESTAMPTZ
    assert getattr(column.type, "timezone", False) is True


def test_upgrade_adds_email_change_cooldown_until_to_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_op = _run_upgrade(monkeypatch)
    matches = [
        col
        for table, col in fake_op.add_column_calls
        if table == "users" and col.name == "email_change_cooldown_until"
    ]
    assert len(matches) == 1
    column = matches[0]
    assert column.nullable is True
    assert getattr(column.type, "timezone", False) is True


def test_upgrade_adds_ownership_transfer_to_project_invitations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_op = _run_upgrade(monkeypatch)
    matches = [
        col
        for table, col in fake_op.add_column_calls
        if (
            table == "project_invitations"
            and col.name == "ownership_transfer_on_accept"
        )
    ]
    assert len(matches) == 1
    column = matches[0]
    assert column.nullable is False
    assert column.server_default is not None


def test_upgrade_creates_ownership_transfer_kind_member_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_op = _run_upgrade(monkeypatch)
    matches = [
        entry
        for entry in fake_op.create_check_constraint_calls
        if entry[0] == "ck_project_invitations_ownership_transfer_kind_member"
    ]
    assert len(matches) == 1
    name, table, condition = matches[0]
    assert table == "project_invitations"
    # The CHECK forbids any row with ownership_transfer_on_accept=true
    # unless kind = 'member'.
    assert "ownership_transfer_on_accept = false" in condition
    assert "kind = 'member'" in condition


def test_upgrade_creates_user_banner_dismissals_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_op = _run_upgrade(monkeypatch)
    table_names = [name for name, _ in fake_op.create_table_calls]
    assert "user_banner_dismissals" in table_names

    # Inspect the columns / constraints passed to create_table.
    matches = [
        args
        for name, args in fake_op.create_table_calls
        if name == "user_banner_dismissals"
    ]
    assert len(matches) == 1
    args = matches[0]

    # Columns by name.
    import sqlalchemy as sa  # local import keeps test file self-contained

    columns = {a.name: a for a in args if isinstance(a, sa.Column)}
    assert set(columns) == {
        "user_id",
        "audit_table",
        "audit_log_id",
        "dismissed_at",
    }
    assert columns["user_id"].nullable is False
    assert columns["audit_table"].nullable is False
    assert columns["audit_log_id"].nullable is False
    assert columns["dismissed_at"].nullable is False
    assert columns["dismissed_at"].server_default is not None

    # Composite primary key on (user_id, audit_table, audit_log_id).
    # Constraints created in a ``create_table`` call do not have their
    # ``columns`` collection populated until the constraint is attached
    # to a live Table; we therefore inspect ``_pending_colargs`` which
    # carries the raw column-name list captured at construction.
    pk_constraints = [a for a in args if isinstance(a, sa.PrimaryKeyConstraint)]
    assert len(pk_constraints) == 1
    assert list(pk_constraints[0]._pending_colargs) == [
        "user_id",
        "audit_table",
        "audit_log_id",
    ]

    # Foreign key on user_id with ON DELETE CASCADE.
    fk_constraints = [a for a in args if isinstance(a, sa.ForeignKeyConstraint)]
    assert len(fk_constraints) == 1
    fk = fk_constraints[0]
    assert list(fk._pending_colargs) == ["user_id"]
    assert any("users.id" in str(elem.target_fullname) for elem in fk.elements)
    assert fk.ondelete == "CASCADE"

    # CHECK constraint enumerates the two allowed audit tables.
    check_constraints = [a for a in args if isinstance(a, sa.CheckConstraint)]
    assert any(
        cc.name == "ck_user_banner_dismissals_audit_table"
        and "project_audit_log" in str(cc.sqltext)
        and "platform_audit_log" in str(cc.sqltext)
        for cc in check_constraints
    )


def test_upgrade_does_not_create_secondary_user_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No secondary index — composite PK is sufficient (data-model.md)."""
    fake_op = _run_upgrade(monkeypatch)
    assert fake_op.create_index_calls == []


def test_upgrade_does_not_drop_or_alter_existing_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 1 is additive-only — no drop / alter on the live schema."""
    fake_op = _run_upgrade(monkeypatch)
    forbidden_ops = {
        "drop_column",
        "drop_table",
        "drop_constraint",
        "drop_index",
        "alter_column",
    }
    unexpected = [call for call in fake_op.other_calls if call[0] in forbidden_ops]
    assert unexpected == []


def test_downgrade_raises_not_implemented_per_forward_only_policy() -> None:
    module = _load_migration()
    with pytest.raises(NotImplementedError, match="NFR-011-002"):
        module.downgrade()
