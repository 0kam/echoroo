"""add_gain_to_dataset

Revision ID: c7a3f2e8d901
Revises: 09290a9be9ed
Create Date: 2025-12-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a3f2e8d901"
down_revision: Union[str, None] = "09290a9be9ed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dataset", sa.Column("gain", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("dataset", "gain")
