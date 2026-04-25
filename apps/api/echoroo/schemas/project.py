"""Project request and response schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from echoroo.models.enums import (
    ProjectLicense,
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.schemas.auth import UserResponse


class ProjectOverviewSite(BaseModel):
    """Site summary within project overview."""

    id: UUID
    name: str
    h3_index: str
    latitude: float | None
    longitude: float | None
    recording_count: int
    dataset_count: int


class RecordingCalendarEntry(BaseModel):
    """Monthly recording activity entry."""

    year: int
    month: int
    site_count: int
    recording_count: int


class ProjectOverviewResponse(BaseModel):
    """Project overview aggregated statistics."""

    sites: list[ProjectOverviewSite]
    recording_calendar: list[RecordingCalendarEntry]
    total_recordings: int
    total_sites: int
    total_duration: float


class ProjectCreateRequest(BaseModel):
    """Project creation request schema."""

    name: str = Field(..., min_length=1, max_length=200, description="Project name")
    description: str | None = Field(None, description="Project description")
    visibility: ProjectVisibility = Field(
        default=ProjectVisibility.RESTRICTED, description="Project visibility level"
    )
    license: ProjectLicense = Field(..., description="Project data license")
    restricted_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Restricted visibility capability toggles",
    )


class ProjectUpdateRequest(BaseModel):
    """Project update request schema."""

    name: str | None = Field(None, min_length=1, max_length=200, description="Project name")
    description: str | None = Field(None, description="Project description")
    visibility: ProjectVisibility | None = Field(None, description="Project visibility level")
    license: ProjectLicense | None = Field(None, description="Project data license")
    restricted_config: dict[str, Any] | None = Field(
        None,
        description="Restricted visibility capability toggles",
    )
    status: ProjectStatus | None = Field(None, description="Project lifecycle status")


class ProjectResponse(BaseModel):
    """Project response schema."""

    id: UUID
    name: str
    description: str | None
    visibility: ProjectVisibility
    license: ProjectLicense
    restricted_config: dict[str, Any]
    restricted_config_version: int
    status: ProjectStatus
    dormant_since: datetime | None
    archived_since: datetime | None
    owner: UserResponse
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """Project list response schema with pagination."""

    items: list[ProjectResponse]
    total: int
    page: int
    limit: int


class ProjectMemberAddRequest(BaseModel):
    """Request to add a member to a project."""

    email: EmailStr = Field(..., description="User's email address")
    role: ProjectMemberRole = Field(default=ProjectMemberRole.MEMBER, description="Member role")


class ProjectMemberUpdateRequest(BaseModel):
    """Request to update a member's role."""

    role: ProjectMemberRole = Field(..., description="New member role")


class ProjectMemberResponse(BaseModel):
    """Project member response schema."""

    id: UUID
    user: UserResponse
    role: ProjectMemberRole
    joined_at: datetime
    expires_at: datetime | None
    removed_at: datetime | None

    model_config = {"from_attributes": True}
