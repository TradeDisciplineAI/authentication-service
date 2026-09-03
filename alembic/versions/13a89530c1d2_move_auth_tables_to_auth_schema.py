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
    """Move authentication tables to the authentication schema if present in public."""
    op.execute("CREATE SCHEMA IF NOT EXISTS authentication")

    tables = ["users", "refresh_tokens", "password_reset_tokens", "email_verification_tokens"]
    for table in tables:
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = '{table}') AND NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'authentication' AND tablename = '{table}') THEN ALTER TABLE public.{table} SET SCHEMA authentication; END IF; END $$;"
        )

    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'public' AND t.typname = 'user_role') AND NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'authentication' AND t.typname = 'user_role') THEN ALTER TYPE public.user_role SET SCHEMA authentication; END IF; END $$;"
    )

def downgrade() -> None:
    """Move authentication tables back to the public schema."""

    op.execute("ALTER TABLE authentication.email_verification_tokens SET SCHEMA public")
    op.execute("ALTER TABLE authentication.password_reset_tokens SET SCHEMA public")
    op.execute("ALTER TABLE authentication.refresh_tokens SET SCHEMA public")
    op.execute("ALTER TABLE authentication.users SET SCHEMA public")

    op.execute("ALTER TYPE authentication.user_role SET SCHEMA public")
