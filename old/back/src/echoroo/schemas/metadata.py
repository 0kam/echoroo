"""Schemas for dataset metadata lookup tables."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from echoroo.schemas.base import BaseSchema
from echoroo.models.project import ProjectMemberRole
from echoroo.schemas.users import SimpleUser

__all__ = [
    "License",
    "LicenseCreate",
    "LicenseUpdate",
    "Project",
    "ProjectCreate",
    "ProjectUpdate",
    "Recorder",
    "RecorderCreate",
    "RecorderUpdate",
    "Site",
    "SiteCreate",
    "SiteUpdate",
    "SiteImage",
    "SiteImageCreate",
    "SiteImageUpdate",
    "ProjectMember",
    "ProjectMemberCreate",
    "ProjectMemberUpdate",
]


class Recorder(BaseSchema):
    """Recorder metadata."""

    recorder_id: str
    recorder_name: str
    manufacturer: str | None = None
    version: str | None = None
    usage_count: int = 0


class RecorderCreate(BaseModel):
    """Payload to create a recorder entry."""

    recorder_id: str
    recorder_name: str
    manufacturer: str | None = None
    version: str | None = None


class RecorderUpdate(BaseModel):
    """Payload to update a recorder entry."""

    recorder_name: str | None = None
    manufacturer: str | None = None
    version: str | None = None


class License(BaseSchema):
    """License metadata."""

    license_id: str
    license_name: str
    license_link: str
    usage_count: int = 0


class LicenseCreate(BaseModel):
    """Payload to create a license entry."""

    license_id: str
    license_name: str
    license_link: str


class LicenseUpdate(BaseModel):
    """Payload to update a license entry."""

    license_name: str | None = None
    license_link: str | None = None


class SiteImage(BaseSchema):
    """Site image metadata."""

    site_image_id: str
    site_id: str
    site_image_path: str


class SiteImageCreate(BaseModel):
    """Payload to create a site image entry."""

    site_image_id: str
    site_id: str
    site_image_path: str


class SiteImageUpdate(BaseModel):
    """Payload to update a site image entry."""

    site_image_path: str | None = None


class Site(BaseSchema):
    """Monitoring site metadata."""

    site_id: str
    site_name: str
    project_id: str
    h3_index: str
    images: list[SiteImage] = Field(default_factory=list)
    center_lat: float | None = None
    center_lon: float | None = None

    @model_validator(mode="after")
    def _compute_center_coords(self):
        """Compute center coordinates from H3 index."""
        if self.h3_index and (self.center_lat is None or self.center_lon is None):
            try:
                import h3
                lat, lon = h3.cell_to_latlng(self.h3_index)
                self.center_lat = lat
                self.center_lon = lon
            except Exception:
                # If H3 conversion fails, leave as None
                pass
        return self


class SiteCreate(BaseModel):
    """Payload to create a site entry."""

    site_id: str
    site_name: str
    project_id: str
    h3_index: str
    images: list[SiteImageCreate] = Field(default_factory=list)


class SiteUpdate(BaseModel):
    """Payload to update a site entry."""

    site_name: str | None = None
    project_id: str | None = None
    h3_index: str | None = None


class Project(BaseSchema):
    """Project metadata."""

    project_id: str
    project_name: str
    url: str | None = None
    description: str | None = None
    target_taxa: str | None = None
    admin_name: str | None = None
    admin_email: str | None = None
    is_active: bool = True
    memberships: list["ProjectMember"] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    """Payload to create a project entry."""

    project_name: str
    url: str | None = None
    description: str | None = None
    target_taxa: str | None = None
    admin_name: str | None = None
    admin_email: str | None = None
    is_active: bool = True
    initial_members: list["ProjectMemberCreate"] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    """Payload to update a project entry."""

    project_name: str | None = None
    url: str | None = None
    description: str | None = None
    target_taxa: str | None = None
    admin_name: str | None = None
    admin_email: str | None = None
    is_active: bool | None = None



class ProjectMember(BaseSchema):
    """Project membership assignment."""

    id: int
    project_id: str
    user_id: UUID
    role: ProjectMemberRole
    user: SimpleUser


class ProjectMemberCreate(BaseModel):
    """Payload to add a project member."""

    user_id: UUID
    role: ProjectMemberRole = ProjectMemberRole.MEMBER


class ProjectMemberUpdate(BaseModel):
    """Payload to change project membership."""

    id: int
    role: ProjectMemberRole


Project.model_rebuild()
ProjectCreate.model_rebuild()
ProjectUpdate.model_rebuild()
