"""License service for license management."""

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.repositories.license import LicenseRepository
from echoroo.schemas.license import (
    LicenseCreate,
    LicenseListResponse,
    LicenseResponse,
    LicenseUpdate,
)


class LicenseService:
    """Service for license management operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize license service with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self.repo = LicenseRepository(db)

    async def list_licenses(self) -> LicenseListResponse:
        """List all licenses.

        Returns:
            List of all licenses
        """
        licenses = await self.repo.get_all()
        items = [LicenseResponse.model_validate(license) for license in licenses]
        return LicenseListResponse(items=items)

    async def get_license(self, license_id: str) -> LicenseResponse:
        """Get a license by ID.

        Args:
            license_id: License identifier code

        Returns:
            License details

        Raises:
            HTTPException: If license not found
        """
        license_obj = await self.repo.get_by_id(license_id)
        if not license_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"License with ID '{license_id}' not found",
            )

        return LicenseResponse.model_validate(license_obj)

    async def create_license(self, data: LicenseCreate) -> LicenseResponse:
        """Create a new license.

        Args:
            data: License creation data

        Returns:
            Created license

        Raises:
            HTTPException: If license with same ID already exists
        """
        # Check if license with same ID already exists
        existing = await self.repo.get_by_id(data.id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"License with ID '{data.id}' already exists",
            )

        try:
            license_obj = await self.repo.create(data)
            await self.db.commit()
            return LicenseResponse.model_validate(license_obj)
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Failed to create license: {e!s}",
            ) from e

    async def update_license(self, license_id: str, data: LicenseUpdate) -> LicenseResponse:
        """Update an existing license.

        Args:
            license_id: License identifier code
            data: License update data

        Returns:
            Updated license

        Raises:
            HTTPException: If license not found
        """
        try:
            license_obj = await self.repo.update(license_id, data)
            if not license_obj:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"License with ID '{license_id}' not found",
                )

            await self.db.commit()
            return LicenseResponse.model_validate(license_obj)
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Failed to update license: {e!s}",
            ) from e

    async def delete_license(self, license_id: str) -> None:
        """Delete a license.

        Args:
            license_id: License identifier code

        Raises:
            HTTPException: If license not found or cannot be deleted
        """
        try:
            deleted = await self.repo.delete(license_id)
            if not deleted:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"License with ID '{license_id}' not found",
                )

            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot delete license: it may be referenced by other records. {e!s}",
            ) from e
