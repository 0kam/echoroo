"""API helpers for metadata lookup tables."""

from __future__ import annotations

from typing import ClassVar, Generic, Sequence, TypeVar

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload
from sqlalchemy.sql import ColumnExpressionArgument
from pydantic import BaseModel

from echoroo import models, schemas, exceptions
from echoroo.api.common import BaseAPI
from echoroo.filters.base import Filter

__all__ = [
    "recorders",
    "projects",
    "sites",
    "site_images",
    "licenses",
]

ModelT = TypeVar("ModelT", bound=models.Base)
SchemaT = TypeVar("SchemaT", bound=schemas.BaseSchema)
CreateSchemaT = TypeVar("CreateSchemaT", bound=BaseModel)
UpdateSchemaT = TypeVar("UpdateSchemaT", bound=BaseModel)


class StringLookupAPI(
    BaseAPI[
        str,
        ModelT,
        SchemaT,
        CreateSchemaT,
        UpdateSchemaT,
    ],
    Generic[ModelT, SchemaT, CreateSchemaT, UpdateSchemaT],
):
    """Base API for simple lookup tables keyed by a string."""

    pk_column_name: ClassVar[str]
    search_columns: ClassVar[tuple[InstrumentedAttribute, ...]] = ()
    default_sort_column: ClassVar[ColumnExpressionArgument | str | None] = None

    # --- BaseAPI overrides -------------------------------------------------
    def _get_pk_condition(self, pk: str) -> ColumnExpressionArgument:
        return getattr(self._model, self.pk_column_name) == pk

    def _get_pk_from_obj(self, obj):
        return getattr(obj, self.pk_column_name)

    def _key_fn(self, obj: dict):
        return obj.get(self.pk_column_name)

    def _get_key_column(self):
        return getattr(self._model, self.pk_column_name)

    # --- Query helpers -----------------------------------------------------
    def _resolve_sort_column(self) -> ColumnExpressionArgument | str:
        return type(self).default_sort_column or self._get_key_column()

    def build_search_filter(
        self,
        search: str,
    ) -> ColumnExpressionArgument | None:
        if not self.search_columns:
            return None

        like = f"%{search.lower()}%"
        return sa.or_(
            *(
                sa.func.lower(column).like(like)
                for column in self.search_columns
            )
        )

    async def list(
        self,
        session,
        *,
        search: str | None = None,
        extra_filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
    ) -> list[SchemaT]:
        filters: list[Filter | ColumnExpressionArgument] = []
        if extra_filters:
            filters.extend(extra_filters)
        if search:
            search_filter = self.build_search_filter(search)
            if search_filter is not None:
                filters.append(search_filter)

        items, _ = await self.get_many(
            session,
            filters=filters or None,
            sort_by=self._resolve_sort_column(),
            limit=None,
        )
        return list(items)


class RecorderAPI(
    StringLookupAPI[
        models.Recorder,
        schemas.Recorder,
        schemas.RecorderCreate,
        schemas.RecorderUpdate,
    ],
):
    _model = models.Recorder
    _schema = schemas.Recorder
    pk_column_name = "recorder_id"
    search_columns = (
        models.Recorder.recorder_id,
        models.Recorder.recorder_name,
    )
    default_sort_column = models.Recorder.recorder_name


class LicenseAPI(
    StringLookupAPI[
        models.License,
        schemas.License,
        schemas.LicenseCreate,
        schemas.LicenseUpdate,
    ],
):
    _model = models.License
    _schema = schemas.License
    pk_column_name = "license_id"
    search_columns = (
        models.License.license_id,
        models.License.license_name,
    )
    default_sort_column = models.License.license_name


class ProjectAPI(
    StringLookupAPI[
        models.Project,
        schemas.Project,
        schemas.ProjectCreate,
        schemas.ProjectUpdate,
    ],
):
    _model = models.Project
    _schema = schemas.Project
    pk_column_name = "project_id"
    search_columns = (
        models.Project.project_id,
        models.Project.project_name,
    )
    default_sort_column = models.Project.project_name

    def build_search_filter(
        self,
        search: str,
    ) -> ColumnExpressionArgument | None:
        like = f"%{search.lower()}%"
        return sa.or_(
            sa.func.lower(models.Project.project_id).like(like),
            sa.func.lower(models.Project.project_name).like(like),
            sa.func.lower(sa.coalesce(models.Project.description, "")).like(like),
        )

    async def create_from_data(
        self,
        session: AsyncSession,
        data: schemas.ProjectCreate | None = None,
        **kwargs,
    ) -> schemas.Project:
        """Create a project and optionally add initial members."""
        from echoroo.api.common.utils import create_object, get_values

        # Extract initial_members from data if present
        initial_members = []
        args = {}

        if data is not None:
            # Get values but exclude initial_members
            args.update(get_values(data))
            initial_members = args.pop("initial_members", [])

        args.update(kwargs)

        if not initial_members:
            raise exceptions.InvalidDataError(
                "At least one project manager must be assigned when creating a project."
            )

        seen_members: set[str] = set()
        has_manager = False
        normalized_members: list[tuple[str, models.ProjectMemberRole]] = []
        for member_data in initial_members:
            if isinstance(member_data, dict):
                user_id = member_data["user_id"]
                role = member_data.get(
                    "role",
                    models.ProjectMemberRole.MEMBER,
                )
            else:
                user_id = member_data.user_id
                role = getattr(
                    member_data,
                    "role",
                    models.ProjectMemberRole.MEMBER,
                )

            if user_id in seen_members:
                raise exceptions.InvalidDataError(
                    "Duplicate project members are not allowed."
                )
            seen_members.add(str(user_id))

            if isinstance(role, str):
                try:
                    role_enum = models.ProjectMemberRole(role)
                except ValueError as error:
                    raise exceptions.InvalidDataError(
                        f"Unsupported project role '{role}'."
                    ) from error
            else:
                role_enum = role

            if role_enum == models.ProjectMemberRole.MANAGER:
                has_manager = True

            normalized_members.append((user_id, role_enum))

        if not has_manager:
            raise exceptions.InvalidDataError(
                "Projects must have at least one manager."
            )

        # Create the project directly without initial_members
        db_obj = await create_object(session, self._model, None, **args)

        # Add initial members if provided
        for user_id, role in normalized_members:
            member = models.ProjectMember(
                project_id=db_obj.project_id,
                user_id=user_id,
                role=role,
            )
            session.add(member)

        # Flush to persist members
        await session.flush()

        # Reload with eager loading of memberships and user details
        from echoroo.models.project import ProjectMember

        stmt = (
            select(self._model)
            .where(self._model.project_id == db_obj.project_id)
            .options(
                selectinload(self._model.memberships).selectinload(
                    ProjectMember.user
                )
            )
        )
        result = await session.execute(stmt)
        db_obj = result.scalar_one()

        # Validate and cache
        project = self._schema.model_validate(db_obj)
        self._update_cache(project)

        return project

    async def get(
        self,
        session: AsyncSession,
        pk: str,
    ) -> schemas.Project:
        """Get a single project with memberships and user details eager loaded."""
        from echoroo.models.project import ProjectMember

        stmt = (
            select(self._model)
            .where(self._model.project_id == pk)
            .options(
                selectinload(self._model.memberships).selectinload(
                    ProjectMember.user
                )
            )
        )
        result = await session.execute(stmt)
        db_obj = result.scalar_one_or_none()

        if db_obj is None:
            raise exceptions.NotFoundError(f"Project with id {pk} not found")

        project = self._schema.model_validate(db_obj)
        self._update_cache(project)
        return project

    async def get_many(
        self,
        session: AsyncSession,
        *,
        limit: int | None = None,
        offset: int | None = None,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = None,
    ) -> tuple[Sequence[schemas.Project], int]:
        """Get many projects with memberships and user details eager loaded."""
        from sqlalchemy.orm import selectinload
        from echoroo.models.project import ProjectMember

        # Build the query with eager loading
        stmt = select(models.Project).options(
            selectinload(models.Project.memberships).selectinload(
                ProjectMember.user
            )
        )

        # Apply filters
        if filters:
            for f in filters:
                if isinstance(f, Filter):
                    stmt = f(stmt)
                else:
                    stmt = stmt.where(f)

        # Apply sorting
        if sort_by is not None:
            if isinstance(sort_by, str):
                if sort_by.startswith("-"):
                    stmt = stmt.order_by(
                        getattr(models.Project, sort_by[1:]).desc()
                    )
                else:
                    stmt = stmt.order_by(getattr(models.Project, sort_by))
            else:
                stmt = stmt.order_by(sort_by)
        else:
            stmt = stmt.order_by(self.default_sort_column)

        # Get total count
        count_stmt = select(sa.func.count()).select_from(models.Project)
        if filters:
            for f in filters:
                if isinstance(f, Filter):
                    count_stmt = f(count_stmt)
                else:
                    count_stmt = count_stmt.where(f)
        count = await session.scalar(count_stmt) or 0

        # Apply pagination
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        # Execute query
        result = await session.execute(stmt)
        objs = result.scalars().all()

        # Validate and return
        return [self._schema.model_validate(obj) for obj in objs], count

    async def update(
        self,
        session: AsyncSession,
        obj: schemas.Project,
        data: schemas.ProjectUpdate,
    ) -> schemas.Project:
        """Update a project and return it with memberships loaded."""
        from echoroo.api.common.utils import update_object
        from echoroo.models.project import ProjectMember

        # Get the DB object
        db_obj = await session.get(self._model, obj.project_id)
        if db_obj is None:
            raise exceptions.NotFoundError(f"Project {obj.project_id} not found")

        # Update it
        # We need to convert Pydantic model to dict for update_object if it isn't already
        # But update_object handles Pydantic models
        updated_db_obj = await update_object(
            session,
            self._model,
            self._get_pk_condition(obj.project_id),
            data,
        )
        
        # We need to ensure memberships are loaded for the response schema
        # We can't easily "refresh" with options on an already loaded object in async session 
        # in the same way as sync. 
        # But we can re-query it with options.
        stmt = (
            select(self._model)
            .where(self._model.project_id == updated_db_obj.project_id)
            .options(
                selectinload(self._model.memberships).selectinload(
                    ProjectMember.user
                )
            )
        )
        result = await session.execute(stmt)
        refreshed_obj = result.scalar_one()

        return self._schema.model_validate(refreshed_obj)

    async def list(
        self,
        session,
        *,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> list[schemas.Project]:
        extra_filters: list[ColumnExpressionArgument] = []
        if is_active is not None:
            extra_filters.append(models.Project.is_active.is_(is_active))

        items = await super().list(
            session,
            search=search,
            extra_filters=extra_filters or None,
        )
        return items


class SiteAPI(
    StringLookupAPI[
        models.Site,
        schemas.Site,
        schemas.SiteCreate,
        schemas.SiteUpdate,
    ],
):
    _model = models.Site
    _schema = schemas.Site
    pk_column_name = "site_id"
    search_columns = (
        models.Site.site_id,
        models.Site.site_name,
    )
    default_sort_column = models.Site.site_name

    async def create_from_data(
        self,
        session: AsyncSession,
        data: schemas.SiteCreate | None = None,
        **kwargs,
    ) -> schemas.Site:
        """Create a site with H3 index validation."""
        import h3
        from echoroo.api.common.utils import create_object, get_values

        args = {}
        if data is not None:
            args.update(get_values(data))
        args.update(kwargs)

        # Remove images from args as they should be created separately
        args.pop("images", None)

        # Validate H3 index
        h3_index = args.get("h3_index")
        if h3_index and not h3.is_valid_cell(h3_index):
            raise exceptions.InvalidDataError(
                f"Invalid H3 cell index: {h3_index}"
            )

        db_obj = await create_object(session, self._model, None, **args)

        # Refresh the object with relationships loaded to avoid MissingGreenlet error
        await session.refresh(db_obj, attribute_names=["images"])

        return self._schema.model_validate(db_obj)

    async def update(
        self,
        session: AsyncSession,
        obj: schemas.Site,
        data: schemas.SiteUpdate,
    ) -> schemas.Site:
        """Update a site with H3 index validation."""
        import h3
        from echoroo.api.common.utils import update_object

        # Validate H3 index if being updated
        if data.h3_index is not None and not h3.is_valid_cell(data.h3_index):
            raise exceptions.InvalidDataError(
                f"Invalid H3 cell index: {data.h3_index}"
            )

        db_obj = await session.get(self._model, obj.site_id)
        if db_obj is None:
            raise exceptions.NotFoundError(f"Site {obj.site_id} not found")

        updated_db_obj = await update_object(
            session,
            self._model,
            self._get_pk_condition(obj.site_id),
            data,
        )
        
        # Refresh the object with relationships loaded to avoid MissingGreenlet error
        # We can't easily "refresh" with options on an already loaded object in async session 
        # in the same way as sync. 
        # But we can re-query it with options.
        stmt = (
            select(self._model)
            .where(self._model.site_id == updated_db_obj.site_id)
            .options(selectinload(self._model.images))
        )
        result = await session.execute(stmt)
        refreshed_obj = result.scalar_one()

        return self._schema.model_validate(refreshed_obj)

    async def get(
        self,
        session: AsyncSession,
        pk: str,
    ) -> schemas.Site:
        """Get a single site with images eager loaded."""
        stmt = (
            select(self._model)
            .where(self._model.site_id == pk)
            .options(selectinload(self._model.images))
        )
        result = await session.execute(stmt)
        db_obj = result.scalar_one_or_none()

        if db_obj is None:
            raise exceptions.NotFoundError(f"Site with id {pk} not found")

        site = self._schema.model_validate(db_obj)
        self._update_cache(site)
        return site

    async def list(
        self,
        session,
        *,
        search: str | None = None,
        project_id: str | None = None,
    ) -> list[schemas.Site]:
        stmt = select(models.Site).options(selectinload(models.Site.images))

        if project_id:
            stmt = stmt.where(models.Site.project_id == project_id)

        if search:
            search_filter = self.build_search_filter(search)
            if search_filter is not None:
                stmt = stmt.where(search_filter)

        stmt = stmt.order_by(self._resolve_sort_column())
        result = await session.execute(stmt)
        return [
            schemas.Site.model_validate(row)
            for row in result.scalars().unique().all()
        ]


class SiteImageAPI(
    StringLookupAPI[
        models.SiteImage,
        schemas.SiteImage,
        schemas.SiteImageCreate,
        schemas.SiteImageUpdate,
    ],
):
    _model = models.SiteImage
    _schema = schemas.SiteImage
    pk_column_name = "site_image_id"


recorders = RecorderAPI()
licenses = LicenseAPI()
projects = ProjectAPI()
sites = SiteAPI()
site_images = SiteImageAPI()
