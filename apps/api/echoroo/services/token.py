"""API token service for token management and authentication."""

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.user import APIToken, User
from echoroo.schemas.token import APITokenCreateRequest


class TokenService:
    """Service for API token management.

    Handles creation, listing, revocation, and authentication of API tokens.
    Tokens are prefixed with 'ecr_' and stored as SHA256 hashes.
    """

    TOKEN_PREFIX = "ecr_"
    TOKEN_LENGTH = 32  # 32 random characters after prefix

    def __init__(self, db: AsyncSession) -> None:
        """Initialize token service.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    def _generate_token(self) -> str:
        """Generate a new API token.

        Returns:
            Plain text token with ecr_ prefix
        """
        random_part = secrets.token_urlsafe(24)[:self.TOKEN_LENGTH]
        return f"{self.TOKEN_PREFIX}{random_part}"

    def _hash_token(self, token: str) -> str:
        """Hash a token using SHA256.

        Args:
            token: Plain text token

        Returns:
            SHA256 hash of the token
        """
        return hashlib.sha256(token.encode()).hexdigest()

    async def list_tokens(self, user_id: UUID) -> list[APIToken]:
        """List all active API tokens for a user.

        Args:
            user_id: User's UUID

        Returns:
            List of active API tokens
        """
        result = await self.db.execute(
            select(APIToken)
            .where(APIToken.user_id == user_id, APIToken.is_active == True)  # noqa: E712
            .order_by(APIToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_token(
        self, user_id: UUID, request: APITokenCreateRequest
    ) -> tuple[APIToken, str]:
        """Create a new API token.

        Args:
            user_id: User's UUID
            request: Token creation request

        Returns:
            Tuple of (created token entity, plain text token)
        """
        # Generate token
        plain_token = self._generate_token()
        token_hash = self._hash_token(plain_token)

        # Create token entity
        api_token = APIToken(
            user_id=user_id,
            token_hash=token_hash,
            name=request.name,
            expires_at=request.expires_at,
        )

        self.db.add(api_token)
        await self.db.flush()
        await self.db.refresh(api_token)

        return api_token, plain_token

    async def revoke_token(self, user_id: UUID, token_id: UUID) -> None:
        """Revoke an API token.

        Args:
            user_id: User's UUID (for ownership verification)
            token_id: Token's UUID

        Raises:
            HTTPException: If token not found or not owned by user
        """
        result = await self.db.execute(
            select(APIToken).where(
                APIToken.id == token_id,
                APIToken.user_id == user_id,
                APIToken.is_active == True,  # noqa: E712
            )
        )
        api_token = result.scalar_one_or_none()

        if not api_token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Token not found",
            )

        api_token.is_active = False
        await self.db.flush()

    async def authenticate_by_token(self, token: str) -> User | None:
        """Authenticate a user by API token.

        Args:
            token: Plain text API token

        Returns:
            User instance if authentication successful, None otherwise
        """
        # Validate token format
        if not token.startswith(self.TOKEN_PREFIX):
            return None

        # Hash the token and look it up
        token_hash = self._hash_token(token)
        result = await self.db.execute(
            select(APIToken)
            .where(
                APIToken.token_hash == token_hash,
                APIToken.is_active == True,  # noqa: E712
            )
        )
        api_token = result.scalar_one_or_none()

        if not api_token:
            return None

        # Check expiration
        if api_token.expires_at and datetime.now(UTC) > api_token.expires_at:
            return None

        # Update last_used_at
        api_token.last_used_at = datetime.now(UTC)
        await self.db.commit()

        # Load the user
        user_result = await self.db.execute(
            select(User).where(User.id == api_token.user_id)
        )
        user = user_result.scalar_one_or_none()

        # Check if user is active
        if user and not user.is_active:
            return None

        return user

    async def get_token_by_id(self, user_id: UUID, token_id: UUID) -> APIToken | None:
        """Get a specific token by ID.

        Args:
            user_id: User's UUID (for ownership verification)
            token_id: Token's UUID

        Returns:
            APIToken if found and owned by user, None otherwise
        """
        result = await self.db.execute(
            select(APIToken).where(
                APIToken.id == token_id,
                APIToken.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
