"""add_subscription_columns_to_users

Revision ID: 60a1b2c3d4e5
Revises: 54a7fb8168af
Create Date: 2026-08-06 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "60a1b2c3d4e5"
down_revision: str | None = "54a7fb8168af"
branch_labels: str | Sequence[str] | None = None
depends_on = '13a89530c1d2'


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "trades_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema="authentication",
    )
    op.alter_column("users", "trades_count", server_default=None, schema="authentication")

    op.add_column(
        "users",
        sa.Column(
            "subscription_tier",
            sa.String(length=20),
            nullable=False,
            server_default="FREE",
        ),
        schema="authentication",
    )
    op.alter_column("users", "subscription_tier", server_default=None, schema="authentication")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "subscription_tier", schema="authentication")
    op.drop_column("users", "trades_count", schema="authentication")
