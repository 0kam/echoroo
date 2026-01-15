"""Add created_on to junction tables.

Revision ID: c014
Revises: c013
Create Date: 2026-01-03

Add created_on column to junction tables that inherit from Base
but were created without this column.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c014"
down_revision: Union[str, None] = "c013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add created_on to ml_project_tag
    op.add_column(
        "ml_project_tag",
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Add created_on to search_session_reference_sound
    op.add_column(
        "search_session_reference_sound",
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("search_session_reference_sound", "created_on")
    op.drop_column("ml_project_tag", "created_on")
