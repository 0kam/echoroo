"""Unit tests for echoroo.core.actions and Action validation (T995, PR-004).

These tests target the action catalog and Action model validator to ensure
high mutation score for the `core/actions.py` and the `register_action`
function in `core/permissions.py`.

Coverage goals (mutation score >= 80%):
  * register_action: idempotency, duplicate-detection ValueError
  * Action._validate_consistency: platform_scope + superuser_only invariants
  * ACTIONS catalog: all exported Actions have required_permission set
    correctly for their scope
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from echoroo.core.permissions import (
    ACTIONS,
    SUPERUSER_PROJECT_SCOPE_ALLOWLIST,
    Action,
    Permission,
    register_action,
)

# ---------------------------------------------------------------------------
# Action model validator — is_platform_scope invariants
# ---------------------------------------------------------------------------


class TestActionValidation:
    """Tests for Action._validate_consistency model validator."""

    def test_platform_scope_requires_superuser_only(self) -> None:
        with pytest.raises(ValueError, match="is_superuser_only=True"):
            Action(
                name="test.bad_platform",
                required_permission=None,
                is_mutating=False,
                is_superuser_only=False,  # violates constraint
                is_platform_scope=True,
            )

    def test_platform_scope_forbids_required_permission(self) -> None:
        with pytest.raises(ValueError, match="required_permission=None"):
            Action(
                name="test.bad_platform_perm",
                required_permission=Permission.EDIT_PROJECT,  # violates constraint
                is_mutating=False,
                is_superuser_only=True,
                is_platform_scope=True,
            )

    def test_project_scope_requires_required_permission(self) -> None:
        with pytest.raises(ValueError, match="required_permission"):
            Action(
                name="test.no_perm",
                required_permission=None,
                is_mutating=False,
                is_superuser_only=False,
                is_platform_scope=False,
            )

    def test_valid_project_scope_action(self) -> None:
        a = Action(
            name="test.valid_project",
            required_permission=Permission.VIEW_DETECTION,
            is_mutating=False,
        )
        assert a.required_permission == Permission.VIEW_DETECTION
        assert not a.is_platform_scope
        assert not a.is_superuser_only

    def test_valid_platform_scope_action(self) -> None:
        a = Action(
            name="test.valid_platform",
            required_permission=None,
            is_mutating=True,
            is_superuser_only=True,
            is_platform_scope=True,
        )
        assert a.is_platform_scope
        assert a.is_superuser_only
        assert a.required_permission is None

    def test_superuser_only_project_scope_action_allowed(self) -> None:
        """is_superuser_only=True on a project-scope action is valid (e.g. project.archive)."""
        a = Action(
            name="test.superuser_project",
            required_permission=Permission.EDIT_PROJECT,
            is_mutating=True,
            is_superuser_only=True,
            is_platform_scope=False,
        )
        assert a.is_superuser_only
        assert a.required_permission == Permission.EDIT_PROJECT

    def test_action_is_frozen(self) -> None:
        """Action must be immutable (frozen=True in ConfigDict)."""
        a = Action(
            name="test.frozen",
            required_permission=Permission.VOTE,
            is_mutating=True,
        )
        with pytest.raises((ValidationError, TypeError)):
            a.name = "changed"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        """extra='forbid' in ConfigDict must raise on unknown fields."""
        with pytest.raises((ValidationError, TypeError)):
            Action(
                name="test.extra",
                required_permission=Permission.VOTE,
                is_mutating=False,
                unknown_field="should_fail",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# register_action — idempotency and duplicate detection
# ---------------------------------------------------------------------------


class TestRegisterAction:
    """Tests for register_action in core/permissions.py."""

    def test_register_returns_same_action(self) -> None:
        """register_action must return the action passed to it."""
        a = Action(
            name="_test.register_return",
            required_permission=Permission.VIEW_MEDIA,
            is_mutating=False,
        )
        result = register_action(a)
        assert result is a
        # Clean up to avoid polluting the global ACTIONS catalog
        ACTIONS.pop("_test.register_return", None)

    def test_register_stores_in_catalog(self) -> None:
        a = Action(
            name="_test.catalog_store",
            required_permission=Permission.DOWNLOAD,
            is_mutating=False,
        )
        register_action(a)
        assert "_test.catalog_store" in ACTIONS
        assert ACTIONS["_test.catalog_store"] == a
        ACTIONS.pop("_test.catalog_store", None)

    def test_idempotent_re_registration_is_allowed(self) -> None:
        """Registering the same action twice is idempotent (no error)."""
        a = Action(
            name="_test.idempotent",
            required_permission=Permission.VOTE,
            is_mutating=True,
        )
        register_action(a)
        # Same object (or equal object) — should not raise
        register_action(a)
        ACTIONS.pop("_test.idempotent", None)

    def test_duplicate_name_different_shape_raises(self) -> None:
        """Duplicate registration with a different Action shape must raise ValueError."""
        name = "_test.duplicate_conflict"
        a = Action(name=name, required_permission=Permission.VOTE, is_mutating=True)
        b = Action(name=name, required_permission=Permission.COMMENT, is_mutating=True)
        register_action(a)
        try:
            with pytest.raises(ValueError, match="Duplicate"):
                register_action(b)
        finally:
            ACTIONS.pop(name, None)


# ---------------------------------------------------------------------------
# ACTIONS catalog integrity — spot-check key properties
# ---------------------------------------------------------------------------


class TestActionsCatalogIntegrity:
    """Verify the global ACTIONS catalog is well-formed after module import."""

    def test_catalog_is_non_empty(self) -> None:
        """The catalog must be populated by importing echoroo.core.actions."""
        # Import side-effects fill ACTIONS via register_action calls.
        import echoroo.core.actions  # noqa: F401
        assert len(ACTIONS) > 0

    def test_all_project_scope_actions_have_required_permission(self) -> None:
        import echoroo.core.actions  # noqa: F401
        for name, action in ACTIONS.items():
            if not action.is_platform_scope:
                assert action.required_permission is not None, (
                    f"{name} is project-scope but has required_permission=None"
                )

    def test_all_platform_scope_actions_are_superuser_only(self) -> None:
        import echoroo.core.actions  # noqa: F401
        for name, action in ACTIONS.items():
            if action.is_platform_scope:
                assert action.is_superuser_only, (
                    f"{name} is platform-scope but is_superuser_only=False"
                )

    def test_all_platform_scope_actions_have_no_required_permission(self) -> None:
        import echoroo.core.actions  # noqa: F401
        for name, action in ACTIONS.items():
            if action.is_platform_scope:
                assert action.required_permission is None, (
                    f"{name} is platform-scope but has required_permission set"
                )

    def test_superuser_project_scope_allowlist_known_entries(self) -> None:
        """SUPERUSER_PROJECT_SCOPE_ALLOWLIST entries that have a corresponding
        ACTIONS registration must exist in ACTIONS.

        Notes on the two unmatched allowlist entries:
        - `project.iucn.force_resync` is registered as `platform.iucn.force_resync`
          in ACTIONS (platform-scope alias used by the gate algorithm).
        - `project.audit_log.read_platform` is handled by the admin router without
          a catalog entry (out-of-scope note in actions.py module docstring).
        """
        import echoroo.core.actions  # noqa: F401
        # These allowlist entries have direct ACTIONS registrations:
        direct_matches = {
            "project.archive",
            "project.restore",
            "project.taxon_override.approve_looser",
            "project.taxon_override.reject_looser",
        }
        for name in direct_matches:
            assert name in SUPERUSER_PROJECT_SCOPE_ALLOWLIST, (
                f"{name!r} expected in SUPERUSER_PROJECT_SCOPE_ALLOWLIST"
            )
            assert name in ACTIONS, (
                f"Allowlist action {name!r} expected in ACTIONS but missing"
            )
        # Verify the allowlist is non-empty (regression guard)
        assert len(SUPERUSER_PROJECT_SCOPE_ALLOWLIST) >= 4

    def test_mutating_actions_have_is_mutating_true(self) -> None:
        """Spot-check: project.delete should be mutating."""
        import echoroo.core.actions  # noqa: F401
        assert ACTIONS["project.delete"].is_mutating is True

    def test_non_mutating_actions_have_is_mutating_false(self) -> None:
        """Spot-check: project.get should not be mutating."""
        import echoroo.core.actions  # noqa: F401
        assert ACTIONS["project.get"].is_mutating is False

    def test_project_archive_is_superuser_only(self) -> None:
        import echoroo.core.actions  # noqa: F401
        assert ACTIONS["project.archive"].is_superuser_only is True

    def test_project_restore_is_superuser_only(self) -> None:
        import echoroo.core.actions  # noqa: F401
        assert ACTIONS["project.restore"].is_superuser_only is True

    def test_platform_iucn_resync_is_platform_scope(self) -> None:
        import echoroo.core.actions  # noqa: F401
        assert ACTIONS["platform.iucn.force_resync"].is_platform_scope is True

    def test_action_names_are_unique(self) -> None:
        """Catalog keys must all be unique (register_action enforces this)."""
        import echoroo.core.actions  # noqa: F401
        names = list(ACTIONS.keys())
        assert len(names) == len(set(names))
