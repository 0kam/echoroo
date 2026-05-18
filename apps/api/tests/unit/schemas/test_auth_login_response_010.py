"""US4 login response schema variants for trusted-device bypass."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from echoroo.schemas.web_v1.auth import LoginResponse


def _dump_login_response(payload: dict[str, object]) -> dict[str, object]:
    parsed = LoginResponse.model_validate(payload)
    dumped = parsed.model_dump()
    assert isinstance(dumped, dict)
    return dumped


@pytest.mark.parametrize("login_state", ["2fa_setup_required", "2fa_required"])
def test_login_response_accepts_interim_variants(login_state: str) -> None:
    body = _dump_login_response(
        {
            "login_state": login_state,
            "interim_token": "interim.jwt",
        }
    )

    assert body == {
        "login_state": login_state,
        "interim_token": "interim.jwt",
    }


def test_login_response_accepts_complete_variant_for_trusted_device() -> None:
    body = _dump_login_response(
        {
            "login_state": "complete",
            "access_token": "access.jwt",
            "expires_in": 900,
            "trusted_device_used": True,
        }
    )

    assert body == {
        "login_state": "complete",
        "access_token": "access.jwt",
        "expires_in": 900,
        "trusted_device_used": True,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "login_state": "complete",
            "interim_token": "interim.jwt",
        },
        {
            "login_state": "2fa_required",
            "access_token": "access.jwt",
            "expires_in": 900,
            "trusted_device_used": True,
        },
        {
            "login_state": "complete",
            "access_token": "access.jwt",
            "expires_in": 900,
        },
    ],
)
def test_login_response_rejects_mixed_or_incomplete_variants(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        LoginResponse.model_validate(payload)
