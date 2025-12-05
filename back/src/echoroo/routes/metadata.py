"""REST routes for metadata lookup tables."""

from __future__ import annotations

import mimetypes
from pathlib import Path
import re
import shutil
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from echoroo import api, schemas, exceptions
from echoroo.api.common.permissions import can_manage_project
from echoroo.models.project import ProjectMember, ProjectMemberRole
from echoroo.routes.dependencies import Session
from echoroo.routes.dependencies.auth import get_current_user_dependency
from echoroo.routes.dependencies.settings import EchorooSettings

__all__ = ["get_metadata_router"]


def get_metadata_router(settings: EchorooSettings) -> APIRouter:
    current_user_dep = get_current_user_dependency(settings)

    # Dependency to require superuser access
    async def require_superuser(
        user: schemas.User = Depends(current_user_dep),
    ) -> schemas.User:
        if not user.is_superuser:
            raise exceptions.NotAuthorizedError("Superuser access required")
        return user

    admin_required_dep = require_superuser
    router = APIRouter()
    metadata_root = Path(settings.metadata_dir).expanduser()

    async def _commit(session: Session) -> None:
        await session.commit()

    def _add_trailing_alias(
        path: str,
        endpoint,
        *,
        methods: list[str],
        **kwargs,
    ) -> None:
        """Expose both `/path` and `/path/` for the same handler."""
        canonical = path.rstrip("/")
        router.add_api_route(
            f"{canonical}/",
            endpoint,
            methods=methods,
            include_in_schema=False,
            **kwargs,
        )

    async def _ensure_project_manager(
        session: Session,
        project_id: str,
        user,
    ) -> None:
        """Ensure the requesting user can manage the specified project."""
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authentication required.",
            )
        if not await can_manage_project(session, project_id, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be a project manager to perform this action.",
            )

    async def _get_project_member(
        session: Session,
        project_id: str,
        user_id: UUID,
    ) -> ProjectMember | None:
        return await session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )

    async def _ensure_manager_survives(
        session: Session,
        project_id: str,
        excluding_user: UUID | None = None,
    ) -> None:
        """Raise if the project would lose its last manager."""
        stmt = select(func.count()).select_from(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.role == ProjectMemberRole.MANAGER,
        )
        if excluding_user is not None:
            stmt = stmt.where(ProjectMember.user_id != excluding_user)
        manager_count = await session.scalar(stmt) or 0
        if manager_count <= 0:
            raise exceptions.InvalidDataError(
                "Projects must retain at least one manager.",
            )

    def _ensure_metadata_root() -> Path:
        metadata_root.mkdir(parents=True, exist_ok=True)
        return metadata_root

    def _sanitize_segment(value: str, fallback: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value)
        cleaned = cleaned.strip("._") or fallback
        return cleaned

    def _build_image_relative_path(
        site_id: str,
        site_image_id: str,
        filename: str | None,
    ) -> Path:
        site_segment = _sanitize_segment(site_id, "site")
        base_segment = _sanitize_segment(site_image_id, "site_image")
        suffix = Path(filename or "").suffix.lower()
        if not suffix:
            suffix = ".bin"
        filename_segment = f"{base_segment}{suffix}"
        return Path("sites") / site_segment / filename_segment

    def _resolve_relative_image_path(relative_path: Path | str) -> Path:
        root = _ensure_metadata_root()
        absolute = (root / Path(relative_path)).resolve()
        try:
            absolute.relative_to(root)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image path.",
            )
        return absolute

    def _delete_file_if_local(image_path: str | None) -> None:
        if not image_path:
            return
        try:
            absolute = _resolve_relative_image_path(Path(image_path))
        except HTTPException:
            return
        if absolute.exists():
            absolute.unlink(missing_ok=True)
            # Prune empty parent directories up to metadata root
            for parent in absolute.parents:
                if parent == metadata_root:
                    break
                try:
                    parent.relative_to(metadata_root)
                except ValueError:
                    break
                if any(parent.iterdir()):
                    break
                parent.rmdir()

    @router.get(
        "/recorders",
        response_model=list[schemas.Recorder],
    )
    async def list_recorders(
        session: Session,
        search: str | None = None,
    ):
        """List available recorders."""

        return await api.recorders.list(session, search=search)

    _add_trailing_alias(
        "/recorders",
        list_recorders,
        methods=["GET"],
        response_model=list[schemas.Recorder],
    )

    @router.post(
        "/recorders",
        response_model=schemas.Recorder,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(admin_required_dep)],
    )
    async def create_recorder(
        session: Session,
        payload: schemas.RecorderCreate,
    ):
        """Create a new recorder entry."""

        recorder = await api.recorders.create_from_data(session, payload)
        await _commit(session)
        return recorder

    _add_trailing_alias(
        "/recorders",
        create_recorder,
        methods=["POST"],
        response_model=schemas.Recorder,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(admin_required_dep)],
    )

    @router.patch(
        "/recorders/{recorder_id}",
        response_model=schemas.Recorder,
        dependencies=[Depends(admin_required_dep)],
    )
    async def update_recorder(
        session: Session,
        recorder_id: str,
        data: schemas.RecorderUpdate,
    ):
        """Update an existing recorder."""

        recorder = await api.recorders.get(session, recorder_id)
        updated = await api.recorders.update(session, recorder, data)
        await _commit(session)
        return updated

    _add_trailing_alias(
        "/recorders/{recorder_id}",
        update_recorder,
        methods=["PATCH"],
        response_model=schemas.Recorder,
        dependencies=[Depends(admin_required_dep)],
    )

    @router.delete(
        "/recorders/{recorder_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(admin_required_dep)],
    )
    async def delete_recorder(
        session: Session,
        recorder_id: str,
    ):
        """Delete a recorder entry."""
        recorder = await api.recorders.get(session, recorder_id)

        # Check usage count
        if hasattr(recorder, 'usage_count') and recorder.usage_count > 0:
            raise exceptions.InvalidDataError(
                f"Cannot delete recorder '{recorder_id}' because it is currently "
                f"used by {recorder.usage_count} dataset(s). "
                "Please update those datasets to use a different recorder first."
            )

        await api.recorders.delete(session, recorder)
        await _commit(session)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    _add_trailing_alias(
        "/recorders/{recorder_id}",
        delete_recorder,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(admin_required_dep)],
    )

    @router.get(
        "/licenses",
        response_model=list[schemas.License],
    )
    async def list_licenses(
        session: Session,
        search: str | None = None,
    ):
        """List available licenses."""

        return await api.licenses.list(session, search=search)

    _add_trailing_alias(
        "/licenses",
        list_licenses,
        methods=["GET"],
        response_model=list[schemas.License],
    )

    @router.post(
        "/licenses",
        response_model=schemas.License,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(admin_required_dep)],
    )
    async def create_license(
        session: Session,
        payload: schemas.LicenseCreate,
    ):
        """Create a new license entry."""

        license_obj = await api.licenses.create_from_data(session, payload)
        await _commit(session)
        return license_obj

    _add_trailing_alias(
        "/licenses",
        create_license,
        methods=["POST"],
        response_model=schemas.License,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(admin_required_dep)],
    )

    @router.patch(
        "/licenses/{license_id}",
        response_model=schemas.License,
        dependencies=[Depends(admin_required_dep)],
    )
    async def update_license(
        session: Session,
        license_id: str,
        data: schemas.LicenseUpdate,
    ):
        """Update an existing license."""

        license_obj = await api.licenses.get(session, license_id)
        updated = await api.licenses.update(session, license_obj, data)
        await _commit(session)
        return updated

    _add_trailing_alias(
        "/licenses/{license_id}",
        update_license,
        methods=["PATCH"],
        response_model=schemas.License,
        dependencies=[Depends(admin_required_dep)],
    )

    @router.delete(
        "/licenses/{license_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(admin_required_dep)],
    )
    async def delete_license(
        session: Session,
        license_id: str,
    ):
        """Delete a license entry."""
        license_obj = await api.licenses.get(session, license_id)

        # Check usage count
        if hasattr(license_obj, 'usage_count') and license_obj.usage_count > 0:
            raise exceptions.InvalidDataError(
                f"Cannot delete license '{license_id}' because it is currently "
                f"used by {license_obj.usage_count} dataset(s). "
                "Please update those datasets to use a different license first."
            )

        await api.licenses.delete(session, license_obj)
        await _commit(session)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    _add_trailing_alias(
        "/licenses/{license_id}",
        delete_license,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(admin_required_dep)],
    )

    @router.get(
        "/projects",
        response_model=list[schemas.Project],
    )
    async def list_projects(
        session: Session,
        search: str | None = None,
        is_active: bool | None = None,
    ):
        """List registered projects."""

        return await api.projects.list(
            session,
            search=search,
            is_active=is_active,
        )

    _add_trailing_alias(
        "/projects",
        list_projects,
        methods=["GET"],
        response_model=list[schemas.Project],
    )

    @router.post(
        "/projects",
        response_model=schemas.Project,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(admin_required_dep)],
    )
    async def create_project(
        session: Session,
        payload: schemas.ProjectCreate,
    ):
        """Create a project entry."""

        project = await api.projects.create_from_data(session, payload)
        await _commit(session)
        return project

    _add_trailing_alias(
        "/projects",
        create_project,
        methods=["POST"],
        response_model=schemas.Project,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(admin_required_dep)],
    )

    @router.get(
        "/projects/{project_id}",
        response_model=schemas.Project,
    )
    async def get_project(
        session: Session,
        project_id: str,
    ):
        """Get a specific project by ID."""
        project = await api.projects.get(session, project_id)
        return project

    _add_trailing_alias(
        "/projects/{project_id}",
        get_project,
        methods=["GET"],
        response_model=schemas.Project,
    )

    @router.patch(
        "/projects/{project_id}",
        response_model=schemas.Project,
    )
    async def update_project(
        session: Session,
        project_id: str,
        data: schemas.ProjectUpdate,
        user = Depends(current_user_dep),
    ):
        """Update an existing project."""

        await _ensure_project_manager(session, project_id, user)



        project = await api.projects.get(session, project_id)
        updated = await api.projects.update(session, project, data)
        await _commit(session)
        return updated

    _add_trailing_alias(
        "/projects/{project_id}",
        update_project,
        methods=["PATCH"],
        response_model=schemas.Project,
    )

    @router.delete(
        "/projects/{project_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(admin_required_dep)],
    )
    async def delete_project(
        session: Session,
        project_id: str,
    ):
        """Delete a project entry."""

        project = await api.projects.get(session, project_id)
        await api.projects.delete(session, project)
        await _commit(session)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    _add_trailing_alias(
        "/projects/{project_id}",
        delete_project,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(admin_required_dep)],
    )

    @router.get(
        "/sites",
        response_model=list[schemas.Site],
    )
    async def list_sites(
        session: Session,
        search: str | None = None,
        project_id: str | None = None,
    ):
        """List known monitoring sites."""

        return await api.sites.list(
            session,
            search=search,
            project_id=project_id,
        )

    _add_trailing_alias(
        "/sites",
        list_sites,
        methods=["GET"],
        response_model=list[schemas.Site],
    )

    @router.post(
        "/sites",
        response_model=schemas.Site,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_site(
        session: Session,
        payload: schemas.SiteCreate,
        user = Depends(current_user_dep),
    ):
        """Create a new site entry."""

        await _ensure_project_manager(session, payload.project_id, user)
        await api.projects.get(session, payload.project_id)

        site = await api.sites.create_from_data(session, payload)
        await _commit(session)
        return site

    _add_trailing_alias(
        "/sites",
        create_site,
        methods=["POST"],
        response_model=schemas.Site,
        status_code=status.HTTP_201_CREATED,
    )

    @router.patch(
        "/sites/{site_id}",
        response_model=schemas.Site,
    )
    async def update_site(
        session: Session,
        site_id: str,
        data: schemas.SiteUpdate,
        user = Depends(current_user_dep),
    ):
        """Update a site entry."""

        site = await api.sites.get(session, site_id)
        await api.projects.get(session, site.project_id)

        await _ensure_project_manager(session, site.project_id, user)

        if (
            data.project_id is not None
            and data.project_id != site.project_id
        ):
            await api.projects.get(session, data.project_id)
            await _ensure_project_manager(session, data.project_id, user)

        updated = await api.sites.update(session, site, data)
        await _commit(session)
        return updated

    _add_trailing_alias(
        "/sites/{site_id}",
        update_site,
        methods=["PATCH"],
        response_model=schemas.Site,
    )

    @router.delete(
        "/sites/{site_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_site(
        session: Session,
        site_id: str,
        user = Depends(current_user_dep),
    ):
        """Delete a site entry."""

        site = await api.sites.get(session, site_id)
        await _ensure_project_manager(session, site.project_id, user)
        stored_paths = [image.site_image_path for image in site.images]
        await api.sites.delete(session, site)
        await _commit(session)
        for path in stored_paths:
            _delete_file_if_local(path)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    _add_trailing_alias(
        "/sites/{site_id}",
        delete_site,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
    )

    @router.post(
        "/sites/{site_id}/images",
        response_model=schemas.SiteImage,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_site_image(
        session: Session,
        site_id: str,
        payload: schemas.SiteImageCreate,
        user = Depends(current_user_dep),
    ):
        """Attach an image to a site."""

        site = await api.sites.get(session, site_id)
        await _ensure_project_manager(session, site.project_id, user)

        image = await api.site_images.create_from_data(
            session,
            payload.model_copy(update={"site_id": site_id}),
        )
        await _commit(session)
        return image

    _add_trailing_alias(
        "/sites/{site_id}/images",
        create_site_image,
        methods=["POST"],
        response_model=schemas.SiteImage,
        status_code=status.HTTP_201_CREATED,
    )

    @router.post(
        "/sites/{site_id}/images/upload",
        response_model=schemas.SiteImage,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_site_image(
        session: Session,
        site_id: str,
        site_image_id: str = Form(...),
        file: UploadFile = File(...),
        user = Depends(current_user_dep),
    ):
        """Upload an image file and attach it to the site."""

        site = await api.sites.get(session, site_id)
        await _ensure_project_manager(session, site.project_id, user)

        identifier = site_image_id.strip()
        if not identifier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="site_image_id is required.",
            )

        if file.content_type and not file.content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only image uploads are supported.",
            )

        try:
            await api.site_images.get(session, identifier)
        except exceptions.NotFoundError:
            pass
        else:
            raise exceptions.InvalidDataError(
                f"Site image '{identifier}' already exists.",
            )

        relative_path = _build_image_relative_path(
            site_id,
            identifier,
            file.filename,
        )
        absolute_path = _resolve_relative_image_path(relative_path)
        absolute_path.parent.mkdir(parents=True, exist_ok=True)

        file.file.seek(0)
        with absolute_path.open("wb") as destination:
            shutil.copyfileobj(file.file, destination)

        try:
            image = await api.site_images.create_from_data(
                session,
                schemas.SiteImageCreate(
                    site_image_id=identifier,
                    site_id=site_id,
                    site_image_path=relative_path.as_posix(),
                ),
            )
        except Exception:
            absolute_path.unlink(missing_ok=True)
            raise

        await _commit(session)
        return image

    _add_trailing_alias(
        "/sites/{site_id}/images/upload",
        upload_site_image,
        methods=["POST"],
        response_model=schemas.SiteImage,
        status_code=status.HTTP_201_CREATED,
    )

    @router.patch(
        "/site_images/{site_image_id}",
        response_model=schemas.SiteImage,
    )
    async def update_site_image(
        session: Session,
        site_image_id: str,
        data: schemas.SiteImageUpdate,
        user = Depends(current_user_dep),
    ):
        """Update a site image entry."""

        image = await api.site_images.get(session, site_image_id)
        site = await api.sites.get(session, image.site_id)
        await _ensure_project_manager(session, site.project_id, user)

        updated = await api.site_images.update(session, image, data)
        await _commit(session)
        return updated

    _add_trailing_alias(
        "/site_images/{site_image_id}",
        update_site_image,
        methods=["PATCH"],
        response_model=schemas.SiteImage,
    )

    @router.delete(
        "/site_images/{site_image_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_site_image(
        session: Session,
        site_image_id: str,
        user = Depends(current_user_dep),
    ):
        """Remove a site image entry."""

        image = await api.site_images.get(session, site_image_id)
        site = await api.sites.get(session, image.site_id)
        await _ensure_project_manager(session, site.project_id, user)
        stored_path = image.site_image_path
        await api.site_images.delete(session, image)
        await _commit(session)
        _delete_file_if_local(stored_path)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    _add_trailing_alias(
        "/site_images/{site_image_id}",
        delete_site_image,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
    )

    @router.get("/site_images/{site_image_id}/download")
    async def download_site_image_file(
        session: Session,
        site_image_id: str,
    ):
        """Serve a locally stored site image."""

        image = await api.site_images.get(session, site_image_id)
        try:
            file_path = _resolve_relative_image_path(
                Path(image.site_image_path),
            )
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image file is not stored on this server.",
            )

        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image file not found.",
            )

        media_type, _ = mimetypes.guess_type(file_path.name)

        return FileResponse(
            file_path,
            media_type=media_type or "application/octet-stream",
            filename=file_path.name,
        )

    _add_trailing_alias(
        "/site_images/{site_image_id}/download",
        download_site_image_file,
        methods=["GET"],
    )

    @router.post(
        "/projects/{project_id}/members",
        response_model=schemas.ProjectMember,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_project_member(
        session: Session,
        project_id: str,
        payload: schemas.ProjectMemberCreate,
        user = Depends(current_user_dep),
    ):
        """Add a member to a project."""

        await _ensure_project_manager(session, project_id, user)
        await api.projects.get(session, project_id)

        existing_member = await _get_project_member(
            session,
            project_id=project_id,
            user_id=payload.user_id,
        )
        if existing_member is not None:
            raise exceptions.InvalidDataError(
                "User is already a member of this project.",
            )

        member = ProjectMember(
            project_id=project_id,
            user_id=payload.user_id,
            role=payload.role,
        )
        session.add(member)
        await session.flush()
        await _commit(session)
        return schemas.ProjectMember.model_validate(member)

    _add_trailing_alias(
        "/projects/{project_id}/members",
        add_project_member,
        methods=["POST"],
        response_model=schemas.ProjectMember,
        status_code=status.HTTP_201_CREATED,
    )

    @router.delete(
        "/projects/{project_id}/members/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def remove_project_member(
        session: Session,
        project_id: str,
        user_id: str,
        user = Depends(current_user_dep),
    ):
        """Remove a member from a project."""

        await _ensure_project_manager(session, project_id, user)
        await api.projects.get(session, project_id)

        member_user_id = UUID(user_id)
        member = await _get_project_member(session, project_id, member_user_id)

        if member is None:
            raise exceptions.NotFoundError(
                f"User {user_id} is not a member of project {project_id}.",
            )

        if member.role == ProjectMemberRole.MANAGER:
            await _ensure_manager_survives(
                session,
                project_id,
                excluding_user=member_user_id,
            )

        await session.delete(member)
        await _commit(session)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    _add_trailing_alias(
        "/projects/{project_id}/members/{user_id}",
        remove_project_member,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
    )

    @router.patch(
        "/projects/{project_id}/members/{user_id}/role",
        response_model=schemas.ProjectMember,
    )
    async def update_member_role(
        session: Session,
        project_id: str,
        user_id: str,
        role_data: schemas.ProjectMemberUpdate,
        user = Depends(current_user_dep),
    ):
        """Update a project member's role."""

        await _ensure_project_manager(session, project_id, user)
        await api.projects.get(session, project_id)

        member_user_id = UUID(user_id)
        member = await _get_project_member(session, project_id, member_user_id)

        if not member:
            raise exceptions.NotFoundError(
                f"User {user_id} is not a member of project {project_id}.",
            )

        target_role = role_data.role

        if target_role == member.role:
            return schemas.ProjectMember.model_validate(member)

        if (
            member.role == ProjectMemberRole.MANAGER
            and target_role != ProjectMemberRole.MANAGER
        ):
            await _ensure_manager_survives(
                session,
                project_id,
                excluding_user=member_user_id,
            )

        member.role = target_role
        await session.flush()
        await _commit(session)
        return schemas.ProjectMember.model_validate(member)

    _add_trailing_alias(
        "/projects/{project_id}/members/{user_id}/role",
        update_member_role,
        methods=["PATCH"],
        response_model=schemas.ProjectMember,
    )

    return router
