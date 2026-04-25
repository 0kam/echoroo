"""Stub credential store for superuser WebAuthn credentials.

Phase 4 T150c uses an in-memory dict; Phase 15 T950 will wire the real
Superuser ORM with the ``superusers.webauthn_credentials`` JSONB column.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from echoroo.core.settings import get_settings
from echoroo.services.webauthn_service import StoredCredential

settings = get_settings()
if settings.ENVIRONMENT == "production":
    raise RuntimeError(
        "InMemorySuperuserCredentialStore is not production-safe. "
        "Phase 15 T950 must wire the real Superuser ORM before production deploy."
    )


class SuperuserCredentialStore(Protocol):
    async def get_credentials(self, user_id: UUID) -> list[StoredCredential]: ...

    async def save_credentials(
        self,
        user_id: UUID,
        credentials: list[StoredCredential],
    ) -> None: ...


class InMemorySuperuserCredentialStore:
    """Process-local stub. NOT production-safe; multi-worker incoherent.

    TODO Phase 15 T950: replace with SqlSuperuserCredentialStore that reads
    /writes superusers.webauthn_credentials JSONB.
    """

    def __init__(self) -> None:
        self._store: dict[UUID, list[StoredCredential]] = {}

    async def get_credentials(self, user_id: UUID) -> list[StoredCredential]:
        return list(self._store.get(user_id, []))

    async def save_credentials(
        self,
        user_id: UUID,
        credentials: list[StoredCredential],
    ) -> None:
        self._store[user_id] = list(credentials)


_default_store = InMemorySuperuserCredentialStore()


def get_default_store() -> SuperuserCredentialStore:
    return _default_store
