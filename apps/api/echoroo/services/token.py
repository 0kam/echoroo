"""Legacy API token service.

The permissions-redesign baseline removed the ``api_tokens`` table. Phase 4
will introduce ``api_keys`` with a different schema, so this service keeps the
old call sites importable until that replacement lands.
"""

import hashlib
import secrets
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.user import User
from echoroo.schemas.token import APITokenCreateRequest


class TokenService:
    """Compatibility shell for legacy API-token call sites."""

    TOKEN_PREFIX = "ecr_"
    TOKEN_LENGTH = 32

    def __init__(self, db: AsyncSession) -> None:
        """Initialize token service."""
        self.db = db

    def _generate_token(self) -> str:
        """Generate a legacy-style token string for unchanged tests/helpers."""
        random_part = secrets.token_urlsafe(24)[: self.TOKEN_LENGTH]
        return f"{self.TOKEN_PREFIX}{random_part}"

    def _hash_token(self, token: str) -> str:
        """Hash a token using SHA256."""
        return hashlib.sha256(token.encode()).hexdigest()

    async def list_tokens(self, user_id: UUID) -> list[object]:
        """List API tokens.

        The legacy ``api_tokens`` table no longer exists. Phase 4 will add the
        new ``api_keys`` model/service with the baseline schema.
        """
        del user_id
        raise NotImplementedError("Phase 4: replace legacy api_tokens with api_keys")

    async def create_token(
        self, user_id: UUID, request: APITokenCreateRequest
    ) -> tuple[object, str]:
        """Create an API token."""
        del user_id, request
        raise NotImplementedError("Phase 4: replace legacy api_tokens with api_keys")

    async def revoke_token(self, user_id: UUID, token_id: UUID) -> None:
        """Revoke an API token."""
        del user_id, token_id
        raise NotImplementedError("Phase 4: replace legacy api_tokens with api_keys")

    async def authenticate_by_token(self, token: str) -> User | None:
        """Authenticate a user by API token."""
        del token
        raise NotImplementedError("Phase 4: replace legacy api_tokens with api_keys")

    async def get_token_by_id(self, user_id: UUID, token_id: UUID) -> object | None:
        """Get a specific API token by ID."""
        del user_id, token_id
        raise NotImplementedError("Phase 4: replace legacy api_tokens with api_keys")
