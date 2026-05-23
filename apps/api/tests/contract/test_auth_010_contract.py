"""Spec 010 canonical contract expectations.

These tests pin the contract-level deltas for email verification and
trusted devices after T016 reconciles the spec-local deltas into the
canonical spec/006 contract files. Runtime OpenAPI behavior is covered by
the user-story integration and schema tests that implement each endpoint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "specs" / "006-permissions-redesign" / "contracts").exists():
            return parent
    pytest.skip("specs/006-permissions-redesign/contracts not available")


def _load_contract(name: str) -> dict[str, Any]:
    path = _repo_root() / "specs" / "006-permissions-redesign" / "contracts" / name
    with path.open() as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"Expected YAML mapping from {path}"
    return data


@pytest.fixture(scope="module")
def auth_contract() -> dict[str, Any]:
    return _load_contract("auth.yaml")


@pytest.fixture(scope="module")
def account_contract() -> dict[str, Any]:
    return _load_contract("account.yaml")


def _schema(contract: dict[str, Any], name: str) -> dict[str, Any]:
    schemas = contract.get("components", {}).get("schemas", {})
    value = schemas.get(name)
    assert isinstance(value, dict), f"Contract schema {name!r} is missing"
    return value


def _properties(schema: dict[str, Any]) -> dict[str, Any]:
    props = schema.get("properties")
    assert isinstance(props, dict), f"Schema has no properties: {schema!r}"
    return props


# spec/011 §FR-011-005 (NFR-011-009) — the
# ``test_verify_email_and_resend_contracts_exist`` case was removed
# alongside the deleted ``/auth/verify-email{,resend}`` path-items in
# ``specs/006-permissions-redesign/contracts/auth.yaml``.


def test_login_response_contract_documents_complete_state(
    auth_contract: dict[str, Any],
) -> None:
    login_response = _schema(auth_contract, "LoginResponse")
    assert "oneOf" in login_response
    assert login_response["discriminator"]["propertyName"] == "login_state"
    mapping = login_response["discriminator"]["mapping"]
    assert {"complete", "2fa_setup_required", "2fa_required"}.issubset(mapping)

    complete = _schema(auth_contract, "LoginCompleteResponse")
    complete_props = _properties(complete)
    assert complete_props["login_state"]["const"] == "complete"
    assert {"access_token", "expires_in", "trusted_device_used"}.issubset(complete_props)

    interim = _schema(auth_contract, "LoginInterimResponse")
    interim_props = _properties(interim)
    assert set(interim_props["login_state"]["enum"]) == {"2fa_setup_required", "2fa_required"}
    assert "interim_token" in interim_props


def test_2fa_success_paths_accept_trust_device_fields(
    auth_contract: dict[str, Any],
) -> None:
    challenge_request = _schema(auth_contract, "TwoFactorChallengeRequest")
    challenge_props = _properties(challenge_request)
    assert "trust_device" in challenge_props
    assert "device_label" in challenge_props

    setup_confirm_request = _schema(auth_contract, "TotpSetupConfirmRequest")
    setup_props = _properties(setup_confirm_request)
    assert "trust_device" in setup_props
    assert "device_label" in setup_props


def test_2fa_success_responses_document_trusted_device_creation(
    auth_contract: dict[str, Any],
) -> None:
    challenge_response = _schema(auth_contract, "TwoFactorChallengeResponse")
    assert "trusted_device_created" in _properties(challenge_response)

    setup_confirm_response = _schema(auth_contract, "TotpSetupConfirmResponse")
    assert "trusted_device_created" in _properties(setup_confirm_response)


def test_account_trusted_device_contracts_exist(account_contract: dict[str, Any]) -> None:
    paths = account_contract.get("paths", {})

    collection = paths.get("/account/trusted-devices")
    assert isinstance(collection, dict)
    assert "get" in collection
    assert collection["get"].get("security") == [{"sessionCookie": []}]

    item = paths.get("/account/trusted-devices/{id}")
    assert isinstance(item, dict)
    assert "delete" in item
    assert item["delete"].get("security") == [{"sessionCookie": [], "csrfToken": []}]

    revoke_all = paths.get("/account/trusted-devices/revoke-all")
    assert isinstance(revoke_all, dict)
    assert "post" in revoke_all
    assert revoke_all["post"].get("security") == [{"sessionCookie": [], "csrfToken": []}]

    summary = _schema(account_contract, "TrustedDeviceSummary")
    assert {"id", "created_at", "last_used_at", "expires_at", "current_device"}.issubset(
        _properties(summary),
    )
