"""Add source columns to annotation_project.

Revision ID: c010_add_source
Revises: c009_add_vernacular_name_to_tag
Create Date: 2026-01-03 00:00:00.000000

This migration adds source tracking for annotation projects created from
Foundation Model detection results:
- source_foundation_model_run_id: FK to foundation_model_run (when converted without filter)
- source_species_filter_application_id: FK to species_filter_application (when converted with filter)

These columns allow tracking which model run and filter application were used
to generate the annotation project.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c010_add_source"
down_revision: Union[str, None] = "c009_vernacular_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add source_foundation_model_run_id column
    op.add_column(
        "annotation_project",
        sa.Column(
            "source_foundation_model_run_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    # Add source_species_filter_application_id column
    op.add_column(
        "annotation_project",
        sa.Column(
            "source_species_filter_application_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    # Add foreign key constraints
    op.create_foreign_key(
        "fk_annotation_project_source_foundation_model_run_id",
        "annotation_project",
        "foundation_model_run",
        ["source_foundation_model_run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_annotation_project_source_species_filter_application_id",
        "annotation_project",
        "species_filter_application",
        ["source_species_filter_application_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Remove foreign key constraints
    op.drop_constraint(
        "fk_annotation_project_source_species_filter_application_id",
        "annotation_project",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_annotation_project_source_foundation_model_run_id",
        "annotation_project",
        type_="foreignkey",
    )

    # Remove columns
    op.drop_column("annotation_project", "source_species_filter_application_id")
    op.drop_column("annotation_project", "source_foundation_model_run_id")
