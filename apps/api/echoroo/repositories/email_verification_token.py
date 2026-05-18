"""Repository helpers for email verification tokens."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update

from echoroo.models.email_verification_token import EmailVerificationToken
from echoroo.repositories.base import BaseRepository


class EmailVerificationTokenRepository(BaseRepository[EmailVerificationToken]):
    """Database operations for hash-only email verification tokens."""

    model = EmailVerificationToken

    async def create(self, token: EmailVerificationToken) -> EmailVerificationToken:
        self.db.add(token)
        await self.db.flush()
        await self.db.refresh(token)
        return token

    async def supersede_active_for_user(
        self,
        *,
        user_id: UUID,
        purpose: str,
        superseded_at: datetime,
    ) -> None:
        """Mark all unconsumed active tokens for ``user_id``/``purpose`` obsolete."""
        await self.db.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == user_id,
                EmailVerificationToken.purpose == purpose,
                EmailVerificationToken.consumed_at.is_(None),
                EmailVerificationToken.superseded_at.is_(None),
            )
            .values(superseded_at=superseded_at, updated_at=superseded_at)
        )
        await self.db.flush()

    async def get_by_token_hash_for_update(
        self,
        token_hash: str,
    ) -> EmailVerificationToken | None:
        """Load a token row by hash, locking it when the database supports it."""
        result = await self.db.execute(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.token_hash == token_hash)
            .with_for_update()
        )
        return result.scalar_one_or_none()
