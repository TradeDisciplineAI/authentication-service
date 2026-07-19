"""create enterprise schemas

Revision ID: 021805c35a4a
Revises: 487eb0ed5647
Create Date: 2026-07-19 16:04:06.801291

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '021805c35a4a'
down_revision: Union[str, Sequence[str], None] = '487eb0ed5647'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from alembic import op


def upgrade() -> None:
    schemas = [
        "auth",
        "market",
        "sentiment",
        "strategy",
        "risk",
        "execution",
        "learning",
        "discipline",
        "analytics",
        "audit",
        "system",
    ]

    for schema in schemas:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    schemas = [
        "system",
        "audit",
        "analytics",
        "discipline",
        "learning",
        "execution",
        "risk",
        "strategy",
        "sentiment",
        "market",
        "auth",
    ]

    for schema in schemas:
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
