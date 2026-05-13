"""TDD coverage for the BFF ``POST /web-api/v1/auth/verify-email`` mirror.

Spec/009 PR B follow-up: research.md §D-3 understated the auth-router
inventory — the BFF surface lacked a ``/verify-email`` mirror. PR B
rewired the frontend (``apps/web/src/lib/api/auth.ts``) to the BFF path
regardless, which would have 404'd in production. This test gates the
mirror's existence and the D-2a / FR-006 contract for the new route.

What this file covers (intentionally minimal — the legacy handler's
behaviour suite at ``tests/contract/test_auth.py::test_verify_email*``
already exercises the full request/response semantics, and both
surfaces share the same :class:`echoroo.services.auth.AuthService`
entry point):

  * The route is wired and visible on the live FastAPI ``openapi()``
    schema under ``/web-api/v1/auth/verify-email`` ``POST``. This is
    the parity check PR J's ``test_bff_path_parity.py`` will assert
    against ``_bff_path_parity_allowlist.BFF_PATHS_DECLARED_BY_SPEC_009``.
  * The route accepts the legacy request shape (``{"token": "..."}``)
    and reaches the shared ``AuthService.verify_email`` entry point.
    The legacy implementation is currently a 501 Phase-4 stub (see
    ``apps/api/echoroo/services/auth.py`` line 280–293); we assert
    the BFF mirror inherits the same stub response (i.e. the wiring
    invokes the shared service, not a divergent BFF copy). Once Phase
    4 lands the real implementation, both surfaces flip together.
  * FR-006 (legacy ``/api/v1`` rejects BFF JWT). Pin the auth-surface
    contract for the legacy verify-email path so a future regression
    can't accidentally start accepting BFF cookies on the programmatic
    surface.

The test deliberately does NOT exercise:

  * Token-validation happy / error paths — owned by the shared
    ``AuthService.verify_email`` and tested at ``tests/contract/test_auth.py``.
  * D-2a #1 (audit actor_kind == session) — verify-email has no audit
    emission today; if Phase-4 lands an audit row, the per-PR test
    that adds it will own the assertion.
  * D-2a #2 / #3 / #4 / #5 — verify-email is a pre-session public
    endpoint exempt from CSRF and auth (see
    ``echoroo.core.auth_paths.PUBLIC_AUTH_PATHS``), so the rate-limit /
    CSRF / RBAC helpers do not apply.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.integration.api.web_v1._helpers import (
    assert_legacy_v1_rejects_bff_token,
)


# ---------------------------------------------------------------------------
# Route existence — OpenAPI surface assertion
# ---------------------------------------------------------------------------


def test_bff_verify_email_in_openapi_surface() -> None:
    """Assert ``POST /web-api/v1/auth/verify-email`` is declared on the app.

    PR J's path-parity gate will read
    :data:`tests.contract._bff_path_parity_allowlist.BFF_PATHS_DECLARED_BY_SPEC_009`
    and assert each entry resolves on the live OpenAPI schema. We
    pre-empt that gate here so a future revert of the handler fails the
    PR B follow-up suite directly, with a clear locality.

    The route is also registered as a public auth path in
    :data:`echoroo.core.auth_paths.PUBLIC_AUTH_PATHS` (so both the
    auth-router and CSRF middlewares bypass it pre-session). The
    parity check below is the lightweight wiring assertion; the
    PUBLIC_AUTH_PATHS registration is exercised implicitly by the
    501-stub assertion further down (a missing public-path
    registration would 401 / 403 long before the service is reached).
    """
    from echoroo.main import create_app

    app = create_app()
    openapi = app.openapi()
    paths = openapi.get("paths", {})
    assert "/web-api/v1/auth/verify-email" in paths, (
        "BFF verify-email mirror missing from OpenAPI surface. PR B "
        "follow-up requires the route at apps/api/echoroo/api/web_v1/"
        "auth.py to expose POST /verify-email so the frontend rewire "
        "(lib/api/auth.ts) does not 404 in production. Check that "
        "create_app() includes the web_v1 router and that the handler "
        "decorator is @router.post('/verify-email', ...)."
    )
    methods = {m.lower() for m in paths["/web-api/v1/auth/verify-email"]}
    assert "post" in methods, (
        f"BFF verify-email must accept POST, got methods={methods!r}"
    )


# ---------------------------------------------------------------------------
# Wiring — POST reaches the shared AuthService.verify_email stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bff_verify_email_invokes_shared_auth_service(
    client: AsyncClient,
) -> None:
    """POST /web-api/v1/auth/verify-email hits the shared service.

    The handler at ``apps/api/echoroo/api/web_v1/auth.py`` mirrors the
    legacy handler at ``apps/api/echoroo/api/v1/auth.py`` line 306: it
    builds ``AuthService(db)`` from ``echoroo.services.auth`` (the
    legacy implementation) and calls ``verify_email(token)``. That
    service method is currently a 501 Phase-4 stub
    (``apps/api/echoroo/services/auth.py`` line 280–293, raises
    ``HTTPException(501, _PHASE4_STUB_DETAIL)``).

    The assertion shape "BFF returns 501 with the Phase-4 stub message"
    is the proof that the BFF mirror does NOT re-implement the
    verification logic locally — it shares the legacy entry point so
    that whenever Phase 4 lands, BOTH surfaces flip together to the
    real implementation. If a future change accidentally bypasses the
    shared service (e.g. inlines a stub response or wires a divergent
    BFF copy), this assertion catches it.

    We send a syntactically valid but never-issued token so the
    request reaches the service layer (no schema-validation early
    return). Phase 4's real implementation will replace the 501 with
    400 ("invalid or expired token") — at that point this test should
    flip to ``assert response.status_code == 400`` (one-line update),
    not be deleted: the wiring assertion remains valuable as a
    forward-compatibility guard.
    """
    token = f"never-issued-{uuid.uuid4()}"
    response = await client.post(
        "/web-api/v1/auth/verify-email",
        json={"token": token},
    )
    # 501 = legacy AuthService.verify_email Phase-4 stub (see
    # apps/api/echoroo/services/auth.py:280). When Phase 4 lands the
    # real implementation, update this expectation to 400 (invalid
    # token) — the wiring assertion (status code is "the legacy stub
    # answer", not 404 / 405 / etc.) remains useful.
    assert response.status_code == 501, (
        f"BFF /verify-email must reach the shared AuthService.verify_email "
        f"stub (currently a 501 Phase-4 stub at services/auth.py:280). "
        f"Got status={response.status_code} body={response.text!r}. "
        f"A 404 would mean the route is unwired; a 405 / 422 would "
        f"mean the handler diverged from the legacy schema; a non-501 "
        f"2xx/4xx would mean the handler bypasses the shared service."
    )


@pytest.mark.asyncio
async def test_bff_verify_email_rejects_missing_token(
    client: AsyncClient,
) -> None:
    """Schema validation: missing ``token`` field returns 422.

    The handler imports :class:`echoroo.schemas.auth.EmailVerifyRequest`,
    which has a single required ``token: str`` field. FastAPI's
    pydantic-bound body validator returns 422 when it is absent. The
    assertion guards against a future change to the request schema
    that would silently widen the contract (e.g. swap to a different
    body model that makes ``token`` optional).
    """
    response = await client.post(
        "/web-api/v1/auth/verify-email",
        json={},
    )
    assert response.status_code == 422, (
        f"BFF /verify-email must validate the EmailVerifyRequest schema; "
        f"missing token field should yield 422, got {response.status_code}: "
        f"{response.text!r}"
    )


# ---------------------------------------------------------------------------
# FR-006 — legacy /api/v1 rejects BFF JWT for this path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_v1_verify_email_rejects_bff_jwt(
    unshimmed_client: AsyncClient,
    bff_jwt_factory: object,
) -> None:
    """FR-006: legacy ``/api/v1/auth/verify-email`` rejects BFF JWT.

    Even though verify-email is a pre-session public endpoint (no auth
    required by design), the auth-router middleware MUST still reject
    any request that presents a Bearer JWT shaped like a BFF-issued
    access token on the legacy ``/api/v1/*`` surface. The legacy
    programmatic surface only accepts ``echoroo_<prefix>_<secret>``
    Bearer credentials; a BFF-issued JWT must hit the canonical
    "API key invalid or revoked" 401 path.

    This pins the auth-surface separation contract for the
    verify-email route specifically, mirroring what
    :func:`tests.integration.api.web_v1._helpers.assert_legacy_v1_rejects_bff_token`
    asserts for every other migrated path.
    """
    factory = bff_jwt_factory  # noqa: F841 — kept for IDE attribution
    bff_token = bff_jwt_factory(user_id=uuid.uuid4())  # type: ignore[operator]
    await assert_legacy_v1_rejects_bff_token(
        unshimmed_client,
        "POST",
        "/api/v1/auth/verify-email",
        bff_token=bff_token,
        body={"token": "irrelevant-fr006-only-checks-auth-rejection"},
    )
