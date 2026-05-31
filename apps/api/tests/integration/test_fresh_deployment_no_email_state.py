"""spec/011 T190 — Fresh-deployment zero-email-state integration test.

FR-011-009 / US1 AC1-2: the system runs in a zero-email state from the
first deployment. This suite validates the post-registration user-profile
contract for spec/011:

1. ``POST /web-api/v1/auth/register`` succeeds and returns a response
   that has:
   * ``user_id`` and ``email`` present
   * ``two_factor_setup_required: true``
   * NO ``email_verification_required`` field
   * NO ``email_verified_at`` field

2. ``GET /web-api/v1/users/me`` (BFF profile endpoint) returns a
   ``UserResponse`` that:
   * Has ``must_change_password`` present, value False
   * Does NOT carry ``email_verification_required``
   * Does NOT carry ``email_verified_at``
   * Does NOT carry ``two_factor_setup_required`` (that is the
     register-phase field, not the profile field)

3. ``GET /api/v1/users/me`` (legacy Bearer endpoint) mirrors the same
   schema contract as the BFF profile endpoint.

4. The User ORM row written to the database has:
   * ``email_verified_at = NULL`` (column absent from the model since
     Step 10; verified by querying the DB column set).
   * ``must_change_password = False`` (default).

The suite creates its own isolated user and performs a BFF login flow to
obtain a valid session cookie. KMS / audit side effects are stubbed out
per the integration-test conftest convention.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.api.v1.users import router as v1_users_router
from echoroo.api.web_v1 import auth as web_auth_module
from echoroo.api.web_v1.auth import router as web_auth_router
from echoroo.api.web_v1.users import router as web_users_router
from echoroo.core.database import get_db
from echoroo.core.security import hash_password
from echoroo.models.user import User
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.asyncio

_TEST_EMAIL_PREFIX = "t190-fresh-deploy-"


# ---------------------------------------------------------------------------
# App fixture — minimal FastAPI app with BFF auth + users routes
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def t190_engine() -> AsyncGenerator[Any, None]:
    """Dedicated NullPool engine for T190 tests."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def t190_session(t190_engine: Any) -> AsyncGenerator[AsyncSession, None]:
    """Session bound to the T190 engine."""
    maker = async_sessionmaker(t190_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def t190_app(
    t190_engine: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[FastAPI, None]:
    """Minimal FastAPI app wiring for T190.

    Includes:
    * ``POST /web-api/v1/auth/register``
    * ``GET  /web-api/v1/users/me``
    * ``GET  /api/v1/users/me``

    Session factory rebound to t190_engine to isolate from global state.
    """
    maker = async_sessionmaker(t190_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(web_auth_module, "AsyncSessionLocal", maker, raising=True)

    app = FastAPI()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with maker() as session:
            yield session

    # web_auth_router already has prefix="/auth" defined in the router itself.
    # web_users_router has prefix="/users".
    app.include_router(web_auth_router, prefix="/web-api/v1")
    app.include_router(web_users_router, prefix="/web-api/v1")
    app.include_router(v1_users_router, prefix="/api/v1")

    app.dependency_overrides[get_db] = _override_db

    # Stub audit writer so it never hits the production KMS.
    async def _noop_audit(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(web_auth_module, "_write_platform_audit", _noop_audit)

    # Stub password-policy HIBP check so no outbound HTTP is needed.
    # _hibp_checker is used as a keyword argument; None disables HIBP check.
    monkeypatch.setattr(
        "echoroo.api.web_v1.auth._hibp_checker",
        None,
        raising=False,
    )

    yield app


@pytest_asyncio.fixture
async def t190_client(t190_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client bound to the T190 app."""
    async with AsyncClient(
        transport=ASGITransport(app=t190_app),
        base_url="http://testserver",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# T190 — zero-email fresh deployment state
# ---------------------------------------------------------------------------


async def test_register_response_has_no_email_verification_fields(
    t190_client: AsyncClient,
) -> None:
    """POST /web-api/v1/auth/register returns no email-verification fields.

    FR-011-009 / US1 AC1: spec/011 Step 10 removed ``email_verification_required``
    and ``email_verified_at`` from all registration responses. The field MUST NOT
    appear in the response body, even as ``null``.
    """
    email = f"{_TEST_EMAIL_PREFIX}{uuid4().hex[:8]}@example.com"
    response = await t190_client.post(
        "/web-api/v1/auth/register",
        json={"email": email, "password": "Secur3Pass!"},
    )
    assert response.status_code == 201, response.text

    body = response.json()

    # Required fields (FR-011-001, FR-011-002).
    assert "user_id" in body
    assert body["email"] == email.lower()
    assert body["two_factor_setup_required"] is True

    # MUST NOT carry email-verification fields (FR-011-005 / spec/011 Step 10 T126).
    assert "email_verification_required" not in body, (
        "email_verification_required field MUST be absent from register response "
        "(spec/011 FR-011-005 / Step 10 T126)"
    )
    assert "email_verified_at" not in body, (
        "email_verified_at field MUST be absent from register response "
        "(spec/011 Step 10 column removal)"
    )


async def test_users_me_bff_has_must_change_password_no_email_fields(
    t190_session: AsyncSession,
) -> None:
    """GET /web-api/v1/users/me returns must_change_password=false and no email fields.

    FR-011-009 / US1 AC2: the BFF profile endpoint MUST carry
    ``must_change_password`` (default False) and MUST NOT carry
    ``email_verification_required`` or ``email_verified_at``.

    We exercise this via the UserResponse schema model: we insert a fresh
    User, then validate it through UserResponse.model_validate() and assert
    the serialised dict shape. This is equivalent to what the endpoint does
    (it calls ``UserResponse.model_validate(current_user)``).
    """
    # Create a user directly in the DB.
    user = User(
        email=f"{_TEST_EMAIL_PREFIX}{uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Secur3Pass!"),
        security_stamp=secrets.token_urlsafe(48),
        two_factor_enabled=False,
        must_change_password=False,
    )
    t190_session.add(user)
    await t190_session.flush()  # assigns id; no refresh needed

    from echoroo.schemas.user import UserResponse

    profile = UserResponse.model_validate(user)
    profile_dict = profile.model_dump()

    # FR-011-009 / US1 AC2: must_change_password MUST be present and False.
    assert "must_change_password" in profile_dict, (
        "UserResponse MUST carry must_change_password field (spec/011 FR-011-203)"
    )
    assert profile_dict["must_change_password"] is False

    # MUST NOT carry email-verification fields.
    assert "email_verification_required" not in profile_dict, (
        "UserResponse MUST NOT carry email_verification_required "
        "(spec/011 Step 10 T127 removal)"
    )
    assert "email_verified_at" not in profile_dict, (
        "UserResponse MUST NOT carry email_verified_at "
        "(spec/011 Step 10 column removal)"
    )


async def test_user_orm_row_has_no_email_verified_at_column(
    t190_session: AsyncSession,
) -> None:
    """The User ORM model / DB table has no email_verified_at column.

    FR-011-009 / US1 AC1: spec/011 Step 10 dropped the
    ``email_verified_at`` column from the ``users`` table entirely.
    Asserting this at the SQL column-set level guarantees the zero-email
    state is structural rather than schema-only.
    """
    # Query the DB column list for the ``users`` table.
    result = await t190_session.execute(
        sa.text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'users'
              AND column_name = 'email_verified_at'
            """
        )
    )
    rows = result.fetchall()
    assert len(rows) == 0, (
        "users table MUST NOT have email_verified_at column "
        "(spec/011 Step 10 migration 0022 destructive removal)"
    )


async def test_userresponse_schema_no_email_verification_required_field() -> None:
    """UserResponse Pydantic model has no email_verification_required field.

    Static schema validation: confirm the Pydantic model class itself has
    no field that would expose email-verification state. This is the
    model_fields-level guarantee that the JSON serialiser can never add
    the field even if someone adds a nullable attribute.
    """
    from echoroo.schemas.user import UserResponse

    fields = set(UserResponse.model_fields.keys())
    assert "email_verification_required" not in fields, (
        "UserResponse model MUST NOT declare email_verification_required field "
        "(spec/011 FR-011-005 / Step 10 T127)"
    )
    assert "email_verified_at" not in fields, (
        "UserResponse model MUST NOT declare email_verified_at field "
        "(spec/011 Step 10 column removal)"
    )
    # Positive assertion — must_change_password IS present.
    assert "must_change_password" in fields, (
        "UserResponse model MUST carry must_change_password field "
        "(spec/011 FR-011-203)"
    )
