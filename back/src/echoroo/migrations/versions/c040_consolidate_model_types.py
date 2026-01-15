"""Consolidate custom_model_type to only SELF_TRAINING_SVM

Revision ID: c040
Revises: c039
Create Date: 2026-01-10
"""

from alembic import op

# revision identifiers
revision = "c040"
down_revision = "c039"
branch_labels = None
depends_on = None


def upgrade():
    """Consolidate model types to only SELF_TRAINING_SVM."""
    # Update all existing records to SELF_TRAINING_SVM
    op.execute("""
        UPDATE custom_model
        SET model_type = 'self_training_svm'
        WHERE model_type IN (
            'logistic_regression',
            'svm_linear',
            'mlp_small',
            'mlp_medium',
            'random_forest'
        )
    """)

    # Convert to varchar temporarily
    op.execute("""
        ALTER TABLE custom_model
        ALTER COLUMN model_type TYPE varchar(50)
    """)

    # Drop old enum type
    op.execute("DROP TYPE IF EXISTS custom_model_type")

    # Create new enum with only SELF_TRAINING_SVM
    op.execute("""
        CREATE TYPE custom_model_type AS ENUM ('self_training_svm')
    """)

    # Convert back to enum
    op.execute("""
        ALTER TABLE custom_model
        ALTER COLUMN model_type TYPE custom_model_type
        USING model_type::custom_model_type
    """)


def downgrade():
    """Restore all model types."""
    # Convert to varchar temporarily
    op.execute("""
        ALTER TABLE custom_model
        ALTER COLUMN model_type TYPE varchar(50)
    """)

    # Drop new enum
    op.execute("DROP TYPE IF EXISTS custom_model_type")

    # Recreate full enum
    op.execute("""
        CREATE TYPE custom_model_type AS ENUM (
            'logistic_regression',
            'svm_linear',
            'mlp_small',
            'mlp_medium',
            'random_forest',
            'self_training_svm'
        )
    """)

    # Convert back to enum
    op.execute("""
        ALTER TABLE custom_model
        ALTER COLUMN model_type TYPE custom_model_type
        USING model_type::custom_model_type
    """)
