"""Project-centric metadata refactor.

Revision ID: 2b1b1fe60c9a
Revises: f9c076e9d88f
Create Date: 2025-01-16 00:00:00.000000
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b1b1fe60c9a"
down_revision: Union[str, None] = "f9c076e9d88f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _utcnow() -> sa.sql.functions.Function[sa.types.DateTime]:
    return sa.func.now().op("AT TIME ZONE")("UTC")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ------------------------------------------------------------------ enums
    # For SQLite compatibility, use native_enum=False to use VARCHAR with CHECK constraint
    project_member_role_enum = sa.Enum(
        "manager",
        "member",
        name="project_member_role",
        native_enum=False,
    )
    project_member_role_enum.create(bind, checkfirst=True)

    datetime_pattern_type_enum = sa.Enum(
        "strptime",
        "regex",
        name="datetime_pattern_type",
    )
    datetime_pattern_type_enum.create(bind, checkfirst=True)

    datetime_parse_status_enum = sa.Enum(
        "pending",
        "success",
        "failed",
        name="recording_datetime_parse_status",
    )
    datetime_parse_status_enum.create(bind, checkfirst=True)

    # ------------------------------------------------------------- project member
    if "project_member" not in inspector.get_table_names():
        op.create_table(
            "project_member",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "project_id",
                sa.String(length=255),
                sa.ForeignKey("project.project_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "role",
                project_member_role_enum,
                nullable=False,
                server_default="member",
            ),
            sa.Column(
                "created_on",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        )

    # ------------------------------------------------------------------- projects
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("fk_project_owner_group_id_group"),
            type_="foreignkey",
        )
        batch_op.drop_column("owner_group_id")

    # ----------------------------------------------------------------------- site
    op.add_column(
        "site",
        sa.Column("project_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "site",
        sa.Column("h3_index", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_site_h3_index", "site", ["h3_index"], unique=False)
    op.create_foreign_key(
        op.f("fk_site_project_id_project"),
        "site",
        "project",
        ["project_id"],
        ["project_id"],
        ondelete="RESTRICT",
    )

    # --------------------------------------------------------------------- dataset
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table("dataset", schema=None) as batch_op:
        batch_op.drop_constraint(
            "chk_dataset_restricted_has_group",
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("fk_dataset_owner_group_id_group"),
            type_="foreignkey",
        )
        batch_op.drop_column("owner_group_id")

    op.execute(
        sa.text(
            "UPDATE dataset SET visibility = 'restricted' "
            "WHERE visibility = 'private'"
        )
    )

    fallback_project_id = "legacy-default-project"
    fallback_name = "Legacy Project"
    op.execute(
        sa.text(
            """
            INSERT INTO project (project_id, project_name, created_on, is_active)
            VALUES (:pid, :pname, CURRENT_TIMESTAMP, TRUE)
            ON CONFLICT (project_id) DO NOTHING
            """
        ).bindparams(pid=fallback_project_id, pname=fallback_name)
    )

    op.execute(
        sa.text(
            """
            UPDATE dataset
            SET project_id = :pid
            WHERE project_id IS NULL
            """
        ).bindparams(pid=fallback_project_id)
    )

    with op.batch_alter_table("dataset", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("fk_dataset_project_id_project"),
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            op.f("fk_dataset_project_id_project"),
            "project",
            ["project_id"],
            ["project_id"],
            ondelete="RESTRICT",
        )
        batch_op.alter_column(
            "project_id",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch_op.alter_column(
            "visibility",
            existing_type=sa.Enum(
                "private",
                "restricted",
                "public",
                name="visibility_level",
            ),
            server_default="restricted",
        )

    # ---------------------------------------------------------------- recording
    op.add_column(
        "recording",
        sa.Column(
            "datetime",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "recording",
        sa.Column("h3_index", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "recording",
        sa.Column(
            "datetime_parse_status",
            datetime_parse_status_enum,
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "recording",
        sa.Column("datetime_parse_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_recording_h3_index", "recording", ["h3_index"])

    # ---------------------------------------------------------------- datetime pattern
    op.create_table(
        "datetime_pattern",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Integer(),
            sa.ForeignKey("dataset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "pattern_type",
            datetime_pattern_type_enum,
            nullable=False,
            server_default="strptime",
        ),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.Column("sample_filename", sa.String(length=255), nullable=True),
        sa.Column(
            "sample_result",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_on",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "dataset_id",
            name="uq_datetime_pattern_dataset_id",
        ),
    )

    # ------------------------------------------------------------- annotation project
    with op.batch_alter_table("annotation_project", schema=None) as batch_op:
        batch_op.drop_constraint(
            "chk_annotation_project_restricted_has_group",
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("fk_annotation_project_owner_group_id_group"),
            type_="foreignkey",
        )
        batch_op.drop_column("owner_group_id")

    op.execute(
        sa.text(
            "UPDATE annotation_project SET visibility = 'restricted' "
            "WHERE visibility = 'private'"
        )
    )

    op.add_column(
        "annotation_project",
        sa.Column("dataset_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "annotation_project",
        sa.Column("project_id", sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_annotation_project_dataset_id_dataset"),
        "annotation_project",
        "dataset",
        ["dataset_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_annotation_project_project_id_project"),
        "annotation_project",
        "project",
        ["project_id"],
        ["project_id"],
        ondelete="RESTRICT",
    )

    op.execute(
        sa.text(
            """
            WITH ap_dataset AS (
                SELECT
                    ap.id AS annotation_project_id,
                    MIN(dr.dataset_id) AS dataset_id
                FROM annotation_project ap
                JOIN annotation_task at
                    ON at.annotation_project_id = ap.id
                JOIN clip c
                    ON c.id = at.clip_id
                JOIN recording r
                    ON r.id = c.recording_id
                JOIN dataset_recording dr
                    ON dr.recording_id = r.id
                GROUP BY ap.id
            )
            UPDATE annotation_project ap
            SET dataset_id = ap_dataset.dataset_id
            FROM ap_dataset
            WHERE ap.id = ap_dataset.annotation_project_id
            """
        )
    )

    # Fallback dataset for annotation projects without tasks
    ap_rows = bind.execute(
        sa.text(
            """
            SELECT id, COALESCE(name, 'annotation_project_' || id::text) AS name
            FROM annotation_project
            WHERE dataset_id IS NULL
            """
        )
    ).fetchall()

    fallback_user = bind.execute(
        sa.text(
            "SELECT id FROM \"user\" ORDER BY created_on ASC LIMIT 1"
        )
    ).scalar()

    if fallback_user is None:
        raise RuntimeError(
            "At least one user is required to seed fallback datasets."
        )

    for ap_id, ap_name in ap_rows:
        dataset_uuid = uuid.uuid4()
        dataset_name = f"legacy_dataset_ap_{ap_id}"
        audio_dir = f"legacy/{ap_id}"
        result = bind.execute(
            sa.text(
                """
                INSERT INTO dataset (
                    uuid,
                    name,
                    description,
                    audio_dir,
                    created_by_id,
                    created_on,
                    visibility,
                    project_id
                ) VALUES (
                    :uuid,
                    :name,
                    :description,
                    :audio_dir,
                    :created_by_id,
                    CURRENT_TIMESTAMP,
                    'restricted',
                    :project_id
                )
                RETURNING id
                """
            ).bindparams(
                uuid=str(dataset_uuid),
                name=dataset_name,
                description=f"Auto-generated dataset for annotation project {ap_name}",
                audio_dir=audio_dir,
                created_by_id=fallback_user,
                project_id=fallback_project_id,
            )
        )
        dataset_id = result.scalar_one()
        bind.execute(
            sa.text(
                """
                UPDATE annotation_project
                SET dataset_id = :dataset_id
                WHERE id = :ap_id
                """
            ).bindparams(dataset_id=dataset_id, ap_id=ap_id)
        )

    op.execute(
        sa.text(
            """
            UPDATE annotation_project ap
            SET project_id = d.project_id
            FROM dataset d
            WHERE ap.dataset_id = d.id
            """
        )
    )

    op.alter_column(
        "annotation_project",
        "dataset_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "annotation_project",
        "project_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.alter_column(
        "annotation_project",
        "visibility",
        existing_type=sa.Enum(
            "private",
            "restricted",
            "public",
            name="visibility_level",
        ),
        server_default="restricted",
    )

    # ------------------------------------------------------------ visibility enum
    visibility_level_new = sa.Enum(
        "restricted",
        "public",
        name="visibility_level_new",
    )
    visibility_level_new.create(bind, checkfirst=True)

    for table in ("dataset", "annotation_project"):
        op.execute(
            sa.text(
                f"""
                ALTER TABLE {table}
                ALTER COLUMN visibility TYPE visibility_level_new
                USING visibility::text::visibility_level_new
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                ALTER TABLE {table}
                ALTER COLUMN visibility SET DEFAULT 'restricted'
                """
            )
        )

    op.execute(sa.text("DROP TYPE visibility_level"))
    op.execute(
        sa.text("ALTER TYPE visibility_level_new RENAME TO visibility_level")
    )

    # ---------------------------------------------------------------- site cleanup
    op.execute(
        sa.text(
            """
            UPDATE site s
            SET project_id = d.project_id
            FROM dataset d
            WHERE d.primary_site_id = s.site_id
              AND s.project_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE site
            SET project_id = :pid
            WHERE project_id IS NULL
            """
        ).bindparams(pid=fallback_project_id)
    )
    op.execute(
        sa.text(
            """
            UPDATE site
            SET h3_index = COALESCE(h3_index, '8fffffffffffffff')
            """
        )
    )
    op.alter_column(
        "site",
        "project_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.alter_column(
        "site",
        "h3_index",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.drop_column("site", "lon")
    op.drop_column("site", "lat")

    # ----------------------------------------------------------- project members seed
    op.execute(
        sa.text(
            """
            INSERT INTO project_member (project_id, user_id, role, created_on)
            SELECT DISTINCT project_id, created_by_id, 'manager', CURRENT_TIMESTAMP
            FROM dataset
            WHERE created_by_id IS NOT NULL
            ON CONFLICT (project_id, user_id) DO NOTHING
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO project_member (project_id, user_id, role, created_on)
            SELECT DISTINCT project_id, created_by_id, 'manager', CURRENT_TIMESTAMP
            FROM annotation_project
            WHERE created_by_id IS NOT NULL
            ON CONFLICT (project_id, user_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    # ---------------------------------------------------------------- project members
    op.drop_table("project_member")
    project_member_role_enum = sa.Enum(
        "manager",
        "member",
        name="project_member_role",
        native_enum=False,
    )
    project_member_role_enum.drop(bind, checkfirst=True)

    # ------------------------------------------------------------- site restoration
    op.add_column(
        "site",
        sa.Column("lat", sa.FLOAT(), nullable=True),
    )
    op.add_column(
        "site",
        sa.Column("lon", sa.FLOAT(), nullable=True),
    )
    op.drop_constraint(
        op.f("fk_site_project_id_project"),
        "site",
        type_="foreignkey",
    )
    op.drop_index("ix_site_h3_index", table_name="site")
    op.drop_column("site", "h3_index")
    op.drop_column("site", "project_id")

    # --------------------------------------------------------------- annotation project
    op.drop_constraint(
        op.f("fk_annotation_project_project_id_project"),
        "annotation_project",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_annotation_project_dataset_id_dataset"),
        "annotation_project",
        type_="foreignkey",
    )
    op.drop_column("annotation_project", "project_id")
    op.drop_column("annotation_project", "dataset_id")
    op.add_column(
        "annotation_project",
        sa.Column("owner_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_annotation_project_owner_group_id_group"),
        "annotation_project",
        "group",
        ["owner_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "chk_annotation_project_restricted_has_group",
        "annotation_project",
        "visibility != 'restricted' OR owner_group_id IS NOT NULL",
    )

    # ------------------------------------------------------------------- datetime pattern
    op.drop_table("datetime_pattern")
    datetime_pattern_type_enum = sa.Enum(
        "strptime",
        "regex",
        name="datetime_pattern_type",
    )
    datetime_pattern_type_enum.drop(bind, checkfirst=True)

    # --------------------------------------------------------------------- recording
    op.drop_index("ix_recording_h3_index", table_name="recording")
    op.drop_column("recording", "datetime_parse_error")
    op.drop_column("recording", "datetime_parse_status")
    op.drop_column("recording", "h3_index")
    op.drop_column("recording", "datetime")
    datetime_parse_status_enum = sa.Enum(
        "pending",
        "success",
        "failed",
        name="recording_datetime_parse_status",
    )
    datetime_parse_status_enum.drop(bind, checkfirst=True)

    # ---------------------------------------------------------------------- dataset
    op.alter_column(
        "dataset",
        "project_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.drop_constraint(
        op.f("fk_dataset_project_id_project"),
        "dataset",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_dataset_project_id_project"),
        "dataset",
        "project",
        ["project_id"],
        ["project_id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "dataset",
        sa.Column("owner_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_dataset_owner_group_id_group"),
        "dataset",
        "group",
        ["owner_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "chk_dataset_restricted_has_group",
        "dataset",
        "visibility != 'restricted' OR owner_group_id IS NOT NULL",
    )

    op.execute(
        sa.text(
            "UPDATE dataset SET visibility = 'private' "
            "WHERE visibility = 'restricted'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE annotation_project SET visibility = 'private' "
            "WHERE visibility = 'restricted'"
        )
    )

    # -------------------------------------------------------------------- projects
    op.add_column(
        "project",
        sa.Column("owner_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_project_owner_group_id_group"),
        "project",
        "group",
        ["owner_group_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --------------------------------------------------------------- visibility enum
    visibility_level_old = sa.Enum(
        "private",
        "restricted",
        "public",
        name="visibility_level_old",
    )
    visibility_level_old.create(bind, checkfirst=True)

    for table in ("dataset", "annotation_project"):
        op.execute(
            sa.text(
                f"""
                ALTER TABLE {table}
                ALTER COLUMN visibility TYPE visibility_level_old
                USING visibility::text::visibility_level_old
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                ALTER TABLE {table}
                ALTER COLUMN visibility SET DEFAULT 'private'
                """
            )
        )

    op.execute(sa.text("DROP TYPE visibility_level"))
    op.execute(
        sa.text("ALTER TYPE visibility_level_old RENAME TO visibility_level")
    )
