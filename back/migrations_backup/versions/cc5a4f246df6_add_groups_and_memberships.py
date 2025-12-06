"""Add user groups and group memberships.

Revision ID: cc5a4f246df6
Revises: a8a44e0eea11
Create Date: 2025-02-15 12:34:56.000000

"""

from typing import Sequence, Union

import fastapi_users_db_sqlalchemy.generics
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cc5a4f246df6"
down_revision: Union[str, None] = "a8a44e0eea11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    group_role_enum = sa.Enum("member", "manager", name="group_role")
    group_role_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=True,
        ),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True), "postgresql"
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["user.id"],
            name=op.f("fk_group_created_by_id_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_group")),
        sa.UniqueConstraint("name", name=op.f("uq_group_name")),
    )

    op.create_table(
        "group_membership",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            fastapi_users_db_sqlalchemy.generics.GUID(),
            nullable=False,
        ),
        sa.Column(
            "role",
            group_role_enum,
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True), "postgresql"
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["group.id"],
            name=op.f("fk_group_membership_group_id_group"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_group_membership_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "group_id",
            "user_id",
            name=op.f("pk_group_membership"),
        ),
    )


def downgrade() -> None:
    op.drop_table("group_membership")
    op.drop_table("group")

    group_role_enum = sa.Enum("member", "manager", name="group_role")
    group_role_enum.drop(op.get_bind(), checkfirst=True)
