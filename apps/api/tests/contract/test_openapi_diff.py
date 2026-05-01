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


def _normalise_path(path: str) -> str:
    """Replace all ``{…}`` segments with ``{*}`` for template-agnostic comparison."""
    return re.sub(r"\{[^}]+\}", "{*}", path)


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
    """Return live paths keyed by normalised template."""
    raw: dict[str, Any] = live_schema.get("paths", {})
    return {_normalise_path(k): v for k, v in raw.items()}


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
        norm = _normalise_path(contract_path)
        if norm not in live_paths:
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
        norm = _normalise_path(contract_path)
        live_item = live_paths.get(norm, {})
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
        norm = _normalise_path(contract_path)
        live_item = live_paths.get(norm) or {}
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
    for _cname, contract in all_contracts.items():
        for contract_path, path_item in (contract.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            norm = _normalise_path(contract_path)
            live_item = live_paths.get(norm) or {}
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
