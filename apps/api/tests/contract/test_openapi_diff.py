"""T980: OpenAPI diff tests — contract/*.yaml vs live app.openapi() (SC-019).

Validates that the paths, response codes, request-body schemas, and
security requirements declared in the six specs/006-permissions-redesign/
contracts/*.yaml files are present in the FastAPI-generated openapi.json.

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
_CONTRACTS_DIR = (_REPO_ROOT / "specs" / "006-permissions-redesign" / "contracts") if _REPO_ROOT else Path("/nonexistent")

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
    return _CONTRACTS_DIR.exists() and any(_CONTRACTS_DIR.glob("*.yaml"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def contracts() -> dict[str, dict[str, Any]]:
    """Load all *.yaml files from the contracts directory.

    Returns a mapping from stem (e.g. 'projects') to parsed YAML dict.
    Skips when the directory is unavailable.
    """
    if not _contracts_available():
        pytest.skip(
            f"Contract YAML files not found at {_CONTRACTS_DIR}. "
            "Skip in-container runs; CI runs against the full source tree."
        )
    return {p.stem: _load_contract(p) for p in sorted(_CONTRACTS_DIR.glob("*.yaml"))}


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
    missing: list[str] = []
    for cname, contract in all_contracts.items():
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
            "/api/v1/setup/",
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
                "/api/v1/projects/{project_id}/xeno-canto/sonogram",
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
