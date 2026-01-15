"""Add source_search_session_id to custom_model.

Revision ID: c039
Revises: c038
Create Date: 2025-01-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c039"
down_revision: str | None = "c038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add source_search_session_id column to custom_model table."""
    op.add_column(
        "custom_model",
        sa.Column(
            "source_search_session_id",
            sa.Integer(),
            sa.ForeignKey("search_session.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_custom_model_source_search_session_id",
        "custom_model",
        ["source_search_session_id"],
    )


def downgrade() -> None:
    """Remove source_search_session_id column from custom_model table."""
    op.drop_index("ix_custom_model_source_search_session_id", "custom_model")
    op.drop_column("custom_model", "source_search_session_id")
