"""Remove legacy fields from ml_project (use dataset_scopes instead).

Revision ID: c027
Revises: c026
Create Date: 2026-01-06

This migration removes deprecated fields from ml_project:
- dataset_id: Replaced by MLProjectDatasetScope (many-to-many)
- embedding_model_run_id: Replaced by foundation_model_run_id in dataset scopes

All projects should now use ml_project_dataset_scope for dataset associations.

This is a BREAKING change:
- API endpoints using these fields will need updates
- Clients must use dataset_scopes instead
"""

from typing import Sequence

from alembic import op

revision: str = "c027"
down_revision: str | None = "c026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove legacy fields from ml_project."""
    # Drop foreign key constraints first
    op.drop_constraint("ml_project_dataset_id_fkey", "ml_project", type_="foreignkey")
    op.drop_constraint("ml_project_embedding_model_run_id_fkey", "ml_project", type_="foreignkey")

    # Drop columns
    op.drop_column("ml_project", "dataset_id")
    op.drop_column("ml_project", "embedding_model_run_id")


def downgrade() -> None:
    """Restore legacy fields to ml_project."""
    # Add columns back
    op.execute("""
        ALTER TABLE ml_project
        ADD COLUMN dataset_id INTEGER,
        ADD COLUMN embedding_model_run_id INTEGER
    """)

    # Add foreign key constraints
    op.create_foreign_key(
        "ml_project_dataset_id_fkey",
        "ml_project",
        "dataset",
        ["dataset_id"],
        ["id"],
        ondelete="SET NULL"
    )
    op.create_foreign_key(
        "ml_project_embedding_model_run_id_fkey",
        "ml_project",
        "model_run",
        ["embedding_model_run_id"],
        ["id"],
        ondelete="SET NULL"
    )
