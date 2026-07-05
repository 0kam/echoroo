"""T980: OpenAPI diff tests — contract/*.yaml vs live app.openapi() (SC-019).

Validates that the paths, response codes, request-body schemas, and
security requirements declared in the contract YAML files are present
in the FastAPI-generated openapi.json. Contract directories live under
``_CONTRACTS_DIRS`` and currently include:

* ``specs/006-permissions-redesign/contracts/`` — the permission baseline.
* ``specs/011-zero-email-deployment/contracts/`` — additive surface
  introduced by the spec/011 step-wise rollout (NFR-011-009). YAMLs in
  this directory describe endpoints that are landed by later steps;
  only the yamls whose paths already exist in the live app are
  subset-asserted at any given moment. The harness has **no snapshot
  file** — it loads YAML on each run and compares directly to the live
  ``app.openapi()`` output. Future contributors should not add
  snapshot-regeneration logic; instead, update the YAML and re-run.
* ``specs/012-license-master-unification/contracts/`` — the license
  master read/delete contracts landed by spec/012 PR-A.

Design notes
------------
* The comparison is *contract → app* (contract is the golden source).
  Extra paths in the app that are not mentioned in the contracts are
  **not** treated as failures — the app can expose internal or legacy
  paths.
* YAML contracts use logical scheme names (``apiKeyAuth``,
  ``sessionCookie``, ``csrfToken``); the generated schema uses
  ``HTTPBearer``.  The normalise helper maps both vocabularies to a
  single canonical set so the diff stays meaningful.
* Path templates in contracts use ``{id}`` / ``{projectId}``; the app
  uses ``{project_id}`` / ``{id}`` etc.  Normalisation converts all
  ``{…}`` segments to a wildcard ``{*}`` before comparison.
* When the specs/ tree is not present (in-container runs where only
  apps/api/ is bind-mounted) every test is skipped instead of failing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI

from echoroo.main import create_app

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Resolve the repo root regardless of whether we run from the host source
# tree (…/echoroo/apps/api/tests/contract/test_openapi_diff.py → 5 levels)
# or from inside the container (/app/tests/contract/… → 3 levels).
# We walk up until we find the ``specs`` directory or exhaust parents.
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT: Path | None = None
for _parent in _THIS_FILE.parents:
    if (_parent / "specs" / "006-permissions-redesign" / "contracts").exists():
        _REPO_ROOT = _parent
        break

# spec/011 Step 6 (T080): the harness now subset-asserts against MULTIPLE
# contract directories. Order matters only for the meta-test count
# assertion (T081). When the spec tree is not present (container-only
# runs) the tuple is left empty and every fixture skips its tests.
_CONTRACTS_DIRS: tuple[Path, ...] = (
    (
        _REPO_ROOT / "specs" / "006-permissions-redesign" / "contracts",
        _REPO_ROOT / "specs" / "011-zero-email-deployment" / "contracts",
        _REPO_ROOT / "specs" / "012-license-master-unification" / "contracts",
    )
    if _REPO_ROOT
    else ()
)

# spec/011 yamls whose endpoints are LIVE in the current step. Only these
# get the full path-existence subset assertion. Other spec/011 yamls
# describe endpoints scheduled for later steps (Step 7 wires the public
# invitation resolver, Step 5 the admin password reset, etc.) and are
# allowed to drift from the live app until those steps land. The meta-
# test (``test_openapi_diff_multi_spec.py``) still enforces that every
# spec/011 yaml is *loadable* so a parse error gets caught early.
_SPEC_011_LIVE_CONTRACT_STEMS: frozenset[str] = frozenset(
    {
        "trusted-users-invitation-url",
        # spec/011 Step 7 (T241): the public-token resolver + accept
        # endpoints landed and the YAML's only two paths are live.
        "invitation-public",
        # spec/011 Step 8 (T290): bulk + revoke endpoints landed
        # alongside the Step 7 single-invite issuer. The YAML now
        # describes 4 live paths (POST single, GET list, POST bulk,
        # POST revoke) and the stem is promoted to live so the harness
        # subset-asserts every path / method / requestBody.
        "member-invitations",
        # spec/011 Step 9 (T540): the project-create endpoint's single
        # path/method (``POST /web-api/v1/projects``) is live. NOTE
        # (2026-06-03, preview feedback #1): the SU-bootstrap
        # ``intended_owner_email`` extension was removed; the stem +
        # YAML are retained but now describe the plain create response.
        "su-bootstrap-project-create",
        # spec/011 US7 (T660): the in-app banner + activity read
        # endpoints (``GET /me/banners``, ``POST /me/banners/dismiss``,
        # ``GET /me/activity``) landed in this slice, so the stem is
        # promoted to live and the harness subset-asserts every path /
        # method / response-code (NFR-011-009).
        "me-banners-activity",
    }
)

# spec/011 yamls whose endpoints are NOT yet implemented in the live app.
# Path / method / requestBody subset assertions skip these stems so the
# harness stays green between the contract-PR and the implementation-PR.
# As each later step lands its endpoints, the corresponding stem MUST
# move from ``_SPEC_011_PENDING_STEMS`` to ``_SPEC_011_LIVE_CONTRACT_STEMS``
# in the same PR (NFR-011-009).
_SPEC_011_PENDING_STEMS: frozenset[str] = frozenset(
    {
        "admin-password-reset",
    }
)

# spec/012 PR-A contracts whose endpoints are live in the backend.
_SPEC_012_LIVE_CONTRACT_STEMS: frozenset[str] = frozenset(
    {
        "admin-licenses-delete",
        "licenses",
        "web-licenses",
    }
)

# Security scheme name mappings  (contract → canonical)
_SCHEME_ALIASES: dict[str, str] = {
    "apiKeyAuth": "bearer",
    "sessionCookie": "session",
    "csrfToken": "csrf",
    # FastAPI generated names
    "HTTPBearer": "bearer",
    "OAuth2": "oauth2",
    "APIKey": "apikey",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Phase 17 follow-up — Codex priority fix.
# Contracts under specs/006-permissions-redesign/contracts/*.yaml describe the
# v1 surface using prefix-less paths (e.g. ``/projects/{id}``). The live
# FastAPI schema mounts those operations under ``/api/v1`` (Bearer surface)
# and/or ``/web-api/v1`` (Cookie surface). Without stripping the mount prefix
# every contract path "missed" the live OpenAPI dictionary and the diff
# harness reported regression-style failures that were really test-side
# normalisation drift. Listed longest-first so the longer prefix matches
# before its substring.
_API_MOUNT_PREFIXES: tuple[str, ...] = ("/web-api/v1", "/api/v1")


def _strip_api_mount_prefix(path: str) -> str:
    """Remove the FastAPI mount prefix so a contract path matches a live path.

    Returns ``"/"`` when the entire path was the prefix (defensive — the
    live schema does not currently expose bare-prefix routes).
    """
    for prefix in _API_MOUNT_PREFIXES:
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            return path[len(prefix) :]
    return path


def _normalise_path(path: str) -> str:
    """Strip the FastAPI mount prefix and replace ``{…}`` segments with ``{*}``.

    The contract YAMLs describe path templates relative to the v1 surface
    (e.g. ``/projects/{id}``); the live OpenAPI carries the full mounted
    template (``/api/v1/projects/{id}``). Stripping the prefix here lets a
    single ``_normalise_path()`` produce a key that both sides agree on.
    """
    return re.sub(r"\{[^}]+\}", "{*}", _strip_api_mount_prefix(path))


# Phase 17 follow-up — Codex 推奨パターン.
# Some contracts (admin.yaml) describe paths *relative to* a sub-router that
# live OpenAPI mounts under /api/v1/{sub}/... or /web-api/v1/{sub}/.... The
# table maps contract name → list of sub-router prefix candidates that the
# resolver tries when the bare normalised path is not found.
#
# Add more entries here as additional contracts surface the same mismatch
# (Codex Round X). An empty / missing entry means "no sub-router — try the
# bare path only".
_SUBROUTER_PREFIXES: dict[str, tuple[str, ...]] = {
    "admin": ("/admin",),
}


def _live_item_for_contract_path(
    contract_name: str,
    contract_path: str,
    live_paths: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Locate the live path-item that corresponds to ``contract_path`` from
    contract ``contract_name``.

    Strategy:
        1. Try the bare normalised path (no sub-router prefix). This covers
           every contract whose paths already include the top-level resource
           segment (projects, auth, account, detections, audit).
        2. Iterate any sub-router prefix candidates registered for this
           contract in :data:`_SUBROUTER_PREFIXES` and try each prepended
           form. This covers contracts (admin) that describe paths relative
           to a sub-router mount.
        3. Return ``None`` when no candidate matches — callers translate
           that into a ``missing`` entry in their assertion.
    """
    bare = _normalise_path(contract_path)
    direct = live_paths.get(bare)
    if direct is not None:
        return direct
    for prefix in _SUBROUTER_PREFIXES.get(contract_name, ()):
        candidate = _normalise_path(prefix + contract_path)
        hit = live_paths.get(candidate)
        if hit is not None:
            return hit
    return None


def _security_list_to_canonical(security: list[dict[str, list[str]]]) -> frozenset[str]:
    """Convert an OpenAPI security requirement list to a canonical frozenset of scheme names."""
    canonical: set[str] = set()
    for req in security:
        for scheme in req:
            canonical.add(_SCHEME_ALIASES.get(scheme, scheme.lower()))
    return frozenset(canonical)


def _load_contract(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"Expected dict from {path}"
    return data


def _contracts_available() -> bool:
    """Return True iff at least one ``_CONTRACTS_DIRS`` entry has yamls.

    The check is conservative: if the spec tree is partially present
    (e.g. only spec/006 yamls landed but spec/011 not yet) we still
    return True so the available subset gets exercised. The per-test
    skip happens at fixture load time when the underlying yaml is
    actually requested.
    """
    return any(
        d.exists() and any(d.glob("*.yaml")) for d in _CONTRACTS_DIRS
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def contracts() -> dict[str, dict[str, Any]]:
    """Load all *.yaml files from every directory in ``_CONTRACTS_DIRS``.

    Returns a mapping from stem (e.g. 'projects', 'trusted-users-invitation-url')
    to parsed YAML dict. spec/006 stems and spec/011 stems coexist in the
    same flat namespace — the spec/011 file names were deliberately
    chosen so there is no collision with spec/006 names. Skips when no
    directory yielded any yaml (container-only runs).
    """
    if not _contracts_available():
        pytest.skip(
            "Contract YAML files not found in any of "
            f"{[str(d) for d in _CONTRACTS_DIRS]}. "
            "Skip in-container runs; CI runs against the full source tree."
        )
    loaded: dict[str, dict[str, Any]] = {}
    for directory in _CONTRACTS_DIRS:
        if not directory.exists():
            continue
        for yaml_path in sorted(directory.glob("*.yaml")):
            stem = yaml_path.stem
            if stem in loaded:  # pragma: no cover - design pin
                raise AssertionError(
                    f"contract YAML stem collision: {stem!r} appears in "
                    f"both {loaded[stem].get('__source__')!r} and {yaml_path}"
                )
            data = _load_contract(yaml_path)
            data["__source__"] = str(yaml_path)
            loaded[stem] = data
    return loaded


@pytest.fixture(scope="module")
def live_schema() -> dict[str, Any]:
    """Return the FastAPI-generated OpenAPI schema."""
    app: FastAPI = create_app()
    schema = app.openapi()
    assert isinstance(schema, dict)
    return schema


@pytest.fixture(scope="module")
def live_paths_normalised(live_schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return live paths keyed by normalised template.

    The same prefix-less template can be served by both the Bearer surface
    (``/api/v1/...``) and the Cookie surface (``/web-api/v1/...``). After
    prefix stripping both collapse onto the same key, so we shallow-merge
    the path-item dicts on collision: the first surface wins for any
    given HTTP method, but both surfaces' methods coexist in the merged
    record so downstream tests (response codes, request body presence,
    security schemes) still see whichever method the contract declares.
    """
    raw: dict[str, Any] = live_schema.get("paths", {})
    merged: dict[str, dict[str, Any]] = {}
    for original_path, path_item in raw.items():
        norm = _normalise_path(original_path)
        if not isinstance(path_item, dict):
            merged[norm] = path_item
            continue
        if norm not in merged:
            merged[norm] = dict(path_item)
            continue
        for method, op in path_item.items():
            merged[norm].setdefault(method, op)
    return merged


# ---------------------------------------------------------------------------
# T980-1: contracts directory is loadable and non-empty
# ---------------------------------------------------------------------------


class TestContractsLoadable:
    def test_contracts_dir_exists(self, contracts: dict[str, dict[str, Any]]) -> None:
        """At least one contract YAML is present and parseable."""
        assert len(contracts) > 0, "Expected at least one contract YAML"

    def test_required_contract_files_present(
        self, contracts: dict[str, dict[str, Any]]
    ) -> None:
        """Core contract files must exist."""
        required = {"projects", "auth", "admin", "account", "detections", "audit"}
        missing = required - set(contracts.keys())
        assert not missing, f"Missing contract files: {missing}"


# ---------------------------------------------------------------------------
# T980-2: every path in each contract exists in the live schema
# ---------------------------------------------------------------------------


class TestContractPathsExistInApp:
    def test_projects_paths_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Every path declared in contracts/projects.yaml exists in the app."""
        _assert_paths_present(contracts["projects"], live_paths_normalised, "projects")

    def test_auth_paths_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Every path declared in contracts/auth.yaml exists in the app."""
        _assert_paths_present(contracts["auth"], live_paths_normalised, "auth")

    def test_admin_paths_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Every path declared in contracts/admin.yaml exists in the app."""
        _assert_paths_present(contracts["admin"], live_paths_normalised, "admin")

    def test_account_paths_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Every path declared in contracts/account.yaml exists in the app."""
        _assert_paths_present(contracts["account"], live_paths_normalised, "account")

    def test_detections_paths_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Every path declared in contracts/detections.yaml exists in the app."""
        _assert_paths_present(
            contracts["detections"], live_paths_normalised, "detections"
        )

    def test_audit_paths_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Every path declared in contracts/audit.yaml exists in the app."""
        _assert_paths_present(contracts["audit"], live_paths_normalised, "audit")


# ---------------------------------------------------------------------------
# T980-2 (spec/011): subset-assert spec/011 yamls whose endpoints are LIVE
# in the current step (Step 6 == ``trusted-users-invitation-url`` only).
# Other spec/011 yamls describe later-step endpoints and are intentionally
# allowed to drift until those steps land — the meta-test in
# ``test_openapi_diff_multi_spec.py`` enforces that every yaml at least
# loads cleanly so a parse error is caught early.
# ---------------------------------------------------------------------------


class TestSpec011LiveContracts:
    """Subset-assert spec/011 yamls whose paths currently exist in app.

    The membership of :data:`_SPEC_011_LIVE_CONTRACT_STEMS` widens as
    later steps wire their endpoints. The harness has no snapshot file —
    each PR that lands new HTTP surface MUST add the yaml's stem here
    AND re-run the harness locally before opening (NFR-011-009).

    .. TODO(spec/011 Step 12 hygiene)
       Tighten this harness to do schema field-level parity (response
       model + requestBody object properties) for LIVE stems, not just
       path + method + response-code + requestBody-presence existence.
       The current harness allowed the ``revoked_reason`` drift between
       ``contracts/member-invitations.yaml`` and the live Pydantic
       ``InvitationListItem`` / ``InvitationRevokeResponse`` shape that
       Codex R1 caught on PR #101 (spec/011 Step 8). A full diff would
       walk ``schema.properties`` and assert (a) every contract-declared
       property exists on the live shape and (b) live shapes do not
       expose properties that the contract does not enumerate (the
       drift direction we just patched).
    """

    def test_spec_011_live_yamls_path_exists(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Each spec/011 live yaml's paths exist in the live OpenAPI schema."""
        missing_by_stem: dict[str, list[str]] = {}
        for stem in sorted(_SPEC_011_LIVE_CONTRACT_STEMS):
            contract = contracts.get(stem)
            if contract is None:
                pytest.fail(
                    f"spec/011 live contract {stem!r} missing from loaded "
                    "contracts — expected one of "
                    f"{sorted(contracts.keys())}"
                )
            missing: list[str] = []
            for contract_path in (contract.get("paths") or {}):
                if _live_item_for_contract_path(
                    stem, contract_path, live_paths_normalised
                ) is None:
                    missing.append(contract_path)
            if missing:
                missing_by_stem[stem] = missing
        assert not missing_by_stem, (
            "spec/011 live contracts missing paths in live OpenAPI:\n"
            + "\n".join(
                f"  {stem}: {paths}"
                for stem, paths in missing_by_stem.items()
            )
        )

    def test_spec_011_live_yamls_methods_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """HTTP methods in spec/011 live yamls are registered in the app."""
        for stem in sorted(_SPEC_011_LIVE_CONTRACT_STEMS):
            contract = contracts.get(stem)
            if contract is None:  # pragma: no cover - guarded above
                pytest.fail(f"spec/011 contract {stem!r} not loaded")
            _assert_methods_present(contract, live_paths_normalised, stem)


class TestSpec012LiveContracts:
    """Subset-assert the live spec/012 license contracts."""

    def test_spec_012_live_yamls_path_exists(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Each spec/012 yaml's paths exist in the live OpenAPI schema."""
        missing_by_stem: dict[str, list[str]] = {}
        for stem in sorted(_SPEC_012_LIVE_CONTRACT_STEMS):
            contract = contracts.get(stem)
            if contract is None:
                pytest.fail(
                    f"spec/012 live contract {stem!r} missing from loaded "
                    "contracts — expected one of "
                    f"{sorted(contracts.keys())}"
                )
            missing: list[str] = []
            for contract_path in (contract.get("paths") or {}):
                if _live_item_for_contract_path(
                    stem, contract_path, live_paths_normalised
                ) is None:
                    missing.append(contract_path)
            if missing:
                missing_by_stem[stem] = missing
        assert not missing_by_stem, (
            "spec/012 live contracts missing paths in live OpenAPI:\n"
            + "\n".join(
                f"  {stem}: {paths}" for stem, paths in missing_by_stem.items()
            )
        )

    def test_spec_012_live_yamls_methods_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """HTTP methods in spec/012 live yamls are registered in the app."""
        for stem in sorted(_SPEC_012_LIVE_CONTRACT_STEMS):
            contract = contracts.get(stem)
            if contract is None:  # pragma: no cover - guarded above
                pytest.fail(f"spec/012 contract {stem!r} not loaded")
            _assert_methods_present(contract, live_paths_normalised, stem)

    def test_spec_012_live_yamls_response_codes_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Response codes in spec/012 live yamls are present in the app."""
        for stem in sorted(_SPEC_012_LIVE_CONTRACT_STEMS):
            contract = contracts.get(stem)
            if contract is None:  # pragma: no cover - guarded above
                pytest.fail(f"spec/012 contract {stem!r} not loaded")
            _assert_response_codes_present(contract, live_paths_normalised, stem)


def _assert_paths_present(
    contract: dict[str, Any],
    live_paths: dict[str, dict[str, Any]],
    name: str,
) -> None:
    """Assert all paths in *contract* appear in *live_paths* after normalisation."""
    missing: list[str] = []
    for contract_path in (contract.get("paths") or {}):
        if _live_item_for_contract_path(name, contract_path, live_paths) is None:
            missing.append(contract_path)
    assert not missing, (
        f"Contract '{name}': {len(missing)} path(s) not found in live OpenAPI:\n"
        + "\n".join(f"  {p}" for p in missing)
    )


# ---------------------------------------------------------------------------
# T980-3: HTTP methods declared in contract exist in app
# ---------------------------------------------------------------------------


class TestContractMethodsExistInApp:
    def test_projects_methods_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """HTTP methods in contracts/projects.yaml are registered in the app."""
        _assert_methods_present(contracts["projects"], live_paths_normalised, "projects")

    def test_auth_methods_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """HTTP methods in contracts/auth.yaml are registered in the app."""
        _assert_methods_present(contracts["auth"], live_paths_normalised, "auth")

    def test_admin_methods_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """HTTP methods in contracts/admin.yaml are registered in the app."""
        _assert_methods_present(contracts["admin"], live_paths_normalised, "admin")

    def test_account_methods_exist(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """HTTP methods in contracts/account.yaml are registered in the app."""
        _assert_methods_present(contracts["account"], live_paths_normalised, "account")


_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def _assert_methods_present(
    contract: dict[str, Any],
    live_paths: dict[str, dict[str, Any]],
    name: str,
) -> None:
    missing: list[str] = []
    for contract_path, path_item in (contract.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        live_item = _live_item_for_contract_path(name, contract_path, live_paths) or {}
        for method in _HTTP_METHODS:
            if method in path_item and method not in live_item:
                missing.append(f"{method.upper()} {contract_path}")
    assert not missing, (
        f"Contract '{name}': {len(missing)} method(s) not in live OpenAPI:\n"
        + "\n".join(f"  {m}" for m in missing)
    )


# ---------------------------------------------------------------------------
# T980-4: response codes declared in contract exist in app operation
# ---------------------------------------------------------------------------


class TestContractResponseCodesExistInApp:
    def test_projects_response_codes(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Response codes in contracts/projects.yaml are present in the app."""
        _assert_response_codes_present(
            contracts["projects"], live_paths_normalised, "projects"
        )

    def test_auth_response_codes(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Response codes in contracts/auth.yaml are present in the app."""
        _assert_response_codes_present(
            contracts["auth"], live_paths_normalised, "auth"
        )


def _assert_response_codes_present(
    contract: dict[str, Any],
    live_paths: dict[str, dict[str, Any]],
    name: str,
) -> None:
    """Assert response codes declared in contract are present in corresponding live ops."""
    missing: list[str] = []
    for contract_path, path_item in (contract.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        live_item = _live_item_for_contract_path(name, contract_path, live_paths) or {}
        for method, op in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            live_op = live_item.get(method) or {}
            live_responses = set((live_op.get("responses") or {}).keys())
            for code in (op.get("responses") or {}):
                if code not in live_responses:
                    missing.append(f"{method.upper()} {contract_path}: missing {code}")
    assert not missing, (
        f"Contract '{name}': {len(missing)} response code(s) absent:\n"
        + "\n".join(f"  {m}" for m in missing)
    )


# ---------------------------------------------------------------------------
# T980-5: contract request bodies present when app has request body
# ---------------------------------------------------------------------------


class TestContractRequestBodyPresence:
    def test_state_changing_ops_have_request_body_if_contract_says_so(
        self,
        contracts: dict[str, dict[str, Any]],
        live_paths_normalised: dict[str, dict[str, Any]],
    ) -> None:
        """Ops declared with requestBody in contracts must have requestBody in app."""
        _assert_request_body_presence(contracts, live_paths_normalised)


def _assert_request_body_presence(
    all_contracts: dict[str, dict[str, Any]],
    live_paths: dict[str, dict[str, Any]],
) -> None:
    # spec/011 Step 6 (T080): yamls under spec/011 that describe endpoints
    # not yet wired (Steps 7-12 deliverables) are deliberately allowed to
    # drift on requestBody presence until their owning step lands. The
    # spec/011 yamls promoted to the live-contract allowlist
    # (_SPEC_011_LIVE_CONTRACT_STEMS) are subset-asserted by
    # ``TestSpec011LiveContracts`` and naturally pick up
    # ``_assert_request_body_presence`` once they enter that set.
    missing: list[str] = []
    for cname, contract in all_contracts.items():
        if cname in _SPEC_011_PENDING_STEMS:
            continue
        for contract_path, path_item in (contract.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            live_item = (
                _live_item_for_contract_path(cname, contract_path, live_paths) or {}
            )
            for method, op in path_item.items():
                if method not in _HTTP_METHODS or not isinstance(op, dict):
                    continue
                if op.get("requestBody") is None:
                    continue  # contract doesn't require a body → skip
                live_op = live_item.get(method) or {}
                if live_op.get("requestBody") is None:
                    missing.append(f"{method.upper()} {contract_path}: requestBody absent in app")
    assert not missing, (
        f"{len(missing)} operation(s) missing requestBody in app:\n"
        + "\n".join(f"  {m}" for m in missing)
    )


# ---------------------------------------------------------------------------
# T980-6: security scheme presence (structural, not name-exact)
# ---------------------------------------------------------------------------


class TestContractSecuritySchemePresence:
    def test_app_exposes_at_least_one_security_scheme(
        self, live_schema: dict[str, Any]
    ) -> None:
        """App must expose at least one securityScheme in components."""
        schemes = (
            live_schema.get("components") or {}
        ).get("securitySchemes") or {}
        assert schemes, "App OpenAPI must define at least one security scheme"

    def test_bearer_scheme_defined(self, live_schema: dict[str, Any]) -> None:
        """HTTPBearer scheme must be defined (covers apiKeyAuth + sessionCookie use cases)."""
        schemes = (
            live_schema.get("components") or {}
        ).get("securitySchemes") or {}
        # Accept any scheme whose type=http and scheme=bearer
        has_bearer = any(
            isinstance(v, dict)
            and v.get("type") == "http"
            and str(v.get("scheme", "")).lower() == "bearer"
            for v in schemes.values()
        )
        assert has_bearer, (
            "No HTTP Bearer security scheme found. "
            f"Available: {list(schemes.keys())}"
        )

    def test_all_operations_have_security_or_global_security(
        self,
        live_schema: dict[str, Any],
    ) -> None:
        """Operations under /api/v1/* and /web-api/v1/* must carry security."""
        _SKIP_PREFIXES = (
            "/web-api/v1/auth/",
            "/api/v1/auth/",
            # W2-3 PR-2 unmounted ``/api/v1/setup/*``; only the W2-2-A BFF mirror
            # of the public, pre-session setup bootstrap endpoints survives
            # (no user/session/CSRF token exists yet).
            "/web-api/v1/setup/",
            "/health",
            "/openapi.json",
            "/docs",
            "/redoc",
        )
        # Intentionally public (no auth required) endpoints that do not fit
        # the prefix-based exemptions above.
        _SKIP_EXACT = frozenset(
            {
                # Publicly available Xeno-canto sonogram proxy (no credentials
                # needed — sonograms are open data from xeno-canto.org).
                # W2-4 PR-D moved this to the /web-api/v1 BFF surface; the
                # legacy /api/v1 route is unmounted.
                "/web-api/v1/projects/{project_id}/xeno-canto/sonogram",
            }
        )
        paths: dict[str, Any] = live_schema.get("paths") or {}
        global_security = live_schema.get("security")
        missing: list[str] = []
        for path, path_item in paths.items():
            if any(path.startswith(p) for p in _SKIP_PREFIXES):
                continue
            if path in _SKIP_EXACT:
                continue
            if not isinstance(path_item, dict):
                continue
            for method, op in path_item.items():
                if method not in _HTTP_METHODS or not isinstance(op, dict):
                    continue
                op_security = op.get("security")
                if op_security is None and global_security is None:
                    missing.append(f"{method.upper()} {path}")
        assert not missing, (
            f"{len(missing)} operations lack security declaration:\n"
            + "\n".join(f"  {m}" for m in missing[:20])
        )


# ---------------------------------------------------------------------------
# T980-7 (Phase 17 follow-up): unit tests for the contract → live path resolver
# ---------------------------------------------------------------------------


class TestLiveItemResolver:
    """Pure unit tests for ``_live_item_for_contract_path``.

    These tests do not depend on the live FastAPI schema — they exercise the
    resolver against a hand-crafted ``live_paths`` dict so the prefix-table
    behaviour is locked in regardless of router registration changes.
    """

    def test_admin_subrouter_prefix_resolves(self) -> None:
        """admin contract paths (prefix-less) hit /admin/<path> in live schema."""
        live_paths: dict[str, dict[str, Any]] = {
            "/admin/projects/{*}/archive": {"post": {"responses": {"204": {}}}},
        }
        item = _live_item_for_contract_path(
            "admin", "/projects/{id}/archive", live_paths
        )
        assert item is not None, (
            "Expected admin resolver to find /admin/projects/{*}/archive "
            "for contract path /projects/{id}/archive"
        )
        assert "post" in item

    def test_non_admin_contract_uses_bare_path(self) -> None:
        """projects contract resolves directly without sub-router prefix.

        Regression guard: if a future change accidentally registers a
        ``/projects`` sub-router prefix for the projects contract this test
        will start matching the wrong live entry.
        """
        live_paths: dict[str, dict[str, Any]] = {
            "/projects/{*}": {"get": {"responses": {"200": {}}}},
            # A spurious /admin-mounted shadow that must NOT be picked up
            # for contract_name="projects".
            "/admin/projects/{*}": {"get": {"responses": {"403": {}}}},
        }
        item = _live_item_for_contract_path("projects", "/projects/{id}", live_paths)
        assert item is not None
        # Confirm we hit the bare entry, not the /admin shadow.
        assert "200" in item["get"]["responses"], (
            "Resolver must hit the bare /projects/{*} entry for the projects "
            "contract, not the /admin-prefixed shadow"
        )

    def test_returns_none_when_no_match(self) -> None:
        """Resolver returns None when neither bare nor prefixed path is present."""
        live_paths: dict[str, dict[str, Any]] = {
            "/projects/{*}": {"get": {}},
        }
        # admin contract path with no /admin entry in live_paths
        item = _live_item_for_contract_path(
            "admin", "/users/{userId}/reset-2fa", live_paths
        )
        assert item is None
