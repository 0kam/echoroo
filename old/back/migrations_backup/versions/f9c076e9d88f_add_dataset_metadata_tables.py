"""Add metadata lookup tables and extend dataset."""

from typing import Sequence, Union

import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import column, table

# revision identifiers, used by Alembic.
revision: str = "f9c076e9d88f"
down_revision: Union[str, None] = "d51f1cf7a1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    recorder_created_on = sa.DateTime().with_variant(
        sa.TIMESTAMP(timezone=True),
        "postgresql",
    )
    op.create_table(
        "recorder",
        sa.Column("recorder_id", sa.String(length=255), nullable=False),
        sa.Column("manufacturer", sa.String(length=255), nullable=True),
        sa.Column("recorder_name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=True),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("recorder_id", name=op.f("pk_recorder")),
    )

    recorder_table = table(
        "recorder",
        column("recorder_id", sa.String(length=255)),
        column("manufacturer", sa.String(length=255)),
        column("recorder_name", sa.String(length=255)),
        column("version", sa.String(length=255)),
        column("created_on", recorder_created_on),
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    op.bulk_insert(
        recorder_table,
        [
            {
                "recorder_id": "am120",
                "manufacturer": "Open Acoustic Devices",
                "recorder_name": "AudioMoth",
                "version": "1.2.0",
                "created_on": now,
            },
            {
                "recorder_id": "smmicro2",
                "manufacturer": "Wildlife Acoustics",
                "recorder_name": "Song Meter Micro2",
                "version": None,
                "created_on": now,
            },
            {
                "recorder_id": "smmini2li",
                "manufacturer": "Wildlife Acoustics",
                "recorder_name": "Song Meter Mini2 Li-ion",
                "version": None,
                "created_on": now,
            },
            {
                "recorder_id": "smmini2aa",
                "manufacturer": "Wildlife Acoustics",
                "recorder_name": "Song Meter Mini2 AA",
                "version": None,
                "created_on": now,
            },
            {
                "recorder_id": "sm4",
                "manufacturer": "Wildlife Acoustics",
                "recorder_name": "Song Meter SM4",
                "version": None,
                "created_on": now,
            },
        ],
    )

    op.create_table(
        "license",
        sa.Column("license_id", sa.String(length=255), nullable=False),
        sa.Column("license_name", sa.String(length=255), nullable=False),
        sa.Column("license_link", sa.String(length=255), nullable=False),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("license_id", name=op.f("pk_license")),
    )

    license_table = table(
        "license",
        column("license_id", sa.String(length=255)),
        column("license_name", sa.String(length=255)),
        column("license_link", sa.String(length=255)),
        column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
        ),
    )

    op.bulk_insert(
        license_table,
        [
            {
                "license_id": "CCBY4",
                "license_name": "Creative Commons Attribution 4.0 International",
                "license_link": "https://creativecommons.org/licenses/by/4.0/",
                "created_on": now,
            },
            {
                "license_id": "CCBYNC4",
                "license_name": "Creative Commons Attribution-NonCommercial 4.0 International",
                "license_link": "https://creativecommons.org/licenses/by-nc/4.0/",
                "created_on": now,
            },
            {
                "license_id": "CC0",
                "license_name": "Creative Commons Zero 1.0 Universal",
                "license_link": "https://creativecommons.org/publicdomain/zero/1.0/",
                "created_on": now,
            },
        ],
    )

    op.create_table(
        "project",
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_taxa", sa.String(length=255), nullable=True),
        sa.Column("admin_name", sa.String(length=255), nullable=True),
        sa.Column("admin_email", sa.String(length=255), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("owner_group_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_group_id"],
            ["group.id"],
            name=op.f("fk_project_owner_group_id_group"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_project")),
    )

    op.create_table(
        "site",
        sa.Column("site_id", sa.String(length=255), nullable=False),
        sa.Column("site_name", sa.String(length=255), nullable=False),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("site_id", name=op.f("pk_site")),
    )

    op.create_table(
        "site_image",
        sa.Column("site_image_id", sa.String(length=255), nullable=False),
        sa.Column("site_id", sa.String(length=255), nullable=False),
        sa.Column("site_image_path", sa.String(length=512), nullable=False),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["site.site_id"],
            name=op.f("fk_site_image_site_id_site"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("site_image_id", name=op.f("pk_site_image")),
    )

    with op.batch_alter_table("dataset", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("project_id", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("primary_site_id", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "primary_recorder_id",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("license_id", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(sa.Column("doi", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("note", sa.Text(), nullable=True))

        batch_op.create_foreign_key(
            op.f("fk_dataset_project_id_project"),
            "project",
            ["project_id"],
            ["project_id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("fk_dataset_primary_site_id_site"),
            "site",
            ["primary_site_id"],
            ["site_id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("fk_dataset_primary_recorder_id_recorder"),
            "recorder",
            ["primary_recorder_id"],
            ["recorder_id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            op.f("fk_dataset_license_id_license"),
            "license",
            ["license_id"],
            ["license_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_dataset_license_id_license"),
        "dataset",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_dataset_primary_recorder_id_recorder"),
        "dataset",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_dataset_primary_site_id_site"),
        "dataset",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_dataset_project_id_project"),
        "dataset",
        type_="foreignkey",
    )

    op.drop_column("dataset", "note")
    op.drop_column("dataset", "doi")
    op.drop_column("dataset", "license_id")
    op.drop_column("dataset", "primary_recorder_id")
    op.drop_column("dataset", "primary_site_id")
    op.drop_column("dataset", "project_id")

    op.drop_table("site_image")
    op.drop_table("site")
    op.drop_table("project")
    op.drop_table("license")
    op.drop_table("recorder")
