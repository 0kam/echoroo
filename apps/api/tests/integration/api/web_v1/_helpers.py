"""D-2a adapter acceptance helpers for the /web-api/v1 BFF surface.

Spec/009 (Browser API → BFF Migration) defines a five-point acceptance
contract that every migrated BFF adapter MUST satisfy, plus FR-006 (the
mirror direction: legacy ``/api/v1/*`` rejects BFF-issued JWTs). The
reference for the contract is
``specs/009-browser-api-bff-migration/research.md`` §D-2a:

  1. Audit ``actor_kind == 'session'`` for every BFF action emitted.
  2. Rate-limit bucket = "web" (not the API-key bucket).
  3. API-key cross-rejection: BFF rejects ``Authorization: Bearer
     echoroo_<prefix>_<secret>`` with HTTP 401 + the canonical
     ``"API key invalid or revoked"`` body.
  4. Permission denial returns 403, NOT 401 (D-7 — the frontend's
     auto-logout fires on 401 only, so any RBAC denial that returns 401
     would log the user out).
  5. CSRF on every BFF mutation: requests missing ``X-CSRF-Token`` are
     rejected with 403.

Plus FR-006 (mirror of #3):

  6. Legacy ``/api/v1/*`` rejects BFF-issued Bearer JWTs with the same
     canonical 401 + ``"API key invalid or revoked"`` body. The check
     MUST be executed against an *unshimmed* FastAPI app (the default
     integration ``client`` fixture installs a Bearer-JWT shim that
     synthesises a full-scope principal from any JWT, which would mask
     the production rejection). See
     :mod:`tests.integration.api.web_v1.conftest` for the
     ``unshimmed_client`` + ``bff_jwt_factory`` fixtures.

Helpers exported by this module:

  * :func:`assert_audit_actor_kind_session`       (D-2a #1, T004)
  * :func:`assert_rate_limit_bucket_web`          (D-2a #2, T005)
  * :func:`assert_api_key_cross_rejected`         (D-2a #3, T006)
  * :func:`assert_permission_denial_returns_403`  (D-2a #4, T007)
  * :func:`assert_csrf_required`                  (D-2a #5, T008)
  * :func:`assert_legacy_v1_rejects_bff_token`    (FR-006,  T009a)

Each helper carries the minimum surface area required by the per-PR
tests (T030 / T032 / T057 / T086 / T095 / T101 / T107 etc.). Helpers
DO NOT seed users / projects / API keys — the per-PR test owns its
fixtures. The helpers only encode the assertion shape so every PR
matches the D-2a contract byte-for-byte.

References
----------
* ``specs/009-browser-api-bff-migration/research.md`` §D-2a / D-7
* ``specs/009-browser-api-bff-migration/tasks.md`` T004–T009b
* ``apps/api/tests/contract/test_auth_separation.py`` (sibling pattern,
  unshimmed client + BFF JWT factory)
* ``apps/api/tests/security/csrf/test_api_v1_no_cookie.py`` (sibling
  unshimmed-client pattern)
* ``apps/api/echoroo/middleware/auth_router.py`` (``Principal.auth_kind``
  is ``"session"`` or ``"api_key"``)
* ``apps/api/echoroo/middleware/csrf.py`` (``CSRF_HEADER_NAME``)
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "API_KEY_CANONICAL_REJECTION_MESSAGE",
    "assert_api_key_cross_rejected",
    "assert_audit_actor_kind_session",
    "assert_csrf_required",
    "assert_legacy_v1_rejects_bff_token",
    "assert_permission_denial_returns_403",
    "assert_rate_limit_bucket_web",
]

# Canonical rejection message emitted by ``AuthRouterMiddleware`` when an
# echoroo_* API key (or any non-echoroo_* Bearer) fails to resolve to a
# live ``api_keys`` row. The middleware lives at
# ``apps/api/echoroo/middleware/auth_router.py:504``. The string is part
# of the wire contract — frontend code keys off it as well — so the
# helpers assert on it verbatim.
API_KEY_CANONICAL_REJECTION_MESSAGE: str = "API key invalid or revoked"


# ---------------------------------------------------------------------------
# T004 — assert_audit_actor_kind_session
# ---------------------------------------------------------------------------


async def assert_audit_actor_kind_session(
    db: AsyncSession,
    audit_id_or_filter: UUID | str | dict[str, Any],
    *,
    expected: str = "session",
    table: str = "project_audit_log",
) -> dict[str, Any]:
    """Assert the audit-log row's ``actor_kind`` matches ``expected``.

    D-2a #1. Every BFF mutation must emit an audit row whose actor type
    is the session principal, never the API-key principal — otherwise
    the audit trail incorrectly attributes the mutation to a programmatic
    caller.

    The current ``project_audit_log`` / ``platform_audit_log`` schema
    does not have a dedicated ``actor_kind`` column (see
    ``apps/api/alembic/versions/0001_baseline_permissions_redesign.py``
    lines ~1147–1214). The ``Principal.auth_kind`` field (``"session"``
    vs ``"api_key"``) is the runtime source of truth and is persisted
    into the audit row's ``detail`` JSONB under the key ``actor_kind``
    by the BFF adapter handlers. The helper therefore reads
    ``detail->>'actor_kind'`` — the per-PR backend implementation is
    responsible for setting this key in the audit ``detail`` payload it
    passes to :class:`echoroo.services.audit_service.AuditService`.

    Args:
        db: Async SQLAlchemy session bound to the test database.
        audit_id_or_filter: One of —

            * A row primary key (``UUID`` or hex string): the helper
              fetches that specific row.
            * A filter dict (e.g. ``{"action": "PROJECT_CREATE",
              "project_id": <pid>}``): the helper picks the most-recent
              row matching all key/value pairs.

        expected: Expected ``actor_kind`` value. Defaults to
            ``"session"`` (the BFF surface always emits session-actor
            rows). Pass ``"api_key"`` only if a test deliberately
            exercises a mixed-surface scenario.
        table: Override the audit table. Defaults to
            ``project_audit_log``; pass ``"platform_audit_log"`` for
            auth / superuser / API-key actions.

    Returns:
        The full audit row as a ``dict`` (column → value), so callers
        can perform additional assertions (e.g. ``before`` / ``after``
        payload checks) without re-querying.
    """
    # Build the query against the requested audit table. We go via raw
    # SQL rather than the SQLAlchemy ORM because the audit-log models
    # are not currently exposed as ORM mappings (the writer uses
    # ``sa.text(...)`` directly — see ``audit_service.py:350``).
    if isinstance(audit_id_or_filter, dict):
        if not audit_id_or_filter:
            raise ValueError(
                "assert_audit_actor_kind_session: filter dict must not be empty"
            )
        where_clauses = []
        params: dict[str, Any] = {}
        for key, value in audit_id_or_filter.items():
            # Whitelist column names by allowing alphanumerics + underscore
            # only. Audit-log column names follow this shape so any value
            # outside it would be a programming error in the test.
            if not key.replace("_", "").isalnum():
                raise ValueError(
                    f"assert_audit_actor_kind_session: unsafe column name: {key!r}"
                )
            where_clauses.append(f"{key} = :{key}")
            params[key] = value
        where_sql = " AND ".join(where_clauses)
        query = sa.text(
            f"SELECT * FROM {table} WHERE {where_sql} "
            "ORDER BY created_at DESC LIMIT 1"
        )
        result = await db.execute(query, params)
    else:
        row_id = (
            audit_id_or_filter
            if isinstance(audit_id_or_filter, UUID)
            else UUID(str(audit_id_or_filter))
        )
        query = sa.text(f"SELECT * FROM {table} WHERE id = :id")
        result = await db.execute(query, {"id": row_id})

    row = result.mappings().first()
    if row is None:
        raise AssertionError(
            f"assert_audit_actor_kind_session: no row found in {table} "
            f"matching {audit_id_or_filter!r}"
        )

    row_dict: dict[str, Any] = dict(row)
    detail = row_dict.get("detail") or {}
    if not isinstance(detail, dict):
        raise AssertionError(
            f"assert_audit_actor_kind_session: {table}.detail is not a JSON "
            f"object for row {row_dict.get('id')!r} (got {type(detail).__name__})"
        )

    actor_kind = detail.get("actor_kind")
    assert actor_kind == expected, (
        f"assert_audit_actor_kind_session: expected detail.actor_kind == "
        f"{expected!r} on {table} row {row_dict.get('id')!r}, "
        f"got {actor_kind!r}. Full detail: {detail!r}"
    )
    return row_dict


# ---------------------------------------------------------------------------
# T005 — assert_rate_limit_bucket_web
# ---------------------------------------------------------------------------


def assert_rate_limit_bucket_web(response: Response) -> None:
    """Assert the request was rate-limited under the "web" bucket.

    D-2a #2. The BFF surface MUST land its rate-limit accounting in a
    session/web bucket — never the per-API-key bucket
    (``rl:apikey:<key_id>:<category>`` — see
    ``apps/api/echoroo/middleware/rate_limit_buckets.py:142``). If a
    migration accidentally reuses the API-key bucket scope, a single
    user can starve every machine-to-machine integration that shares
    the same API key, and worse, exhausting a programmatic budget would
    return 429s on first-party traffic.

    Mechanism:

      The codebase exposes generic ``X-RateLimit-{Limit,Remaining,Reset}``
      headers (see ``apps/api/echoroo/middleware/security.py:278``) but
      does not embed the bucket name in the response. The most reliable
      signal available to a black-box integration test is therefore the
      *absence* of the API-key-bucket marker the per-API-key
      middleware emits when an ``apikey:`` scope is consumed. The
      assertion here is:

        * No header with prefix ``X-RateLimit-API-Key-`` may be present
          (the per-API-key middleware adds this prefix when it consumes
          an ``apikey:<id>:<category>`` bucket — production codepath).
        * Either the standard ``X-RateLimit-Limit`` header is missing
          (no bucket was consumed — request never crossed a limiter,
          which is also valid for BFF reads) OR it is present with a
          generic / web bucket (i.e. its companion header
          ``X-RateLimit-Bucket`` — if present — does NOT start with
          ``apikey:``).

      This is a permissive form: it does NOT require the response to
      carry a bucket marker, only that no API-key-bucket marker leaks
      through. The contract is documented as "rate-limit accounting did
      not land on the API-key bucket".
    """
    # Inspect every header case-insensitively. ``Response.headers`` is
    # already case-insensitive but iterating its items returns the
    # original casing, which makes the assertion message readable.
    for name, value in response.headers.items():
        lower = name.lower()
        # The per-API-key rate-limit middleware (if wired to a BFF route
        # — which would be a regression) tags responses with an explicit
        # API-key bucket prefix. Any such header here = bug.
        if lower.startswith("x-ratelimit-api-key-"):
            raise AssertionError(
                "assert_rate_limit_bucket_web: response carries an API-key "
                f"rate-limit header ({name}={value!r}) — the BFF surface "
                "must not route through the per-API-key bucket"
            )
        # Some deployments add an ``X-RateLimit-Bucket`` companion that
        # names the scope explicitly. If present, it must not name an
        # API-key scope.
        if lower == "x-ratelimit-bucket" and value.lower().startswith("apikey:"):
            raise AssertionError(
                "assert_rate_limit_bucket_web: X-RateLimit-Bucket names an "
                f"apikey scope ({value!r}) — expected web/session bucket"
            )


# ---------------------------------------------------------------------------
# T006 — assert_api_key_cross_rejected
# ---------------------------------------------------------------------------


async def assert_api_key_cross_rejected(
    client: AsyncClient,
    method: str,
    path: str,
    *,
    body: Any | None = None,
) -> Response:
    """Assert /web-api/v1/* rejects an API-key Bearer credential.

    D-2a #3. The BFF surface authenticates via the ``echoroo_session``
    cookie + ``X-CSRF-Token`` header. Any request that arrives carrying
    ``Authorization: Bearer echoroo_<prefix>_<secret>`` is treated as a
    surface-confusion attempt — the BFF MUST reject with HTTP 401 and
    the canonical body :data:`API_KEY_CANONICAL_REJECTION_MESSAGE`.

    The helper sends a syntactically valid but never-issued API key so
    no DB seed is required. The point of failure is the verifier path,
    not the surface routing.

    Args:
        client: An ``httpx.AsyncClient`` bound to the FastAPI app.
        method: HTTP method (case-insensitive).
        path: Target ``/web-api/v1/...`` path.
        body: Optional JSON body for mutating methods.

    Returns:
        The ``Response`` so callers can attach further assertions.
    """
    if not path.startswith("/web-api/v1/"):
        raise ValueError(
            f"assert_api_key_cross_rejected: path must be /web-api/v1/*, "
            f"got {path!r}. Use assert_legacy_v1_rejects_bff_token for "
            "the reverse direction (FR-006)."
        )

    # Build a syntactically valid but never-issued key. The
    # ``echoroo_<prefix>_<secret>`` wire shape is parsed by
    # ``services/api_key_verification.parse_api_key`` — using
    # ``token_hex(4)`` for the prefix guarantees the 8-char
    # ``[A-Za-z0-9]`` constraint and avoids ``_`` collisions in the
    # prefix segment.
    fake_key = f"echoroo_{secrets.token_hex(4)}_{secrets.token_urlsafe(32)}"
    headers = {"Authorization": f"Bearer {fake_key}"}

    response = await client.request(
        method.upper(),
        path,
        headers=headers,
        json=body,
    )
    assert response.status_code == 401, (
        f"assert_api_key_cross_rejected: {method.upper()} {path} with a "
        f"Bearer echoroo_* key must return 401, got {response.status_code}: "
        f"{response.text!r}"
    )
    assert API_KEY_CANONICAL_REJECTION_MESSAGE in response.text, (
        f"assert_api_key_cross_rejected: {method.upper()} {path} 401 body "
        f"must contain {API_KEY_CANONICAL_REJECTION_MESSAGE!r}, got "
        f"{response.text!r}"
    )
    return response


# ---------------------------------------------------------------------------
# T007 — assert_permission_denial_returns_403
# ---------------------------------------------------------------------------


async def assert_permission_denial_returns_403(
    client: AsyncClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any | None = None,
    cookies: dict[str, str] | None = None,
) -> Response:
    """Assert RBAC denial on a BFF route returns 403, NOT 401.

    D-2a #4 + D-7. The frontend's session-refresh + auto-logout flow
    keys off HTTP 401: any 401 on a BFF route is interpreted as "the
    session is dead, log the user out and redirect to /login". That is
    correct for *authentication* failures (no cookie, expired session)
    but catastrophic for *authorisation* failures (the user is logged
    in fine, they just lack permission for this resource) — a 401 on a
    permission denial would log out a perfectly-good session.

    The caller's responsibility:

      Build a ``client`` / ``headers`` / ``cookies`` triple that
      authenticates the caller as a real but unprivileged user (e.g.
      a VIEWER member trying to mutate a project they cannot edit, or
      a non-member trying to read a restricted project). The helper
      itself only asserts the *status code* — it does not seed
      identities.

    Args:
        client: An ``httpx.AsyncClient`` bound to the FastAPI app.
        method: HTTP method (case-insensitive).
        path: Target ``/web-api/v1/...`` path.
        headers: Additional headers (typically ``X-CSRF-Token`` for
            mutations).
        body: Optional JSON body for mutating methods.
        cookies: Session cookies for the authenticated-but-unauthorised
            identity.

    Returns:
        The ``Response`` so callers can attach further assertions.
    """
    response = await client.request(
        method.upper(),
        path,
        headers=headers,
        json=body,
        cookies=cookies,
    )
    assert response.status_code == 403, (
        f"assert_permission_denial_returns_403: {method.upper()} {path} "
        f"with authenticated-but-unauthorised credentials must return 403 "
        f"(NOT 401 — would trigger frontend auto-logout per D-7), got "
        f"{response.status_code}: {response.text!r}"
    )
    return response


# ---------------------------------------------------------------------------
# T008 — assert_csrf_required
# ---------------------------------------------------------------------------


async def assert_csrf_required(
    client: AsyncClient,
    method: str,
    path: str,
    *,
    body: Any | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Response:
    """Assert BFF mutation rejects requests without ``X-CSRF-Token``.

    D-2a #5. Every BFF mutation (POST / PUT / PATCH / DELETE) on the
    ``/web-api/v1/*`` surface is double-submit-cookie CSRF-protected
    (see ``apps/api/echoroo/middleware/csrf.py``). A request that
    presents a valid session cookie but omits the
    ``X-CSRF-Token`` header MUST be rejected with HTTP 403.

    The caller's responsibility: supply a ``client`` already carrying a
    valid session cookie (typically via ``cookies={"echoroo_session":
    ...}`` or by logging in earlier in the test). The helper strips
    ``X-CSRF-Token`` from any forwarded ``headers`` and asserts the 403
    response.

    Args:
        client: An ``httpx.AsyncClient`` bound to the FastAPI app.
        method: HTTP method (case-insensitive). Must be a mutating
            method — GET / HEAD / OPTIONS are not CSRF-protected and
            using the helper for them would always fail.
        path: Target ``/web-api/v1/...`` mutation path.
        body: Optional JSON body for the mutation.
        headers: Additional headers. ``X-CSRF-Token`` is dropped if
            present (case-insensitive).
        cookies: Session cookies for the authenticated identity.

    Returns:
        The ``Response`` so callers can attach further assertions.
    """
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        raise ValueError(
            f"assert_csrf_required: {method.upper()} is not CSRF-protected "
            "(only mutations are). The helper is for POST / PUT / PATCH / "
            "DELETE."
        )

    # Defensively drop any X-CSRF-Token header the caller passed in by
    # mistake — the whole point is to send the request *without* CSRF.
    sent_headers: dict[str, str] = {}
    if headers:
        for name, value in headers.items():
            if name.lower() == "x-csrf-token":
                continue
            sent_headers[name] = value

    response = await client.request(
        method.upper(),
        path,
        headers=sent_headers,
        json=body,
        cookies=cookies,
    )
    assert response.status_code == 403, (
        f"assert_csrf_required: {method.upper()} {path} without X-CSRF-Token "
        f"must return 403, got {response.status_code}: {response.text!r}"
    )
    return response


# ---------------------------------------------------------------------------
# T009a — assert_legacy_v1_rejects_bff_token
# ---------------------------------------------------------------------------


async def assert_legacy_v1_rejects_bff_token(
    unshimmed_client: AsyncClient,
    method: str,
    path: str,
    *,
    bff_token: str,
    body: Any | None = None,
) -> Response:
    """Assert legacy /api/v1/* rejects a BFF-issued Bearer JWT.

    FR-006 (mirror of D-2a #3). The legacy programmatic surface only
    accepts ``echoroo_<prefix>_<secret>`` Bearer credentials. A
    BFF-issued JWT (the cookie-session refresh token's access-token
    payload) MUST be rejected by the legacy surface with HTTP 401 and
    the canonical :data:`API_KEY_CANONICAL_REJECTION_MESSAGE` body —
    same as for any non-echoroo_* Bearer.

    The ``unshimmed_client`` argument MUST be the conftest fixture
    that builds the FastAPI app WITHOUT the integration-suite default
    Bearer-JWT shim (see :mod:`tests.integration.api.web_v1.conftest`).
    The shim patches ``AuthRouterMiddleware._authenticate_api_key`` to
    synthesise a full-scope ``Principal`` from any JWT — convenient for
    legacy test ergonomics but it masks the very rejection FR-006 is
    asserting.

    Args:
        unshimmed_client: The ``unshimmed_client`` fixture from
            ``tests.integration.api.web_v1.conftest``.
        method: HTTP method (case-insensitive).
        path: Target ``/api/v1/...`` path (legacy mount).
        bff_token: BFF-issued access token (use the
            ``bff_jwt_factory`` fixture).
        body: Optional JSON body for mutating methods.

    Returns:
        The ``Response`` so callers can attach further assertions.
    """
    if not path.startswith("/api/v1/"):
        raise ValueError(
            f"assert_legacy_v1_rejects_bff_token: path must be /api/v1/* "
            f"(legacy mount), got {path!r}. Use assert_api_key_cross_rejected "
            "for the BFF→API-key direction (D-2a #3)."
        )

    response = await unshimmed_client.request(
        method.upper(),
        path,
        headers={"Authorization": f"Bearer {bff_token}"},
        json=body,
    )
    assert response.status_code == 401, (
        f"assert_legacy_v1_rejects_bff_token: {method.upper()} {path} with "
        f"a BFF-issued Bearer JWT must return 401, got {response.status_code}: "
        f"{response.text!r}"
    )
    assert API_KEY_CANONICAL_REJECTION_MESSAGE in response.text, (
        f"assert_legacy_v1_rejects_bff_token: {method.upper()} {path} 401 "
        f"body must contain {API_KEY_CANONICAL_REJECTION_MESSAGE!r}, got "
        f"{response.text!r}"
    )
    return response
