"""Remove review columns from inference_prediction table

Revision ID: c041
Revises: c040
Create Date: 2026-01-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "c041"
down_revision = "c040"
branch_labels = None
depends_on = None


def upgrade():
    # Check if constraint exists before dropping
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Get existing foreign keys
    try:
        foreign_keys = inspector.get_foreign_keys("inference_prediction")
        constraint_names = [fk["name"] for fk in foreign_keys]

        if "inference_prediction_reviewed_by_id_fkey" in constraint_names:
            op.drop_constraint(
                "inference_prediction_reviewed_by_id_fkey",
                "inference_prediction",
                type_="foreignkey",
            )
    except Exception:
        pass

    # Get existing columns
    try:
        columns = inspector.get_columns("inference_prediction")
        column_names = [col["name"] for col in columns]

        # Drop columns only if they exist
        if "reviewed_by_id" in column_names:
            op.drop_column("inference_prediction", "reviewed_by_id")
        if "reviewed_on" in column_names:
            op.drop_column("inference_prediction", "reviewed_on")
        if "notes" in column_names:
            op.drop_column("inference_prediction", "notes")
        if "review_status" in column_names:
            op.drop_column("inference_prediction", "review_status")
    except Exception:
        pass

    # Drop enum type (IF EXISTS handles non-existence)
    op.execute("DROP TYPE IF EXISTS inference_prediction_review_status")


def downgrade():
    # Recreate enum type
    op.execute(
        """
        CREATE TYPE inference_prediction_review_status AS ENUM (
            'unreviewed', 'confirmed', 'rejected', 'uncertain'
        )
    """
    )

    # Recreate columns
    op.add_column(
        "inference_prediction",
        sa.Column(
            "review_status",
            postgresql.ENUM(
                "unreviewed",
                "confirmed",
                "rejected",
                "uncertain",
                name="inference_prediction_review_status",
            ),
            nullable=False,
            server_default="unreviewed",
        ),
    )

    op.add_column(
        "inference_prediction", sa.Column("reviewed_by_id", sa.UUID(), nullable=True)
    )

    op.add_column(
        "inference_prediction",
        sa.Column("reviewed_on", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "inference_prediction", sa.Column("notes", sa.String(), nullable=True)
    )

    # Recreate foreign key
    op.create_foreign_key(
        "inference_prediction_reviewed_by_id_fkey",
        "inference_prediction",
        "user",
        ["reviewed_by_id"],
        ["id"],
    )
