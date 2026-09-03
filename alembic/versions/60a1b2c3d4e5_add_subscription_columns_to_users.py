"""add_subscription_columns_to_users

Revision ID: 60a1b2c3d4e5
Revises: 54a7fb8168af
Create Date: 2026-08-06 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "60a1b2c3d4e5"
down_revision: str | None = "13a89530c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on = '13a89530c1d2'


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'authentication' AND table_name = 'users' AND column_name = 'trades_count') THEN ALTER TABLE authentication.users ADD COLUMN trades_count INTEGER NOT NULL DEFAULT 0; ALTER TABLE authentication.users ALTER COLUMN trades_count DROP DEFAULT; END IF; END $$;"
    )
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'authentication' AND table_name = 'users' AND column_name = 'subscription_tier') THEN ALTER TABLE authentication.users ADD COLUMN subscription_tier VARCHAR(20) NOT NULL DEFAULT 'FREE'; ALTER TABLE authentication.users ALTER COLUMN subscription_tier DROP DEFAULT; END IF; END $$;"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "subscription_tier", schema="authentication")
    op.drop_column("users", "trades_count", schema="authentication")
