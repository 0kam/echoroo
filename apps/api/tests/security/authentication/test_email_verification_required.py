"""US2 security tests for protected-action email verification enforcement.

spec/011 Step 3 (forced-password-change middleware swap) removed the
``EmailVerificationEnforcementMiddleware`` registration from the
application's middleware stack and dropped the
``EMAIL_VERIFICATION_ENFORCEMENT_ENABLED`` setting. The 403
``ERR_EMAIL_VERIFICATION_REQUIRED`` contract this suite asserts no
longer applies — the equivalent contract under the new gate is the
423 ``ERR_PASSWORD_CHANGE_REQUIRED`` response covered by
``apps/api/tests/integration/test_must_change_password_middleware.py``.
The entire module is skipped at import time; Step 10 will delete the
file alongside the rest of the email-verification surface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytest.skip(
    "spec/011 Step 3: EmailVerificationEnforcementMiddleware no longer "
    "registered; replaced by ForcedPasswordChangeMiddleware. New contract "
    "covered by tests/integration/test_must_change_password_middleware.py.",
    allow_module_level=True,
)

import sqlalchemy as sa  # noqa: E402
from httpx import AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from echoroo.core.auth import issue_access_token  # noqa: E402
from echoroo.core.auth_paths import PUBLIC_AUTH_PATHS  # noqa: E402
from echoroo.core.security import hash_password  # noqa: E402
from echoroo.core.settings import get_settings  # noqa: E402
from echoroo.middleware.csrf import CSRF_HEADER_NAME, issue_csrf_token  # noqa: E402
from echoroo.models.user import User  # noqa: E402

_PUBLIC_EMAIL_VERIFICATION_PATHS = {
    "/web-api/v1/auth/login",
    "/web-api/v1/auth/register",
    "/web-api/v1/auth/verify-email",
    "/web-api/v1/auth/verify-email/resend",
    "/web-api/v1/auth/logout",
}


async def _create_unverified_user(session: AsyncSession) -> User:
    user = User(
        email=f"email-required-{uuid4()}@example.com",
        password_hash=hash_password("CorrectHorseBatteryStaple123!"),
        display_name="Email Verification Required",
        security_stamp=f"email-required-{uuid4()}",
        two_factor_enabled=False,
        last_login_at=None,
        last_first_party_activity_at=datetime.now(UTC),
        email_verified_at=None,
    )
    session.add(user)
    await session.flush()
    return user


async def _web_session_auth(
    client: AsyncClient,
    session: AsyncSession,
    user: User,
) -> dict[str, str]:
    settings = get_settings()
    family_id = uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, now())"
        ),
        {"family_id": family_id, "user_id": user.id},
    )
    await session.commit()
    access_token = issue_access_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
    )
    csrf_token = issue_csrf_token(
        str(family_id),
        session_secret=settings.web_session_secret,
    )
    client.cookies.set(
        settings.web_session_cookie_name,
        str(family_id),
        path="/web-api/v1/",
    )
    client.cookies.set(
        settings.web_csrf_cookie_name,
        csrf_token,
        path="/",
    )
    return {
        "Authorization": f"Bearer {access_token}",
        CSRF_HEADER_NAME: csrf_token,
    }


def _enable_email_verification_enforcement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_VERIFICATION_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setattr(
        get_settings(),
        "EMAIL_VERIFICATION_ENFORCEMENT_ENABLED",
        True,
        raising=False,
    )


@pytest.mark.asyncio
async def test_unverified_session_cannot_create_project_when_enforcement_enabled(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project creation is a representative protected action."""
    _enable_email_verification_enforcement(monkeypatch)
    user = await _create_unverified_user(db_session)
    headers = await _web_session_auth(client, db_session, user)

    response = await client.post(
        "/web-api/v1/projects/",
        headers=headers,
        json={
            "name": "Blocked Until Email Verified",
            "description": "Created by a still-unverified account",
            "visibility": "public",
            "license": "CC-BY",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ERR_EMAIL_VERIFICATION_REQUIRED"


@pytest.mark.parametrize("path", sorted(_PUBLIC_EMAIL_VERIFICATION_PATHS))
def test_email_verification_public_auth_paths_are_not_enforcement_blocked(
    path: str,
) -> None:
    """Verify/login/resend/logout stay outside protected-action enforcement."""
    assert path in PUBLIC_AUTH_PATHS


def test_protected_endpoint_inventory_contains_representative_mutations() -> None:
    """Inventory guard: endpoint-selection drift should be reviewed explicitly."""
    protected_actions = {
        "POST /web-api/v1/projects",
        "PATCH /web-api/v1/projects/{project_id}",
        "DELETE /web-api/v1/projects/{project_id}",
        "POST /web-api/v1/projects/{project_id}/members",
    }

    assert "POST /web-api/v1/auth/verify-email" not in protected_actions
    assert "POST /web-api/v1/auth/verify-email/resend" not in protected_actions
    assert "POST /web-api/v1/projects" in protected_actions
    assert len(protected_actions) >= 4
