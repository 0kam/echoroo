"""merge heads

Revision ID: 7ea39f3ee58d
Revises: 1c4e919a2b2c, 2b1b1fe60c9a
Create Date: 2025-11-21 17:24:37.839847

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "7ea39f3ee58d"
down_revision: Union[str, None] = ("1c4e919a2b2c", "2b1b1fe60c9a")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
