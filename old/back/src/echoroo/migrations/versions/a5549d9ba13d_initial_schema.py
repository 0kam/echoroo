"""initial_schema

Revision ID: a5549d9ba13d
Revises:
Create Date: 2025-12-05 16:42:53.042057

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5549d9ba13d'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Initial schema - tables are created by Base.metadata.create_all()"""
    pass


def downgrade() -> None:
    """Drop all tables"""
    pass
