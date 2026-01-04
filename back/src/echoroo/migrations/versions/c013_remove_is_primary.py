"""Remove is_primary from ml_project_dataset_scope.

Revision ID: c013
Revises: c012
Create Date: 2026-01-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c013"
down_revision: Union[str, None] = "c012_ss_multi_ds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove is_primary column from ml_project_dataset_scope table."""
    op.drop_column("ml_project_dataset_scope", "is_primary")


def downgrade() -> None:
    """Add is_primary column back to ml_project_dataset_scope table."""
    op.add_column(
        "ml_project_dataset_scope",
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
