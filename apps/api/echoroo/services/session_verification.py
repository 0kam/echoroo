"""Session and API key verifiers for :class:`AuthRouterMiddleware` (T155).

This module wires the :class:`SessionVerifier` and :class:`ApiKeyVerifier`
protocol implementations declared in
:mod:`echoroo.middleware.auth_router` against the production data
stores.

Design notes
------------

* :class:`JwtSessionVerifier` resolves the first-party ``/web-api/v1/*``
  cookie session. The session cookie carries the **refresh-token family
  id** (see :func:`echoroo.api.web_v1.auth._set_session_cookies`) and
  the access JWT is supplied either in a cookie (legacy / SSR) or as a
  ``Authorization: Bearer`` header (SPA flow). The verifier:

  1. Looks up the family in :class:`echoroo.core.auth.SqlTokenStore`.
     A revoked or unknown family yields ``None``.
  2. Resolves the user the family belongs to (via
     ``token_families.user_id``) and reads the user's live
     ``security_stamp`` from ``users``. Returning that stamp lets the
     auth-router reject access tokens whose ``ss`` claim is stale
     (FR-055 / FR-071).
  3. Returns ``None`` for any malformed input — never raises — so the
     middleware can convert the failure into a uniform 401 response.

* :class:`StubApiKeyVerifier` is a deliberate no-op for now. The
  Phase 15 (T950+) admin-scope work will replace it with the real KMS-
  backed lookup. Until then, the legacy ``middleware.auth.get_current_*``
  Depends-based path remains the source of truth for ``/api/v1/*``
  authentication. Wiring the stub here keeps the middleware enabled so
  ``/web-api/v1/*`` benefits from the principal-resolution chain
  immediately, without prematurely flipping ``/api/v1/*`` over to a
  half-implemented verifier.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa

from echoroo.core.auth import SqlTokenStore
from echoroo.middleware.auth_router import ApiKeyRecord, ApiKeyVerifier, SessionVerifier


class JwtSessionVerifier(SessionVerifier):
    """:class:`SessionVerifier` implementation backed by Postgres.

    The constructor accepts an ``AsyncSession`` factory (typically
    :func:`echoroo.core.database.AsyncSessionLocal`) — each call opens
    its own short-lived session so the verifier never pins a connection
    between requests.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        # Reuse SqlTokenStore.is_family_revoked rather than reissuing
        # the same SELECT here — keeps the canonical token-state logic
        # in one place.
        self._token_store = SqlTokenStore(session_factory)

    async def verify(self, session_id: str) -> tuple[UUID, str] | None:
        """Resolve a session-cookie value to ``(user_id, security_stamp)``.

        ``session_id`` is the refresh-token family UUID written by
        ``_set_session_cookies`` at login / 2FA-completion time.

        Returns ``None`` if:

        * ``session_id`` is empty or not a valid UUID (defensive — the
          cookie value is attacker-controllable);
        * the family does not exist in ``token_families``;
        * the family has been revoked (``revoked_at IS NOT NULL``);
        * the user the family belongs to has been soft-deleted.
        """
        if not session_id:
            return None
        try:
            family_uuid = UUID(session_id)
        except (TypeError, ValueError):
            return None

        if await self._token_store.is_family_revoked(str(family_uuid)):
            return None

        async with self._session_factory() as session:
            row = await session.execute(
                sa.text(
                    "SELECT tf.user_id, u.security_stamp, u.deleted_at "
                    "FROM token_families tf "
                    "JOIN users u ON u.id = tf.user_id "
                    "WHERE tf.family_id = :family_id"
                ),
                {"family_id": family_uuid},
            )
            mapping = row.mappings().first()
            if mapping is None:
                return None
            if mapping["deleted_at"] is not None:
                # Soft-deleted users are treated as having no live
                # session even if the family row still exists.
                return None
            user_id = mapping["user_id"]
            stamp = mapping["security_stamp"]
            if not isinstance(stamp, str):
                return None
            if isinstance(user_id, UUID):
                resolved_user_id = user_id
            else:
                try:
                    resolved_user_id = UUID(str(user_id))
                except (TypeError, ValueError):
                    return None
            return (resolved_user_id, stamp)


class StubApiKeyVerifier(ApiKeyVerifier):
    """Placeholder verifier returned for ``/api/v1/*`` requests.

    TODO(Phase 15 T950+): replace with the real KMS-backed lookup once
    the admin-scope API key tooling lands.

    Until then, ``/api/v1/*`` routes continue to authenticate via the
    legacy :func:`echoroo.middleware.auth.get_current_user` dependency.
    To avoid the auth router pre-empting the legacy chain with a 401
    on every API call, :func:`echoroo.main.create_app` configures the
    middleware with a sentinel ``programmatic_prefix`` that does not
    match any real path — so requests to ``/api/v1/*`` fall through to
    the ``else`` branch (anonymous principal) and the existing Depends
    layer continues to handle them. Wiring this stub here documents
    the contract and keeps Phase 15 changes localised to a single
    ``StubApiKeyVerifier`` swap-out.
    """

    async def verify(self, raw_key: str) -> ApiKeyRecord | None:  # noqa: ARG002
        return None


__all__ = ["JwtSessionVerifier", "StubApiKeyVerifier"]
