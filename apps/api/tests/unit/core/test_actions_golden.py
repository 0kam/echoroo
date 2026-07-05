"""Golden snapshot test for the ACTIONS catalog (W3-5).

``echoroo.core.actions`` was refactored from 147 hand-written ``register_action``
stanzas into a single declarative table (``_ACTION_ROWS``) plus a factory loop.
This test machine-proves that the refactor is **semantics-preserving**: it
serializes the live ``ACTIONS`` registry with the exact same shape used to
generate the reviewed golden fixture and asserts byte-for-byte deep equality.

If this test fails, an Action's ``name`` / ``required_permission`` /
``is_mutating`` / ``is_superuser_only`` / ``is_platform_scope`` changed. That is
a **security-relevant semantic change to the permission gate**. Do NOT blindly
regenerate the fixture — a diff here must be reviewed explicitly and the fixture
only updated once the new authorization behavior is confirmed intentional.

Regenerate the fixture (only after explicit review) with::

    docker exec echoroo-backend uv run python -c "
    import json
    import echoroo.core.actions  # noqa: F401
    from echoroo.core.permissions import ACTIONS
    out = {name: {
        'required_permission': (a.required_permission.value if a.required_permission else None),
        'is_mutating': a.is_mutating,
        'is_superuser_only': a.is_superuser_only,
        'is_platform_scope': a.is_platform_scope,
    } for name, a in sorted(ACTIONS.items())}
    print(json.dumps(out, indent=2, sort_keys=True))
    " > apps/api/tests/unit/core/fixtures/actions_golden.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import echoroo.core.actions as actions_module  # noqa: F401 — side-effect: fills ACTIONS
from echoroo.core.permissions import ACTIONS

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "actions_golden.json"


def _serialize_registry() -> dict[str, dict[str, Any]]:
    """Serialize ACTIONS with the exact shape used to build the golden fixture."""
    return {
        name: {
            "required_permission": (
                action.required_permission.value
                if action.required_permission
                else None
            ),
            "is_mutating": action.is_mutating,
            "is_superuser_only": action.is_superuser_only,
            "is_platform_scope": action.is_platform_scope,
        }
        for name, action in sorted(ACTIONS.items())
    }


def test_actions_registry_matches_golden_snapshot() -> None:
    """The live ACTIONS registry must deep-equal the reviewed golden fixture.

    Any diff means an Action's authorization contract changed (a semantic change
    to the Stage-1 permission gate). See the module docstring before touching the
    fixture.
    """
    golden = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    actual = _serialize_registry()

    missing = sorted(set(golden) - set(actual))
    added = sorted(set(actual) - set(golden))
    changed = sorted(
        name
        for name in set(golden) & set(actual)
        if golden[name] != actual[name]
    )

    assert actual == golden, (
        "ACTIONS registry drifted from the golden fixture "
        f"({_FIXTURE_PATH.name}). This is a SEMANTIC change to the permission "
        "gate and must be reviewed explicitly — do NOT blindly regenerate the "
        "fixture.\n"
        f"  removed actions: {missing}\n"
        f"  added actions:   {added}\n"
        f"  changed actions: {changed}"
    )


def test_all_matches_table_and_registry() -> None:
    """__all__, the declarative table constants, and _BUILT must agree exactly.

    Guards against a row being added to the table without a corresponding typed
    re-binding (or vice versa) and keeps ``__all__`` from drifting.
    """
    table_consts = {row.const for row in actions_module._ACTION_ROWS}
    built_consts = set(actions_module._BUILT)
    all_consts = set(actions_module.__all__)

    # No accidental duplicate constant names in the table.
    table_const_list = [row.const for row in actions_module._ACTION_ROWS]
    assert len(table_const_list) == len(table_consts), (
        "Duplicate constant name in _ACTION_ROWS"
    )

    assert table_consts == built_consts, (
        "Table constants and _BUILT keys differ: "
        f"table-only={sorted(table_consts - built_consts)}, "
        f"built-only={sorted(built_consts - table_consts)}"
    )
    assert all_consts == table_consts, (
        "__all__ and table constants differ: "
        f"all-only={sorted(all_consts - table_consts)}, "
        f"table-only={sorted(table_consts - all_consts)}"
    )
    # Every exported constant is a real module-level Action bound by identity.
    for const in actions_module.__all__:
        bound = getattr(actions_module, const)
        assert bound is actions_module._BUILT[const], (
            f"{const} is not bound to its _BUILT Action by identity"
        )


def test_registry_action_count_matches_table() -> None:
    """Sanity: the registry must contain exactly one entry per table row."""
    assert len(actions_module._ACTION_ROWS) == len({r.name for r in actions_module._ACTION_ROWS})
    for row in actions_module._ACTION_ROWS:
        assert row.name in ACTIONS, f"table row {row.const} ({row.name}) not registered"
