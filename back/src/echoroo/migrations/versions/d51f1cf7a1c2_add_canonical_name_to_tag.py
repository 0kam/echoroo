"""Add canonical_name column to tag table.

Revision ID: d51f1cf7a1c2
Revises: cc5a4f246df6
Create Date: 2025-05-15 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d51f1cf7a1c2"
down_revision: Union[str, None] = "cc5a4f246df6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tag") as batch_op:
        batch_op.add_column(
            sa.Column("canonical_name", sa.String(length=255), nullable=True)
        )

    op.execute("UPDATE tag SET canonical_name = value")

    with op.batch_alter_table("tag") as batch_op:
        batch_op.alter_column(
            "canonical_name",
            existing_type=sa.String(length=255),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("tag") as batch_op:
        batch_op.drop_column("canonical_name")
