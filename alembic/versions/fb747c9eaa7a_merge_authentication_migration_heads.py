"""Merge authentication migration heads

Revision ID: fb747c9eaa7a
Revises: 13a89530c1d2, 60a1b2c3d4e5
Create Date: 2026-08-07 06:42:14.520131

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb747c9eaa7a'
down_revision: Union[str, Sequence[str], None] = ('13a89530c1d2', '60a1b2c3d4e5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
