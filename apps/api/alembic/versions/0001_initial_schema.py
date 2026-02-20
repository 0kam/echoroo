"""Initial schema: create all tables.

Revision ID: 0001
Revises: None
Create Date: 2026-02-20 00:00:00.000000

This migration creates the complete initial database schema covering:
- Core administration tables (users, projects, system settings, licenses)
- Data management tables (sites, recorders, datasets, recordings, clips)
- Annotation tables (tags, annotation projects, tasks, clip/sound event annotations, notes)
- All association tables and enum types
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create all tables in dependency order."""

    # ------------------------------------------------------------------
    # Step 1: Create PostgreSQL enum types
    # All enums must be created before any table that references them.
    # ------------------------------------------------------------------

    # Core enums
    projectvisibility = sa.Enum(
        "private",
        "public",
        name="projectvisibility",
        create_type=True,
    )
    projectvisibility.create(op.get_bind(), checkfirst=True)

    projectrole = sa.Enum(
        "admin",
        "member",
        "viewer",
        name="projectrole",
        create_type=True,
    )
    projectrole.create(op.get_bind(), checkfirst=True)

    setting_type = sa.Enum(
        "string",
        "number",
        "boolean",
        "json",
        name="setting_type",
        create_type=True,
    )
    setting_type.create(op.get_bind(), checkfirst=True)

    # Data management enums
    datasetvisibility = sa.Enum(
        "private",
        "public",
        name="datasetvisibility",
        create_type=True,
    )
    datasetvisibility.create(op.get_bind(), checkfirst=True)

    datasetstatus = sa.Enum(
        "pending",
        "scanning",
        "processing",
        "completed",
        "failed",
        name="datasetstatus",
        create_type=True,
    )
    datasetstatus.create(op.get_bind(), checkfirst=True)

    datetimeparsestatus = sa.Enum(
        "pending",
        "success",
        "failed",
        name="datetimeparsestatus",
        create_type=True,
    )
    datetimeparsestatus.create(op.get_bind(), checkfirst=True)

    # Annotation enums
    tagcategory = sa.Enum(
        "species",
        "sound_type",
        "quality",
        name="tagcategory",
        create_type=True,
    )
    tagcategory.create(op.get_bind(), checkfirst=True)

    annotationprojectvisibility = sa.Enum(
        "private",
        "public",
        name="annotationprojectvisibility",
        create_type=True,
    )
    annotationprojectvisibility.create(op.get_bind(), checkfirst=True)

    annotationtaskstatus = sa.Enum(
        "pending",
        "in_progress",
        "completed",
        "review_pending",
        name="annotationtaskstatus",
        create_type=True,
    )
    annotationtaskstatus.create(op.get_bind(), checkfirst=True)

    reviewstatus = sa.Enum(
        "unreviewed",
        "approved",
        "rejected",
        name="reviewstatus",
        create_type=True,
    )
    reviewstatus.create(op.get_bind(), checkfirst=True)

    annotationsource = sa.Enum(
        "human",
        "model",
        name="annotationsource",
        create_type=True,
    )
    annotationsource.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # Step 2: Tables with no foreign key dependencies
    # ------------------------------------------------------------------

    # users table (no FK deps besides self-referential, none here)
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("organization", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_verification_token", sa.String(255), nullable=True),
        sa.Column("email_verification_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_reset_token", sa.String(255), nullable=True),
        sa.Column("password_reset_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_is_active", "users", ["is_active"])
    # Index for created_at (from TimestampMixin)
    op.create_index("ix_users_created_at", "users", ["created_at"])

    # licenses table (no FK deps)
    op.create_table(
        "licenses",
        sa.Column("id", sa.String(50), primary_key=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("short_name", sa.String(50), nullable=False),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Index for created_at (from TimestampMixin)
    op.create_index("ix_licenses_created_at", "licenses", ["created_at"])

    # recorders table (no FK deps)
    op.create_table(
        "recorders",
        sa.Column("id", sa.String(50), primary_key=True, nullable=False),
        sa.Column("manufacturer", sa.String(100), nullable=False),
        sa.Column("recorder_name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Index for created_at (from TimestampMixin)
    op.create_index("ix_recorders_created_at", "recorders", ["created_at"])

    # ------------------------------------------------------------------
    # Step 3: Tables depending only on users
    # ------------------------------------------------------------------

    # api_tokens table (depends on users)
    op.create_table(
        "api_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_index("ix_api_tokens_is_active", "api_tokens", ["is_active"])

    # login_attempts table (depends on users)
    op.create_table(
        "login_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_login_attempts_email", "login_attempts", ["email"])
    op.create_index("ix_login_attempts_ip_address", "login_attempts", ["ip_address"])
    op.create_index("ix_login_attempts_success", "login_attempts", ["success"])
    op.create_index("ix_login_attempts_attempted_at", "login_attempts", ["attempted_at"])
    op.create_index(
        "ix_login_attempts_email_attempted_at",
        "login_attempts",
        ["email", "attempted_at"],
    )
    op.create_index(
        "ix_login_attempts_ip_address_attempted_at",
        "login_attempts",
        ["ip_address", "attempted_at"],
    )

    # ------------------------------------------------------------------
    # Step 4: Projects and membership tables (depend on users)
    # ------------------------------------------------------------------

    # projects table (depends on users)
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_taxa", sa.String(500), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum("private", "public", name="projectvisibility", create_type=False),
            nullable=False,
            server_default="private",
        ),
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_visibility", "projects", ["visibility"])
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index("ix_projects_created_at", "projects", ["created_at"])

    # project_members table (depends on users, projects)
    op.create_table(
        "project_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum("admin", "member", "viewer", name="projectrole", create_type=False),
            nullable=False,
            server_default="member",
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "invited_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("user_id", "project_id", name="uq_user_project"),
    )
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index(
        "ix_project_members_project_id_user_id",
        "project_members",
        ["project_id", "user_id"],
    )

    # project_invitations table (depends on users, projects)
    op.create_table(
        "project_invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "member", "viewer", name="projectrole", create_type=False),
            nullable=False,
            server_default="member",
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column(
            "invited_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_project_invitations_project_id", "project_invitations", ["project_id"])
    op.create_index("ix_project_invitations_email", "project_invitations", ["email"])

    # system_settings table (depends on users)
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(100), primary_key=True, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "value_type",
            sa.Enum("string", "number", "boolean", "json", name="setting_type", create_type=False),
            nullable=False,
        ),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------
    # Step 5: Data management tables
    # sites depends on projects
    # ------------------------------------------------------------------

    # sites table (depends on projects)
    op.create_table(
        "sites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("h3_index", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_site_project_name"),
        sa.UniqueConstraint("project_id", "h3_index", name="uq_site_project_h3"),
    )
    op.create_index("ix_sites_project_id", "sites", ["project_id"])
    op.create_index("ix_sites_h3_index", "sites", ["h3_index"])
    op.create_index("ix_sites_created_at", "sites", ["created_at"])

    # datasets table (depends on sites, projects, recorders, licenses, users)
    op.create_table(
        "datasets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "site_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recorder_id",
            sa.String(50),
            sa.ForeignKey("recorders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "license_id",
            sa.String(50),
            sa.ForeignKey("licenses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("audio_dir", sa.String(500), nullable=False),
        sa.Column(
            "visibility",
            sa.Enum("private", "public", name="datasetvisibility", create_type=False),
            nullable=False,
            server_default="private",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "scanning",
                "processing",
                "completed",
                "failed",
                name="datasetstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("doi", sa.String(255), nullable=True),
        sa.Column("gain", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("datetime_pattern", sa.String(500), nullable=True),
        sa.Column("datetime_format", sa.String(100), nullable=True),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("processed_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_dataset_project_name"),
    )
    op.create_index("ix_datasets_project_id", "datasets", ["project_id"])
    op.create_index("ix_datasets_site_id", "datasets", ["site_id"])
    op.create_index("ix_datasets_status", "datasets", ["status"])
    op.create_index("ix_datasets_visibility", "datasets", ["visibility"])
    op.create_index("ix_datasets_created_at", "datasets", ["created_at"])

    # recordings table (depends on datasets)
    op.create_table(
        "recordings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False),
        sa.Column("samplerate", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("bit_depth", sa.Integer(), nullable=True),
        sa.Column("datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "datetime_parse_status",
            sa.Enum("pending", "success", "failed", name="datetimeparsestatus", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("datetime_parse_error", sa.Text(), nullable=True),
        sa.Column("time_expansion", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dataset_id", "path", name="uq_recording_dataset_path"),
    )
    op.create_index("ix_recordings_dataset_id", "recordings", ["dataset_id"])
    op.create_index("ix_recordings_hash", "recordings", ["hash"])
    op.create_index("ix_recordings_datetime", "recordings", ["datetime"])
    op.create_index(
        "ix_recordings_dataset_id_datetime",
        "recordings",
        ["dataset_id", "datetime"],
    )
    op.create_index("ix_recordings_created_at", "recordings", ["created_at"])

    # clips table (depends on recordings)
    op.create_table(
        "clips",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "recording_id",
            UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "recording_id", "start_time", "end_time", name="uq_clip_recording_time"
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_clip_valid_time_range"),
    )
    op.create_index("ix_clips_recording_id", "clips", ["recording_id"])
    op.create_index("ix_clips_created_at", "clips", ["created_at"])

    # ------------------------------------------------------------------
    # Step 6: Annotation tables
    # tags depends on projects
    # annotation_projects depends on projects, users
    # annotation_tasks depends on annotation_projects, clips, users
    # clip_annotations depends on annotation_tasks, clips, users
    # sound_event_annotations depends on clip_annotations, users
    # notes depends on users, clip_annotations, sound_event_annotations
    # Association tables depend on their respective parent tables.
    # ------------------------------------------------------------------

    # tags table (depends on projects; self-referential for parent_id)
    op.create_table(
        "tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "category",
            sa.Enum("species", "sound_type", "quality", name="tagcategory", create_type=False),
            nullable=False,
        ),
        sa.Column("gbif_taxon_key", sa.Integer(), nullable=True),
        sa.Column("scientific_name", sa.String(300), nullable=True),
        sa.Column("common_name", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "name", "category", name="uq_tag_project_name_category"
        ),
    )
    op.create_index("ix_tags_project_id", "tags", ["project_id"])
    op.create_index("ix_tags_category", "tags", ["category"])
    op.create_index("ix_tags_gbif_taxon_key", "tags", ["gbif_taxon_key"])
    op.create_index("ix_tags_created_at", "tags", ["created_at"])

    # annotation_projects table (depends on projects, users)
    op.create_table(
        "annotation_projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum(
                "private",
                "public",
                name="annotationprojectvisibility",
                create_type=False,
            ),
            nullable=False,
            server_default="private",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_annotation_project_project_name"
        ),
    )
    op.create_index(
        "ix_annotation_projects_project_id", "annotation_projects", ["project_id"]
    )
    op.create_index(
        "ix_annotation_projects_created_by_id", "annotation_projects", ["created_by_id"]
    )
    op.create_index("ix_annotation_projects_created_at", "annotation_projects", ["created_at"])

    # annotation_project_datasets association table
    # (depends on annotation_projects, datasets)
    op.create_table(
        "annotation_project_datasets",
        sa.Column(
            "annotation_project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("annotation_projects.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )

    # annotation_project_tags association table
    # (depends on annotation_projects, tags)
    op.create_table(
        "annotation_project_tags",
        sa.Column(
            "annotation_project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("annotation_projects.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )

    # annotation_tasks table (depends on annotation_projects, clips, users)
    op.create_table(
        "annotation_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "annotation_project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("annotation_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clip_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assigned_to_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "in_progress",
                "completed",
                "review_pending",
                name="annotationtaskstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "annotation_project_id", "clip_id", name="uq_annotation_task_project_clip"
        ),
    )
    op.create_index(
        "ix_annotation_tasks_project_status",
        "annotation_tasks",
        ["annotation_project_id", "status"],
    )
    op.create_index(
        "ix_annotation_tasks_assigned_to_id", "annotation_tasks", ["assigned_to_id"]
    )
    op.create_index("ix_annotation_tasks_created_at", "annotation_tasks", ["created_at"])

    # clip_annotations table (depends on annotation_tasks, clips, users)
    op.create_table(
        "clip_annotations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("annotation_tasks.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "clip_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "review_status",
            sa.Enum(
                "unreviewed",
                "approved",
                "rejected",
                name="reviewstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="unreviewed",
        ),
        sa.Column(
            "reviewed_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_clip_annotations_clip_id", "clip_annotations", ["clip_id"])
    op.create_index(
        "ix_clip_annotations_review_status", "clip_annotations", ["review_status"]
    )
    op.create_index("ix_clip_annotations_created_at", "clip_annotations", ["created_at"])

    # clip_annotation_tags association table (depends on clip_annotations, tags)
    op.create_table(
        "clip_annotation_tags",
        sa.Column(
            "clip_annotation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clip_annotations.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )

    # sound_event_annotations table (depends on clip_annotations, users)
    op.create_table(
        "sound_event_annotations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "clip_annotation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clip_annotations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("geometry", JSONB(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("human", "model", name="annotationsource", create_type=False),
            nullable=False,
            server_default="human",
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_sea_confidence_range",
        ),
    )
    op.create_index(
        "ix_sound_event_annotations_clip_annotation_id",
        "sound_event_annotations",
        ["clip_annotation_id"],
    )
    op.create_index(
        "ix_sound_event_annotations_created_at", "sound_event_annotations", ["created_at"]
    )

    # sound_event_annotation_tags association table
    # (depends on sound_event_annotations, tags)
    op.create_table(
        "sound_event_annotation_tags",
        sa.Column(
            "sound_event_annotation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sound_event_annotations.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )

    # notes table (depends on users, clip_annotations, sound_event_annotations)
    op.create_table(
        "notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "clip_annotation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clip_annotations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "sound_event_annotation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sound_event_annotations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(clip_annotation_id IS NOT NULL AND sound_event_annotation_id IS NULL) OR "
            "(clip_annotation_id IS NULL AND sound_event_annotation_id IS NOT NULL)",
            name="ck_note_exactly_one_parent",
        ),
    )
    op.create_index("ix_notes_clip_annotation_id", "notes", ["clip_annotation_id"])
    op.create_index(
        "ix_notes_sound_event_annotation_id", "notes", ["sound_event_annotation_id"]
    )
    op.create_index("ix_notes_created_at", "notes", ["created_at"])


def downgrade() -> None:
    """Drop all tables and enum types in reverse dependency order."""

    # ------------------------------------------------------------------
    # Step 1: Drop annotation tables (deepest dependency level first)
    # ------------------------------------------------------------------
    op.drop_table("notes")
    op.drop_table("sound_event_annotation_tags")
    op.drop_table("sound_event_annotations")
    op.drop_table("clip_annotation_tags")
    op.drop_table("clip_annotations")
    op.drop_table("annotation_tasks")
    op.drop_table("annotation_project_tags")
    op.drop_table("annotation_project_datasets")
    op.drop_table("annotation_projects")
    op.drop_table("tags")

    # ------------------------------------------------------------------
    # Step 2: Drop data management tables
    # ------------------------------------------------------------------
    op.drop_table("clips")
    op.drop_table("recordings")
    op.drop_table("datasets")
    op.drop_table("sites")

    # ------------------------------------------------------------------
    # Step 3: Drop core tables
    # ------------------------------------------------------------------
    op.drop_table("system_settings")
    op.drop_table("project_invitations")
    op.drop_table("project_members")
    op.drop_table("projects")
    op.drop_table("login_attempts")
    op.drop_table("api_tokens")

    # ------------------------------------------------------------------
    # Step 4: Drop independent tables
    # ------------------------------------------------------------------
    op.drop_table("recorders")
    op.drop_table("licenses")
    op.drop_table("users")

    # ------------------------------------------------------------------
    # Step 5: Drop PostgreSQL enum types
    # ------------------------------------------------------------------
    sa.Enum(name="annotationsource").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="reviewstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="annotationtaskstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="annotationprojectvisibility").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tagcategory").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="datetimeparsestatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="datasetstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="datasetvisibility").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="setting_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="projectrole").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="projectvisibility").drop(op.get_bind(), checkfirst=True)
