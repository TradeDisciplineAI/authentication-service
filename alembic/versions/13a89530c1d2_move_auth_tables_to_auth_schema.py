"""move auth tables to auth schema

Revision ID: 13a89530c1d2
Revises: 021805c35a4a
Create Date: 2026-07-19 16:41:04.715671

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '13a89530c1d2'
down_revision: Union[str, Sequence[str], None] = '021805c35a4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Move authentication tables to the authentication schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS authentication")

    op.execute("ALTER TABLE public.users SET SCHEMA authentication")
    op.execute("ALTER TABLE public.refresh_tokens SET SCHEMA authentication")
    op.execute("ALTER TABLE public.password_reset_tokens SET SCHEMA authentication")
    op.execute("ALTER TABLE public.email_verification_tokens SET SCHEMA authentication")

    op.execute("ALTER TYPE public.user_role SET SCHEMA authentication")

def downgrade() -> None:
    """Move authentication tables back to the public schema."""

    op.execute("ALTER TABLE authentication.email_verification_tokens SET SCHEMA public")
    op.execute("ALTER TABLE authentication.password_reset_tokens SET SCHEMA public")
    op.execute("ALTER TABLE authentication.refresh_tokens SET SCHEMA public")
    op.execute("ALTER TABLE authentication.users SET SCHEMA public")

    op.execute("ALTER TYPE authentication.user_role SET SCHEMA public")
