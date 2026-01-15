"""merge gain and inference heads

Revision ID: e8f9a0b1c2d3
Revises: c7a3f2e8d901, a1b2c3d4e5f6
Create Date: 2025-12-05

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = ("c7a3f2e8d901", "a1b2c3d4e5f6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
