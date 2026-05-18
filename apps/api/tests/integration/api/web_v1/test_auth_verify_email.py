"""US1 integration coverage for first-party email verification."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.services.email_verification_service import (
    unseal_email_verification_outbox_token,
)
from tests.integration.api.web_v1._helpers import (
    assert_legacy_v1_rejects_bff_token,
)

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_EVENT_TYPE = "auth.email_verification.requested"


async def _registered_user_id(
    session: AsyncSession,
    email: str,
) -> str:
    result = await session.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": email},
    )
    user_id = result.scalar_one_or_none()
    assert user_id is not None
    return str(user_id)


async def _verification_outbox_payload(
    session: AsyncSession,
    user_id: str,
) -> dict[str, Any]:
    result = await session.execute(
        text(
            "SELECT payload FROM outbox_events "
            "WHERE event_type = :event_type "
            "AND payload->>'user_id' = :user_id"
        ),
        {"event_type": _EVENT_TYPE, "user_id": user_id},
    )
    payloads = [row[0] for row in result.all()]
    assert len(payloads) == 1
    payload = payloads[0]
    assert isinstance(payload, dict)
    return payload


def test_bff_verify_email_in_openapi_surface() -> None:
    """The first-party verify endpoint remains declared as a public POST."""
    from echoroo.main import create_app

    openapi = create_app().openapi()

    path = openapi.get("paths", {}).get("/web-api/v1/auth/verify-email")
    assert path is not None
    assert "post" in {method.lower() for method in path}


@pytest.mark.asyncio
async def test_register_enqueues_verification_email_and_verify_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Registration issues one token, queues one email, and the token verifies."""
    email = "verify-success@example.com"
    response = await client.post(
        "/web-api/v1/auth/register",
        json={
            "email": email,
            "password": "CorrectHorseBatteryStaple123!",
            "display_name": "Verify Success",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert body["email_verified_at"] is None
    assert body["email_verification_required"] is True
    assert body["two_factor_setup_required"] is True

    user_id = body.get("user_id") or await _registered_user_id(db_session, email)
    payload = await _verification_outbox_payload(db_session, str(user_id))
    assert "token" not in payload
    assert "email" not in payload
    token_envelope = payload.get("token_envelope")
    assert isinstance(token_envelope, str)
    token = unseal_email_verification_outbox_token(token_envelope)
    assert isinstance(token, str)
    assert _TOKEN_RE.fullmatch(token)
    assert isinstance(payload.get("email_hash"), str)
    assert isinstance(payload.get("token_hash_prefix"), str)
    assert payload["purpose"] == "verify_email"

    stored = await db_session.execute(
        text(
            "SELECT token_hash, consumed_at, superseded_at "
            "FROM email_verification_tokens "
            "WHERE user_id = :user_id AND purpose = 'verify_email'"
        ),
        {"user_id": str(user_id)},
    )
    token_hash, consumed_at, superseded_at = stored.one()
    assert token_hash != token
    assert consumed_at is None
    assert superseded_at is None

    verify_response = await client.post(
        "/web-api/v1/auth/verify-email",
        json={"token": token},
    )
    assert verify_response.status_code == 200
    verify_body = verify_response.json()
    assert verify_body["user_id"] == str(user_id)
    assert verify_body["email"] == email
    assert verify_body["email_verified_at"] is not None
    assert verify_body["email_verification_required"] is False

    refreshed = await db_session.execute(
        text(
            "SELECT users.email_verified_at, tokens.consumed_at "
            "FROM users "
            "JOIN email_verification_tokens tokens ON tokens.user_id = users.id "
            "WHERE users.id = :user_id"
        ),
        {"user_id": str(user_id)},
    )
    verified_at, consumed_at = refreshed.one()
    assert verified_at is not None
    assert consumed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "expected_error"),
    [
        ("not-a-real-token", "ERR_EMAIL_VERIFICATION_INVALID"),
        ("A" * 42 + "!", "ERR_EMAIL_VERIFICATION_INVALID"),
    ],
)
async def test_verify_email_rejects_invalid_or_tampered_tokens(
    client: AsyncClient,
    token: str,
    expected_error: str,
) -> None:
    """Invalid tokens fail generically without leaking account existence."""
    response = await client.post(
        "/web-api/v1/auth/verify-email",
        json={"token": token},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == expected_error
    assert "email" not in body
    assert "user_id" not in body


@pytest.mark.asyncio
async def test_legacy_v1_verify_email_rejects_bff_jwt(
    unshimmed_client: AsyncClient,
    bff_jwt_factory: object,
) -> None:
    """FR-006: legacy ``/api/v1/auth/verify-email`` rejects BFF JWT."""
    bff_token = bff_jwt_factory(user_id=uuid.UUID(int=1))  # type: ignore[operator]
    await assert_legacy_v1_rejects_bff_token(
        unshimmed_client,
        "POST",
        "/api/v1/auth/verify-email",
        bff_token=bff_token,
        body={"token": "irrelevant-fr006-only-checks-auth-rejection"},
    )
