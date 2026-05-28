"""T081 — meta-test for the multi-spec OpenAPI harness extension.

spec/011 NFR-011-009 widens
``apps/api/tests/contract/test_openapi_diff.py`` so the contract subset
assertion runs against multiple directories: the spec/006 baseline,
spec/011 zero-email contracts, and spec/012 license-master contracts.
This meta-test pins the refactor itself:

* ``_CONTRACTS_DIRS`` is a tuple (multi-dir support active).
* All expected directories are members of the tuple.
* Every yaml under each directory loads cleanly (catches parse errors
  introduced by future PRs that touch the contract YAMLs without
  re-running the harness locally).
* The union of yamls matches the documented count
  (8 spec/006 + 6 spec/011 + 3 spec/012 = 17) — a regression guard that
  catches a yaml being silently deleted or duplicated.

The harness has NO snapshot file (NFR-011-009). When a future step adds
a new yaml or removes one, this test SHOULD be updated to reflect the
new count — that update belongs in the same PR as the contract change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.contract.test_openapi_diff import (
    _CONTRACTS_DIRS,
    _contracts_available,
    _load_contract,
)

#: spec/011 zero-email contracts inventory (T081 + tasks.md Step 6).
#: The exact filenames are checked so a typo or rename gets caught.
_SPEC_011_EXPECTED_STEMS: frozenset[str] = frozenset(
    {
        "admin-password-reset",
        "invitation-public",
        "me-banners-activity",
        "member-invitations",
        "su-bootstrap-project-create",
        "trusted-users-invitation-url",
    }
)

#: spec/006 baseline inventory at the time of the spec/011 Step 6 merge.
#: When the spec/006 set changes (very rare — only follow-up patches
#: would add to it), update this set and the total below in lock-step.
_SPEC_006_EXPECTED_STEMS: frozenset[str] = frozenset(
    {
        "account",
        "admin",
        "audit",
        "auth",
        "detections",
        "projects",
        "taxa",
        "trusted",
    }
)

_SPEC_012_EXPECTED_STEMS: frozenset[str] = frozenset(
    {
        "admin-licenses-delete",
        "licenses",
        "web-licenses",
    }
)

_EXPECTED_TOTAL_YAML_COUNT: int = (
    len(_SPEC_006_EXPECTED_STEMS)
    + len(_SPEC_011_EXPECTED_STEMS)
    + len(_SPEC_012_EXPECTED_STEMS)
)


def _skip_if_no_spec_tree() -> None:
    if not _contracts_available():
        pytest.skip(
            "Contract YAML tree not present (in-container run); the host "
            "tree is the canonical source for this meta-test."
        )


class TestContractsDirsTuple:
    """Pin the ``_CONTRACTS_DIRS`` tuple shape and membership."""

    def test_contracts_dirs_is_tuple(self) -> None:
        """``_CONTRACTS_DIRS`` is a tuple (not a single Path / list).

        The tuple shape is the contract — downstream code in
        ``test_openapi_diff.py`` iterates it, and a list could silently
        be mutated by an over-eager monkeypatch.
        """
        assert isinstance(_CONTRACTS_DIRS, tuple), (
            f"_CONTRACTS_DIRS must be a tuple, got {type(_CONTRACTS_DIRS)!r}"
        )

    def test_contracts_dirs_contains_expected_specs(self) -> None:
        """spec/006, spec/011, and spec/012 directories are tuple members."""
        _skip_if_no_spec_tree()
        names = {p.name for p in _CONTRACTS_DIRS}
        assert "contracts" in names, (
            "_CONTRACTS_DIRS entries should resolve to a 'contracts' "
            f"directory each — got {[str(p) for p in _CONTRACTS_DIRS]}"
        )
        # The parent directory of each contracts dir identifies the spec.
        parents = {p.parent.name for p in _CONTRACTS_DIRS}
        assert "006-permissions-redesign" in parents, (
            "spec/006 contracts directory missing from _CONTRACTS_DIRS "
            f"— parents={parents}"
        )
        assert "011-zero-email-deployment" in parents, (
            "spec/011 contracts directory missing from _CONTRACTS_DIRS "
            f"— parents={parents}"
        )
        assert "012-license-master-unification" in parents, (
            "spec/012 contracts directory missing from _CONTRACTS_DIRS "
            f"— parents={parents}"
        )


class TestSpec011YamlInventory:
    """Pin the spec/011 yaml inventory."""

    def test_all_spec_011_yamls_load(self) -> None:
        """Every yaml under specs/011-zero-email-deployment/contracts/ loads."""
        _skip_if_no_spec_tree()
        spec_011_dir: Path | None = None
        for directory in _CONTRACTS_DIRS:
            if directory.parent.name == "011-zero-email-deployment":
                spec_011_dir = directory
                break
        if spec_011_dir is None or not spec_011_dir.exists():
            pytest.skip("spec/011 contracts directory not present")
        found: set[str] = set()
        parse_errors: list[str] = []
        for yaml_path in sorted(spec_011_dir.glob("*.yaml")):
            try:
                _load_contract(yaml_path)
            except Exception as exc:  # noqa: BLE001 — parse / shape error
                parse_errors.append(f"{yaml_path.name}: {exc!r}")
                continue
            found.add(yaml_path.stem)
        assert not parse_errors, (
            "spec/011 contract yaml load errors:\n"
            + "\n".join(parse_errors)
        )
        missing = _SPEC_011_EXPECTED_STEMS - found
        unexpected = found - _SPEC_011_EXPECTED_STEMS
        assert not missing, (
            f"spec/011 expected yaml(s) missing: {sorted(missing)} "
            f"(found {sorted(found)})"
        )
        assert not unexpected, (
            f"spec/011 unexpected yaml(s) found: {sorted(unexpected)} "
            "— update _SPEC_011_EXPECTED_STEMS in the same PR"
        )


class TestSpec012YamlInventory:
    """Pin the spec/012 yaml inventory."""

    def test_all_spec_012_yamls_load(self) -> None:
        """Every yaml under specs/012-license-master-unification/contracts/ loads."""
        _skip_if_no_spec_tree()
        spec_012_dir: Path | None = None
        for directory in _CONTRACTS_DIRS:
            if directory.parent.name == "012-license-master-unification":
                spec_012_dir = directory
                break
        if spec_012_dir is None or not spec_012_dir.exists():
            pytest.skip("spec/012 contracts directory not present")
        found: set[str] = set()
        parse_errors: list[str] = []
        for yaml_path in sorted(spec_012_dir.glob("*.yaml")):
            try:
                _load_contract(yaml_path)
            except Exception as exc:  # noqa: BLE001 — parse / shape error
                parse_errors.append(f"{yaml_path.name}: {exc!r}")
                continue
            found.add(yaml_path.stem)
        assert not parse_errors, (
            "spec/012 contract yaml load errors:\n" + "\n".join(parse_errors)
        )
        missing = _SPEC_012_EXPECTED_STEMS - found
        unexpected = found - _SPEC_012_EXPECTED_STEMS
        assert not missing, (
            f"spec/012 expected yaml(s) missing: {sorted(missing)} "
            f"(found {sorted(found)})"
        )
        assert not unexpected, (
            f"spec/012 unexpected yaml(s) found: {sorted(unexpected)} "
            "— update _SPEC_012_EXPECTED_STEMS in the same PR"
        )


class TestUnionInventory:
    """Pin the union of yamls across both contract directories."""

    def test_total_yaml_count_matches_expected(self) -> None:
        """Total yaml count = spec/006 baseline + spec/011 inventory."""
        _skip_if_no_spec_tree()
        total = 0
        for directory in _CONTRACTS_DIRS:
            if not directory.exists():
                continue
            total += sum(1 for _ in directory.glob("*.yaml"))
        assert total == _EXPECTED_TOTAL_YAML_COUNT, (
            f"Expected {_EXPECTED_TOTAL_YAML_COUNT} yaml files across "
            f"{[p.name for p in _CONTRACTS_DIRS]}, found {total}. "
            "When you add/remove a contract yaml, update "
            "_SPEC_006_EXPECTED_STEMS, _SPEC_011_EXPECTED_STEMS, or "
            "_SPEC_012_EXPECTED_STEMS in this file in the same PR."
        )
