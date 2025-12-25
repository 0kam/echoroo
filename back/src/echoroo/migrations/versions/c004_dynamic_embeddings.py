"""Make embedding dimensions dynamic.

Revision ID: c004_make_embedding_dimensions_dynamic
Revises: c003_create_foundation_models
Create Date: 2025-12-06

Changes vector columns from fixed 1536 dimensions to dynamic dimensions
to support both BirdNET (1024) and Perch (1536) embeddings.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c004_dynamic_embeddings"
down_revision = "c003_create_foundation_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Change clip_embedding.embedding from vector(1536) to vector (no dimension)
    op.execute("ALTER TABLE clip_embedding ALTER COLUMN embedding TYPE vector USING embedding::vector")

    # Change sound_event_embedding.embedding from vector(1536) to vector (no dimension)
    op.execute("ALTER TABLE sound_event_embedding ALTER COLUMN embedding TYPE vector USING embedding::vector")

    # Change reference_sound.embedding from vector(1536) to vector (no dimension)
    op.execute("ALTER TABLE reference_sound ALTER COLUMN embedding TYPE vector USING embedding::vector")


def downgrade() -> None:
    # Revert to fixed 1536 dimensions
    # Note: This will fail if there are embeddings with different dimensions
    op.execute("ALTER TABLE clip_embedding ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
    op.execute("ALTER TABLE sound_event_embedding ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
    op.execute("ALTER TABLE reference_sound ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
