"""Project request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from echoroo.models.enums import ProjectRole, ProjectVisibility
from echoroo.schemas.auth import UserResponse


class ProjectCreateRequest(BaseModel):
    """Project creation request schema."""

    name: str = Field(..., min_length=1, max_length=200, description="Project name")
    description: str | None = Field(None, description="Project description")
    target_taxa: str | None = Field(
        None, max_length=500, description="Target taxonomic groups (comma-separated)"
    )
    visibility: ProjectVisibility = Field(
        default=ProjectVisibility.PRIVATE, description="Project visibility level"
    )


class ProjectUpdateRequest(BaseModel):
    """Project update request schema."""

    name: str | None = Field(None, min_length=1, max_length=200, description="Project name")
    description: str | None = Field(None, description="Project description")
    target_taxa: str | None = Field(
        None, max_length=500, description="Target taxonomic groups (comma-separated)"
    )
    visibility: ProjectVisibility | None = Field(None, description="Project visibility level")


class ProjectResponse(BaseModel):
    """Project response schema."""

    id: UUID
    name: str
    description: str | None
    target_taxa: str | None
    visibility: ProjectVisibility
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
    role: ProjectRole = Field(default=ProjectRole.MEMBER, description="Member role")


class ProjectMemberUpdateRequest(BaseModel):
    """Request to update a member's role."""

    role: ProjectRole = Field(..., description="New member role")


class ProjectMemberResponse(BaseModel):
    """Project member response schema."""

    id: UUID
    user: UserResponse
    role: ProjectRole
    joined_at: datetime

    model_config = {"from_attributes": True}
