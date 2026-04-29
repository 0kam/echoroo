"""Baseline schema for the 006-permissions-redesign feature.

Revision ID: 0001
Revises: None
Create Date: 2026-04-24 00:00:00.000000

This is the single authoritative baseline after wiping the 24 legacy migrations
(archived to ``alembic/versions/.archive/``). It creates the full database
schema from scratch per spec FR-113.

Structure follows data-model.md:
- T020a: Enum types (11) + users + superusers + superuser_approval_requests
         + outbox_events (early) + system_settings (seeded)
- T020b: projects + project_license_history + project_members
         + project_invitations + project_trusted_users
         + project_taxon_sensitivity_overrides + sites + recordings
         + datasets + detections + annotations + tags
- T020c: annotation_votes + annotation_comments + taxon_sensitivities
         + iucn_sync_attempts + api_keys + project_audit_log
         + platform_audit_log + dek_rewrap_failures + wipe_guard
- T020d: All indexes per data-model §5, CHECK constraints (FR-048, FR-027,
         FR-091 etc.), sites.h3_index_member_resolution default 15 (NFR-003),
         system_settings seed (NFR-006)
- T020e: Triggers ``prevent_last_superuser_deletion`` (FR-111a, echoroo_app
         only) and ``forbid_audit_log_mutation`` (FR-094)
- T020f: ACL REVOKE UPDATE, DELETE on audit log tables and
         project_license_history from echoroo_app (FR-094)
- T020g: Genesis INSERT into project_audit_log and platform_audit_log with
         ``prev_hash = repeat('0', 64)`` (FR-092, data-model §3.17)

The ``downgrade`` path is intentionally a full teardown: the baseline is not
meant to be rolled back via alembic in production. The reverse direction is
covered by the ``scripts.wipe_database`` script guarded by the three-point
wipe_guard (FR-114).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op
from echoroo._alembic_phase13_supporting_ddl import (
    SUPPORTING_TABLES_REVERSE_DROP_ORDER,
    apply_phase13_supporting_tables,
)

# Revision identifiers used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# --------------------------------------------------------------------------- #
# Enum type definitions (T020a)
# --------------------------------------------------------------------------- #

# Legacy-compat enums reused by the supporting tables (datasets/detections/...)
#
# Phase 13 P1 (T803): ``detectionsource`` widened to seven values to match the
# ORM canonical shape (BirdNET / Perch / Perch search / similarity search /
# custom SVM / human / sampling round). On existing dev DBs the four new
# values are also added by 0006a via ``ALTER TYPE ... ADD VALUE``; the
# duplication is intentional so a fresh DB reaches the final shape from the
# baseline alone (FR-113), and the delta migration remains idempotent for
# DBs already past 0005.
_LEGACY_ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("datasetstatus", ("pending", "scanning", "processing", "completed", "failed")),
    ("datasetvisibility", ("private", "public")),
    ("tagcategory", ("species", "sound_type", "quality")),
    (
        "detectionsource",
        (
            "birdnet",
            "perch",
            "perch_search",
            "similarity_search",
            "custom_svm",
            "human",
            "sampling_round",
        ),
    ),
    ("detectionstatus", ("unreviewed", "confirmed", "rejected")),
    ("annotationsource", ("human", "model")),
)

# Permission-redesign enums from data-model §1 (11 total).
_REDESIGN_ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("projectvisibility", ("public", "restricted")),
    ("projectstatus", ("active", "dormant", "archived")),
    ("projectmemberrole", ("viewer", "member", "admin")),
    ("projectlicense", ("CC0", "CC-BY", "CC-BY-NC", "CC-BY-SA")),
    ("invitationkind", ("member", "trusted")),
    (
        "invitationstatus",
        ("pending", "accepted", "declined", "expired", "revoked"),
    ),
    ("trusteduserstatus", ("active", "expired", "revoked")),
    (
        "annotationvotesource",
        ("member", "guest_authenticated", "trusted_user"),
    ),
    ("taxonsensitivitysource", ("iucn", "moe_rdb", "manual")),
    ("taxonoverridedirection", ("stricter", "looser")),
    (
        "taxonoverrideapprovalstatus",
        ("applied", "pending_superuser_approval", "rejected"),
    ),
)


# Phase 13 P1 (T803): 16 ORM-only enums needed by the 32 supporting tables
# below. Names MUST match the ``Enum(name=...)`` parameter on each ORM
# ``mapped_column``; see ``apps/api/echoroo/models/*.py``. The list mirrors
# ``alembic/versions/0006_schema_reconcile_static.py::_PHASE13_ENUMS`` so a
# fresh DB built from 0001 ends up byte-for-byte identical to a long-lived
# dev DB that arrives via 0001 + 0005 + 0006 + 0006a. The ``setting_type``
# enum was retired with ``system_settings.value_type`` in T803a so the
# count is 16, not 17.
_PHASE13_ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("datetimeparsestatus", ("pending", "success", "failed")),
    ("annotation_set_status", ("sampling", "ready", "in_progress", "completed")),
    ("annotation_segment_status", ("unannotated", "annotated", "skipped")),
    (
        "annotationtaskstatus",
        ("pending", "in_progress", "completed", "review_pending"),
    ),
    ("annotationprojectvisibility", ("private", "public")),
    ("reviewstatus", ("unreviewed", "approved", "rejected")),
    ("geometrytype", ("BoundingBox", "TimeInterval")),
    ("signalquality", ("solo", "dominant", "mixed")),
    (
        "consensusstatus",
        ("needs_votes", "agreed", "rejected", "disputed"),
    ),
    ("detectionrunstatus", ("pending", "running", "completed", "failed")),
    (
        "uploadsessionstatus",
        (
            "issued",
            "uploaded",
            "validating",
            "validated",
            "importing",
            "imported",
            "failed",
        ),
    ),
    (
        "uploadfilestatus",
        ("pending", "uploaded", "valid", "invalid", "imported"),
    ),
    ("searchsessionstatus", ("pending", "running", "completed", "failed")),
    ("votetype", ("agree", "disagree", "unsure")),
    (
        "custommodelstatus",
        ("draft", "training", "trained", "deployed", "failed", "archived"),
    ),
    (
        "evaluation_run_status",
        ("pending", "running", "completed", "failed"),
    ),
)


def _create_enums(enums: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    bind = op.get_bind()
    for name, values in enums:
        sa.Enum(*values, name=name, create_type=True).create(bind, checkfirst=True)


def _drop_enums(enums: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    bind = op.get_bind()
    for name, _ in enums:
        sa.Enum(name=name).drop(bind, checkfirst=True)


def _enum(name: str) -> postgresql.ENUM:
    """Reference an already-created enum without re-emitting CREATE TYPE.

    We use ``postgresql.ENUM`` (not ``sa.Enum``) because it is the dialect-
    specific form that accepts ``create_type=False`` and simply emits the
    type name in DDL. A bare ``sa.Enum(name=..., create_type=False)`` would
    still attempt to emit ``CREATE TYPE name AS ENUM ()`` because it has no
    value literals.
    """

    return postgresql.ENUM(name=name, create_type=False)


# --------------------------------------------------------------------------- #
# Upgrade
# --------------------------------------------------------------------------- #


def upgrade() -> None:  # noqa: PLR0915 — baseline migration, long by nature
    bind = op.get_bind()

    # Ensure pgcrypto is available for gen_random_uuid().
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------ #
    # T020a — enums + users + superusers + outbox_events + system_settings
    # ------------------------------------------------------------------ #

    _create_enums(_LEGACY_ENUMS)
    _create_enums(_REDESIGN_ENUMS)
    # Phase 13 P1 (T803): create the ORM-only enums up-front so the
    # supporting tables emitted at the end of upgrade() can reference them.
    _create_enums(_PHASE13_ENUMS)

    # Phase 13 P1 (T803): pgvector for ``embeddings`` / ``search_query_embeddings``.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("two_factor_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("two_factor_secret_dek_version", sa.Integer(), nullable=True),
        sa.Column("two_factor_backup_codes_hashed", ARRAY(sa.String()), nullable=True),
        sa.Column("security_stamp", sa.String(64), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_first_party_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_timezone", sa.String(64), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("two_factor_reset_cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    op.create_table(
        "superusers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("added_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "webauthn_credentials",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "allowed_ip_cidrs",
            ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY[]::varchar[]"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_superusers_revoked_at", "superusers", ["revoked_at"])

    op.create_table(
        "superuser_approval_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("detail", JSONB(), nullable=False),
        # Round 1 review M3 (2026-04-28): ``requested_by_id`` historically
        # FK'd ``superusers.id`` and was ``nullable=False``, but project
        # owners (regular users) initiate looser-override approval tickets
        # — they are NOT superusers so the FK violated on every owner-
        # initiated request. The schema now records BOTH:
        #
        # * ``requested_by_id`` (FK → superusers.id, nullable) — set when
        #   a superuser opens the ticket directly (e.g. operator triage).
        # * ``requesting_user_id`` (FK → users.id, nullable, ON DELETE
        #   SET NULL) — set when a regular user (typically project owner /
        #   admin) opens the ticket via :func:`apply_taxon_override`.
        #
        # Exactly one of the two MUST be populated per row; a CHECK
        # constraint enforces XOR ("exactly one") so the audit trail
        # carries a single, unambiguous actor identity. Round 2 review
        # M3 (2026-04-28): tightened from "at least one" to XOR after
        # the original wording allowed both columns to be filled.
        # Existing dev DBs at HEAD=0004 are repaired by migration 0005.
        #
        # Round 3 review (2026-04-28): the ``requesting_user_id`` FK is
        # given an explicit constraint name and ``ON DELETE SET NULL`` so
        # a fresh DB built from 0001 ends up byte-for-byte identical to
        # an existing dev DB after 0005 has run. Without the ``name=`` /
        # ``ondelete=`` here the two paths produced different final FK
        # shapes for the same logical column.
        sa.Column(
            "requested_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("superusers.id"),
            nullable=True,
        ),
        sa.Column(
            "requesting_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                name="fk_superuser_approval_requests_requesting_user_id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "approvals",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "(requested_by_id IS NOT NULL) <> (requesting_user_id IS NOT NULL)",
            name="ck_superuser_approval_requests_actor_present",
        ),
    )

    # outbox_events — created early because ORM event listeners may INSERT into
    # it as soon as the app process touches any table (data-model §2 note).
    op.create_table(
        "outbox_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True, unique=True),
    )
    op.create_index(
        "ix_outbox_events_status_next_retry",
        "outbox_events",
        ["status", "next_retry_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.create_index(
        "ix_outbox_events_event_type_created",
        "outbox_events",
        ["event_type", sa.text("created_at DESC")],
    )

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "updated_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("superusers.id"),
            nullable=True,
        ),
    )

    # NFR-006: seed system_settings initial values.
    # updated_by_id is nullable here because the initial superuser is created
    # after this migration by scripts.init_superuser; we fill it at that time.
    op.execute(
        """
        INSERT INTO system_settings (key, value, updated_at, updated_by_id) VALUES
            ('trusted_default_duration_seconds', '7776000'::jsonb, now(), NULL),
            ('trusted_max_duration_seconds', '31536000'::jsonb, now(), NULL),
            ('dormant_threshold_seconds', '31622400'::jsonb, now(), NULL),
            ('api_key_rotation_warn_days', '90'::jsonb, now(), NULL),
            ('api_key_scope_violation_window_seconds', '600'::jsonb, now(), NULL),
            ('api_key_scope_violation_threshold', '10'::jsonb, now(), NULL),
            ('totp_verify_window_per_15min', '5'::jsonb, now(), NULL),
            ('totp_lockout_threshold', '10'::jsonb, now(), NULL)
        """
    )

    # ------------------------------------------------------------------ #
    # T020b — projects family + datasets / sites / recordings / detections
    # / annotations / tags
    # ------------------------------------------------------------------ #

    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("visibility", _enum("projectvisibility"), nullable=False),
        sa.Column("license", _enum("projectlicense"), nullable=False),
        sa.Column(
            "restricted_config",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("restricted_config_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "status",
            _enum("projectstatus"),
            nullable=False,
            server_default=sa.text("'active'::projectstatus"),
        ),
        sa.Column("dormant_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_min_votes", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("review_consensus_threshold", sa.Float(), nullable=False, server_default=sa.text("0.667")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        # CHECK: restricted_config well-formed when visibility = 'restricted' (FR-001..005)
        sa.CheckConstraint(
            """
            restricted_config IS NOT NULL
            AND jsonb_typeof(restricted_config) = 'object'
            AND (
                visibility <> 'restricted' OR (
                    restricted_config ? 'allow_media_playback'
                    AND restricted_config ? 'allow_detection_view'
                    AND restricted_config ? 'mask_species_in_detection'
                    AND restricted_config ? 'allow_download'
                    AND restricted_config ? 'allow_export'
                    AND restricted_config ? 'allow_voting_and_comments'
                    AND restricted_config ? 'public_location_precision_h3_res'
                    AND restricted_config ? 'allow_precise_location_to_viewer'
                )
            )
            """,
            name="ck_projects_restricted_config_shape",
        ),
    )
    op.create_index("ix_projects_visibility", "projects", ["visibility"])
    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_index(
        "ix_projects_status_dormant_since",
        "projects",
        ["status", sa.text("dormant_since DESC")],
    )

    op.create_table(
        "project_license_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_license", _enum("projectlicense"), nullable=True),
        sa.Column("new_license", _enum("projectlicense"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "changed_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_project_license_history_project_changed_at",
        "project_license_history",
        ["project_id", sa.text("changed_at DESC")],
    )

    op.create_table(
        "project_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("role", _enum("projectmemberrole"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invited_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "role = 'viewer'::projectmemberrole OR expires_at IS NULL",
            name="ck_project_members_viewer_expires",
        ),
    )
    op.create_index(
        "ux_project_members_active",
        "project_members",
        ["project_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index("ix_project_members_project_role", "project_members", ["project_id", "role"])
    op.create_index(
        "ix_project_members_user_project",
        "project_members",
        ["user_id", "project_id"],
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.create_table(
        "project_invitations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", _enum("invitationkind"), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("role", _enum("projectmemberrole"), nullable=True),
        sa.Column("granted_permissions", JSONB(), nullable=True),
        sa.Column("trusted_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            _enum("invitationstatus"),
            nullable=False,
            server_default=sa.text("'pending'::invitationstatus"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        # FR-048 improved CHECK: kind × field consistency
        sa.CheckConstraint(
            """
            kind IS NOT NULL AND status IS NOT NULL AND (
                (kind = 'member'
                 AND role IS NOT NULL
                 AND granted_permissions IS NULL
                 AND trusted_duration_seconds IS NULL)
                OR
                (kind = 'trusted'
                 AND role IS NULL
                 AND jsonb_typeof(granted_permissions) = 'array'
                 AND trusted_duration_seconds IS NOT NULL
                 AND trusted_duration_seconds BETWEEN 1 AND 31536000)
            )
            """,
            name="ck_project_invitations_kind_fields",
        ),
        # Status × timestamps consistency (security H-1)
        sa.CheckConstraint(
            """
            (status = 'accepted'
                AND accepted_at IS NOT NULL AND declined_at IS NULL AND revoked_at IS NULL)
            OR (status = 'declined'
                AND declined_at IS NOT NULL AND accepted_at IS NULL AND revoked_at IS NULL)
            OR (status = 'revoked'
                AND revoked_at IS NOT NULL)
            OR (status = 'pending'
                AND accepted_at IS NULL AND declined_at IS NULL AND revoked_at IS NULL)
            OR (status = 'expired'
                AND accepted_at IS NULL AND declined_at IS NULL)
            """,
            name="ck_project_invitations_status_timestamps",
        ),
    )
    op.create_index(
        "ux_project_invitations_pending",
        "project_invitations",
        ["project_id", "email_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_project_invitations_status_expires",
        "project_invitations",
        ["status", "expires_at"],
    )

    op.create_table(
        "project_trusted_users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "invitation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("project_invitations.id"),
            nullable=False,
        ),
        sa.Column("granted_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            _enum("trusteduserstatus"),
            nullable=False,
            server_default=sa.text("'active'::trusteduserstatus"),
        ),
        sa.Column("granted_permissions", JSONB(), nullable=False),
        sa.Column("email_at_invitation", sa.String(255), nullable=True),
        sa.Column("email_at_invitation_hash", sa.String(64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "jsonb_typeof(granted_permissions) = 'array' AND jsonb_array_length(granted_permissions) > 0",
            name="ck_trusted_users_permissions_non_empty_array",
        ),
        sa.CheckConstraint(
            "expires_at > granted_at AND expires_at <= granted_at + INTERVAL '1 year'",
            name="ck_trusted_users_duration_within_one_year",
        ),
    )
    op.create_index(
        "ix_project_trusted_users_project_user_status",
        "project_trusted_users",
        ["project_id", "user_id", "status"],
    )
    op.create_index(
        "ix_project_trusted_users_status_expires",
        "project_trusted_users",
        ["status", "expires_at"],
    )
    # FR-041 / FR-044 — at most one ACTIVE overlay per (project, user) pair.
    # Without this partial unique, parallel accept_invitation calls can race
    # past the application-level pre-check and create two ACTIVE rows that
    # the permission engine would union, escalating capability beyond the
    # issuing Owner's intent.
    op.create_index(
        "ux_project_trusted_users_active",
        "project_trusted_users",
        ["project_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "project_taxon_sensitivity_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("taxon_id", sa.String(64), nullable=False),
        sa.Column("sensitivity_h3_res", sa.Integer(), nullable=False),
        sa.Column("direction", _enum("taxonoverridedirection"), nullable=False),
        sa.Column(
            "approval_status",
            _enum("taxonoverrideapprovalstatus"),
            nullable=False,
            server_default=sa.text("'applied'::taxonoverrideapprovalstatus"),
        ),
        sa.Column(
            "requested_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "approved_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("superusers.id"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        # FR-027: discrete h3 resolutions
        sa.CheckConstraint(
            "sensitivity_h3_res IN (2, 5, 7, 9, 15)",
            name="ck_taxon_overrides_h3_discrete",
        ),
        sa.CheckConstraint(
            """
            (direction = 'stricter' AND approval_status = 'applied')
            OR (direction = 'looser'
                AND approval_status IN ('pending_superuser_approval', 'applied', 'rejected'))
            """,
            name="ck_taxon_overrides_direction_vs_approval",
        ),
    )
    op.create_index(
        "ux_taxon_overrides_applied_unique",
        "project_taxon_sensitivity_overrides",
        ["project_id", "taxon_id"],
        unique=True,
        postgresql_where=sa.text("approval_status = 'applied'"),
    )
    op.create_index(
        "ix_taxon_overrides_taxon_approval",
        "project_taxon_sensitivity_overrides",
        ["taxon_id", "approval_status"],
    )

    # sites — raw lat/lng intentionally absent (FR-031)
    op.create_table(
        "sites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("h3_index_member", sa.String(32), nullable=False),
        sa.Column(
            "h3_index_member_resolution",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("15"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        # NFR-003: only precise resolutions allowed for member-side storage
        sa.CheckConstraint(
            "h3_index_member_resolution IN (9, 15)",
            name="ck_sites_h3_member_resolution",
        ),
        sa.UniqueConstraint("project_id", "name", name="ux_sites_project_name"),
        sa.UniqueConstraint("project_id", "h3_index_member", name="ux_sites_project_h3"),
    )
    op.create_index("ix_sites_h3_index_member", "sites", ["h3_index_member"])

    # datasets (supporting table, placeholder columns — Phase 3+ extends)
    op.create_table(
        "datasets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _enum("datasetstatus"),
            nullable=False,
            server_default=sa.text("'pending'::datasetstatus"),
        ),
        sa.Column(
            "visibility",
            _enum("datasetvisibility"),
            nullable=False,
            server_default=sa.text("'private'::datasetvisibility"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_datasets_project_id", "datasets", ["project_id"])

    op.create_table(
        "recordings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "site_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sites.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        # Optional per-recording h3 override (nullable — falls back to site.h3_index_member)
        sa.Column("h3_index_member", sa.String(32), nullable=True),
        sa.Column("h3_index_member_resolution", sa.Integer(), nullable=True),
        sa.Column("gps_stripped", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_recordings_project_id", "recordings", ["project_id"])
    op.create_index("ix_recordings_dataset_id", "recordings", ["dataset_id"])
    op.create_index("ix_recordings_site_id", "recordings", ["site_id"])

    # detections + annotations + tags (supporting tables, minimal FK-bearing schema)
    op.create_table(
        "detections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "recording_id",
            UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("taxon_id", sa.String(64), nullable=True),
        sa.Column("source", _enum("detectionsource"), nullable=False),
        sa.Column(
            "status",
            _enum("detectionstatus"),
            nullable=False,
            server_default=sa.text("'unreviewed'::detectionstatus"),
        ),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_detections_recording", "detections", ["recording_id"])
    op.create_index("ix_detections_project_taxon", "detections", ["project_id", "taxon_id"])

    op.create_table(
        "annotations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "detection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("detections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source", _enum("annotationsource"), nullable=False),
        sa.Column("taxon_id", sa.String(64), nullable=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_annotations_detection", "annotations", ["detection_id"])

    op.create_table(
        "tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", _enum("tagcategory"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("taxon_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "category", "name", name="ux_tags_project_category_name"),
    )
    op.create_index("ix_tags_project_id", "tags", ["project_id"])

    # ------------------------------------------------------------------ #
    # T020c — annotation_votes + annotation_comments + taxon_sensitivities
    # + iucn_sync_attempts + api_keys + audit logs + dek_rewrap_failures
    # + wipe_guard
    # ------------------------------------------------------------------ #

    op.create_table(
        "annotation_votes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "annotation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("annotations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("voter_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vote", sa.SmallInteger(), nullable=False),
        sa.Column("source", _enum("annotationvotesource"), nullable=False),
        sa.Column("project_role_at_vote", _enum("projectmemberrole"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        # FR-037: member votes must capture role at vote time; non-member must not
        sa.CheckConstraint(
            """
            (source = 'member' AND project_role_at_vote IS NOT NULL)
            OR (source IN ('guest_authenticated', 'trusted_user')
                AND project_role_at_vote IS NULL)
            """,
            name="ck_annotation_votes_source_role_consistency",
        ),
    )
    op.create_index(
        "ix_annotation_votes_annotation", "annotation_votes", ["annotation_id"]
    )
    op.create_index(
        "ix_annotation_votes_project_source",
        "annotation_votes",
        ["project_id", "source"],
    )

    op.create_table(
        "annotation_comments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "annotation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("annotations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("commenter_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", _enum("annotationvotesource"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_annotation_comments_annotation",
        "annotation_comments",
        ["annotation_id"],
    )

    op.create_table(
        "taxon_sensitivities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("taxon_id", sa.String(64), nullable=False),
        sa.Column("source", _enum("taxonsensitivitysource"), nullable=False),
        sa.Column("category", sa.String(10), nullable=True),
        sa.Column("sensitivity_h3_res", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "sensitivity_h3_res IN (2, 5, 7, 9, 15)",
            name="ck_taxon_sensitivities_h3_discrete",
        ),
        sa.UniqueConstraint("taxon_id", "source", name="ux_taxon_sensitivities_taxon_source"),
    )
    op.create_index("ix_taxon_sensitivities_taxon", "taxon_sensitivities", ["taxon_id"])
    op.create_index(
        "ix_taxon_sensitivities_source_updated",
        "taxon_sensitivities",
        ["source", sa.text("updated_at DESC")],
    )

    op.create_table(
        "iucn_sync_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("synced_count", sa.Integer(), nullable=True),
        sa.Column("loosened_species_count", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_iucn_sync_attempts_status_started",
        "iucn_sync_attempts",
        ["status", sa.text("started_at DESC")],
    )

    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False, unique=True),
        sa.Column("hashed_secret", sa.String(64), nullable=False),
        sa.Column("granted_permissions", JSONB(), nullable=False),
        sa.Column(
            "project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=True
        ),
        sa.Column("allowed_ip_cidrs", ARRAY(sa.String()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(100), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scope_violation_count_10min",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "ip_violation_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + INTERVAL '2 years'",
            name="ck_api_keys_expires_at_window",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(granted_permissions) = 'array'",
            name="ck_api_keys_granted_permissions_array",
        ),
    )
    op.create_index(
        "ix_api_keys_user_revoked", "api_keys", ["user_id", "revoked_at"]
    )
    op.create_index(
        "ix_api_keys_project_revoked", "api_keys", ["project_id", "revoked_at"]
    )
    op.create_index(
        "ix_api_keys_expires_at_active",
        "api_keys",
        ["expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # project_audit_log (FR-088, FR-090..096)
    op.create_table(
        "project_audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actor_user_id_hash", sa.String(64), nullable=False),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("user_agent_hash", sa.String(64), nullable=False),
        sa.Column("before", JSONB(), nullable=True),
        sa.Column("after", JSONB(), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("row_hash", sa.String(64), nullable=False),
        # genesis row is the only one allowed to have project_id IS NULL
        sa.CheckConstraint(
            "action = 'genesis' OR project_id IS NOT NULL",
            name="ck_project_audit_log_project_id_required",
        ),
    )
    op.create_index(
        "ix_project_audit_log_project_created",
        "project_audit_log",
        ["project_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_project_audit_log_action_created",
        "project_audit_log",
        ["action", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_project_audit_log_actor_created",
        "project_audit_log",
        ["actor_user_id_hash", sa.text("created_at DESC")],
    )

    op.create_table(
        "platform_audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("actor_user_id_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("user_agent_hash", sa.String(64), nullable=False),
        sa.Column("before", JSONB(), nullable=True),
        sa.Column("after", JSONB(), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("row_hash", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_platform_audit_log_action_created",
        "platform_audit_log",
        ["action", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_platform_audit_log_actor_created",
        "platform_audit_log",
        ["actor_user_id_hash", sa.text("created_at DESC")],
    )

    op.create_table(
        "dek_rewrap_failures",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("table_name", sa.String(100), nullable=False),
        sa.Column("row_id", UUID(as_uuid=True), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # wipe_guard — singleton. Baseline inserts no row; wipe_database.py inserts on re-run.
    op.create_table(
        "wipe_guard",
        sa.Column("id", sa.Integer(), primary_key=True, server_default=sa.text("1")),
        sa.Column("wiped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wiped_by_superuser_ids", ARRAY(sa.String()), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_wipe_guard_singleton"),
    )

    # ------------------------------------------------------------------ #
    # T020e — Triggers
    # ------------------------------------------------------------------ #

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_last_superuser_deletion()
        RETURNS trigger AS $$
        BEGIN
            IF current_user = 'echoroo_app' THEN
                IF (SELECT COUNT(*) FROM superusers WHERE revoked_at IS NULL) <= 1 THEN
                    IF current_setting('app.superuser_deletion_override', true)
                       IS DISTINCT FROM 'true' THEN
                        RAISE EXCEPTION
                          'Cannot delete last superuser without creator_founder override';
                    END IF;
                END IF;
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER superuser_last_protection
        BEFORE DELETE ON superusers
        FOR EACH ROW
        EXECUTE FUNCTION prevent_last_superuser_deletion();
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION forbid_audit_log_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER project_audit_log_immutable
        BEFORE UPDATE OR DELETE ON project_audit_log
        FOR EACH ROW
        EXECUTE FUNCTION forbid_audit_log_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER platform_audit_log_immutable
        BEFORE UPDATE OR DELETE ON platform_audit_log
        FOR EACH ROW
        EXECUTE FUNCTION forbid_audit_log_mutation();
        """
    )

    # ------------------------------------------------------------------ #
    # T020f — ACL: REVOKE UPDATE/DELETE from echoroo_app on append-only tables
    # Only emitted when the role exists, so CI / testcontainers runs don't fail.
    # ------------------------------------------------------------------ #

    role_exists = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_roles WHERE rolname = 'echoroo_app'"
        )
    ).scalar()
    if role_exists:
        op.execute(
            """
            REVOKE UPDATE, DELETE ON project_audit_log FROM echoroo_app;
            REVOKE UPDATE, DELETE ON platform_audit_log FROM echoroo_app;
            REVOKE UPDATE, DELETE ON project_license_history FROM echoroo_app;
            GRANT INSERT ON project_audit_log TO echoroo_app;
            GRANT INSERT ON platform_audit_log TO echoroo_app;
            GRANT INSERT ON project_license_history TO echoroo_app;
            """
        )

    # ------------------------------------------------------------------ #
    # T020g — Genesis rows (prev_hash = '0'*64, row_hash placeholder = '0'*64)
    # ------------------------------------------------------------------ #

    op.execute(
        """
        INSERT INTO project_audit_log (
            id, created_at, actor_user_id_hash, project_id, action, detail,
            request_id, ip_hash, user_agent_hash, before, after, prev_hash, row_hash
        )
        VALUES (
            gen_random_uuid(), now(), repeat('0', 64), NULL, 'genesis',
            '{}'::jsonb, 'genesis', repeat('0', 64), repeat('0', 64), NULL, NULL,
            repeat('0', 64), repeat('0', 64)
        );
        """
    )
    op.execute(
        """
        INSERT INTO platform_audit_log (
            id, created_at, actor_user_id_hash, action, detail,
            request_id, ip_hash, user_agent_hash, before, after, prev_hash, row_hash
        )
        VALUES (
            gen_random_uuid(), now(), repeat('0', 64), 'genesis',
            '{}'::jsonb, 'genesis', repeat('0', 64), repeat('0', 64), NULL, NULL,
            repeat('0', 64), repeat('0', 64)
        );
        """
    )

    # ------------------------------------------------------------------ #
    # T020h (Phase 13 P1 / T803) — emit the 32 ORM-only supporting tables
    # so a fresh DB built from 0001 alone reaches the final Phase 13 shape.
    # The same DDL block is re-emitted by 0006_schema_reconcile_static
    # under ``IF NOT EXISTS`` for long-lived dev DBs that arrive via the
    # delta path; both paths therefore converge on byte-for-byte identical
    # final schemas. See ``echoroo._alembic_phase13_supporting_ddl``.
    # ------------------------------------------------------------------ #
    apply_phase13_supporting_tables()


# --------------------------------------------------------------------------- #
# Downgrade — full teardown (baseline is not meant to be partially reverted)
# --------------------------------------------------------------------------- #


def downgrade() -> None:  # noqa: PLR0915
    bind = op.get_bind()

    # Drop triggers first (they reference functions + tables)
    op.execute("DROP TRIGGER IF EXISTS platform_audit_log_immutable ON platform_audit_log")
    op.execute("DROP TRIGGER IF EXISTS project_audit_log_immutable ON project_audit_log")
    op.execute("DROP TRIGGER IF EXISTS superuser_last_protection ON superusers")
    op.execute("DROP FUNCTION IF EXISTS forbid_audit_log_mutation()")
    op.execute("DROP FUNCTION IF EXISTS prevent_last_superuser_deletion()")

    # Phase 13 P1 (T803): drop the supporting tables first since they FK
    # back into projects / users / datasets / etc. ``detections`` is
    # intentionally NOT in this list (its rows predate Phase 13 and are
    # treated as part of the legacy core; it is dropped below).
    for tname in SUPPORTING_TABLES_REVERSE_DROP_ORDER:
        op.execute(f'DROP TABLE IF EXISTS "{tname}" CASCADE')

    # Drop tables in reverse FK dependency order.
    for table in (
        "wipe_guard",
        "dek_rewrap_failures",
        "platform_audit_log",
        "project_audit_log",
        "api_keys",
        "iucn_sync_attempts",
        "taxon_sensitivities",
        "annotation_comments",
        "annotation_votes",
        "tags",
        "annotations",
        "detections",
        "recordings",
        "datasets",
        "sites",
        "project_taxon_sensitivity_overrides",
        "project_trusted_users",
        "project_invitations",
        "project_members",
        "project_license_history",
        "projects",
        "system_settings",
        "outbox_events",
        "superuser_approval_requests",
        "superusers",
        "users",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    _drop_enums(_PHASE13_ENUMS)
    _drop_enums(_REDESIGN_ENUMS)
    _drop_enums(_LEGACY_ENUMS)

    # pgcrypto extension intentionally left installed (cluster-level resource)
    _ = bind  # silence vulture / keep reference for future use
