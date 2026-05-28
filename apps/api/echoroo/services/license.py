"""License service for license management."""

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.repositories.license import LicenseRepository
from echoroo.schemas.license import (
    LicenseCreate,
    LicenseListResponse,
    LicensePublicListResponse,
    LicensePublicResponse,
    LicenseResponse,
    LicenseUpdate,
)


class LicenseInUseError(Exception):
    """Raised when a license cannot be deleted because rows still reference it.

    spec/012 FR-006 + FR-012 + FR-015. Carries the offending license's
    ``short_name`` plus a per-table dependency count so the API layer
    can render the actionable 409 envelope without re-running queries.

    The error is raised in TWO scenarios that share the same payload
    shape (see ``contracts/admin-licenses-delete.yaml`` NOTE_race_condition):

    1. **Pre-query refusal** — :meth:`LicenseService.delete_license`
       runs :meth:`LicenseRepository.count_dependents` first and raises
       this error when either count > 0, without ever issuing the
       ``DELETE`` statement.
    2. **FK race recovery** — when the pre-query returns ``(0, 0)`` but
       a concurrent INSERT writes a referencing row before the
       ``DELETE`` lands, PostgreSQL raises ``ForeignKeyViolation`` (FK
       ``ON DELETE RESTRICT``). The service catches the
       :class:`sqlalchemy.exc.IntegrityError`, re-runs the count, and
       raises this error with the freshly-recounted values. No sentinel
       — the response body is structurally identical to path (1).
    """

    def __init__(
        self,
        *,
        short_name: str,
        project_count: int,
        dataset_count: int,
    ) -> None:
        self.short_name = short_name
        self.project_count = project_count
        self.dataset_count = dataset_count
        super().__init__(
            f"License {short_name!r} is still in use "
            f"(projects={project_count}, datasets={dataset_count})"
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

    async def list_public(self) -> LicensePublicListResponse:
        """Return the public license list (spec/012 FR-001/FR-002/FR-017).

        Delegates to :meth:`LicenseRepository.list_all` so the rows are
        ordered by ``short_name`` ascending. The wire shape is the
        :class:`LicensePublicResponse` subset (no timestamps) — see
        ``specs/012-license-master-unification/contracts/web-licenses.yaml``.
        FR-017 makes this readable by ANY authenticated caller (the
        endpoint layer enforces the auth, not this method).
        """
        licenses = await self.repo.list_all()
        items = [LicensePublicResponse.model_validate(lic) for lic in licenses]
        return LicensePublicListResponse(items=items)

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
        """Delete a license (spec/012 FR-006 / FR-012 / FR-015).

        Layered defence:

        1. Service-layer pre-query computes the dependency counts via
           :meth:`LicenseRepository.count_dependents`. Either count > 0
           raises :class:`LicenseInUseError` before any ``DELETE`` is
           issued — the row, the dependents, and the rest of the
           transaction are untouched.
        2. Otherwise the ``DELETE`` runs. The FK ``ON DELETE RESTRICT``
           is the authoritative gate against a concurrent INSERT that
           landed between steps 1 and 2. When that fires we re-run the
           dependency count (post-race counts) and re-raise as
           :class:`LicenseInUseError` so the API layer always sees the
           same exception shape (no sentinel — the response body is
           structurally identical to the pre-query refusal path).

        Args:
            license_id: License identifier code

        Raises:
            HTTPException: 404 when the license id does not exist.
            LicenseInUseError: 409 mapping; refused due to dependents.
        """
        license_obj = await self.repo.get_by_id(license_id)
        if license_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"License with ID '{license_id}' not found",
            )

        # Pre-query path — refuse before issuing the DELETE.
        project_count, dataset_count = await self.repo.count_dependents(license_id)
        if project_count > 0 or dataset_count > 0:
            raise LicenseInUseError(
                short_name=license_obj.short_name,
                project_count=project_count,
                dataset_count=dataset_count,
            )

        try:
            await self.repo.delete(license_id)
            await self.db.commit()
        except IntegrityError as exc:
            # Race window: pre-count returned (0, 0) but a concurrent
            # INSERT wrote a referencing row before the DELETE landed.
            # The FK ``ON DELETE RESTRICT`` rejected the statement —
            # re-run the count so the 409 body reflects post-race state.
            await self.db.rollback()
            post_project_count, post_dataset_count = await self.repo.count_dependents(
                license_id
            )
            raise LicenseInUseError(
                short_name=license_obj.short_name,
                project_count=post_project_count,
                dataset_count=post_dataset_count,
            ) from exc
