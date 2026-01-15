"""Remove is_labeling_complete from search_session.

Revision ID: c016
Revises: c015
Create Date: 2026-01-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c016"
down_revision: Union[str, None] = "c015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove is_labeling_complete column from search_session table."""
    op.drop_column("search_session", "is_labeling_complete")


def downgrade() -> None:
    """Add back is_labeling_complete column to search_session table."""
    op.add_column(
        "search_session",
        sa.Column(
            "is_labeling_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
